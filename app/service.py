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
import uuid
from dataclasses import dataclass, field

from dotenv import load_dotenv

from .chat_provider import get_provider
from .models import QueryResponse, SourceDoc
from .prompts import build_messages
from .query_router import classify
from .search_word_docs import search_excel_promos, search_word_docs

load_dotenv()

log = logging.getLogger(__name__)


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
        if d.get("date"):
            parts.append(f"תאריך: {d['date']}")
        if d.get("rating"):
            parts.append(f"רייטינג: {d['rating']}")
        if d.get("section"):
            parts.append(f"נקודת פתיחה / קטגוריה: {d['section']}")
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
    """Fetch docs for each route; return context string + raw docs."""
    if route == "excel_numeric":
        docs = search_excel_promos(query, top=5)
        log.info("  Excel hits: %d | Word hits: 0", len(docs))
        if not docs:
            log.warning("  *** No Excel hits — answer will have no numeric evidence ***")
        return _RetrievalResult(context=_fmt_excel(docs), excel_docs=docs)

    if route == "word_quote":
        docs = search_word_docs(query, top=5)
        log.info("  Word hits: %d | Excel hits: 0", len(docs))
        if not docs:
            log.warning("  *** No Word hits — answer will have no document evidence ***")
        else:
            titles = [d.get("title") or "(no title)" for d in docs]
            log.info("  Word sources: %s", ", ".join(titles))
        return _RetrievalResult(context=_fmt_word(docs), word_docs=docs)

    if route == "hybrid":
        excel_docs = search_excel_promos(query, top=4)
        word_docs  = search_word_docs(query, top=4)
        log.info("  Excel hits: %d | Word hits: %d", len(excel_docs), len(word_docs))
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

def run_query(question: str, debug: bool = False) -> QueryResponse:
    """Full pipeline: classify → retrieve → prompt → LLM → structured response.

    Parameters
    ----------
    question : user question (any language, typically Hebrew)
    debug    : when True, the full retrieval context is included in the response

    Returns
    -------
    QueryResponse with answer, route, confidence, sources, trace_id
    """
    trace_id = str(uuid.uuid4())
    log.info("[%s] question=%r  debug=%s", trace_id, question[:80], debug)

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

    # Step 3 — build messages
    messages = build_messages(route, retrieval.context, question)
    log.debug("[%s] === USER MESSAGE ===\n%s\n=== END ===",
              trace_id, messages[-1]["content"])

    # Step 4 — call LLM via configured provider
    provider = get_provider()
    log.info("[%s] Sending to provider: %s", trace_id, os.getenv("CHAT_PROVIDER", "azure_openai"))
    try:
        answer = provider.complete(messages)
    except Exception as exc:
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
