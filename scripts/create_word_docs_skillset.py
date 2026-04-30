"""
create_word_docs_skillset.py

Creates (or updates) the "word-docs-skillset" in Azure AI Search via the REST API.

Pipeline:
    /document/content
        └─ SplitSkill (512 tokens, 64 overlap)
              └─ /document/pages/*
                    └─ AzureOpenAIEmbeddingSkill (text-embedding-3-small)
                          └─ /document/pages/*/content_vector

Each enriched chunk is projected into the "word-docs" index as an independent
document.  The parent document's key is stored in the "parent_id" field.

cognitiveServices is null — no Cognitive Services resource is required.

Usage:
    python create_word_docs_skillset.py
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
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")

SKILLSET_NAME = "word-docs-skillset"
INDEX_NAME = "word-docs"

# 2024-09-01-preview is required for token-based splitting (unit: azureOpenAITokens)
# and for the AzureOpenAIEmbeddingSkill with dimensions parameter.
API_VERSION = "2024-09-01-preview"


# ---------------------------------------------------------------------------
# Skillset body
# ---------------------------------------------------------------------------


def build_skillset_body() -> dict:
    return {
        "name": SKILLSET_NAME,
        "description": (
            "Split Word documents into 512-token chunks and embed each chunk "
            "with Azure OpenAI text-embedding-3-small."
        ),
        "skills": [
            # ----------------------------------------------------------------
            # Skill 1 — split document content into token-based pages
            # ----------------------------------------------------------------
            {
                "@odata.type": "#Microsoft.Skills.Text.SplitSkill",
                "name": "split-skill",
                "description": "Split /document/content into 512-token chunks with 64-token overlap",
                "context": "/document",
                "textSplitMode": "pages",
                "maximumPageLength": 512,
                "pageOverlapLength": 64,
                "unit": "azureOpenAITokens",
                # Required when unit=azureOpenAITokens — specifies the tokenizer.
                # cl100k_base matches text-embedding-3-small and all GPT-4 models.
                "azureOpenAITokenizerParameters": {
                    "encoderModelName": "cl100k_base"
                },
                "inputs": [
                    {"name": "text", "source": "/document/content"}
                ],
                "outputs": [
                    {"name": "textItems", "targetName": "pages"}
                ],
            },
            # ----------------------------------------------------------------
            # Skill 2 — embed each chunk
            # ----------------------------------------------------------------
            {
                "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill",
                "name": "embedding-skill",
                "description": "Embed each chunk with text-embedding-3-small (1536 dims)",
                "context": "/document/pages/*",
                "resourceUri": AZURE_OPENAI_ENDPOINT.rstrip("/"),
                "apiKey": AZURE_OPENAI_KEY,
                "deploymentId": AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                "modelName": AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                "dimensions": 1536,
                "inputs": [
                    {"name": "text", "source": "/document/pages/*"}
                ],
                "outputs": [
                    {"name": "embedding", "targetName": "content_vector"}
                ],
            },
        ],
        # No Cognitive Services resource needed for this skillset
        "cognitiveServices": None,
        # ----------------------------------------------------------------
        # Index projections — map each chunk to a document in "word-docs"
        # ----------------------------------------------------------------
        "indexProjections": {
            "selectors": [
                {
                    "targetIndexName": INDEX_NAME,
                    # This field receives the parent document key automatically
                    "parentKeyFieldName": "parent_id",
                    # One projected document per chunk
                    "sourceContext": "/document/pages/*",
                    "mappings": [
                        # The chunk text
                        {
                            "name": "content",
                            "source": "/document/pages/*",
                        },
                        # The chunk embedding produced by skill 2
                        {
                            "name": "content_vector",
                            "source": "/document/pages/*/content_vector",
                        },
                        # Document title — comes from blob metadata
                        {
                            "name": "title",
                            "source": "/document/metadata_storage_name",
                        },
                        # Blob URL of the source file
                        {
                            "name": "source_file",
                            "source": "/document/metadata_storage_path",
                        },
                        # Ordinal of the chunk within the parent document — useful for reassembly
                        {
                            "name": "chunk_index",
                            "source": "/document/pages/*/\$index",  # built-in ordinal from SplitSkill
                        },

                    ],
                }
            ],
            "parameters": {
                # Only index the projected chunks — skip indexing the raw parent document
                "projectionMode": "skipIndexingParentDocuments",
            },
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    required = {
        "AZURE_SEARCH_ENDPOINT": AZURE_SEARCH_ENDPOINT,
        "AZURE_SEARCH_KEY": AZURE_SEARCH_KEY,
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

    url = (
        f"{AZURE_SEARCH_ENDPOINT.rstrip('/')}/skillsets/{SKILLSET_NAME}"
        f"?api-version={API_VERSION}"
    )
    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_SEARCH_KEY,
    }

    body = build_skillset_body()

    logger.info(f"Creating/updating skillset '{SKILLSET_NAME}' ...")

    # Suppress the charset_normalizer warning — Azure APIs always return UTF-8
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        response = requests.put(url, json=body, headers=headers, timeout=30)

    if response.status_code == 201:
        logger.info(f"Skillset '{SKILLSET_NAME}' created successfully.")
    elif response.status_code in (200, 204):
        logger.info(f"Skillset '{SKILLSET_NAME}' updated successfully (HTTP {response.status_code}).")
    else:
        logger.error(f"ERROR {response.status_code}:")
        logger.error(response.text)
        response.raise_for_status()


if __name__ == "__main__":
    main()
