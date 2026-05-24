"""
diagnose_word_docs.py

Diagnoses the current state of the "word-docs" Azure AI Search index
(default) OR the "promo-docs-json" blob container (--source json).

Index mode reports:
  1. Total chunk count and per-source-file breakdown.
  2. Headers / sections found in each document.
  3. Chunk quality signals: empty chunks, very short chunks, very long chunks.
  4. Sample chunk text per document (first 250 chars).

JSON-blob mode reports the same, PLUS:
  5. Count of chunks with show_name / season / doc_type / question_type populated.
  6. Per-file metadata sample (useful to validate Phase 6 semantic chunking before
     the Azure Search schema migration makes these fields queryable).

This is a READ-ONLY script — it queries but changes nothing.

Usage:
    python scripts/diagnose_word_docs.py                      # index mode
    python scripts/diagnose_word_docs.py --source json        # JSON-blob mode
    python scripts/diagnose_word_docs.py --verbose            # full chunk text
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections import defaultdict

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

AZURE_SEARCH_ENDPOINT      = os.getenv("AZURE_SEARCH_ENDPOINT", "")
AZURE_SEARCH_KEY           = os.getenv("AZURE_SEARCH_KEY", "")
AZURE_STORAGE_CONN         = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
WORD_INDEX_NAME            = os.getenv("AZURE_SEARCH_WORD_INDEX", "word-docs")
JSON_CONTAINER             = "promo-docs-json"

# Chunk length thresholds for quality reporting
SHORT_CHUNK_CHARS = 50
LONG_CHUNK_CHARS  = 2800   # close to the 3000-char split limit


# ---------------------------------------------------------------------------
# Shared: render per-file stats to logger
# ---------------------------------------------------------------------------

def _report(
    per_file: dict[str, dict],
    total: int,
    source_label: str,
    verbose: bool,
    show_meta: bool = False,
) -> None:
    sep = "=" * 64
    logger.info(sep)
    logger.info(f"  Source         : {source_label}")
    logger.info(f"  Total chunks   : {total}")
    logger.info(f"  Source files   : {len(per_file)}")
    logger.info(sep)

    for title in sorted(per_file):
        f       = per_file[title]
        chunks  = f["chunks"]
        headers = sorted(f["headers"])

        logger.info(f"\n{'─' * 64}")
        logger.info(f"  FILE  : {title}")
        logger.info(f"  Chunks: {len(chunks)}"
                    + (f"  |  EMPTY: {f['empty']}" if f["empty"] else "")
                    + (f"  |  SHORT(<{SHORT_CHUNK_CHARS}c): {f['short']}" if f["short"] else "")
                    + (f"  |  LONG(>{LONG_CHUNK_CHARS}c): {f['long']}" if f["long"] else ""))

        if show_meta:
            with_show   = sum(1 for c in chunks if c.get("show_name"))
            with_season = sum(1 for c in chunks if c.get("season") is not None)
            with_qtype  = sum(1 for c in chunks if c.get("question_type") and c["question_type"] != "כללי")
            logger.info(
                f"  Metadata: show_name={with_show}/{len(chunks)}"
                f"  season={with_season}/{len(chunks)}"
                f"  question_type={with_qtype}/{len(chunks)}"
            )

        if headers:
            logger.info(f"  Sections ({len(headers)}):")
            for h in headers:
                logger.info(f"      \u2022 {h}")
        else:
            logger.info("  Sections: none (all chunks have empty header)")

        sample_count = len(chunks) if verbose else min(3, len(chunks))
        logger.info(f"  Sample chunks (first {sample_count}):")
        for i, c in enumerate(chunks[:sample_count]):
            hdr_str  = f"[{c['header']}] " if c.get("header") else ""
            meta_str = ""
            if show_meta and c.get("show_name"):
                meta_str = (
                    f" | show={c.get('show_name')} s{c.get('season','?')}"
                    f" [{c.get('doc_type','?')}] q={c.get('question_type','?')}"
                )
            text    = (c.get("chunk") or "").replace("\n", " ").strip()
            preview = text if verbose else (text[:250] + "\u2026" if len(text) > 250 else text)
            logger.info(f"    [{i+1}] {hdr_str}{meta_str}  {preview}")

    logger.info(f"\n{sep}")
    total_empty = sum(f["empty"] for f in per_file.values())
    total_short = sum(f["short"] for f in per_file.values())
    total_long  = sum(f["long"]  for f in per_file.values())
    logger.info("  QUALITY SUMMARY")
    logger.info(f"  Empty chunks           : {total_empty}")
    logger.info(f"  Very short (<{SHORT_CHUNK_CHARS} chars) : {total_short}")
    logger.info(f"  Very long (>{LONG_CHUNK_CHARS} chars)  : {total_long}")
    if total_empty:
        logger.warning("  \u26a0  Empty chunks found — re-run preprocess_word_docs.py --overwrite"
                       " to refresh the JSON source files.")
    elif total_short > 50:
        logger.info("  \u2139  Short chunks are typically heading-only paragraphs — normal after"
                    " HeadingBold-based chunking.")
    logger.info(sep)


# ---------------------------------------------------------------------------
# Mode A — read from Azure AI Search index (default)
# ---------------------------------------------------------------------------

def _collect_from_index() -> tuple[dict[str, dict], int]:
    missing = [v for v in ("AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_KEY") if not os.getenv(v)]
    if missing:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")

    client = SearchClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        index_name=WORD_INDEX_NAME,
        credential=AzureKeyCredential(AZURE_SEARCH_KEY),
    )
    logger.info(f"\nQuerying '{WORD_INDEX_NAME}' index — reading all chunks ...")
    results = client.search(
        search_text="*",
        select=["chunk_id", "chunk", "header", "title", "source_file"],
        top=1000,
    )

    per_file: dict[str, dict] = defaultdict(lambda: {
        "chunks": [], "headers": set(), "short": 0, "long": 0, "empty": 0,
    })
    total = 0
    for doc in results:
        total += 1
        title    = doc.get("title") or doc.get("source_file") or "?"
        chunk    = doc.get("chunk") or ""
        header   = doc.get("header") or ""
        chunk_id = doc.get("chunk_id") or ""

        f = per_file[title]
        f["chunks"].append({"chunk_id": chunk_id, "header": header, "chunk": chunk})
        if header:
            f["headers"].add(header)
        clen = len(chunk.strip())
        if clen == 0:
            f["empty"] += 1
        elif clen < SHORT_CHUNK_CHARS:
            f["short"] += 1
        elif clen > LONG_CHUNK_CHARS:
            f["long"] += 1

    return per_file, total


# ---------------------------------------------------------------------------
# Mode B — read from promo-docs-json blob container (--source json)
# ---------------------------------------------------------------------------

def _collect_from_blobs() -> tuple[dict[str, dict], int]:
    if not AZURE_STORAGE_CONN:
        raise EnvironmentError("AZURE_STORAGE_CONNECTION_STRING is required for --source json")

    blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONN)
    container    = blob_service.get_container_client(JSON_CONTAINER)
    json_blobs   = [b for b in container.list_blobs() if b.name.lower().endswith(".json")]
    logger.info(f"\nReading {len(json_blobs)} JSON blob(s) from '{JSON_CONTAINER}' ...")

    per_file: dict[str, dict] = defaultdict(lambda: {
        "chunks": [], "headers": set(), "short": 0, "long": 0, "empty": 0,
    })
    total = 0
    for blob_props in json_blobs:
        try:
            raw    = container.get_blob_client(blob_props.name).download_blob().readall()
            chunks = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            logger.warning(f"  Could not read {blob_props.name}: {exc}")
            continue

        for c in chunks:
            total += 1
            title    = c.get("title") or blob_props.name
            chunk    = c.get("chunk") or ""
            header   = c.get("header") or ""
            chunk_id = c.get("chunk_id") or ""

            f = per_file[title]
            f["chunks"].append({
                "chunk_id":     chunk_id,
                "header":       header,
                "chunk":        chunk,
                "show_name":    c.get("show_name", ""),
                "season":       c.get("season"),
                "doc_type":     c.get("doc_type", ""),
                "question_type": c.get("question_type", ""),
            })
            if header:
                f["headers"].add(header)
            clen = len(chunk.strip())
            if clen == 0:
                f["empty"] += 1
            elif clen < SHORT_CHUNK_CHARS:
                f["short"] += 1
            elif clen > LONG_CHUNK_CHARS:
                f["long"] += 1

    return per_file, total


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(verbose: bool = False, source: str = "index") -> None:
    if source == "json":
        per_file, total = _collect_from_blobs()
        _report(per_file, total, f"promo-docs-json blobs", verbose, show_meta=True)
    else:
        per_file, total = _collect_from_index()
        _report(per_file, total, f"index: {WORD_INDEX_NAME}", verbose, show_meta=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Read-only diagnostic for word-docs index or promo-docs-json blobs"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print full chunk text (not just first 250 chars)",
    )
    parser.add_argument(
        "--source",
        choices=["index", "json"],
        default="index",
        help=(
            "'index' (default): query Azure AI Search word-docs index. "
            "'json': read promo-docs-json blobs — shows Phase 6 metadata fields "
            "(show_name, season, doc_type, question_type) before schema migration."
        ),
    )
    args = parser.parse_args()
    main(verbose=args.verbose, source=args.source)
