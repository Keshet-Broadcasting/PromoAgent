"""
create_word_docs_index.py

Creates (or recreates) the "word-docs" Azure AI Search index.

Schema:
    chunk_id      — String, key  (keyword analyzer — required for SDK uploads)
    chunk         — String, searchable (he.microsoft analyzer), retrievable
    chunk_vector  — Collection(Edm.Single), 1536-dim HNSW vector, hidden
    header        — String, searchable, filterable (he.microsoft), retrievable
    title         — String, filterable, retrievable
    source_file   — String, retrievable
    parent_id     — String, filterable, retrievable

Usage:
    python create_word_docs_index.py
    python create_word_docs_index.py --recreate
"""

import argparse
import logging
import os

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    HnswParameters,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

INDEX_NAME = "word-docs"
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")


# ---------------------------------------------------------------------------
# Index definition
# ---------------------------------------------------------------------------


def get_index_definition() -> SearchIndex:
    fields = [
        # Primary key — stable hash-based ID, one per chunk.
        # keyword analyzer required by Azure Search for exact-match key lookups.
        SearchField(
            name="chunk_id",
            type=SearchFieldDataType.String,
            key=True,
            searchable=True,
            hidden=False,
            analyzer_name="keyword",
        ),
        # The semantic text chunk — primary search target.
        SearchableField(
            name="chunk",
            type=SearchFieldDataType.String,
            retrievable=True,
            analyzer_name="he.microsoft",
        ),
        # Dense vector embedding of the chunk text (text-embedding-3-small).
        SearchField(
            name="chunk_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            hidden=True,
            vector_search_dimensions=1536,
            vector_search_profile_name="chunk-hnsw-profile",
        ),
        # The section heading under which this chunk appears.
        SearchableField(
            name="header",
            type=SearchFieldDataType.String,
            retrievable=True,
            filterable=True,
            analyzer_name="he.microsoft",
        ),
        # Source filename (metadata_storage_name equivalent).
        SimpleField(
            name="title",
            type=SearchFieldDataType.String,
            retrievable=True,
            filterable=True,
        ),
        # Full blob URL of the source Word file.
        SimpleField(
            name="source_file",
            type=SearchFieldDataType.String,
            retrievable=True,
        ),
        # Links every chunk back to its parent document (hash of title).
        SimpleField(
            name="parent_id",
            type=SearchFieldDataType.String,
            retrievable=True,
            filterable=True,
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(
            name="chunk-hnsw",
            parameters=HnswParameters(m=10, ef_search=200),
        )],
        profiles=[VectorSearchProfile(
            name="chunk-hnsw-profile",
            algorithm_configuration_name="chunk-hnsw",
        )],
    )

    semantic_config = SemanticConfiguration(
        name="word-docs-semantic-config",
        prioritized_fields=SemanticPrioritizedFields(
            content_fields=[SemanticField(field_name="chunk")],
            keywords_fields=[
                SemanticField(field_name="header"),
                SemanticField(field_name="title"),
            ],
        ),
    )

    return SearchIndex(
        name=INDEX_NAME,
        fields=fields,
        vector_search=vector_search,
        semantic_search=SemanticSearch(configurations=[semantic_config]),
    )


# ---------------------------------------------------------------------------
# Create / recreate helpers
# ---------------------------------------------------------------------------


def _get_client() -> SearchIndexClient:
    if not AZURE_SEARCH_ENDPOINT or not AZURE_SEARCH_KEY:
        raise EnvironmentError(
            "AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY must be set in .env"
        )
    return SearchIndexClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        credential=AzureKeyCredential(AZURE_SEARCH_KEY),
    )


def create_index() -> None:
    client = _get_client()
    result = client.create_or_update_index(get_index_definition())
    logger.info(f"Index '{result.name}' created/updated successfully.")


def recreate_index() -> None:
    client = _get_client()
    try:
        client.delete_index(INDEX_NAME)
        logger.info(f"Deleted existing index '{INDEX_NAME}'.")
    except Exception as exc:
        msg = str(exc).lower()
        if "not found" in msg or "does not exist" in msg:
            logger.info(f"Index '{INDEX_NAME}' did not exist — skipping deletion.")
        else:
            raise
    result = client.create_index(get_index_definition())
    logger.info(f"Index '{result.name}' created successfully.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create or recreate the 'word-docs' Azure AI Search index"
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete the existing index and recreate it from scratch",
    )
    args = parser.parse_args()

    if args.recreate:
        recreate_index()
    else:
        create_index()
