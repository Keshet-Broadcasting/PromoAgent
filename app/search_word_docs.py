"""
search_word_docs.py

Search helper module for querying Azure AI Search indexes.

Functions
---------
search_word_docs(query, top)   — queries the "word-docs" index (Word documents)
search_excel_promos(query, top) — queries the "tv-promos" index (Excel promo data)
search_both(query, top)         — queries both indexes and returns combined results

Usage (CLI smoke-test)
----------------------
    python search_word_docs.py "האם מאסטר שף עונה 11 הייתה פופולרית?"
"""

from __future__ import annotations

import os
import sys
import logging
from collections.abc import Sequence

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import QueryType
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "")
_KEY = os.getenv("AZURE_SEARCH_KEY", "")

_WORD_DOCS_INDEX   = os.getenv("AZURE_SEARCH_WORD_INDEX",   "word-docs")
_PROMOS_INDEX      = os.getenv("AZURE_SEARCH_INDEX_NAME",   "tv-promos")
_WORD_SEMANTIC_CFG = os.getenv("AZURE_SEARCH_WORD_SEMANTIC_CONFIG",  "word-docs-semantic-config")
_PROMO_SEMANTIC_CFG = os.getenv("AZURE_SEARCH_PROMO_SEMANTIC_CONFIG", "promo-semantic-config")

_QUERY_LANGUAGE = "he-il"
_SEARCH_TIMEOUT = int(os.getenv("AZURE_SEARCH_TIMEOUT_SECONDS", "30"))
_WORD_METADATA_FILTERS_ENABLED = os.getenv("WORD_METADATA_FILTERS_ENABLED", "false").lower() in ("true", "1", "yes")

# SearchClient instances are reused across requests — creating a new client on
# every call incurs unnecessary TLS handshake + connection overhead.
_client_cache: dict[str, SearchClient] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _client(index_name: str) -> SearchClient:
    if index_name not in _client_cache:
        if not _ENDPOINT or not _KEY:
            raise EnvironmentError(
                "AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY must be set in .env"
            )
        _client_cache[index_name] = SearchClient(
            endpoint=_ENDPOINT,
            index_name=index_name,
            credential=AzureKeyCredential(_KEY),
            connection_timeout=_SEARCH_TIMEOUT,
            read_timeout=_SEARCH_TIMEOUT,
        )
    return _client_cache[index_name]


def _first_caption(result) -> str:
    captions = result.get("@search.captions") or []
    if captions:
        return captions[0].get("text", "") if isinstance(captions[0], dict) else getattr(captions[0], "text", "")
    return ""


def _escape_odata(value: str) -> str:
    return value.replace("'", "''")


def _or_filter(field: str, values: Sequence[str] | None) -> str:
    if not values:
        return ""
    parts = [f"{field} eq '{_escape_odata(str(value))}'" for value in values if str(value).strip()]
    return "(" + " or ".join(parts) + ")" if parts else ""


def _build_word_filter(
    show_names: Sequence[str] | None = None,
    seasons: Sequence[str | int] | None = None,
    doc_types: Sequence[str] | None = None,
    question_types: Sequence[str] | None = None,
    titles: Sequence[str] | None = None,
) -> str | None:
    """Build an OData filter for metadata fields added in the Phase 6b schema.

    Returns None when no filter is needed. The caller is responsible for only
    passing the filter to Azure Search when WORD_METADATA_FILTERS_ENABLED=true.
    """
    filters = [
        _or_filter("show_name", show_names),
        _or_filter("season", [str(s) for s in seasons] if seasons else None),
        _or_filter("doc_type", doc_types),
        _or_filter("question_type", question_types),
        _or_filter("title", titles),
    ]
    filters = [f for f in filters if f]
    return " and ".join(filters) if filters else None


# ---------------------------------------------------------------------------
# Public search functions
# ---------------------------------------------------------------------------


_ANSWER_SCORE_THRESHOLD = 0.85
"""Minimum @search.answers confidence to promote a chunk to the front of the
context list.  Answers below this score are still present in the value list if
they ranked in the top-N; they just don't get promoted ahead of other results."""


