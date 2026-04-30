"""
create_word_txt_datasource.py

Creates (or updates) the Azure AI Search datasource "word-txt-datasource" that
points to the "promo-docs-txt" Azure Blob Storage container.

This datasource is used by the indexer after running preprocess_word_docs.py,
which converts .docx files to UTF-8 .txt files in that container.

Usage:
    python create_word_txt_datasource.py
"""

import os
import warnings
import logging

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

DATASOURCE_NAME = "word-txt-datasource"
CONTAINER_NAME = "promo-docs-txt"

API_VERSION = "2024-09-01-preview"


def build_datasource_body() -> dict:
    return {
        "name": DATASOURCE_NAME,
        "description": (
            "UTF-8 plain-text files pre-processed from Word documents. "
            "Source container: promo-docs-txt."
        ),
        "type": "azureblob",
        "credentials": {
            "connectionString": AZURE_STORAGE_CONNECTION_STRING,
        },
        "container": {
            "name": CONTAINER_NAME,
            # Index only .txt files
            "query": "*.txt",
        },
        # Change-detection policy: high-watermark on last-modified metadata
        "dataChangeDetectionPolicy": {
            "@odata.type": (
                "#Microsoft.Azure.Search.HighWaterMarkChangeDetectionPolicy"
            ),
            "highWaterMarkColumnName": "metadata_storage_last_modified",
        },
    }


def main() -> None:
    missing = []
    if not AZURE_SEARCH_ENDPOINT:
        missing.append("AZURE_SEARCH_ENDPOINT")
    if not AZURE_SEARCH_KEY:
        missing.append("AZURE_SEARCH_KEY")
    if not AZURE_STORAGE_CONNECTION_STRING:
        missing.append("AZURE_STORAGE_CONNECTION_STRING")
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Check your .env file."
        )

    url = (
        f"{AZURE_SEARCH_ENDPOINT.rstrip('/')}"
        f"/datasources/{DATASOURCE_NAME}"
        f"?api-version={API_VERSION}"
    )
    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_SEARCH_KEY,
    }

    body = build_datasource_body()
    logger.info(f"Creating/updating datasource '{DATASOURCE_NAME}' ...")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        response = requests.put(url, json=body, headers=headers, timeout=30)

    if response.status_code == 201:
        logger.info(f"Datasource '{DATASOURCE_NAME}' created successfully (HTTP 201).")
    elif response.status_code in (200, 204):
        logger.info(
            f"Datasource '{DATASOURCE_NAME}' updated successfully "
            f"(HTTP {response.status_code})."
        )
    else:
        logger.error(f"ERROR {response.status_code}:")
        logger.error(response.text)
        response.raise_for_status()


if __name__ == "__main__":
    main()
