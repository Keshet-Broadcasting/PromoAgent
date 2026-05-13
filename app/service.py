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

from .chat_provider import get_provider
from .models import QueryResponse, SourceDoc
from .prompts import build_messages
from .query_router import classify
from .search_word_docs import fetch_show_promos, search_excel_promos, search_word_docs

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
    # Short name → full name as stored in the index
    # "פאלו אלטו" is stored as "אף אחד לא עוזב את פאלו אלטו"
    (re.compile(r"פאלו אלטו"),   "אף אחד לא עוזב את פאלו אלטו"),
]


def _expand_aliases(query: str) -> str:
    """Replace known team nicknames with the official show name.

    This improves Azure Search recall — the index stores the full official
    show name, so searching for a nickname can miss exact-field matches.
    The longer/more-specific alias must come first in _SHOW_ALIASES.
    """
    for pattern, official in _SHOW_ALIASES:
        query = pattern.sub(official, query)
    return query


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
    for show in sorted(_KNOWN_SHOWS, key=len, reverse=True):
        if show in query:
            return show
    return None


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
    excel_docs: list[dict] = field(default_factory=list)
    word_docs:  list[dict] = field(default_factory=list)


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
    lines = []
    for i, d in enumerate(docs, 1):
        parts = [f"[{i}]"]
        if d.get("tab_name"):
            parts.append(f"[מקור: {d['tab_name']}]")
        if d.get("show_name"):
            parts.append(f"תוכנית: {d['show_name']}")
        if d.get("season"):
            parts.append(f"עונה: {d['season']}")
        if d.get("episode_number"):
            parts.append(f"פרק: {d['episode_number']}")
        if d.get("date"):
            parts.append(f"תאריך: {d['date']}")
        if d.get("opening_point"):
            parts.append(f"נקודת פתיחה: {d['opening_point']}%")
        if d.get("rating"):
            parts.append(f"רייטינג ממוצע: {d['rating']}%")
        if d.get("competition"):
            parts.append(f"תחרות: {d['competition']}")
        if d.get("section"):
            parts.append(f"קטגוריה: {d['section']}")
        header = " | ".join(parts)
        text = (d.get("promo_text") or "").strip()[:500]
        lines.append(f"{header}\nטקסט: {text}")
    return "\n\n".join(lines)