def search_word_docs(
    query: str,
    top: int = 5,
    *,
    show_names: Sequence[str] | None = None,
    seasons: Sequence[str | int] | None = None,
    doc_types: Sequence[str] | None = None,
    question_types: Sequence[str] | None = None,
    titles: Sequence[str] | None = None,
) -> list[dict]:
    """Query the 'word-docs' index with Hebrew semantic search.

    In addition to the standard reranked result list, Azure AI Search returns
    semantic answers in ``@search.answers``.  These are produced by a dedicated
    extraction pipeline and often surface the most directly relevant chunk even
    when it ranks outside the top-N by reranker score.

    Any answer whose confidence score is >= _ANSWER_SCORE_THRESHOLD is promoted
    to the front of the returned list so the LLM always sees the best direct-
    answer chunk first, regardless of where it landed in the reranker ranking.

    Metadata filters require WORD_METADATA_FILTERS_ENABLED=true and the Phase 6b
    word-docs schema fields to exist. When disabled, filter arguments are
    ignored so production does not break before the schema migration.

    Returns a list of dicts with keys:
        chunk_id, chunk, header, title, source_file, score, caption,
        show_name, season, doc_type, question_type
    """
    client = _client(_WORD_DOCS_INDEX)
    word_filter = _build_word_filter(
        show_names=show_names,
        seasons=seasons,
        doc_types=doc_types,
        question_types=question_types,
        titles=titles,
    )
    if word_filter and not _WORD_METADATA_FILTERS_ENABLED:
        logger.info("  Word metadata filter requested but WORD_METADATA_FILTERS_ENABLED=false; using unfiltered search.")
        word_filter = None

    select_fields = ["chunk_id", "chunk", "header", "title", "source_file"]
    if _WORD_METADATA_FILTERS_ENABLED:
        select_fields.extend(["show_name", "season", "doc_type", "question_type"])

    results = client.search(
        search_text=query,
        filter=word_filter,
        query_type=QueryType.SEMANTIC,
        semantic_configuration_name=_WORD_SEMANTIC_CFG,
        query_language=_QUERY_LANGUAGE,
        query_caption="extractive",
        query_answer="extractive|count-3",
        top=top,
        select=select_fields,
    )

    # Collect all value results, keyed by chunk_id.  Iterating the response
    # triggers the first-page fetch, which also populates @search.answers.
    by_id: dict[str, dict] = {}
    value_order: list[str] = []
    for r in results:
        chunk_id = r.get("chunk_id", "")
        by_id[chunk_id] = {
            "chunk_id":    chunk_id,
            "chunk":       r.get("chunk", ""),
            "header":      r.get("header", ""),
            "title":       r.get("title", ""),
            "source_file": r.get("source_file", ""),
            "show_name":   r.get("show_name", ""),
            "season":      r.get("season", ""),
            "doc_type":    r.get("doc_type", ""),
            "question_type": r.get("question_type", ""),
            "score":       r.get("@search.reranker_score") or r.get("@search.score", 0),
            "caption":     _first_caption(r),
        }
        value_order.append(chunk_id)

    # Promote high-confidence semantic answers to the front of the context list.
    promoted_ids: list[str] = []
    for answer in (results.get_answers() or []):
        score = getattr(answer, "score", 0) or 0
        if score < _ANSWER_SCORE_THRESHOLD:
            continue
        key = getattr(answer, "key", None)
        if not key or key in promoted_ids:
            continue
        if key not in by_id:
            # Chunk ranked outside top-N. Look up its full metadata via the
            # index so the LLM (and the eval's groundedness check) can see the
            # source. Without this enrichment the chunk would land with
            # title="" / show_name=""; the bot couldn't cite the doc by name
            # and groundedness markers like 'מסמך'/'docx' wouldn't appear in
            # the answer, even though the content IS from a real source.
            try:
                doc = client.get_document(key=key)
                by_id[key] = {
                    "chunk_id":    key,
                    "chunk":       doc.get("chunk") or getattr(answer, "text", "") or "",
                    "header":      doc.get("header", ""),
                    "title":       doc.get("title", ""),
                    "source_file": doc.get("source_file", ""),
                    "show_name":   doc.get("show_name", ""),
                    "season":      doc.get("season", ""),
                    "doc_type":    doc.get("doc_type", ""),
                    "question_type": doc.get("question_type", ""),
                    "score":       score,
                    "caption":     getattr(answer, "highlights", "") or "",
                }
                logger.debug(
                    "  @search.answers promoted (out-of-range, enriched): "
                    "key=%s score=%.3f title=%r",
                    key, score, by_id[key]["title"],
                )
            except Exception as exc:
                # If lookup fails (network, deleted doc, etc.), fall back to
                # the minimal-doc behavior so the chunk content still reaches
                # the LLM. Title will be missing but content is preserved.
                logger.warning(
                    "  @search.answers metadata lookup failed for key=%s (%s); "
                    "falling back to minimal doc",
                    key, type(exc).__name__,
                )
                by_id[key] = {
                    "chunk_id":    key,
                    "chunk":       getattr(answer, "text", "") or "",
                    "header":      "",
                    "title":       "",
                    "source_file": "",
                    "show_name":   "",
                    "season":      "",
                    "doc_type":    "",
                    "question_type": "",
                    "score":       score,
                    "caption":     getattr(answer, "highlights", "") or "",
                }
        else:
            # Already in value results; boost its recorded score so the source
            # confidence in the API response reflects the answer confidence.
            by_id[key]["score"] = max(by_id[key]["score"], score)
            logger.debug(
                "  @search.answers promoted (in-range): key=%s score=%.3f", key, score
            )
        promoted_ids.append(key)

    # Build final list: promoted chunks first, then remaining value docs in
    # their original reranker order.  Truncate to the requested top-N.
    promoted_set = set(promoted_ids)
    remaining = [by_id[k] for k in value_order if k not in promoted_set]
    return ([by_id[k] for k in promoted_ids if k in by_id] + remaining)[:top]


