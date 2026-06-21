"""
excel_selector.py

Excel row selection, date parsing, launch/finale detection, season filtering,
and VIP-campaign targeting for the Promo agent.

Responsibilities
----------------
- Parse Israeli date strings (DD.M[.YYYY]) into sortable tuples.
- Tag each Excel row as launch / finale / regular within its (show, season) group.
- Filter rows to a target season order (first / last) per show.
- Re-rank Word doc chunks by detected season number.
- Identify and narrow to VIP campaign rows (with legacy-index fallback).
- Select and cap the final set of rows for the LLM context budget.

All functions are pure or close to pure — no Azure I/O, no LLM calls.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# VIP / promo-content patterns (used by _filter_vip_campaign_excel_rows)
# ---------------------------------------------------------------------------

_PROMO_CONTENT_PATTERNS = re.compile(r"בפרומו|פרומואים|פרומו|מנות|אוכל|קולינר")
_VIP_CAMPAIGN_PATTERNS  = re.compile(r"\bVIP\b|וי\s?איי\s?פי|נבחרת\s+החלומות")

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?")


def _parse_date_key(value) -> tuple[int, int, int] | None:
    """Parse a promo date into a sortable (year, month, day) tuple, or None."""
    if not value:
        return None
    m = _DATE_RE.search(str(value))
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    year = m.group(3)
    if year:
        year = int(year)
        if year < 100:
            year += 2000
    else:
        year = 0
    return (year, month, day)


# ---------------------------------------------------------------------------
# Scalar coercions
# ---------------------------------------------------------------------------

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


def _season_as_int(season_val) -> int:
    """Parse a season value (int, float, or string) to int for sorting. Returns -1 on failure."""
    try:
        text = str(season_val).strip()
        match = re.search(r"\d+", text)
        if match:
            return int(match.group(0))
        return int(float(text))
    except (ValueError, TypeError):
        return -1


def _doc_text(doc: dict) -> str:
    return " ".join(
        str(doc.get(k) or "")
        for k in ("promo_text", "section", "tab_name", "source_file")
    )


# ---------------------------------------------------------------------------
# Sort metric
# ---------------------------------------------------------------------------

def _sort_metric(doc: dict) -> float:
    return (
        _as_float(doc.get("opening_point"))
        or _as_float(doc.get("opening_rating"))
        or _as_float(doc.get("rating"))
        or _as_float(doc.get("average_rating"))
        or 0.0
    )


# ---------------------------------------------------------------------------
# Launch / finale tagging
# ---------------------------------------------------------------------------

def _mark_launch_finale(docs: list[dict]) -> None:
    """Tag each row's _role by date within its (show, season) group.

    episode_number is blank on ~65 % of rows, so the only reliable per-row
    signal for launch/finale is the date: earliest = launch, latest = finale.
    Sets doc['_role'] in-place.  Groups with fewer than 2 dated rows are left
    untouched (the text/episode heuristics in _is_launch_row / _is_finale_row
    still apply).
    """
    groups: dict[tuple, list[tuple]] = defaultdict(list)
    for d in docs:
        k = _parse_date_key(d.get("date"))
        if k is not None:
            groups[(d.get("show_name", ""), str(d.get("season") or ""))].append((k, d))

    for members in groups.values():
        if len(members) < 2:
            continue
        years = [k[0] for k, _ in members if k[0]]
        ref_year = max(set(years), key=years.count) if years else 0
        norm = [((k[0] or ref_year, k[1], k[2]), d) for k, d in members]
        dates = [nk for nk, _ in norm]
        min_d, max_d = min(dates), max(dates)
        if min_d == max_d:
            continue
        for _, d in norm:
            d["_role"] = "regular"
        launch = max((d for nk, d in norm if nk == min_d), key=_sort_metric)
        finale = max((d for nk, d in norm if nk == max_d), key=_sort_metric)
        launch["_role"] = "launch"
        finale["_role"] = "finale"


def _is_launch_row(doc: dict) -> bool:
    if doc.get("_role"):
        return doc["_role"] == "launch"
    episode = _episode_as_int(doc.get("episode_number") or doc.get("episode"))
    return episode == 1 or "השק" in _doc_text(doc)


def _is_finale_row(doc: dict) -> bool:
    if doc.get("_role"):
        return doc["_role"] == "finale"
    text = _doc_text(doc)
    return "גמר" in text or "סיום" in text or "פינאל" in text


# ---------------------------------------------------------------------------
# Season-order filters
# ---------------------------------------------------------------------------

def _filter_by_season_order(docs: list[dict], prefer: str) -> list[dict]:
    """Keep only the max (prefer='last') or min (prefer='first') season per show.

    Shows without a parseable season field are kept untouched so that shows
    like 'המירוץ למיליון' (season column omitted) are not silently discarded.
    """
    if not docs:
        return docs

    by_show: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        by_show[d.get("show_name") or ""].append(d)

    result: list[dict] = []
    for show_name, show_docs in by_show.items():
        seasons = [_season_as_int(d.get("season")) for d in show_docs]
        valid_seasons = [s for s in seasons if s >= 0]
        if not valid_seasons:
            result.extend(show_docs)
            log.info(
                "  Temporal filter '%s': show=%r has no season numbers — kept %d doc(s)",
                prefer, show_name, len(show_docs),
            )
            continue
        target = max(valid_seasons) if prefer == "last" else min(valid_seasons)
        filtered = [d for d in show_docs if _season_as_int(d.get("season")) == target]
        kept = filtered if filtered else show_docs
        result.extend(kept)
        log.info(
            "  Temporal filter '%s': show=%r keeping season %d (%d/%d doc(s))",
            prefer, show_name, target, len(kept), len(show_docs),
        )

    return result if result else docs


def _filter_vip_campaign_excel_rows(docs: list[dict], query: str) -> list[dict]:
    """Prefer populated VIP-season Excel rows for explicit VIP campaign queries."""
    if not docs or not _VIP_CAMPAIGN_PATTERNS.search(query):
        return docs

    vip_docs = [
        doc for doc in docs
        if "VIP" in str(doc.get("season") or "") and (doc.get("promo_text") or "").strip()
    ]
    if vip_docs:
        latest_vip_season = max(_season_as_int(doc.get("season")) for doc in vip_docs)
        filtered = [
            doc for doc in vip_docs
            if _season_as_int(doc.get("season")) == latest_vip_season
        ]
        if filtered:
            return filtered

    # Fallback for legacy indexes where "מאסטר שף עונה 11 VIP" was stored as
    # season "11" before the ingestion fix preserved the VIP suffix.
    campaign_season_hints = {"נבחרת החלומות": 11}
    for term, season in campaign_season_hints.items():
        if term not in query:
            continue
        hinted_docs = [
            doc for doc in docs
            if _season_as_int(doc.get("season")) == season and (doc.get("promo_text") or "").strip()
        ]
        if hinted_docs:
            return hinted_docs

    return docs


# ---------------------------------------------------------------------------
# Word doc season re-ranking
# ---------------------------------------------------------------------------

def _max_season_in_text(text: str) -> int:
    """Return the highest 'עונה N' number found in text, or -1."""
    seasons = [int(m) for m in re.findall(r"עונה\s+(\d+)", text)]
    return max(seasons) if seasons else -1


def _rerank_word_docs_by_season(docs: list[dict], prefer: str) -> list[dict]:
    """Re-sort Word doc chunks so the highest (prefer='last') or lowest
    (prefer='first') season appears first, breaking ties by original score.
    """
    if not docs:
        return docs

    def sort_key(d: dict):
        chunk_text = (d.get("chunk") or "") + " " + (d.get("caption") or "")
        season = _max_season_in_text(chunk_text)
        score = float(d.get("score") or 0)
        if season < 0:
            return (1, 0, -score)
        if prefer == "last":
            return (0, -season, -score)
        return (0, season, -score)

    reranked = sorted(docs, key=sort_key)
    if reranked != docs:
        top_before = _max_season_in_text(
            (docs[0].get("chunk") or "") + " " + (docs[0].get("caption") or "")
        )
        top_after = _max_season_in_text(
            (reranked[0].get("chunk") or "") + " " + (reranked[0].get("caption") or "")
        )
        log.info(
            "  Word temporal rerank (%s): top season before=%s → after=%s",
            prefer,
            top_before if top_before >= 0 else "?",
            top_after  if top_after  >= 0 else "?",
        )
    return reranked


# ---------------------------------------------------------------------------
# Excel row selection for context budget
# ---------------------------------------------------------------------------

# "except launch and finale" / "regular only" — drops BOTH.
_EXCLUDE_LAUNCH_FINALE_RE = re.compile(
    r"למעט.{0,15}(?:השק|גמר)|חוץ מ.{0,15}(?:השק|גמר)|פרט ל.{0,10}(?:השק|גמר)"
    r"|לא כולל.{0,15}(?:השק|גמר)|(?:except|excluding).{0,15}(?:launch|finale)"
)


def _select_excel_rows_for_plan(docs: list[dict], plan, limit: int = 60) -> list[dict]:
    """Filter and cap Excel rows to match the retrieval plan intent."""
    if not docs:
        return []

    _mark_launch_finale(docs)

    if _EXCLUDE_LAUNCH_FINALE_RE.search(plan.query):
        selected = [d for d in docs if not _is_launch_row(d) and not _is_finale_row(d)]
    elif plan.event_intent in ("launch", "conversion"):
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