def _fmt_word(docs: list[dict]) -> str:
    if not docs:
        return "לא נמצאו תוצאות רלוונטיות במסמכי Word."
    lines = []
    for i, d in enumerate(docs, 1):
        source   = d.get("title") or ""
        header   = d.get("header") or ""
        caption  = (d.get("caption") or "").strip()
        chunk    = (d.get("chunk") or "").strip()[:900]
        score    = d.get("score") or 0
        chunk_id = d.get("chunk_id") or ""
        pos      = _chunk_pos(chunk_id) if chunk_id else "—"

        meta = f"[{i}] [מקור: {source}] | קטע מס': {pos}"
        if header:
            meta += f" | פרק: {header}"
        meta += f" | רלוונטיות: {score:.2f}"

        parts = [meta]
        if caption:
            parts.append(f"ציטוט מודגש (Azure): {caption}")
        parts.append(f"תוכן מלא: {chunk}")
        lines.append("\n".join(parts))
    return "\n\n---\n\n".join(lines)


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

    # For ranking queries, detect a show name so we can use a filter-based
    # fetch that returns ALL rows for that show (not just top-30 semantic hits).
    ranking_show: str | None = _extract_show_name(query) if ranking_intent else None

    # Use a wider fetch when we need to find extremes or rank across many rows.
    # When ranking_show is set, fetch_show_promos() is used instead (no top limit needed).
    if season_filter:
        excel_top = 15
    elif ranking_intent and not ranking_show:
        excel_top = 30   # fallback when show name not detected
    else:
        excel_top = 5
    # 15 Word chunks gives richer cross-show context for strategic synthesis.
    # The retry mechanism in _call_llm handles the rare case where 15 chunks
    # exceed the context window.
    word_top = 15

    def _fetch_excel() -> list[dict]:
        """Select the right Excel retrieval strategy for this query."""
        if ranking_show:
            docs = fetch_show_promos(ranking_show, top=500)
            log.info("  show-filter fetch: show=%r → %d doc(s) (all rows)", ranking_show, len(docs))
            return docs
        docs = search_excel_promos(query, top=excel_top)
        if season_filter:
            docs = _filter_by_season_order(docs, season_filter)
        return docs

    if route == "excel_numeric":
        docs = _fetch_excel()
        log.info("  Excel hits: %d | Word hits: 0 | season_filter=%s | ranking_show=%s",
                 len(docs), season_filter or "none", ranking_show or "none")
        if not docs:
            log.warning("  *** No Excel hits — answer will have no numeric evidence ***")
        return _RetrievalResult(context=_fmt_excel(docs), excel_docs=docs)

    if route == "word_quote":
        docs = search_word_docs(query, top=word_top)
        log.info("  Word hits: %d | Excel hits: 0", len(docs))
        if not docs:
            log.warning("  *** No Word hits — answer will have no document evidence ***")
        else:
            titles = [d.get("title") or "(no title)" for d in docs]
            log.info("  Word sources: %s", ", ".join(titles))
        return _RetrievalResult(context=_fmt_word(docs), word_docs=docs)

    if route == "hybrid":
        excel_docs = _fetch_excel()
        word_docs  = search_word_docs(query, top=word_top)
        log.info("  Excel hits: %d | Word hits: %d | season_filter=%s | ranking_show=%s",
                 len(excel_docs), len(word_docs), season_filter or "none", ranking_show or "none")
        if word_docs:
            titles = [d.get("title") or "(no title)" for d in word_docs]
            log.info("  Word sources: %s", ", ".join(titles))
        ctx = (
            "=== נתוני Excel ===\n\n"
            f"{_fmt_excel(excel_docs)}\n\n"
            "=== מסמכי Word ===\n\n"
            f"{_fmt_word(word_docs)}"
        )
        return _RetrievalResult(context=ctx, excel_docs=excel_docs, word_docs=word_docs)

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
    # Highest-scoring first
    sources.sort(key=lambda s: s.score, reverse=True)
    return sources


def _confidence(sources: list[SourceDoc]) -> str:
    if not sources:
        return "low"
    top_score = sources[0].score
    if top_score >= 0.85:
        return "high"
    if top_score >= 0.50:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_query(
    question: str,
    debug: bool = False,
    history: list[dict] | None = None,
) -> QueryResponse:
    """Full pipeline: classify → retrieve → prompt → LLM → structured response.

    Parameters
    ----------
    question : user question (any language, typically Hebrew)
    debug    : when True, the full retrieval context is included in the response
    history  : previous conversation turns [{"role": ..., "content": ...}]

    Returns
    -------
    QueryResponse with answer, route, confidence, sources, trace_id
    """
    trace_id = str(uuid.uuid4())
    log.info("[%s] question=%r  debug=%s", trace_id, question[:80], debug)

    # Step 0 — expand team nicknames to official show names for better search recall
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

    # Step 2 — retrieve
    try:
        retrieval = _retrieve(route, question)
    except EnvironmentError:
        raise  # bubble up — api.py returns 503
    except Exception as exc:
        log.error("[%s] Retrieval failed: %s", trace_id, exc, exc_info=True)
        raise RuntimeError(f"Azure Search error: {type(exc).__name__}") from exc
    log.info("[%s] Context length: %d chars", trace_id, len(retrieval.context))
    log.debug("[%s] === FULL CONTEXT ===\n%s\n=== END ===", trace_id, retrieval.context)

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
    log.info("[%s] Answer length: %d chars", trace_id, len(answer))

    # Step 5 — assemble response
    sources    = _build_sources(retrieval)
    confidence = _confidence(sources)

    return QueryResponse(
        answer=answer,
        route=route,
        confidence=confidence,
        sources=sources,
        trace_id=trace_id,
        debug_trace=retrieval.context if debug else None,
    )


def answer_question(user_query: str) -> str:
    """Backwards-compatible alias for run_query().

    Returns the answer string only.  Used by the CLI and the test suite.
    """
    return run_query(user_query).answer
