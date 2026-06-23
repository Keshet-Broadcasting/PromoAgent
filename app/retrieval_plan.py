"""
retrieval_plan.py

Intent-level retrieval planning for the Promo agent.

Responsibilities
----------------
- Compiled regex patterns for routing intent classification (ranking, rating,
  strategic, temporal, event, scope, coverage, launch, finale, tonight,
  conversion).
- _RetrievalResult dataclass: raw output container before formatting.
- _RetrievalPlan dataclass: intent-level plan built from route + query.
- _detect_event_intent() / _build_retrieval_plan(): planner functions.
- Plan-level helpers used by the retriever layer:
    _fmt_plan_targets, _fmt_broad_excel_evidence,
    _question_types_for_plan, _doc_types_for_plan,
    _single_show_word_kwargs.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .domain_catalog import (
    extract_show_names as _catalog_extract_show_names,
    genre_label,
    genres_for_query,
    official_show_names,
    shows_for_genres,
)
from .formatters import _fmt_excel

# Feature flag — read once at import time (same as service.py).
_BROAD_RETRIEVAL = os.getenv("BROAD_RETRIEVAL_ENABLED", "false").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# Compiled regex patterns for intent classification
# ---------------------------------------------------------------------------

_RANKING_PATTERNS = re.compile(
    r"הכי גבוה|הכי נמוך|הכי הרבה|הכי טוב|הכי גרוע"
    r"|טופ\s*\d*|top\s*\d*"
    r"|סדר לי|סדר את|דרג|דרוג"
    r"|הגבוה ביותר|הנמוך ביותר|הגבוהה ביותר|הנמוכה ביותר"
    r"|מוביל|מובילים|ראשון ב|אחרון ב"
    r"|מי הכי|מה הכי"
)

_RATING_INTENT_PATTERNS = re.compile(
    r"רייטינג|נקודת פתיחה|נקודות פתיחה|אחוזי צפייה|שֵיר|share"
)

_STRATEGIC_INTENT_PATTERNS = re.compile(
    r"מה הייתי|מה היית|תמליץ|הצע|מה כדאי|כיצד הייתי|תחשוב מה"
    r"|סכם|תובנות|פתרונות|דפוסים|מאפיין|מאפיינים"
)

_FOLLOWUP_CONTEXT_PATTERNS = re.compile(
    r"העונה\s+הזו|העונה\s+הזאת"
    r"|הקמפיין\s+הזה|הקמפיין\s+הזו|הקמפיין\s+הזאת"
    r"|השם\s+הזה|הפורמט\s+הזה"
    r"|התוכנית\s+הזו|התוכנית\s+הזאת|התכנית\s+הזו|התכנית\s+הזאת"
)

_CAMPAIGN_CONTEXT_TERMS: tuple[str, ...] = (
    "נבחרת החלומות",
    "VIP",
    "אולסטארס",
)

_LAST_SEASON_PATTERNS = re.compile(
    r"ה?עונה\s+האחרונה|עונה\s+אחרונה|עונה\s+הכי\s+אחרונה"
    r"|עונה\s+אחרון|עונה\s+עדכנית"
    r"|last\s+season|latest\s+season"
)
_FIRST_SEASON_PATTERNS = re.compile(
    r"ה?עונה\s+הראשונה|עונה\s+ראשונה|עונה\s+1\b"
    r"|first\s+season"
)

_BROAD_SCOPE_PATTERNS = re.compile(
    r"כל ה|כל ה?תוכניות|כל ה?סדרות|כל הדרמות|כל הריאליטי|לעומת|השווה|השוואה"
    r"|דפוסים|משותפים|רוחבי|מכפיל|יחס המרה|כוונות צפייה.*רייטינג|רייטינג.*כוונות צפייה"
)
_COVERAGE_INTENT_PATTERNS = re.compile(
    r"כל ה?דרמות|כל ה?תוכניות|כל ה?סדרות|כל ה?תכניות|כל ה?ריאליטי"
    r"|של כל ה|לכל אחת|לכל אחד|כל אחת מ|כל אחד מ"
)
_LAUNCH_EVENT_TERMS = r"השקה|השקת|פתיחה|פרק ראשון|פרק 1"
_NEW_SEASON_TERMS = r"לקראת\s+עונה\s+חדש(?:ה)?|עונה\s+חדש(?:ה)?|עונה\s+חוזרת"
_LAUNCH_PATTERNS = re.compile(f"{_LAUNCH_EVENT_TERMS}|{_NEW_SEASON_TERMS}")
_OPENING_METRIC_RE = re.compile(r"נקוד[התו]+\s+ה?פתיחה")
_FINALE_PATTERNS = re.compile(r"גמר|סיום|פרק סיום|פינאל")
_TONIGHT_PATTERNS = re.compile(r"טונייט|טונייטים|שוטף|פרומואים שוטפים")
_CONVERSION_PATTERNS = re.compile(
    r"מכפיל|יחס המרה|כוונות צפייה.*רייטינג|רייטינג.*כוונות צפייה"
)


# ---------------------------------------------------------------------------
# Dataclasses
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
    """Intent-level retrieval plan built before querying Azure Search."""
    route: str
    query: str
    show_names: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    event_intent: str | None = None
    broad_scope: bool = False
    comparison: bool = False
    conversion: bool = False
    ranking: bool = False
    coverage: bool = False
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
# Planner helpers
# ---------------------------------------------------------------------------

def _extract_show_names(query: str) -> list[str]:
    return _catalog_extract_show_names(query)


def _detect_event_intent(query: str) -> str | None:
    if _CONVERSION_PATTERNS.search(query):
        return "conversion"
    cleaned = _OPENING_METRIC_RE.sub(" ", query)
    if _LAUNCH_PATTERNS.search(cleaned):
        return "launch"
    if _FINALE_PATTERNS.search(cleaned):
        return "finale"
    if _TONIGHT_PATTERNS.search(query):
        return "tonight"
    return None


def _build_retrieval_plan(
    route: str,
    query: str,
    ranking: bool,
    season_filter: str | None,
) -> _RetrievalPlan:
    show_names   = _extract_show_names(query)
    genres       = genres_for_query(query)
    event_intent = _detect_event_intent(query)
    comparison   = bool(re.search(r"לעומת|השווה|השוואה|ביחס ל|בין", query)) or len(show_names) > 1
    conversion   = bool(_CONVERSION_PATTERNS.search(query))
    broad_scope  = (
        bool(_BROAD_SCOPE_PATTERNS.search(query))
        or len(show_names) > 1
        or (bool(genres) and len(show_names) == 0)
        or conversion
    )
    if ranking and len(show_names) <= 1 and not genres:
        broad_scope = False
    coverage = (
        bool(_COVERAGE_INTENT_PATTERNS.search(query))
        or (comparison and len(show_names) > 1)
    )
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
        coverage=coverage,
        season_filter=season_filter,
    )


# ---------------------------------------------------------------------------
# Plan-level formatting helpers (no Azure I/O)
# ---------------------------------------------------------------------------

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


def _fmt_broad_excel_evidence(
    docs: list[dict],
    selected: list[dict],
    plan: _RetrievalPlan,
) -> str:
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
        return ["אסטרטגיה", "שיקול", "חידושים", "תובנות", "מחקר", "כוונות"]
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
    """Scope Word retrieval to one show for single-show, non-comparison queries."""
    if len(plan.show_names) == 1 and not plan.genres and not plan.comparison:
        kwargs = {"show_names": [plan.show_names[0]]}
        if plan.event_intent != "tonight":
            doc_types = _doc_types_for_plan(plan)
            question_types = _question_types_for_plan(plan)
            if doc_types:
                kwargs["doc_types"] = doc_types
            if question_types:
                kwargs["question_types"] = question_types
        return kwargs
    return {}