def search_excel_promos(query: str, top: int = 5) -> list[dict]:
    """Query the 'tv-promos' index with Hebrew semantic search.

    Returns a list of dicts with keys:
        show_name, season, episode_number, date, promo_text,
        opening_point, rating, competition, section, tab_name, score
    """
    client = _client(_PROMOS_INDEX)

    results = client.search(
        search_text=query,
        query_type=QueryType.SEMANTIC,
        semantic_configuration_name=_PROMO_SEMANTIC_CFG,
        query_language=_QUERY_LANGUAGE,
        query_caption="extractive",
        query_answer="extractive|count-3",
        top=top,
        select=[
            "show_name", "season", "episode_number", "date",
            "promo_text", "opening_point", "rating", "competition",
            "section", "source_file",
        ],
    )

    docs = []
    for r in results:
        docs.append({
            "show_name":      r.get("show_name", ""),
            "season":         r.get("season", ""),
            "episode_number": r.get("episode_number", ""),
            "date":           r.get("date", ""),
            "promo_text":     r.get("promo_text", ""),
            "opening_point":  r.get("opening_point", ""),
            "rating":         r.get("rating", ""),
            "competition":    r.get("competition", ""),
            "section":        r.get("section", ""),
            "tab_name":       r.get("source_file", ""),
            "score":          r.get("@search.reranker_score") or r.get("@search.score", 0),
        })
    return docs


