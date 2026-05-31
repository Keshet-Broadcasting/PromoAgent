"""
service.py

Core pipeline for the Promo department agent.

This module is the single source of truth for the query pipeline.
Both the FastAPI layer (api.py) and the CLI (agent.py) call run_query().

Public API
----------
    run_query(question, debug=False)  →  QueryResult
    answer_question(question)         →  str   (backwards-compat alias)

Pipeline
--------
    1. classify  (query_router.classify)
    2. retrieve  (search_word_docs / search_excel_promos)
    3. format    (_fmt_excel / _fmt_word)
    4. prompt    (prompts.build_messages)
    5. LLM call  (Azure OpenAI via openai SDK)
    6. return    QueryResult
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Inject the OS/Windows certificate store so Python trusts corporate proxies.
# Must run before any HTTPS connection is opened (Langfuse, Azure SDKs, etc.).
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from .chat_provider import get_provider

try:
    from langfuse import observe as _lf_observe, get_client as _lf_get_client
    from opentelemetry import trace as _otel_trace
    _LF_AVAILABLE = True
except Exception:
    _LF_AVAILABLE = False
    def _lf_observe(*args, **kwargs):  # no-op shim when langfuse is absent
        def decorator(fn):
            return fn
        return decorator
from .models import QueryResponse, SourceDoc
from .prompts import build_messages
from .query_router import classify
from .domain_catalog import (
    expand_aliases as _catalog_expand_aliases,
    extract_show_names as _catalog_extract_show_names,
    genre_label,
    genres_for_query,
    official_show_names,
    shows_for_genres,
)
from .search_word_docs import fetch_many_show_promos, fetch_show_promos, search_excel_promos, search_word_docs

# SharePoint fallback — optional; skipped gracefully when not configured.
try:
    from .tools.sharepoint_tool import get_sharepoint_client as _get_sp_client
    _SP_AVAILABLE = True
except ImportError:
    _SP_AVAILABLE = False

# SharePoint enrichment feature flags (all default OFF).
# IMPORTANT: Azure semantic reranker scores are on 0–4 scale (verified from prod API).
# 2.5 ≈ "reasonably confident" | 3.0+ = "high confidence" | typical range: 2.1–2.5
_SP_ENRICHMENT       = os.getenv("SP_ENRICHMENT_ENABLED", "false").lower() == "true"
_SP_SCORE_THRESHOLD  = float(os.getenv("SP_SCORE_THRESHOLD", "2.5"))
_SP_ENRICHMENT_TOP   = int(os.getenv("SP_ENRICHMENT_TOP", "3"))
_SP_ALLOWED_EXTENSIONS: list[str] = ["docx", "xlsx", "pdf"]
_BROAD_RETRIEVAL     = os.getenv("BROAD_RETRIEVAL_ENABLED", "false").lower() in ("true", "1", "yes")

load_dotenv()

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Show nickname expansion
# ---------------------------------------------------------------------------

# Nicknames used by the promo team that must be resolved to the official index
# show_name before sending to Azure Search.  Keep in sync with the aliases
# table in system_prompt.txt.
_SHOW_ALIASES: list[tuple[re.Pattern, str]] = [
    # Nickname → official show name (longer/more-specific aliases first)
    (re.compile(r"חתונמי\s*2"),  "חתונה ממבט שני"),
    (re.compile(r"חתונמי"),      "חתונה ממבט ראשון"),
    (re.compile(r"פאלו אלטו"),   "אף אחד לא עוזב את פאלו אלטו"),
    (re.compile(r"רוקדים"),       "רוקדים עם כוכבים"),
    (re.compile(r"\bארץ\b"),      "ארץ נהדרת"),
    (re.compile(r"\bזמר\b"),      "הזמר במסכה"),
    (re.compile(r"\bכוכב\b"),     "הכוכב הבא"),
]


def _expand_aliases(query: str) -> str:
    """Replace known team nicknames with the official show name.

    This improves Azure Search recall — the index stores the full official
    show name, so searching for a nickname can miss exact-field matches.
    The domain catalog is the source of truth for alias mappings.
    """
    return _catalog_expand_aliases(query)


# ---------------------------------------------------------------------------
# Known show names — must match the exact stored value in the tv-promos index.
# Run `python scripts/list_show_names.py` to verify / expand this list.
# Longer names must come before shorter sub-strings (sorted by length descending
# in _extract_show_name so "חתונה ממבט ראשון" is matched before "חתונה").
# ---------------------------------------------------------------------------

_KNOWN_SHOWS: list[str] = [
    # ----------------------------------------------------------------
    # Derived from parse_tab_name() applied to every Excel tab.
    # Exact stored values — must match show_name in the tv-promos index.
    # Sorted longest-first so _extract_show_name() finds the most
    # specific match (e.g. "הכוכב הבא לאירוויזיון" before "הכוכב הבא").
    # ----------------------------------------------------------------

    # Reality — relationship / wedding
    "חתונה ממבט ראשון",        # עונות 2–7
    "חתונה ממבט שני",           # 1 season (no season in tab name)
    "המירוץ למיליון",            # 1 season (no season in tab name)
    "רוקדים עם כוכבים",         # עונות 1–4
    "הזמר במסכה",               # עונות 1–4
    "ישמח חתני",                # עונה 1

    # Reality — competition / cooking
    "נינג'ה ישראל",              # עונות 2–5
    "הכוכב הבא לאירוויזיון",    # עונות 10–12  ← MUST come before "הכוכב הבא"
    "הכוכב הבא",                # עונות 7–9
    "המטבח המנצח",              # עונות 2, 6, VIP
    "הקינוח המושלם",            # עונות 1–2
    "הכרישים",                  # עונות 2–4
    "מה שבע",                   # no season
    "מה באמת קרה שם ארז טל",   # עונה 1
    "מבחן ההורים הגדול",        # no season
    "אהבה גדולה מהחיים",        # עונה 1

    # Reality — other
    "זה לא אולפן שישי",         # עונות 1–4
    "שיטת אשכנזי",              # עונה 1
    "ארץ נהדרת",                # עונות 18–22
    "יצאת צדיק",                # עונות 8–9 (⚠ promo_text col named differently — may not be indexed)
    "מאסטר שף",                 # עונות 8–12 (⚠ non-standard headers — data may be sparse in index)

    # Drama / scripted
    "אף אחד לא עוזב את פאלו אלטו",  # no season (users search "פאלו אלטו" → alias expands)
    "החיים הם תקופה קשה",       # no season
    "הראש",                     # עונה 1
    "גוף שלישי",                # no season
    "חולי אהבה",                # no season
    "אור ראשון",                # no season (⚠ no column headers — may not be indexed)
    "ביום שהאדמה רעדה",         # no season
    "בייבי בום",                # no season
    "בית הספר למוזיקה",         # no season
    "בקרוב אצלי",               # no season
    "הבוגדים",                  # no season
    "הנחלה",                    # no season
    "השוטרים",                  # עונות 1–2
    "המתמחים",                  # עונות 3–4
    "להיות איתה",               # עונה 3
    "צומת מילר",                # עונות 3–4

    # ⚠ נוטוק — row 2 has data values not headers; likely not indexed properly
    # "נוטוק",  # kept out — filter would return 0 useful rows
]


def _extract_show_name(query: str) -> str | None:
    """Return the first known show name found in the query (longest match wins)."""
    matches = _extract_show_names(query)
    return matches[0] if matches else None


def _extract_show_names(query: str) -> list[str]:
    """Return all known show names found in the query."""
    return _catalog_extract_show_names(query)


# ---------------------------------------------------------------------------
# Temporal qualifier detection
# ---------------------------------------------------------------------------

# Queries that need a broad sweep of Excel rows to find extremes or build a
# ranked list.  For these we raise excel_top from 5 → 30.
_RANKING_PATTERNS = re.compile(
    r"הכי גבוה|הכי נמוך|הכי הרבה|הכי טוב|הכי גרוע"
    r"|טופ\s*\d*|top\s*\d*"
    r"|סדר לי|סדר את|דרג|דרוג"
    r"|הגבוה ביותר|הנמוך ביותר|הגבוהה ביותר|הנמוכה ביותר"
    r"|מוביל|מובילים|ראשון ב|אחרון ב"
    r"|מי הכי|מה הכי"
)

# Single-show rating/metric questions ("מה היה הרייטינג של X", "רייטינג הגמר של Y",
# "מה היו הרייטינגים של Z") need EVERY row for the show, not a semantic top-N that
# routinely misses the launch / finale / specific-season episode. They are not
# phrased as rankings, so _RANKING_PATTERNS misses them — detect them separately
# so complete fetch_show_promos still fires.
_RATING_INTENT_PATTERNS = re.compile(r"רייטינג|נקודת פתיחה|נקודות פתיחה|אחוזי צפייה|שֵיר|share")

_LAST_SEASON_PATTERNS = re.compile(
    # Require "עונה" to be near the temporal word — avoids false positives on
    # "ההחלטה האחרונה", "הפעם האחרונה", etc.
    r"ה?עונה\s+האחרונה|עונה\s+אחרונה|עונה\s+הכי\s+אחרונה"
    r"|עונה\s+אחרון|עונה\s+חדש(?:ה)?|עונה\s+עדכנית"
    r"|last\s+season|latest\s+season"
)
_FIRST_SEASON_PATTERNS = re.compile(
    # Require "עונה" to be near the temporal word — avoids false positives on
    # show names containing "ראשון" (e.g. "חתונה ממבט ראשון").
    r"ה?עונה\s+הראשונה|עונה\s+ראשונה|עונה\s+1\b"
    r"|first\s+season"
)


def _season_as_int(season_val) -> int:
    """Parse a season value (int, float, or string) to int for sorting. Returns -1 on failure."""
    try:
        return int(float(str(season_val).strip()))
    except (ValueError, TypeError):
        return -1


def _max_season_in_text(text: str) -> int:
    """Extract the highest season number mentioned anywhere in a text chunk.

    Scans for "עונה N" patterns and returns the largest N found.
    Returns -1 when no season number is found (chunk is kept as-is in sort).
    Used to temporally re-rank Word doc chunks when the query asks for
    the last/first season and Azure's semantic score happens to rank an
    older season chunk higher.
    """
    seasons = [int(m) for m in re.findall(r"עונה\s+(\d+)", text)]
    return max(seasons) if seasons else -1


def _rerank_word_docs_by_season(docs: list[dict], prefer: str) -> list[dict]:
    """Re-sort Word doc chunks so the highest (prefer='last') or lowest
    (prefer='first') season appears first, breaking ties by original score.

    Chunks with no detectable season number keep their original relative order
    at the end of the list, so they don't displace season-bearing chunks but
    are still available to the LLM for context.
    """
    if not docs:
        return docs

    def sort_key(d: dict):
        chunk_text = (d.get("chunk") or "") + " " + (d.get("caption") or "")
        season = _max_season_in_text(chunk_text)
        score = float(d.get("score") or 0)
        if season < 0:
            # No season found → push to end regardless of direction
            return (1, 0, -score)
        if prefer == "last":
            return (0, -season, -score)   # highest season first
        return (0, season, -score)         # lowest season first

    reranked = sorted(docs, key=sort_key)
    if reranked != docs:
        top_before = _max_season_in_text(
            (docs[0].get("chunk") or "") + " " + (docs[0].get("caption") or "")
        )
        top_after  = _max_season_in_text(
            (reranked[0].get("chunk") or "") + " " + (reranked[0].get("caption") or "")
        )
        log.info(
            "  Word temporal rerank (%s): top season before=%s → after=%s",
            prefer, top_before if top_before >= 0 else "?", top_after if top_after >= 0 else "?",
        )
    return reranked


def _filter_by_season_order(docs: list[dict], prefer: str) -> list[dict]:
    """Filter excel docs to only keep the max (prefer='last') or min (prefer='first') season,
    computed **per show**. Shows that have no parseable season field are kept as-is so
    that shows like 'המירוץ למיליון' (which omit the season column) are not silently
    discarded when their docs happen to share the result set with shows that do carry season
    numbers.
    """
    if not docs:
        return docs

    from collections import defaultdict
    by_show: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        by_show[d.get("show_name") or ""].append(d)

    result: list[dict] = []
    for show_name, show_docs in by_show.items():
        seasons = [_season_as_int(d.get("season")) for d in show_docs]
        valid_seasons = [s for s in seasons if s >= 0]
        if not valid_seasons:
            # No season data for this show — keep all its docs unchanged
            result.extend(show_docs)
            log.info("  Temporal filter '%s': show=%r has no season numbers — kept %d doc(s)",
                     prefer, show_name, len(show_docs))
            continue
        target = max(valid_seasons) if prefer == "last" else min(valid_seasons)
        filtered = [d for d in show_docs if _season_as_int(d.get("season")) == target]
        kept = filtered if filtered else show_docs
        result.extend(kept)
        log.info("  Temporal filter '%s': show=%r keeping season %d (%d/%d doc(s))",
                 prefer, show_name, target, len(kept), len(show_docs))

    return result if result else docs


# ---------------------------------------------------------------------------
# Internal result container
# ---------------------------------------------------------------------------

@dataclass
class _RetrievalResult:
    """Raw retrieval output before formatting."""
    context: str
    excel_docs:      list[dict] = field(default_factory=list)
    word_docs:       list[dict] = field(default_factory=list)
    sharepoint_docs: list[dict] = field(default_factory=list)


@dataclass
class _RetrievalPlan:
    """Intent-level retrieval plan used before querying Azure Search."""
    route: str
    query: str
    show_names: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    event_intent: str | None = None
    broad_scope: bool = False
    comparison: bool = False
    conversion: bool = False
    ranking: bool = False
    season_filter: str | None = None

    @property
    def broad_excel(self) -> bool:
        return _BROAD_RETRIEVAL and self.broad_scope and self.route in ("excel_numeric", "hybrid")

    @property
    def broad_word(self) -> bool:
        return _BROAD_RETRIEVAL and self.broad_scope and self.route in ("word_quote", "hybrid")

    @property
    def target_show_names(self) -> list[str]:
        if self.show_names:
            return self.show_names
        if self.genres:
            return shows_for_genres(self.genres)
        if self.broad_scope and re.search(r"כל ה?תוכניות|כל ה?סדרות|כל ה", self.query):
            return official_show_names()
        return []


# ---------------------------------------------------------------------------
# Context formatters  (private)
# ---------------------------------------------------------------------------

def _chunk_pos(chunk_id: str) -> str:
    """Extract the sequential position from a chunk_id like '…_chunk_0_111'."""
    if "_chunk_" in chunk_id:
        return chunk_id.split("_chunk_", 1)[1]
    return chunk_id


def _fmt_excel(docs: list[dict]) -> str:
    if not docs:
        return "לא נמצאו תוצאות רלוונטיות ב-Excel."

    # Build a structured Markdown table so the LLM can parse rows logically.
    header = "| # | תוכנית | עונה | פרק | תאריך | נקודת פתיחה (%) | רייטינג ממוצע (%) | מקור |"
    separator = "|---|---|---|---|---|---|---|---|"
    rows = []
    promo_texts = []

    for i, d in enumerate(docs, 1):
        show = d.get("show_name") or "—"
        season = d.get("season") or "—"
        episode = d.get("episode_number") or "—"
        date = d.get("date") or "—"
        opening = f"{d['opening_point']}" if d.get("opening_point") else "—"
        rating = f"{d['rating']}" if d.get("rating") else "—"
        source = d.get("tab_name") or d.get("source_file") or "—"

        rows.append(f"| {i} | {show} | {season} | {episode} | {date} | {opening} | {rating} | {source} |")

        text = _sanitize_for_content_filter((d.get("promo_text") or "").strip()[:500])
        if text:
            promo_texts.append(f"**[{i}]** {text}")

    table = "\n".join([header, separator] + rows)

    if promo_texts:
        table += "\n\n### טקסטי פרומו\n\n" + "\n\n".join(promo_texts)

    return table


def _fmt_word(docs: list[dict]) -> str:
    if not docs:
        return "לא נמצאו תוצאות רלוונטיות במסמכי Word."
    lines = []
    for i, d in enumerate(docs, 1):
        source   = d.get("title") or ""
        header   = d.get("header") or ""
        caption  = _sanitize_for_content_filter((d.get("caption") or "").strip())
        chunk    = _sanitize_for_content_filter((d.get("chunk") or "").strip()[:900])
        score    = d.get("score") or 0
        chunk_id = d.get("chunk_id") or ""
        show_name = d.get("show_name") or ""
        season = d.get("season") or ""
        qtype = d.get("question_type") or ""
        pos      = _chunk_pos(chunk_id) if chunk_id else "—"

        meta = f"[{i}] [מקור: {source}] | קטע מס': {pos}"
        if header:
            meta += f" | פרק: {header}"
        if show_name:
            meta += f" | תוכנית: {show_name}"
        if season:
            meta += f" | עונה: {season}"
        if qtype:
            meta += f" | סוג שאלה: {qtype}"
        meta += f" | רלוונטיות: {score:.2f}"

        parts = [meta]
        if caption:
            parts.append(f"ציטוט מודגש (Azure): {caption}")
        parts.append(f"תוכן מלא: {chunk}")
        lines.append("\n".join(parts))
    return "\n\n---\n\n".join(lines)


def _fmt_sharepoint(docs: list[dict]) -> str:
    if not docs:
        return "לא נמצאו תוצאות ב-SharePoint."
    lines = []
    for i, d in enumerate(docs, 1):
        title = d.get("title") or "(ללא שם)"
        url   = d.get("url") or ""
        text  = _sanitize_for_content_filter((d.get("text") or "").strip()[:600])
        meta  = f"[{i}] {title}"
        if url:
            meta += f"  |  {url}"
        parts = [meta]
        if text:
            parts.append(text)
        lines.append("\n".join(parts))
    return "\n\n---\n\n".join(lines)


def _is_context_insufficient(retrieval: _RetrievalResult) -> bool:
    """Return True when primary Azure Search retrieval returned no documents.

    Used to decide whether to invoke the SharePoint fallback.
    We only fall back when BOTH indexes came up empty — this avoids adding
    SharePoint latency to the majority of queries that already have evidence.
    """
    return not retrieval.excel_docs and not retrieval.word_docs


def _fetch_sharepoint_fallback(query: str, top: int = 5) -> list[dict]:
    """Call SharePoint search and return normalised result dicts.

    Returns an empty list (never raises) so callers need no error handling.
    """
    if not _SP_AVAILABLE:
        return []
    try:
        client = _get_sp_client()
        return client.search_in_library(query, top=top)
    except EnvironmentError:
        # SP credentials not configured — skip silently
        log.debug("SharePoint fallback skipped: credentials not configured")
        return []
    except Exception as exc:
        log.warning("SharePoint fallback failed: %s", exc)
        return []


def _needs_sharepoint_enrichment(route: str, word_docs: list[dict]) -> bool:
    """Return True when SP enrichment should run for this query.

    Decision logic (matches the handoff decision table):
    - Always False when SP_ENRICHMENT_ENABLED is not set (feature flag).
    - Always False for excel_numeric — SP has no numeric data.
    - True when word_docs is empty (zero Azure results for this route).
    - False when top doc has a caption AND score >= threshold (Azure is confident).
    - True when top score is below threshold (low confidence).

    Note: Azure reranker scores are on a 0–4 scale (verified from prod API).
    SP_SCORE_THRESHOLD defaults to 2.5 — typical confident results score 2.1–2.5.
    """
    if not _SP_ENRICHMENT or not _SP_AVAILABLE:
        return False
    if route not in ("word_quote", "hybrid"):
        return False
    if not word_docs:
        return True
    top_doc   = word_docs[0]
    caption   = (top_doc.get("caption") or "").strip()
    top_score = float(top_doc.get("score") or 0)
    # Azure confident: caption present AND high score → skip SP
    if caption and top_score >= _SP_SCORE_THRESHOLD:
        return False
    # Low score (or no caption) → enrich
    return top_score < _SP_SCORE_THRESHOLD


def _fetch_sharepoint_enrichment(
    query: str,
    show_name: str | None,
    top: int | None = None,
) -> list[dict]:
    """Targeted SP enrichment — scoped to show folder when show name is known.

    Falls back to the generic 'עבודה ChatGPT' folder when no show is detected.
    Never raises — returns empty list on any error or misconfiguration.
    """
    if not _SP_AVAILABLE:
        return []
    n = top if top is not None else _SP_ENRICHMENT_TOP
    folder = show_name if show_name else "עבודה ChatGPT"
    try:
        client = _get_sp_client()
        return client.search_in_library(
            query,
            folder_path=folder,
            top=n,
            file_types=_SP_ALLOWED_EXTENSIONS,
        )
    except EnvironmentError:
        log.debug("SP enrichment skipped: credentials not configured")
        return []
    except Exception as exc:
        log.warning("SP enrichment failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Retrieval planning and broad evidence packs
# ---------------------------------------------------------------------------

_BROAD_SCOPE_PATTERNS = re.compile(
    r"כל ה|כל ה?תוכניות|כל ה?סדרות|כל הדרמות|כל הריאליטי|לעומת|השווה|השוואה"
    r"|דפוסים|משותפים|רוחבי|מכפיל|יחס המרה|כוונות צפייה.*רייטינג|רייטינג.*כוונות צפייה"
)
_LAUNCH_PATTERNS = re.compile(r"השקה|השקת|פתיחה|פרק ראשון|פרק 1")
_FINALE_PATTERNS = re.compile(r"גמר|סיום|פרק סיום|פינאל")
_TONIGHT_PATTERNS = re.compile(r"טונייט|טונייטים|שוטף|פרומואים שוטפים")
_CONVERSION_PATTERNS = re.compile(r"מכפיל|יחס המרה|כוונות צפייה.*רייטינג|רייטינג.*כוונות צפייה")

# ---------------------------------------------------------------------------
# Azure OpenAI content-filter sanitizer (Phase D)
# ---------------------------------------------------------------------------
# The Azure content filter (violence: medium) blocks prompts that contain
# explicit violence phrases common in drama/thriller promo texts (e.g. הראש).
# Each tuple is (compiled_pattern, neutral_replacement).
# Replacements preserve the meaning so the LLM can still answer correctly,
# but use brackets so it's clear they are sanitized — not original wording.
# ---------------------------------------------------------------------------
_CF_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    # Most common single trigger — explicit weapon-to-head phrase
    (re.compile(r"אקדח\s+לראש"),        "[נשק מכוון]"),
    # General weapon references
    (re.compile(r"אקדח"),               "[נשק]"),
    # Shooting verbs / nouns
    (re.compile(r"ירייה|יריות|ירי"),    "[תקיפה]"),
    (re.compile(r"יורה"),               "[תוקף]"),
    # "נורה " with trailing space/punct to avoid matching "נורא" (terrible)
    (re.compile(r"נורה(?=[\s,.\-\u05d0-\u05ea])"), "[נפגע]"),
    (re.compile(r"נורים|נורות"),        "[נפגעים]"),
    # Killing — match root + all common suffixes to avoid mid-word bracket artifacts
    (re.compile(r"נהרג(?:ו|ת|ים|ות)?"), "[נחסל]"),
    (re.compile(r"הורג(?:ת|ים|ות)?"),   "[מחסל]"),
    (re.compile(r"להרוג"),              "[לחסל]"),
    (re.compile(r"הרוג(?:ים|ות)?"),     "[נחסל]"),
    # Stabbing
    (re.compile(r"נדקר"),               "[נתקף]"),
    (re.compile(r"דוקר"),               "[תוקף בנשק]"),
    # Corpse
    (re.compile(r"גופ[הות]"),           "[קורבן]"),
]


def _sanitize_for_content_filter(text: str) -> str:
    """Replace phrases that trigger Azure OpenAI violence content filter.

    Applied to promo_text and Word/SharePoint chunks before prompt assembly.
    This prevents Error 400 on queries about shows with violent promo content
    (e.g. הראש) while preserving enough meaning for the LLM to answer.
    """
    for pattern, replacement in _CF_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def _detect_event_intent(query: str) -> str | None:
    if _CONVERSION_PATTERNS.search(query):
        return "conversion"
    if _LAUNCH_PATTERNS.search(query):
        return "launch"
    if _FINALE_PATTERNS.search(query):
        return "finale"
    if _TONIGHT_PATTERNS.search(query):
        return "tonight"
    return None


def _build_retrieval_plan(route: str, query: str, ranking: bool, season_filter: str | None) -> _RetrievalPlan:
    show_names = _extract_show_names(query)
    genres = genres_for_query(query)
    event_intent = _detect_event_intent(query)
    comparison = bool(re.search(r"לעומת|השווה|השוואה|ביחס ל|בין", query)) or len(show_names) > 1
    conversion = bool(_CONVERSION_PATTERNS.search(query))
    broad_scope = (
        bool(_BROAD_SCOPE_PATTERNS.search(query))
        or len(show_names) > 1
        # genres broaden only when no single show constrains the query; a single-show
        # query like "ציטוט מ-אור ראשון על הדרמה" should stay narrow even if
        # "דרמה"/"סדרה" is detected. Cross-genre/no-show queries legitimately broaden.
        or (bool(genres) and len(show_names) == 0)
        or conversion
    )
    # A single-show ranking is handled by fetch_show_promos; broad ranking uses
    # a compact evidence pack so the model sees enough rows without token blowup.
    if ranking and len(show_names) <= 1 and not genres:
        broad_scope = False
    return _RetrievalPlan(
        route=route,
        query=query,
        show_names=show_names,
        genres=genres,
        event_intent=event_intent,
        broad_scope=broad_scope,
        comparison=comparison,
        conversion=conversion,
        ranking=ranking,
        season_filter=season_filter,
    )


def _as_float(value) -> float | None:
    try:
        text = str(value).strip().replace("%", "")
        if not text or text == "—":
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _episode_as_int(value) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return -1


def _doc_text(doc: dict) -> str:
    return " ".join(
        str(doc.get(k) or "")
        for k in ("promo_text", "section", "tab_name", "source_file")
    )


def _is_launch_row(doc: dict) -> bool:
    episode = _episode_as_int(doc.get("episode_number") or doc.get("episode"))
    return episode == 1 or "השק" in _doc_text(doc)


def _is_finale_row(doc: dict) -> bool:
    text = _doc_text(doc)
    return "גמר" in text or "סיום" in text or "פינאל" in text


def _sort_metric(doc: dict) -> float:
    return (
        _as_float(doc.get("opening_point"))
        or _as_float(doc.get("opening_rating"))
        or _as_float(doc.get("rating"))
        or _as_float(doc.get("average_rating"))
        or 0.0
    )


def _select_excel_rows_for_plan(docs: list[dict], plan: _RetrievalPlan, limit: int = 60) -> list[dict]:
    if not docs:
        return []

    if plan.event_intent in ("launch", "conversion"):
        selected = [d for d in docs if _is_launch_row(d)]
    elif plan.event_intent == "finale":
        selected = [d for d in docs if _is_finale_row(d)]
    elif plan.event_intent == "tonight":
        selected = [d for d in docs if not _is_launch_row(d)]
    else:
        selected = list(docs)

    if not selected:
        selected = list(docs)

    selected.sort(key=_sort_metric, reverse=True)
    return selected[:limit]


def _fmt_plan_targets(plan: _RetrievalPlan) -> str:
    parts: list[str] = []
    if plan.show_names:
        parts.append("תוכניות: " + ", ".join(plan.show_names))
    if plan.genres:
        parts.append("ז'אנרים: " + ", ".join(genre_label(g) for g in plan.genres))
    if plan.event_intent:
        parts.append(f"כוונה: {plan.event_intent}")
    if plan.comparison:
        parts.append("סוג: השוואה")
    if plan.conversion:
        parts.append("סוג: יחס המרה")
    return " | ".join(parts) if parts else "שליפה כללית"


def _fmt_broad_excel_evidence(docs: list[dict], selected: list[dict], plan: _RetrievalPlan) -> str:
    if not docs:
        return "לא נמצאו נתוני Excel בשליפה הרחבה."
    coverage = (
        "### כיסוי שליפה רחבה\n"
        f"- {_fmt_plan_targets(plan)}\n"
        f"- שורות שנשלפו לפני סינון: {len(docs)}\n"
        f"- שורות שנכנסו לקונטקסט: {len(selected)}\n"
        "- אם חסרה תוכנית או עונה מבוקשת, חובה לציין שהתשובה חלקית.\n"
    )
    return coverage + "\n" + _fmt_excel(selected)


def _question_types_for_plan(plan: _RetrievalPlan) -> list[str]:
    if plan.event_intent == "launch":
        return ["אסטרטגיה", "תובנות", "מחקר", "כוונות"]
    if plan.event_intent == "finale":
        return ["אסטרטגיה", "תובנות", "סלוגן"]
    if plan.event_intent == "tonight":
        return ["עשה_ואל_תעשה", "פרקים", "תובנות"]
    if plan.conversion:
        return ["מחקר", "כוונות", "רייטינג", "תובנות"]
    return []


def _doc_types_for_plan(plan: _RetrievalPlan) -> list[str]:
    if plan.event_intent == "launch":
        return ["השקה", "מחקר", "אסטרטגיה"]
    if plan.event_intent == "finale":
        return ["גמר", "אסטרטגיה"]
    if plan.conversion:
        return ["מחקר", "השקה"]
    return []


def _single_show_word_kwargs(plan: _RetrievalPlan) -> dict:
    """Scope Word retrieval to one show for single-show, non-comparison queries.

    Word-side counterpart of the complete Excel fetch. Without it, a thin
    single-show section (e.g. "חולי אהבה", which records very few numbers) ranks
    below richer, semantically-similar sections from OTHER dramas, so the LLM
    receives only other shows' chunks and mis-attributes their numbers
    (observed: פאלו אלטו's 29%/82% reported as חולי אהבה's). Filtering by
    show_name keeps retrieval on the requested show. Requires
    WORD_METADATA_FILTERS_ENABLED=true; otherwise search_word_docs ignores it.
    """
    if len(plan.show_names) == 1 and not plan.genres and not plan.comparison:
        return {"show_names": [plan.show_names[0]]}
    return {}


# ---------------------------------------------------------------------------
# Retriever  (private)
# ---------------------------------------------------------------------------

def _retrieve(route: str, query: str) -> _RetrievalResult:
    """Fetch docs for each route; return context string + raw docs.

    When the query contains a temporal qualifier ("last season", "first season"),
    we fetch a wider result set (top=15) and then filter to only the max/min
    season number found, so the LLM receives consistent, targeted evidence.
    """
    # Detect temporal ordering intent once, used by all routes below.
    # Ranking queries override season filtering — a "rank all seasons" question
    # must NOT be filtered to a single season.
    ranking_intent = bool(_RANKING_PATTERNS.search(query))
    if ranking_intent:
        # Never apply season filter for ranking — it would hide most of the data
        season_filter = None
    elif _LAST_SEASON_PATTERNS.search(query):
        season_filter = "last"
    elif _FIRST_SEASON_PATTERNS.search(query):
        season_filter = "first"
    else:
        season_filter = None

    plan = _build_retrieval_plan(route, query, ranking_intent, season_filter)

    # Route upgrade: cross-show / multi-show / genre-broad questions can fall to
    # the 'unknown' router branch (e.g. "דפוסים משותפים בכל התוכניות") or be
    # rigidly silo'd to 'excel_numeric' by a numeric trigger word (e.g.
    # "ממוצע השלמות בסדרה X") even though the retrieval planner correctly
    # detects broad_scope. Without this upgrade they bypass the Phase 6b
    # broad-Word retrieval entirely and end up with Excel-only context for
    # questions whose answer lives in Word docs.
    if plan.broad_scope and (
        route == "unknown"
        or (route == "excel_numeric" and plan.genres)
    ):
        log.info(
            "  Route upgrade: %s → hybrid (broad_scope + %s)",
            route,
            "genre-aware" if plan.genres else "multi-source",
        )
        route = "hybrid"
        plan.route = "hybrid"

    if plan.broad_scope:
        log.info(
            "  Retrieval plan: broad=%s route=%s shows=%s genres=%s event=%s comparison=%s conversion=%s",
            plan.broad_scope, route, plan.show_names or "—", plan.genres or "—",
            plan.event_intent or "—", plan.comparison, plan.conversion,
        )

    # Use a filter-based fetch that returns ALL rows for a single show (not just
    # top-N semantic hits) whenever the question is about that show's ratings,
    # rankings, launch/finale, or a specific/last season. Semantic top-N
    # routinely misses the launch or finale row, which then breaks ranking,
    # min/max, per-season, and "rating of X" answers. The variable keeps the
    # name `ranking_show` for the downstream Excel-selection wiring.
    rating_intent = bool(_RATING_INTENT_PATTERNS.search(query))
    single_show = len(plan.show_names) == 1 and not plan.genres
    ranking_show: str | None = (
        plan.show_names[0]
        if single_show and (
            ranking_intent
            or rating_intent
            or plan.event_intent in ("launch", "finale", "tonight")
            or season_filter is not None
        )
        else None
    )

    # Use a wider fetch when we need to find extremes or rank across many rows.
    # When ranking_show is set, fetch_show_promos() is used instead (no top limit needed).
    if season_filter:
        excel_top = 15
    elif ranking_intent and not ranking_show:
        excel_top = 30   # fallback when show name not detected
    else:
        excel_top = 5
    # Strategic synthesis benefits from more chunks for cross-show context.
    # Other routes use fewer chunks to stay within latency/token budgets.
    # Target: keep typical input tokens under 6,000 (p90 was 9–13k before this).
    strategic_intent = bool(re.search(r"מה הייתי|מה היית|תמליץ|הצע|מה כדאי|כיצד הייתי|תחשוב מה", query))
    word_top = 12 if strategic_intent else 6

    def _fetch_excel() -> list[dict]:
        """Select the right Excel retrieval strategy for this query."""
        if plan.broad_excel:
            show_targets = plan.target_show_names
            if show_targets:
                docs = fetch_many_show_promos(show_targets, top_per_show=500)
                log.info(
                    "  broad show-filter fetch: %d show(s) → %d doc(s)",
                    len(show_targets), len(docs),
                )
                return docs
            log.info("  broad retrieval requested without catalog target → semantic fallback")
        if ranking_show:
            docs = fetch_show_promos(ranking_show, top=500)
            # A complete fetch ignores semantic ranking, so a "last/first season"
            # qualifier must still be applied here to narrow to the target season.
            if season_filter:
                docs = _filter_by_season_order(docs, season_filter)
            log.info("  show-filter fetch: show=%r → %d doc(s) (all rows, season_filter=%s)",
                     ranking_show, len(docs), season_filter or "none")
            return docs
        docs = search_excel_promos(query, top=excel_top)
        if season_filter:
            docs = _filter_by_season_order(docs, season_filter)
        return docs

    if route == "excel_numeric":
        docs = _fetch_excel()
        # Cap rows before formatting. The broad path already does this; the
        # ranking_show path previously dumped ALL rows (e.g. 188 deduped rows
        # for חתונה ממבט ראשון → 100k+ char context → exceeds token/TPM budget
        # → BadRequestError). _select_excel_rows_for_plan sorts by the ranking
        # metric, applies launch/finale/tonight intent filtering, and caps at 60.
        if plan.broad_excel or ranking_show:
            selected_docs = _select_excel_rows_for_plan(docs, plan)
        else:
            selected_docs = docs
        log.info("  Excel hits: %d (selected %d) | Word hits: 0 | season_filter=%s | ranking_show=%s",
                 len(docs), len(selected_docs), season_filter or "none", ranking_show or "none")
        if not docs:
            log.warning("  *** No Excel hits — answer will have no numeric evidence ***")
        if plan.broad_excel:
            context = _fmt_broad_excel_evidence(docs, selected_docs, plan)
        else:
            # ranking_show and plain numeric both format the (possibly capped)
            # selected rows.
            context = _fmt_excel(selected_docs)
        return _RetrievalResult(context=context, excel_docs=selected_docs)

    if route == "word_quote":
        word_kwargs = {}
        if plan.broad_word:
            word_kwargs = {
                "show_names": plan.target_show_names or None,
                "doc_types": _doc_types_for_plan(plan) or None,
                "question_types": _question_types_for_plan(plan) or None,
            }
        else:
            word_kwargs = _single_show_word_kwargs(plan)
        # When scoped to a single show (few chunks total), pull more of them so a
        # low-ranked but on-topic chunk (e.g. the promo-test result) isn't cut off.
        wt = 15 if word_kwargs.get("show_names") and not plan.broad_word else word_top
        docs = search_word_docs(query, top=wt, **word_kwargs)
        if season_filter:
            docs = _rerank_word_docs_by_season(docs, season_filter)
        log.info("  Word hits: %d | Excel hits: 0", len(docs))
        if not docs:
            log.warning("  *** No Word hits — answer will have no document evidence ***")
        else:
            titles = [d.get("title") or "(no title)" for d in docs]
            log.info("  Word sources: %s", ", ".join(titles))

        if _needs_sharepoint_enrichment(route, docs):
            show_name = _extract_show_name(query)
            top_score = float(docs[0].get("score") or 0) if docs else 0.0
            caption   = (docs[0].get("caption") or "").strip() if docs else ""
            log.info(
                "  SP enrichment triggered: route=%s show=%r score=%.2f caption=%s",
                route, show_name, top_score, bool(caption),
            )
            sp_docs = _fetch_sharepoint_enrichment(query, show_name)
            # Dedup: drop SP docs whose title already appears in Azure word results
            azure_titles = {(d.get("title") or "").lower() for d in docs if d.get("title")}
            sp_docs = [d for d in sp_docs if (d.get("title") or "").lower() not in azure_titles]
            if sp_docs:
                sp_section = (
                    "\n\n=== מסמכי SharePoint (תובנות ומחקר) ===\n\n"
                    + _fmt_sharepoint(sp_docs)
                )
                log.info("  SP enrichment: %d doc(s) returned, folder=%r", len(sp_docs), show_name)
                return _RetrievalResult(
                    context=_fmt_word(docs) + sp_section,
                    word_docs=docs,
                    sharepoint_docs=sp_docs,
                )
            else:
                log.info("  SP enrichment: 0 doc(s) after dedup/empty, folder=%r", show_name)

        return _RetrievalResult(context=_fmt_word(docs), word_docs=docs)

    if route == "hybrid":
        excel_docs = _fetch_excel()
        selected_excel_docs = _select_excel_rows_for_plan(excel_docs, plan) if plan.broad_excel else excel_docs
        word_kwargs = {}
        if plan.broad_word:
            word_kwargs = {
                "show_names": plan.target_show_names or None,
                "doc_types": _doc_types_for_plan(plan) or None,
                "question_types": _question_types_for_plan(plan) or None,
            }
        else:
            word_kwargs = _single_show_word_kwargs(plan)
        wt = 15 if word_kwargs.get("show_names") and not plan.broad_word else word_top
        word_docs  = search_word_docs(query, top=wt, **word_kwargs)
        if season_filter:
            word_docs = _rerank_word_docs_by_season(word_docs, season_filter)
        log.info("  Excel hits: %d | Word hits: %d | season_filter=%s | ranking_show=%s",
                 len(excel_docs), len(word_docs), season_filter or "none", ranking_show or "none")
        if word_docs:
            titles = [d.get("title") or "(no title)" for d in word_docs]
            log.info("  Word sources: %s", ", ".join(titles))

        sp_docs: list[dict] = []
        if _needs_sharepoint_enrichment(route, word_docs):
            show_name = _extract_show_name(query)
            top_score = float(word_docs[0].get("score") or 0) if word_docs else 0.0
            caption   = (word_docs[0].get("caption") or "").strip() if word_docs else ""
            log.info(
                "  SP enrichment triggered: route=%s show=%r score=%.2f caption=%s",
                route, show_name, top_score, bool(caption),
            )
            sp_docs = _fetch_sharepoint_enrichment(query, show_name)
            azure_titles = {(d.get("title") or "").lower() for d in word_docs if d.get("title")}
            sp_docs = [d for d in sp_docs if (d.get("title") or "").lower() not in azure_titles]
            if sp_docs:
                log.info("  SP enrichment: %d doc(s) returned, folder=%r", len(sp_docs), show_name)
            else:
                log.info("  SP enrichment: 0 doc(s) after dedup/empty, folder=%r", show_name)

        sp_section = (
            "\n\n=== מסמכי SharePoint (תובנות ומחקר) ===\n\n" + _fmt_sharepoint(sp_docs)
            if sp_docs else ""
        )
        ctx = (
            "=== נתוני Excel ===\n\n"
            f"{_fmt_broad_excel_evidence(excel_docs, selected_excel_docs, plan) if plan.broad_excel else _fmt_excel(excel_docs)}\n\n"
            "=== מסמכי Word ===\n\n"
            f"{_fmt_word(word_docs)}"
            f"{sp_section}"
        )
        return _RetrievalResult(context=ctx, excel_docs=selected_excel_docs, word_docs=word_docs, sharepoint_docs=sp_docs)

    # unknown — shallow search on both, model instructed to be cautious
    log.info("Route unknown — shallow retrieval from both indexes (top=3 each)")
    excel_docs = search_excel_promos(query, top=3)
    word_docs  = search_word_docs(query, top=3)
    log.info("  Excel hits: %d | Word hits: %d", len(excel_docs), len(word_docs))
    ctx = (
        "=== נתוני Excel (חיפוש כללי) ===\n\n"
        f"{_fmt_excel(excel_docs)}\n\n"
        "=== מסמכי Word (חיפוש כללי) ===\n\n"
        f"{_fmt_word(word_docs)}"
    )
    return _RetrievalResult(context=ctx, excel_docs=excel_docs, word_docs=word_docs)


# ---------------------------------------------------------------------------
# Hebrew language guard
# ---------------------------------------------------------------------------

_HEBREW_CHAR_RE = re.compile(r'[\u05d0-\u05fa]')

_HEBREW_REJECTION = "אנא שאל בעברית."


def _is_hebrew_query(text: str) -> bool:
    """Return True when the query contains at least one Hebrew character."""
    return bool(_HEBREW_CHAR_RE.search(text.strip()))


# ---------------------------------------------------------------------------
# Source metadata  (private)
# ---------------------------------------------------------------------------

def _build_sources(retrieval: _RetrievalResult) -> list[SourceDoc]:
    sources: list[SourceDoc] = []
    for d in retrieval.excel_docs:
        sources.append(SourceDoc(
            type="excel",
            title=d.get("tab_name") or d.get("source_file") or "",
            reference=f"{d.get('show_name', '')} / עונה {d.get('season', '')} / {d.get('date', '')}".strip(" /"),
            score=float(d.get("score") or 0),
        ))
    for d in retrieval.word_docs:
        sources.append(SourceDoc(
            type="word",
            title=d.get("title") or "",
            reference=d.get("chunk_id") or "",
            score=float(d.get("score") or 0),
        ))
    for d in retrieval.sharepoint_docs:
        sources.append(SourceDoc(
            type="sharepoint",
            title=d.get("title") or "",
            reference=d.get("url") or "",
            score=float(d.get("score") or 1.0),
        ))
    # Highest-scoring first
    sources.sort(key=lambda s: s.score, reverse=True)
    return sources


def _confidence(sources: list[SourceDoc]) -> str:
    # Azure reranker scores are on a 0–4 scale (not 0–1)
    if not sources:
        return "low"
    top_score = sources[0].score
    if top_score >= 3.0:
        return "high"
    if top_score >= 2.0:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@_lf_observe(name="promobot-query", as_type="agent")
def run_query(
    question: str,
    debug: bool = False,
    history: list[dict] | None = None,
    session_id: str | None = None,
) -> QueryResponse:
    """Full pipeline: classify → retrieve → prompt → LLM → structured response.

    Parameters
    ----------
    question   : user question (any language, typically Hebrew)
    debug      : when True, the full retrieval context is included in the response
    history    : previous conversation turns [{"role": ..., "content": ...}]
    session_id : client-provided session identifier for Langfuse session grouping

    Returns
    -------
    QueryResponse with answer, route, confidence, sources, trace_id, lf_trace_id
    """
    trace_id = str(uuid.uuid4())
    log.info("[%s] question=%r  debug=%s", trace_id, question[:80], debug)

    # Attach session context to the Langfuse trace so multi-turn conversations group together.
    if _LF_AVAILABLE:
        if session_id:
            _otel_trace.get_current_span().set_attribute("session.id", session_id)
        _lf_get_client().update_current_span(input=question)

    # Step 0a — Hebrew language guard (before any retrieval to avoid wasting tokens)
    if not _is_hebrew_query(question):
        log.info("[%s] Non-Hebrew query rejected (no Hebrew chars detected)", trace_id)
        lf_trace_id: str | None = None
        if _LF_AVAILABLE:
            _lf = _lf_get_client()
            lf_trace_id = _lf.get_current_trace_id()
            _lf.update_current_span(
                output=_HEBREW_REJECTION,
                metadata={"route": "rejected_non_hebrew"},
            )
        return QueryResponse(
            answer=_HEBREW_REJECTION,
            route="rejected_non_hebrew",
            confidence="low",
            sources=[],
            trace_id=trace_id,
            lf_trace_id=lf_trace_id,
        )

    # Step 0b — expand team nicknames to official show names for better search recall
    expanded = _expand_aliases(question)
    if expanded != question:
        log.info("[%s] Alias expansion: %r → %r", trace_id, question[:60], expanded[:60])
    question = expanded

    # Step 1 — classify
    route_result = classify(question)
    route = route_result.route
    log.info("[%s] Route: %s | numeric=%s | quote=%s | analysis=%s",
             trace_id, route,
             route_result.numeric_hits  or "—",
             route_result.quote_hits    or "—",
             route_result.analysis_hits or "—")

    # Step 2 — retrieve from primary sources (Azure AI Search)
    try:
        retrieval = _retrieve(route, question)
    except EnvironmentError:
        raise  # bubble up — api.py returns 503
    except Exception as exc:
        log.error("[%s] Retrieval failed: %s", trace_id, exc, exc_info=True)
        raise RuntimeError(f"Azure Search error: {type(exc).__name__}") from exc

    # Step 2b — SharePoint fallback (complementary source)
    # Only called when primary retrieval found nothing in either Azure Search index.
    # This keeps latency impact zero for the vast majority of queries.
    if _is_context_insufficient(retrieval):
        log.info("[%s] Primary retrieval empty — trying SharePoint fallback", trace_id)
        sp_docs = _fetch_sharepoint_fallback(question, top=5)
        if sp_docs:
            retrieval.sharepoint_docs = sp_docs
            sp_section = (
                "=== מסמכי SharePoint (DocLib4) ===\n\n"
                f"{_fmt_sharepoint(sp_docs)}"
            )
            # Prepend SharePoint section; primary context already says "no results"
            retrieval = _RetrievalResult(
                context=sp_section,
                excel_docs=retrieval.excel_docs,
                word_docs=retrieval.word_docs,
                sharepoint_docs=sp_docs,
            )
            log.info("[%s] SharePoint fallback: %d doc(s)", trace_id, len(sp_docs))
        else:
            log.info("[%s] SharePoint fallback returned no results", trace_id)

    log.info("[%s] Context length: %d chars", trace_id, len(retrieval.context))
    log.debug("[%s] === FULL CONTEXT ===\n%s\n=== END ===", trace_id, retrieval.context)

    # Attach retrieval stats to the Langfuse trace for latency + coverage analysis.
    if _LF_AVAILABLE:
        _lf_get_client().update_current_span(
            metadata={
                "route": route,
                "retrieval_excel_docs": len(retrieval.excel_docs),
                "retrieval_word_docs": len(retrieval.word_docs),
                "retrieval_sp_docs": len(retrieval.sharepoint_docs),
                "context_chars": len(retrieval.context),
            }
        )

    # Step 3 — build messages (with conversation history if provided)
    messages = build_messages(route, retrieval.context, question, history=history)
    log.debug("[%s] === USER MESSAGE ===\n%s\n=== END ===",
              trace_id, messages[-1]["content"])

    # Step 4 — call LLM via configured provider
    provider = get_provider()
    log.info("[%s] Sending to provider: %s", trace_id, os.getenv("CHAT_PROVIDER", "azure_openai"))
    try:
        answer = provider.complete(messages)
    except Exception as exc:
        # BadRequestError typically means the context exceeded the model's
        # token limit (happens when word_top=10 returns very large chunks).
        # Retry once with the context trimmed to the first half of Word docs.
        exc_name = type(exc).__name__
        if "BadRequest" in exc_name or "context_length" in str(exc).lower() or "token" in str(exc).lower():
            log.warning("[%s] Context too large (%s) — retrying with trimmed context", trace_id, exc_name)
            try:
                trimmed_ctx = retrieval.context[:len(retrieval.context) // 2]
                messages_trimmed = build_messages(route, trimmed_ctx, question, history=history)
                answer = provider.complete(messages_trimmed)
                log.info("[%s] Retry with trimmed context succeeded", trace_id)
            except Exception as exc2:
                log.error("[%s] LLM call failed even after trim: %s", trace_id, exc2, exc_info=True)
                raise RuntimeError(f"LLM error: {type(exc2).__name__}") from exc2
        else:
            log.error("[%s] LLM call failed: %s", trace_id, exc, exc_info=True)
            raise RuntimeError(f"LLM error: {type(exc).__name__}") from exc
    # Step 4b — strip internal <thinking> block before returning to user
    answer = re.sub(r'<thinking>.*?</thinking>\s*', '', answer, flags=re.DOTALL).strip()

    log.info("[%s] Answer length: %d chars", trace_id, len(answer))

    # Step 5 — assemble response
    sources    = _build_sources(retrieval)
    confidence = _confidence(sources)

    lf_trace_id: str | None = None
    if _LF_AVAILABLE:
        _lf = _lf_get_client()
        lf_trace_id = _lf.get_current_trace_id()
        confidence_score = {"high": 1.0, "medium": 0.5, "low": 0.0}.get(confidence, 0.0)
        _lf.update_current_span(
            output=answer,
            metadata={
                "route": route,
                "confidence": confidence,
                "retrieval_excel_docs": len(retrieval.excel_docs),
                "retrieval_word_docs": len(retrieval.word_docs),
                "context_chars": len(retrieval.context),
            },
        )
        _lf.score_current_trace(
            name="retrieval-confidence",
            value=confidence_score,
            comment=f"{confidence} — top source score: {sources[0].score:.2f}" if sources else confidence,
        )

    return QueryResponse(
        answer=answer,
        route=route,
        confidence=confidence,
        sources=sources,
        trace_id=trace_id,
        lf_trace_id=lf_trace_id,
        debug_trace=retrieval.context if debug else None,
    )


def answer_question(user_query: str) -> str:
    """Backwards-compatible alias for run_query().

    Returns the answer string only.  Used by the CLI and the test suite.
    """
    return run_query(user_query).answer
