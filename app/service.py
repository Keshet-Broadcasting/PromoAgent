"""
service.py  — Promo agent pipeline orchestrator.

Responsibilities
----------------
Public entry points only: run_query() / answer_question().
All retrieval, formatting, and planning logic lives in the sub-modules below.

Sub-modules
-----------
  formatters.py        content-filter sanitizer + context formatters
  excel_selector.py    date/launch/season/VIP row selection
  retrieval_plan.py    intent patterns + _RetrievalPlan dataclass + planner
  sharepoint_helper.py SP fallback / enrichment helpers
  retriever.py         _retrieve dispatcher + _fetch_word_docs
"""

from __future__ import annotations

import logging
import os
import re
import uuid

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
from .domain_catalog import expand_aliases as _catalog_expand_aliases
from .search_word_docs import fetch_show_promos, search_excel_promos, search_word_docs
from .formatters import _fmt_sharepoint
from .excel_selector import (          # re-exported: tests import via svc.*
    _parse_date_key,
    _mark_launch_finale,
    _is_launch_row,
    _is_finale_row,
    _select_excel_rows_for_plan,
)
from .retrieval_plan import (          # re-exported: tests import via svc.*
    _STRATEGIC_INTENT_PATTERNS,
    _FOLLOWUP_CONTEXT_PATTERNS,
    _CAMPAIGN_CONTEXT_TERMS,
    _RetrievalResult,
    _RetrievalPlan,
    _extract_show_names,
    _build_retrieval_plan,
)
from .sharepoint_helper import (
    _is_context_insufficient,
    _fetch_sharepoint_fallback,
)
from .retriever import _retrieve as _retrieve_impl


load_dotenv()

log = logging.getLogger(__name__)

# Warn loudly when broad retrieval is off — a silent default caused the
# 2026-06-03 genre-contamination bug in production.
if os.getenv("BROAD_RETRIEVAL_ENABLED", "false").lower() not in ("true", "1", "yes"):
    log.warning(
        "BROAD_RETRIEVAL_ENABLED is OFF — genre/show retrieval filtering is "
        "disabled. Set BROAD_RETRIEVAL_ENABLED=true to enable."
    )


def _expand_aliases(query: str) -> str:
    return _catalog_expand_aliases(query)


def _extract_show_name(query: str) -> str | None:
    """Return the first known show name found in the query (longest match wins)."""
    matches = _extract_show_names(query)
    return matches[0] if matches else None



_HISTORY_CONTEXT_MAX_CHARS = 600
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _safe_history_content(turn: object) -> str:
    """Return bounded text from a history turn for retrieval-only context."""
    if not isinstance(turn, dict):
        return ""
    content = turn.get("content")
    if content is None:
        return ""
    text = _CONTROL_CHARS_RE.sub(" ", str(content))
    return text[:_HISTORY_CONTEXT_MAX_CHARS]


def _contextualize_followup_query(query: str, history: list[object] | None) -> str:
    """Append recent campaign context for retrieval when the user uses anaphora.

    The UI-visible question remains unchanged; this enriched string is only used
    for classification/retrieval so follow-ups like "העונה הזו" can search with
    the show/campaign from the previous turn.
    """
    if not history or not _FOLLOWUP_CONTEXT_PATTERNS.search(query):
        return query

    # If the user already named the show in this turn, the retrieval query is
    # self-contained and does not need history-derived context.
    if _extract_show_names(query):
        return query

    recent_turns = history[-6:]
    recent_text = " ".join(
        _expand_aliases(text)
        for text in (_safe_history_content(turn) for turn in recent_turns)
        if text
    )

    context_terms: list[str] = []
    for show_name in _extract_show_names(recent_text):
        if show_name not in context_terms:
            context_terms.append(show_name)
    for term in _CAMPAIGN_CONTEXT_TERMS:
        if term in recent_text and term not in context_terms:
            context_terms.append(term)

    if not context_terms:
        return query

    return f"{query} (בהקשר מהשיחה הקודמת: {', '.join(context_terms)})"










def _retrieve(route: str, query: str) -> _RetrievalResult:
    return _retrieve_impl(route, query, _extract_show_name)


_HEBREW_CHAR_RE  = re.compile(r'[\u05d0-\u05fa]')
_HEBREW_REJECTION = "אנא שאל בעברית."


def _is_hebrew_query(text: str) -> bool:
    return bool(_HEBREW_CHAR_RE.search(text.strip()))

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

    # Step 0c — enrich retrieval-only query for follow-ups like "העונה הזו".
    # The user-facing prompt still receives the original current question.
    retrieval_query = _contextualize_followup_query(question, history)
    if retrieval_query != question:
        log.info(
            "[%s] Retrieval query contextualized: %r → %r",
            trace_id,
            question[:80],
            retrieval_query[:120],
        )

    # Step 1 — classify
    route_result = classify(retrieval_query)
    route = route_result.route
    log.info("[%s] Route: %s | numeric=%s | quote=%s | analysis=%s",
             trace_id, route,
             route_result.numeric_hits  or "—",
             route_result.quote_hits    or "—",
             route_result.analysis_hits or "—")

    # Step 2 — retrieve from primary sources (Azure AI Search)
    try:
        retrieval = _retrieve(route, retrieval_query)
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
        sp_docs = _fetch_sharepoint_fallback(retrieval_query, top=5)
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
