"""
ingest_json_to_azure.py

Reads processed_promos.json (produced by convert_excel_to_json.py) and uploads
all records to the existing Azure AI Search tv-promos index.

Each record is enriched with:
  - A stable SHA-256 document ID (show + season + episode + index position)
  - A cohesive Hebrew text chunk combining all key fields, used as promo_text
    when the original promo_text is missing, and also embedded as a vector.
  - A promo_vector (text-embedding-3-small via Azure OpenAI)

Usage:
    python scripts/ingest_json_to_azure.py [path/to/processed_promos.json]

Defaults to ./processed_promos.json in the project root.

Environment variables required (from .env):
    AZURE_SEARCH_ENDPOINT
    AZURE_SEARCH_KEY
    AZURE_SEARCH_INDEX_NAME
    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_KEY
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT
    AZURE_OPENAI_API_VERSION        (optional, default: 2024-02-01)

Dependencies:
    pip install azure-search-documents azure-core httpx python-dotenv
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path

import httpx
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
load_dotenv(BASE / ".env")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AZURE_SEARCH_ENDPOINT   = os.getenv("AZURE_SEARCH_ENDPOINT", "")
AZURE_SEARCH_KEY        = os.getenv("AZURE_SEARCH_KEY", "")
AZURE_SEARCH_INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX_NAME", "tv-promos")

AZURE_OPENAI_ENDPOINT            = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY                 = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
AZURE_OPENAI_API_VERSION         = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")

SOURCE_FILE = os.getenv("EXCEL_BLOB_NAME", "מעקבי פרומו.xlsx")

UPLOAD_BATCH_SIZE = 100   # Azure Search max is 1000; keep lower for safety
EMBED_BATCH_SIZE  = 32    # Max texts per Azure OpenAI embeddings request


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_env() -> None:
    required = {
        "AZURE_SEARCH_ENDPOINT":            AZURE_SEARCH_ENDPOINT,
        "AZURE_SEARCH_KEY":                 AZURE_SEARCH_KEY,
        "AZURE_SEARCH_INDEX_NAME":          AZURE_SEARCH_INDEX_NAME,
        "AZURE_OPENAI_ENDPOINT":            AZURE_OPENAI_ENDPOINT,
        "AZURE_OPENAI_KEY":                 AZURE_OPENAI_KEY,
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Check your .env file."
        )


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------

def _make_id(show_name: str, season: str, episode: str, index: int) -> str:
    """Stable SHA-256-based document ID (first 40 hex chars)."""
    raw = f"{show_name}|{season}|{episode}|{index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _to_str(value) -> str:
    """Convert any value to a clean string; None / empty → empty string."""
    if value is None:
        return ""
    s = str(value).strip()
    return s if s not in ("None", "nan") else ""


def _build_text_chunk(rec: dict) -> str:
    """
    Build a single cohesive Hebrew text string from all key fields.
    This becomes the promo_text stored in the index (and what gets embedded).
    """
    parts: list[str] = []
    if rec.get("show_name"):
        parts.append(f"תוכנית: {rec['show_name']}")
    if rec.get("season"):
        parts.append(f"עונה: {rec['season']}")
    if rec.get("episode"):
        parts.append(f"פרק: {rec['episode']}")
    if rec.get("date"):
        parts.append(f"תאריך: {rec['date']}")
    if rec.get("opening_rating") is not None:
        parts.append(f"נקודת פתיחה: {rec['opening_rating']}%")
    if rec.get("average_rating") is not None:
        parts.append(f"רייטינג ממוצע: {rec['average_rating']}%")
    if rec.get("promo_text"):
        parts.append(f"פרומו: {rec['promo_text']}")
    if rec.get("competition"):
        parts.append(f"תחרות: {rec['competition']}")
    return " | ".join(parts)


def _record_to_doc(rec: dict, idx: int) -> dict:
    """Map a JSON record to an Azure Search document."""
    show_name = _to_str(rec.get("show_name"))
    season    = _to_str(rec.get("season"))
    episode   = _to_str(rec.get("episode"))

    # Build the rich combined text; fall back to original promo_text alone
    text_chunk = _build_text_chunk(rec)
    promo_text = text_chunk or _to_str(rec.get("promo_text"))

    return {
        "id":             _make_id(show_name, season, episode, idx),
        "show_name":      show_name,
        "season":         season,
        "episode_number": episode,
        "date":           _to_str(rec.get("date")),
        "day_of_week":    "",                          # not in JSON output
        "promo_text":     promo_text,
        "opening_point":  _to_str(rec.get("opening_rating")),
        "rating":         _to_str(rec.get("average_rating")),
        "competition":    _to_str(rec.get("competition")),
        "source_file":    SOURCE_FILE,
    }


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _embed_texts(http: httpx.Client, texts: list[str]) -> list[list[float] | None]:
    """
    Embed texts in batches via Azure OpenAI REST API.
    Empty/whitespace texts get None (field omitted from document).
    """
    vectors: list[list[float] | None] = [None] * len(texts)
    non_empty = [(i, t) for i, t in enumerate(texts) if t.strip()]

    if not non_empty:
        return vectors

    url = (
        f"{AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/"
        f"{AZURE_OPENAI_EMBEDDING_DEPLOYMENT}/embeddings"
        f"?api-version={AZURE_OPENAI_API_VERSION}"
    )

    for batch_start in range(0, len(non_empty), EMBED_BATCH_SIZE):
        batch = non_empty[batch_start : batch_start + EMBED_BATCH_SIZE]
        indices, batch_texts = zip(*batch)
        resp = http.post(url, json={"input": list(batch_texts)})
        resp.raise_for_status()
        for item in resp.json()["data"]:
            vectors[indices[item["index"]]] = item["embedding"]
        log.info(
            "  Embedded batch %d-%d (%d texts)",
            batch_start + 1, batch_start + len(batch), len(batch)
        )

    return vectors


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def _upload_batches(client: SearchClient, docs: list[dict]) -> int:
    """Upload documents in batches; returns count of successes."""
    total = 0
    for start in range(0, len(docs), UPLOAD_BATCH_SIZE):
        batch = docs[start : start + UPLOAD_BATCH_SIZE]
        results = client.upload_documents(documents=batch)
        ok  = sum(1 for r in results if r.succeeded)
        bad = len(batch) - ok
        total += ok
        if bad:
            log.warning("  WARNING: %d document(s) failed in this batch.", bad)
        log.info(
            "  Uploaded batch %d-%d  (%d/%d succeeded)",
            start + 1, start + len(batch), ok, len(batch)
        )
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _validate_env()

    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "processed_promos.json"
    if not json_path.exists():
        log.error("Input file not found: %s", json_path)
        sys.exit(1)

    log.info("Reading %s ...", json_path)
    records: list[dict] = json.loads(json_path.read_text(encoding="utf-8"))
    log.info("Loaded %d records.", len(records))

    # Build Azure Search documents
    log.info("Building documents ...")
    docs = [_record_to_doc(rec, i) for i, rec in enumerate(records)]

    # Embed promo_text in batches
    log.info("Embedding %d texts via Azure OpenAI (%s) ...", len(docs), AZURE_OPENAI_EMBEDDING_DEPLOYMENT)
    openai_http = httpx.Client(
        headers={"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"},
        timeout=120.0,
    )
    texts   = [d["promo_text"] for d in docs]
    vectors = _embed_texts(openai_http, texts)
    embedded = 0
    for doc, vec in zip(docs, vectors):
        if vec is not None:
            doc["promo_vector"] = vec
            embedded += 1
    log.info("Embedded %d/%d documents.", embedded, len(docs))

    # Upload to Azure Search
    search_client = SearchClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        index_name=AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(AZURE_SEARCH_KEY),
    )
    log.info("Uploading to index '%s' in batches of %d ...", AZURE_SEARCH_INDEX_NAME, UPLOAD_BATCH_SIZE)
    total = _upload_batches(search_client, docs)

    log.info("")
    log.info("=" * 52)
    log.info("  Records in JSON : %d", len(records))
    log.info("  Docs embedded   : %d", embedded)
    log.info("  Docs uploaded   : %d", total)
    log.info("=" * 52)


if __name__ == "__main__":
    main()
