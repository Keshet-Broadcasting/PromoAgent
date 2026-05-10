"""
diagnose_word_docs.py

Diagnoses the current state of the "word-docs" Azure AI Search index.

Reports:
  1. Total chunk count and per-source-file breakdown.
  2. Headers / sections found in each document.
  3. Chunk quality signals: empty chunks, very short chunks, very long chunks.
  4. Sample chunk text per document (first 200 chars).

This is a READ-ONLY script — it queries the index but changes nothing.

Usage:
    python scripts/diagnose_word_docs.py
    python scripts/diagnose_word_docs.py --verbose   # show full sample chunk text
"""

from __future__ import annotations

import argparse
import logging
import os
from collections import defaultdict

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "")
AZURE_SEARCH_KEY      = os.getenv("AZURE_SEARCH_KEY", "")
WORD_INDEX_NAME       = os.getenv("AZURE_SEARCH_WORD_INDEX", "word-docs")

# Chunk length thresholds for quality reporting
SHORT_CHUNK_CHARS = 50
LONG_CHUNK_CHARS  = 2800   # close to the 3000-char split limit


def main(verbose: bool = False) -> None:
    missing = [v for v in ("AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_KEY") if not os.getenv(v)]
    if missing:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")

    client = SearchClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        index_name=WORD_INDEX_NAME,
        credential=AzureKeyCredential(AZURE_SEARCH_KEY),
    )

    logger.info(f"\nQuerying '{WORD_INDEX_NAME}' index — reading all chunks ...")

    # SDK auto-paginates; fetch all pages (no hard cap)
    results = client.search(
        search_text="*",
        select=["chunk_id", "chunk", "header", "title", "source_file"],
        top=1000,
    )

    # Collect stats per source file
    # {title: {"chunks": [...], "headers": set(), "short": int, "long": int}}
    per_file: dict[str, dict] = defaultdict(lambda: {
        "chunks": [],
        "headers": set(),
        "short": 0,
        "long": 0,
        "empty": 0,
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

    sep = "=" * 64
    logger.info(sep)
    logger.info(f"  Index          : {WORD_INDEX_NAME}")
    logger.info(f"  Total chunks   : {total}")
    logger.info(f"  Source files   : {len(per_file)}")
    logger.info(sep)

    for title in sorted(per_file):
        f      = per_file[title]
        chunks = f["chunks"]
        headers = sorted(f["headers"])

        logger.info(f"\n{'─' * 64}")
        logger.info(f"  FILE  : {title}")
        logger.info(f"  Chunks: {len(chunks)}"
                    + (f"  |  EMPTY: {f['empty']}" if f["empty"] else "")
                    + (f"  |  SHORT(<{SHORT_CHUNK_CHARS}c): {f['short']}" if f["short"] else "")
                    + (f"  |  LONG(>{LONG_CHUNK_CHARS}c): {f['long']}" if f["long"] else ""))

        if headers:
            logger.info(f"  Sections ({len(headers)}):")
            for h in headers:
                logger.info(f"      • {h}")
        else:
            logger.info(f"  Sections: none (all chunks have empty header)")

        # Show sample chunks
        sample_count = len(chunks) if verbose else min(3, len(chunks))
        logger.info(f"  Sample chunks (first {sample_count}):")
        for i, c in enumerate(chunks[:sample_count]):
            hdr_str = f"[{c['header']}] " if c["header"] else ""
            text = c["chunk"].replace("\n", " ").strip()
            preview = text if verbose else (text[:250] + "…" if len(text) > 250 else text)
            logger.info(f"    [{i+1}] {hdr_str}{preview}")

    logger.info(f"\n{sep}")

    # Overall quality summary
    total_empty = sum(f["empty"] for f in per_file.values())
    total_short = sum(f["short"] for f in per_file.values())
    total_long  = sum(f["long"]  for f in per_file.values())

    logger.info("  QUALITY SUMMARY")
    logger.info(f"  Empty chunks           : {total_empty}")
    logger.info(f"  Very short (<{SHORT_CHUNK_CHARS} chars) : {total_short}")
    logger.info(f"  Very long (>{LONG_CHUNK_CHARS} chars)  : {total_long}")
    if total_empty:
        logger.warning("  ⚠  Empty chunks found — re-run preprocess_word_docs.py --overwrite"
                       " to refresh the JSON source files.")
    elif total_short > 50:
        logger.info("  ℹ  Short chunks are typically heading-only paragraphs — normal after"
                    " HeadingBold-based chunking.")
    logger.info(sep)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Read-only diagnostic for the 'word-docs' Azure AI Search index"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print full chunk text (not just first 250 chars)",
    )
    args = parser.parse_args()
    main(verbose=args.verbose)