def fetch_show_promos(show_name: str, season: str | None = None, top: int = 500) -> list[dict]:
    """Retrieve ALL promo rows for a specific show using an OData filter.

    Unlike search_excel_promos() (which uses semantic ranking and returns only
    the top-N most similar rows), this function returns every indexed row for
    the requested show — guaranteed complete coverage, no semantic cutoff.

    Used when ranking_intent is True and a show name is detected in the query,
    so that "rank all seasons" questions see every data point, not just the
    30 rows that happen to be semantically closest to the question text.

    Parameters
    ----------
    show_name : exact show name as stored in the index (case-sensitive)
    season    : optional exact season string (e.g. "5") — further filters to
                that season only; omit for cross-season ranking
    top       : max rows to return (default 500 — covers the largest shows)
    """
    client = _client(_PROMOS_INDEX)

    filter_expr = f"show_name eq '{_escape_odata(show_name)}'"
    if season:
        filter_expr += f" and season eq '{_escape_odata(season)}'"

    results = client.search(
        search_text="*",
        filter=filter_expr,
        top=top,
        select=[
            "show_name", "season", "episode_number", "date",
            "promo_text", "opening_point", "rating", "competition",
            "section", "source_file",
        ],
    )

    # Safety net: drop EXACT-duplicate rows (same show+season+episode+date+
    # promo_text), mirroring fetch_many_show_promos(). NOTE: this is NOT the
    # main fix for the high-row-show context overflow — verified that חתונה
    # ממבט ראשון's 362 rows are NOT exact duplicates (they're multiple distinct
    # promos per episode: same rating, different promo text/date). The real fix
    # for the token/TPM overflow is row-capping in service._retrieve(). This
    # dedup only removes genuine exact-dupes if the index ever has any.
    docs = []
    seen: set[tuple] = set()
    for r in results:
        key = (
            r.get("show_name", ""),
            r.get("season", ""),
            r.get("episode_number", ""),
            r.get("date", ""),
            r.get("promo_text", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        docs.append({
            "show_name":      r.get("show_name", ""),
            "season":         r.get("season", ""),
            "episode_number": r.get("episode_number", ""),
            "date":           r.get("date", ""),
            "promo_text":     r.get("promo_text", ""),
            "opening_point":  r.get("opening_point", ""),
            "rating":         r.get("rating", ""),
            "competition":    r.get("competition", ""),
            "section":        r.get("section", ""),
            "tab_name":       r.get("source_file", ""),
            "score":          1.0,  # filter-based — all rows are equally relevant
        })
    return docs


def fetch_many_show_promos(show_names: Sequence[str], top_per_show: int = 500) -> list[dict]:
    """Retrieve promo rows for multiple shows using exact show_name filters."""
    docs: list[dict] = []
    seen: set[tuple] = set()
    for show_name in show_names:
        for doc in fetch_show_promos(show_name, top=top_per_show):
            key = (
                doc.get("show_name"),
                doc.get("season"),
                doc.get("episode_number"),
                doc.get("date"),
                doc.get("promo_text"),
            )
            if key in seen:
                continue
            seen.add(key)
            docs.append(doc)
    return docs


def search_both(query: str, top: int = 5) -> dict:
    """Query both indexes and return combined results.

    Returns:
        {
            "word_docs":     [list from search_word_docs],
            "excel_promos":  [list from search_excel_promos],
        }
    """
    return {
        "word_docs":    search_word_docs(query, top=top),
        "excel_promos": search_excel_promos(query, top=top),
    }


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------


def _print_word_docs(docs: list[dict]) -> None:
    logger.info(f"\n{'='*60}")
    logger.info(f"  WORD-DOCS results ({len(docs)} hits)")
    logger.info(f"{'='*60}")
    for i, d in enumerate(docs, 1):
        logger.info(f"\n[{i}] {d['title']}  |  header: {d['header'] or '—'}  |  score: {d['score']:.3f}")
        if d["caption"]:
            logger.info(f"    Caption: {d['caption']}")
        snippet = d["chunk"][:200].replace("\n", " ")
        logger.info(f"    Chunk:   {snippet}{'…' if len(d['chunk']) > 200 else ''}")


def _print_excel_promos(docs: list[dict]) -> None:
    logger.info(f"\n{'='*60}")
    logger.info(f"  TV-PROMOS (Excel) results ({len(docs)} hits)")
    logger.info(f"{'='*60}")
    for i, d in enumerate(docs, 1):
        logger.info(
            f"\n[{i}] {d['show_name']} עונה {d['season']}  |  {d['date']}"
            f"  |  section: {d['section'] or '—'}  |  rating: {d['rating'] or '—'}"
            f"  |  score: {d['score']:.3f}"
        )
        snippet = d["promo_text"][:200].replace("\n", " ")
        logger.info(f"    Promo:   {snippet}{'…' if len(d['promo_text']) > 200 else ''}")


if __name__ == "__main__":
    # Ensure Hebrew prints correctly in Windows terminals
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    query = sys.argv[1] if len(sys.argv) > 1 else "האם מאסטר שף עונה 11 הייתה פופולרית?"
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    logger.info(f"\nQuery: {query}  (top={top})")

    combined = search_both(query, top=top)
    _print_word_docs(combined["word_docs"])
    _print_excel_promos(combined["excel_promos"])
