"""
retriever.py

Azure Search retrieval layer for the Promo agent.

Responsibilities
----------------
- _fetch_word_docs : choose the right Word-retrieval strategy for a plan.
- _retrieve        : main dispatcher — builds a retrieval plan from route +
                     query, fetches Excel and/or Word documents, applies
                     intent-based filtering (launch/finale, season, VIP),
                     optionally enriches with SharePoint, and returns a
                     _RetrievalResult with a formatted context string.
"""

from __future__ import annotations

import logging
import re

from .excel_selector import (
    _EXCLUDE_LAUNCH_FINALE_RE,
    _PROMO_CONTENT_PATTERNS,
    _VIP_CAMPAIGN_PATTERNS,
    _filter_by_season_order,
    _filter_vip_campaign_excel_rows,
    _rerank_word_docs_by_season,
    _select_excel_rows_for_plan,
)
from .formatters import _fmt_excel, _fmt_sharepoint, _fmt_word
from .retrieval_plan import (
    _LAST_SEASON_PATTERNS,
    _FIRST_SEASON_PATTERNS,
    _RANKING_PATTERNS,
    _RATING_INTENT_PATTERNS,
    _STRATEGIC_INTENT_PATTERNS,
    _RetrievalPlan,
    _RetrievalResult,
    _build_retrieval_plan,
    _doc_types_for_plan,
    _fmt_broad_excel_evidence,
    _fmt_plan_targets,
    _question_types_for_plan,
    _single_show_word_kwargs,
)
from .search_word_docs import (
    fetch_many_show_promos,
    fetch_show_promos,
    fetch_word_docs_per_show,
    search_excel_promos,
    search_word_docs,
)
from .sharepoint_helper import (
    _fetch_sharepoint_enrichment,
    _needs_sharepoint_enrichment,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Word-document fetch strategy
# ---------------------------------------------------------------------------

def _fetch_word_docs(plan: _RetrievalPlan, query: str, word_top: int) -> list[dict]:
    """Choose the right Word-retrieval strategy for this plan.

    - broad + coverage → per-show fetch so every target show is represented.
    - broad (no coverage) → one filtered semantic search.
    - single show → scoped search, wider top.
    """
    if plan.broad_word:
        targets = plan.word_targets
        # Named-show-vs-genre comparisons must fetch per-show so every comparator
        # is represented, not only the explicitly named show.
        force_per_show = plan.coverage or (
            plan.comparison and bool(plan.genres) and bool(plan.show_names)
        )
        if force_per_show and len(targets) > 1:
            prefer = None
            if re.search(r"אסטרטגי|מכירה|סלוגן|בריף|פוזישנינג|מיצוב", query):
                prefer = ["אסטרטגיה", "סלוגן"]
            return fetch_word_docs_per_show(
                query,
                targets,
                top_per_show=1,
                max_total=20,
                prefer_question_types=prefer,
            )
        word_kwargs = {
            "show_names": targets or None,
            "doc_types":  _doc_types_for_plan(plan) or None,
            "question_types": _question_types_for_plan(plan) or None,
        }
    else:
        word_kwargs = _single_show_word_kwargs(plan)
    wt = 15 if word_kwargs.get("show_names") and not plan.broad_word else word_top
    return search_word_docs(query, top=wt, **word_kwargs)


# ---------------------------------------------------------------------------
# Main retrieval dispatcher
# ---------------------------------------------------------------------------

def _retrieve(
    route: str,
    query: str,
    extract_show_name_fn,
) -> _RetrievalResult:
    """Fetch docs for each route; return context string + raw docs.

    Parameters
    ----------
    route              : one of 'excel_numeric', 'word_quote', 'hybrid', 'unknown'
    query              : final retrieval query (already alias-expanded / contextualised)
    extract_show_name_fn : callable(query) -> str | None  (passed in to avoid circular import)
    """
    ranking_intent = bool(_RANKING_PATTERNS.search(query))
    if ranking_intent:
        season_filter = None
    elif _LAST_SEASON_PATTERNS.search(query):
        season_filter = "last"
    elif _FIRST_SEASON_PATTERNS.search(query):
        season_filter = "first"
    else:
        season_filter = None

    plan = _build_retrieval_plan(route, query, ranking_intent, season_filter)

    # Route upgrade: cross-show / genre-broad questions routed to 'unknown' or
    # 'excel_numeric' should see Word docs too.
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
            "  Retrieval plan: broad=%s route=%s shows=%s genres=%s event=%s "
            "comparison=%s conversion=%s",
            plan.broad_scope, route, plan.show_names or "—", plan.genres or "—",
            plan.event_intent or "—", plan.comparison, plan.conversion,
        )

    rating_intent = bool(_RATING_INTENT_PATTERNS.search(query))
    single_show = len(plan.show_names) == 1 and not plan.genres
    vip_campaign_excel_intent = bool(
        route == "hybrid"
        and single_show
        and _VIP_CAMPAIGN_PATTERNS.search(query)
        and _PROMO_CONTENT_PATTERNS.search(query)
    )
    ranking_show: str | None = (
        plan.show_names[0]
        if single_show and (
            ranking_intent
            or rating_intent
            or vip_campaign_excel_intent
            or plan.event_intent in ("launch", "finale", "tonight")
            or season_filter is not None
        )
        else None
    )

    if season_filter:
        excel_top = 15
    elif ranking_intent and not ranking_show:
        excel_top = 30
    else:
        excel_top = 5
    strategic_intent = bool(_STRATEGIC_INTENT_PATTERNS.search(query))
    word_top = 12 if strategic_intent else 6

    def _fetch_excel() -> list[dict]:
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
            if vip_campaign_excel_intent:
                docs = _filter_vip_campaign_excel_rows(docs, query)
            if season_filter:
                docs = _filter_by_season_order(docs, season_filter)
            log.info(
                "  show-filter fetch: show=%r → %d doc(s) (all rows, season_filter=%s)",
                ranking_show, len(docs), season_filter or "none",
            )
            return docs
        docs = search_excel_promos(query, top=excel_top)
        if season_filter:
            docs = _filter_by_season_order(docs, season_filter)
        return docs

    if route == "excel_numeric":
        docs = _fetch_excel()
        if plan.broad_excel or ranking_show:
            selected_docs = _select_excel_rows_for_plan(docs, plan)
        else:
            selected_docs = docs
        log.info(
            "  Excel hits: %d (selected %d) | Word hits: 0 | season_filter=%s | ranking_show=%s",
            len(docs), len(selected_docs), season_filter or "none", ranking_show or "none",
        )
        if not docs:
            log.warning("  *** No Excel hits — answer will have no numeric evidence ***")
        if plan.broad_excel:
            context = _fmt_broad_excel_evidence(docs, selected_docs, plan)
        else:
            context = _fmt_excel(selected_docs)
        return _RetrievalResult(context=context, excel_docs=selected_docs)

    if route == "word_quote":
        docs = _fetch_word_docs(plan, query, word_top)
        if season_filter:
            docs = _rerank_word_docs_by_season(docs, season_filter)
        log.info("  Word hits: %d | Excel hits: 0", len(docs))
        if not docs:
            log.warning("  *** No Word hits — answer will have no document evidence ***")
        else:
            titles = [d.get("title") or "(no title)" for d in docs]
            log.info("  Word sources: %s", ", ".join(titles))

        if _needs_sharepoint_enrichment(route, docs):
            show_name = extract_show_name_fn(query)
            top_score = float(docs[0].get("score") or 0) if docs else 0.0
            caption   = (docs[0].get("caption") or "").strip() if docs else ""
            log.info(
                "  SP enrichment triggered: route=%s show=%r score=%.2f caption=%s",
                route, show_name, top_score, bool(caption),
            )
            sp_docs = _fetch_sharepoint_enrichment(query, show_name)
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
        selected_excel_docs = (
            _select_excel_rows_for_plan(excel_docs, plan)
            if plan.broad_excel or ranking_show else excel_docs
        )
        word_docs = _fetch_word_docs(plan, query, word_top)
        if season_filter:
            word_docs = _rerank_word_docs_by_season(word_docs, season_filter)
        log.info(
            "  Excel hits: %d | Word hits: %d | season_filter=%s | ranking_show=%s",
            len(excel_docs), len(word_docs), season_filter or "none", ranking_show or "none",
        )
        if word_docs:
            titles = [d.get("title") or "(no title)" for d in word_docs]
            log.info("  Word sources: %s", ", ".join(titles))

        sp_docs: list[dict] = []
        if _needs_sharepoint_enrichment(route, word_docs):
            show_name = extract_show_name_fn(query)
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
        return _RetrievalResult(
            context=ctx,
            excel_docs=selected_excel_docs,
            word_docs=word_docs,
            sharepoint_docs=sp_docs,
        )

    # unknown — shallow search on both indexes; model instructed to be cautious
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
