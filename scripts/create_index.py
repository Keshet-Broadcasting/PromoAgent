"""
create_index.py

Creates an Azure AI Search index for TV show promo data extracted from Excel.
Run this once before ingesting data with ingest_excel.py.

Usage:
    python create_index.py
    python create_index.py --recreate
"""

import os
import argparse
import logging
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    SimpleField,
    SearchableField,
    SemanticConfiguration,
    SemanticSearch,
    SemanticPrioritizedFields,
    SemanticField,
    VectorSearch,
    HnswAlgorithmConfiguration,
    HnswParameters,
    VectorSearchProfile,
)

# Load environment variables from .env file
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX_NAME")


def get_index_definition() -> SearchIndex:
    """Get the SearchIndex definition with all required fields and semantic config."""
    # Define the fields for the index.
    # All values are stored as strings to handle mixed Excel cell types cleanly.
    fields = [
        # Primary key — a unique hash generated per row during ingestion
        SimpleField(
            name="id",
            type=SearchFieldDataType.String,
            key=True,
            filterable=True,
        ),
        # Show name extracted from the Excel tab title
        SearchableField(
            name="show_name",
            type=SearchFieldDataType.String,
            filterable=True,
            retrievable=True,
            analyzer_name="he.microsoft",
        ),
        # Season number extracted from the Excel tab title
        SearchableField(
            name="season",
            type=SearchFieldDataType.String,
            filterable=True,
            retrievable=True,
        ),
        # מספר פרק — episode number
        SimpleField(
            name="episode_number",
            type=SearchFieldDataType.String,
            filterable=True,
            retrievable=True,
        ),
        # תאריך — broadcast date
        SimpleField(
            name="date",
            type=SearchFieldDataType.String,
            filterable=True,
            retrievable=True,
        ),
        # יום בשבוע — day of week
        SimpleField(
            name="day_of_week",
            type=SearchFieldDataType.String,
            filterable=True,
            retrievable=True,
        ),
        # בפרומו — free-text promo description; primary semantic search field
        SearchableField(
            name="promo_text",
            type=SearchFieldDataType.String,
            retrievable=True,
            analyzer_name="he.microsoft",  # Hebrew language analyzer
        ),
        # נקודת פתיחה — opening point / starting score
        SimpleField(
            name="opening_point",
            type=SearchFieldDataType.String,
            retrievable=True,
        ),
        # רייטינג פרק — episode rating
        SimpleField(
            name="rating",
            type=SearchFieldDataType.String,
            filterable=True,
            retrievable=True,
        ),
        # תחרות — competing shows / competition notes
        SimpleField(
            name="competition",
            type=SearchFieldDataType.String,
            retrievable=True,
        ),
        # Name of the source Excel file, for traceability
        SimpleField(
            name="source_file",
            type=SearchFieldDataType.String,
            filterable=True,
            retrievable=True,
        ),
        # Embedding of promo_text — used for vector (nearest-neighbour) search
        SearchField(
            name="promo_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            hidden=True,            # Don't return raw floats in search results
            vector_search_dimensions=1536,
            vector_search_profile_name="promo-hnsw-profile",
        ),
    ]

    # Vector search: HNSW algorithm wired to the profile used by promo_vector
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(
            name="promo-hnsw",
            parameters=HnswParameters(m=10, ef_search=200),
        )],
        profiles=[VectorSearchProfile(
            name="promo-hnsw-profile",
            algorithm_configuration_name="promo-hnsw",
        )],
    )

    # Semantic configuration: prioritises promo_text as the content field and
    # show_name as a keyword field, enabling vector-free semantic ranking for RAG.
    semantic_config = SemanticConfiguration(
        name="promo-semantic-config",
        prioritized_fields=SemanticPrioritizedFields(
            content_fields=[SemanticField(field_name="promo_text")],
            keywords_fields=[
                SemanticField(field_name="show_name"),
                SemanticField(field_name="season"),
            ],
        ),
    )

    semantic_search = SemanticSearch(configurations=[semantic_config])

    # Assemble the index definition
    index = SearchIndex(
        name=AZURE_SEARCH_INDEX_NAME,
        fields=fields,
        semantic_search=semantic_search,
        vector_search=vector_search,
    )
    return index


def create_index() -> None:
    """Create the Azure AI Search index with all required fields and semantic config."""

    if not all([AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX_NAME]):
        raise EnvironmentError(
            "Missing required environment variables. "
            "Please ensure AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, and "
            "AZURE_SEARCH_INDEX_NAME are set in your .env file."
        )

    # Build the index client
    credential = AzureKeyCredential(AZURE_SEARCH_KEY)
    index_client = SearchIndexClient(
        endpoint=AZURE_SEARCH_ENDPOINT, credential=credential
    )

    index = get_index_definition()

    # Create or update the index (create_or_update is idempotent)
    logger.info(f"Creating index '{AZURE_SEARCH_INDEX_NAME}' ...")
    result = index_client.create_or_update_index(index)
    logger.info(f"Index '{result.name}' created/updated successfully.")


def recreate_index() -> None:
    """Delete the index if it exists, then recreate it with the same schema."""

    if not all([AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX_NAME]):
        raise EnvironmentError(
            "Missing required environment variables. "
            "Please ensure AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, and "
            "AZURE_SEARCH_INDEX_NAME are set in your .env file."
        )

    # Build the index client
    credential = AzureKeyCredential(AZURE_SEARCH_KEY)
    index_client = SearchIndexClient(
        endpoint=AZURE_SEARCH_ENDPOINT, credential=credential
    )

    # Try to delete the index
    try:
        logger.info(f"Attempting to delete index '{AZURE_SEARCH_INDEX_NAME}' if it exists...")
        index_client.delete_index(AZURE_SEARCH_INDEX_NAME)
        logger.info(f"Index '{AZURE_SEARCH_INDEX_NAME}' deleted successfully.")
    except Exception as e:
        if "not found" in str(e).lower() or "does not exist" in str(e).lower():
            logger.info(f"Index '{AZURE_SEARCH_INDEX_NAME}' does not exist, skipping deletion.")
        else:
            logger.error(f"Error deleting index: {e}")
            raise

    # Recreate the index
    index = get_index_definition()
    logger.info(f"Creating index '{AZURE_SEARCH_INDEX_NAME}' ...")
    result = index_client.create_index(index)
    logger.info(f"Index '{result.name}' created successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or recreate Azure AI Search index")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate the index")
    args = parser.parse_args()

    if args.recreate:
        recreate_index()
    else:
        create_index()
