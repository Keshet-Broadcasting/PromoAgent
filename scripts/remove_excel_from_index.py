"""
remove_excel_from_index.py

Finds and deletes the Excel document "מעקבי פרומו.xlsx" from the auto-created
Azure AI Search index "search-1775984451728" (populated by a blob-storage indexer).

Usage:
    python remove_excel_from_index.py
"""

import os
import logging
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
KEY = os.getenv("AZURE_SEARCH_KEY")
INDEX_NAME = "search-1775984451728"
EXCEL_FILENAME = "מעקבי פרומו.xlsx"


def main() -> None:
    if not ENDPOINT or not KEY:
        raise EnvironmentError("AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY must be set in .env")

    credential = AzureKeyCredential(KEY)

    # --- 1. Discover the key field name from the index schema.
    index_client = SearchIndexClient(endpoint=ENDPOINT, credential=credential)
    index_def = index_client.get_index(INDEX_NAME)
    key_field = next(f.name for f in index_def.fields if f.key)
    logger.info(f"Index key field: '{key_field}'")

    # --- 2. Search for the Excel document by filename.
    search_client = SearchClient(endpoint=ENDPOINT, index_name=INDEX_NAME, credential=credential)

    # Blob-indexer indexes expose the filename in metadata_storage_name.
    # Use a filter if the field exists; otherwise fall back to a wildcard search.
    field_names = {f.name for f in index_def.fields}
    if "metadata_storage_name" in field_names:
        results = list(search_client.search(
            search_text="*",
            filter=f"metadata_storage_name eq '{EXCEL_FILENAME}'",
            select=[key_field, "metadata_storage_name"],
            top=5,
        ))
    else:
        # Fallback: full-text search on the filename, inspect manually
        results = list(search_client.search(
            search_text=EXCEL_FILENAME,
            select=[key_field],
            top=5,
        ))

    if not results:
        logger.info(f"No document found matching '{EXCEL_FILENAME}'. Nothing to delete.")
        return

    if len(results) > 1:
        logger.warning(f"WARNING: Found {len(results)} matching documents. Showing all:")
        for r in results:
            logger.info(f"  key={r[key_field]!r}")
        logger.info("Aborting — please narrow the filter and re-run.")
        return

    doc = results[0]
    doc_key = doc[key_field]
    logger.info(f"Found document key: {doc_key!r}")

    # --- 3. Delete the document.
    delete_batch = [{key_field: doc_key}]
    delete_results = search_client.delete_documents(documents=delete_batch)

    result = delete_results[0]
    if result.succeeded:
        logger.info(f"Deletion succeeded (key={doc_key!r}, status={result.status_code}).")
    else:
        logger.error(f"Deletion FAILED: {result.error_message}")


if __name__ == "__main__":
    main()
