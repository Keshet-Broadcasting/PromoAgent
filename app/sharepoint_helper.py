"""
sharepoint_helper.py

SharePoint fallback and enrichment helpers for the Promo agent.

Responsibilities
----------------
- Lazy-import the optional SharePoint client (absent in CI / unit tests).
- _is_context_insufficient : decide whether primary retrieval needs a fallback.
- _fetch_sharepoint_fallback : generic SP search when Azure indexes return nothing.
- _needs_sharepoint_enrichment : decide whether to augment a low-confidence result.
- _fetch_sharepoint_enrichment : targeted SP search scoped to a show folder.

All public functions return [] and never raise, so callers need no try/except.
"""

from __future__ import annotations

import logging
import os

from .retrieval_plan import _RetrievalResult

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional SharePoint client import
# ---------------------------------------------------------------------------
try:
    from .tools.sharepoint_tool import get_sharepoint_client as _get_sp_client
    _SP_AVAILABLE = True
except ImportError:
    _SP_AVAILABLE = False

# ---------------------------------------------------------------------------
# Feature flags (read once at import; same keys as service.py)
# ---------------------------------------------------------------------------
_SP_ENRICHMENT      = os.getenv("SP_ENRICHMENT_ENABLED", "false").lower() == "true"
_SP_SCORE_THRESHOLD = float(os.getenv("SP_SCORE_THRESHOLD", "2.5"))
_SP_ENRICHMENT_TOP  = int(os.getenv("SP_ENRICHMENT_TOP", "3"))
_SP_ALLOWED_EXTENSIONS: list[str] = ["docx", "xlsx", "pdf"]


# ---------------------------------------------------------------------------
# Decision helpers
# ---------------------------------------------------------------------------

def _is_context_insufficient(retrieval: _RetrievalResult) -> bool:
    """True when primary Azure Search returned no documents at all."""
    return not retrieval.excel_docs and not retrieval.word_docs


def _needs_sharepoint_enrichment(route: str, word_docs: list[dict]) -> bool:
    """True when SP enrichment should run for this query.

    - Always False when SP_ENRICHMENT_ENABLED is not set.
    - Always False for excel_numeric (SP has no numeric data).
    - True when word_docs is empty.
    - False when the top doc has a caption AND score >= threshold (Azure confident).
    - True when top score is below threshold.
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
    if caption and top_score >= _SP_SCORE_THRESHOLD:
        return False
    return top_score < _SP_SCORE_THRESHOLD


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _fetch_sharepoint_fallback(query: str, top: int = 5) -> list[dict]:
    """Generic SP search used when Azure indexes return nothing."""
    if not _SP_AVAILABLE:
        return []
    try:
        client = _get_sp_client()
        return client.search_in_library(query, top=top)
    except EnvironmentError:
        log.debug("SharePoint fallback skipped: credentials not configured")
        return []
    except Exception as exc:
        log.warning("SharePoint fallback failed: %s", exc)
        return []


def _fetch_sharepoint_enrichment(
    query: str,
    show_name: str | None,
    top: int | None = None,
) -> list[dict]:
    """Targeted SP enrichment scoped to a show folder when show name is known."""
    if not _SP_AVAILABLE:
        return []
    n      = top if top is not None else _SP_ENRICHMENT_TOP
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
