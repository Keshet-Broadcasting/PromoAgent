"""
ingest_word_chunks.py

Reads the JSON chunk files produced by preprocess_word_docs.py from the
"promo-docs-json" blob container, embeds each chunk's text via Azure OpenAI
text-embedding-3-small, and bulk-uploads the results to the "word-docs" Azure AI
Search index.

Upload logic:
  - Chunks are batched (UPLOAD_BATCH_SIZE) for the Search SDK upload call.
  - Embeddings are requested in separate batches (EMBED_BATCH_SIZE) to stay within
    per-request token limits.
  - Chunks whose text is empty after stripping are skipped.

Required .env variables:
    AZURE_SEARCH_ENDPOINT
    AZURE_SEARCH_KEY
    AZURE_STORAGE_CONNECTION_STRING
    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_KEY
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT
    AZURE_OPENAI_API_VERSION          (optional, default: 2024-02-01)

Usage:
    python ingest_word_chunks.py
    python ingest_word_chunks.py --dry-run   # parse + embed but skip upload
"""

import argparse
import json
import logging
import os

import httpx
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")

INDEX_NAME = "word-docs"
JSON_CONTAINER = "promo-docs-json"

# Azure OpenAI: max items per embedding request
EMBED_BATCH_SIZE = 32
# Azure AI Search: max documents per upload_documents call
UPLOAD_BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


def embed_texts(
    http: httpx.Client,
    texts: list[str],
) -> list[list[float] | None]:
    """
    Embed a list of strings using the Azure OpenAI REST API.

    Returns a list of float vectors aligned with the input.
    Empty / whitespace-only texts receive None — callers omit the vector field.
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

        response = http.post(url, json={"input": list(batch_texts)})
        response.raise_for_status()

        for item in response.json()["data"]:
            vectors[indices[item["index"]]] = item["embedding"]

    return vectors


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------


def upload_batch(
    search_client: SearchClient,
    documents: list[dict],
    dry_run: bool,
) -> tuple[int, int]:
    """Upload one batch; return (succeeded, failed)."""
    if dry_run:
        return len(documents), 0

    results = search_client.upload_documents(documents=documents)
    succeeded = sum(1 for r in results if r.succeeded)
    failed = len(documents) - succeeded
    return succeeded, failed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(dry_run: bool = False) -> None:
    required = {
        "AZURE_SEARCH_ENDPOINT": AZURE_SEARCH_ENDPOINT,
        "AZURE_SEARCH_KEY": AZURE_SEARCH_KEY,
        "AZURE_STORAGE_CONNECTION_STRING": AZURE_STORAGE_CONNECTION_STRING,
        "AZURE_OPENAI_ENDPOINT": AZURE_OPENAI_ENDPOINT,
        "AZURE_OPENAI_KEY": AZURE_OPENAI_KEY,
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Check your .env file."
        )

    if dry_run:
        logger.info("DRY RUN — documents will be parsed and embedded but NOT uploaded.\n")

    # Clients
    from azure.storage.blob import BlobServiceClient
    blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    json_container = blob_service.get_container_client(JSON_CONTAINER)

    search_client = SearchClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        index_name=INDEX_NAME,
        credential=AzureKeyCredential(AZURE_SEARCH_KEY),
    )
    openai_http = httpx.Client(
        headers={"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"},
        timeout=60.0,
    )

    # List JSON blobs
    json_blobs = [b for b in json_container.list_blobs() if b.name.lower().endswith(".json")]
    logger.info(f"Found {len(json_blobs)} JSON file(s) in '{JSON_CONTAINER}'.\n")

    grand_total_chunks = 0
    grand_succeeded = 0
    grand_failed = 0
    files_processed = 0
    files_errors = 0

    for blob_props in json_blobs:
        blob_name = blob_props.name
        logger.info(f"  {blob_name}")

        try:
            # Download and parse JSON
            raw = json_container.get_blob_client(blob_name).download_blob().readall()
            chunks: list[dict] = json.loads(raw.decode("utf-8"))

            if not chunks:
                logger.info("    Empty — skipping.")
                continue

            # Filter out chunks with no text
            chunks = [c for c in chunks if c.get("chunk", "").strip()]
            if not chunks:
                logger.info("    All chunks empty after filtering — skipping.")
                continue

            logger.info(f"    {len(chunks)} chunk(s) — embedding ...")

            # Embed all chunks in batches
            texts = [c["chunk"] for c in chunks]
            vectors = embed_texts(openai_http, texts)

            # Attach vectors; skip chunks where embedding failed (empty text)
            docs_to_upload: list[dict] = []
            for chunk, vector in zip(chunks, vectors):
                if vector is None:
                    continue
                doc = dict(chunk)           # copy fields from JSON
                doc["chunk_vector"] = vector
                docs_to_upload.append(doc)

            skipped_no_vec = len(chunks) - len(docs_to_upload)
            if skipped_no_vec:
                logger.info(f"    {skipped_no_vec} chunk(s) skipped (no embedding).")

            # Upload in batches of UPLOAD_BATCH_SIZE
            file_succeeded = 0
            file_failed = 0
            for start in range(0, len(docs_to_upload), UPLOAD_BATCH_SIZE):
                batch = docs_to_upload[start : start + UPLOAD_BATCH_SIZE]
                s, f = upload_batch(search_client, batch, dry_run)
                file_succeeded += s
                file_failed += f

            grand_total_chunks += len(chunks)
            grand_succeeded += file_succeeded
            grand_failed += file_failed
            files_processed += 1

            status = "would upload" if dry_run else "uploaded"
            warn = f"  ({file_failed} failed)" if file_failed else ""
            logger.info(f"    {status} {file_succeeded}/{len(docs_to_upload)}{warn}")

        except Exception as exc:
            logger.error(f"    ERROR: {exc}")
            files_errors += 1

    logger.info("")
    logger.info("=" * 52)
    logger.info(f"  JSON files processed  : {files_processed}")
    logger.info(f"  JSON files errored    : {files_errors}")
    logger.info(f"  Total chunks seen     : {grand_total_chunks}")
    if dry_run:
        logger.info(f"  Chunks (dry run)      : {grand_succeeded}")
    else:
        logger.info(f"  Chunks uploaded OK    : {grand_succeeded}")
        logger.info(f"  Chunks failed         : {grand_failed}")
    logger.info("=" * 52)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Embed JSON chunks and upload to 'word-docs' Azure AI Search index"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and embed but skip the actual upload to Search",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
