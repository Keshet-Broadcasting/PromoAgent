"""
list_show_names.py

Lists all unique show names and seasons stored in the tv-promos index.
Run this once to populate _KNOWN_SHOWS in service.py.

Usage:
    python scripts/list_show_names.py
"""
import os
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

load_dotenv()

ENDPOINT   = os.getenv("AZURE_SEARCH_ENDPOINT", "")
KEY        = os.getenv("AZURE_SEARCH_KEY", "")
INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX_NAME", "tv-promos")

client = SearchClient(
    endpoint=ENDPOINT,
    index_name=INDEX_NAME,
    credential=AzureKeyCredential(KEY),
)

# Iterate all documents and collect unique (show_name, season) pairs.
# show_name is not facetable, so we use a full scan instead.
from collections import defaultdict

show_counts: dict[str, int] = defaultdict(int)
season_counts: dict[str, int] = defaultdict(int)

results = client.search(
    search_text="*",
    select=["show_name", "season"],
    top=1000,   # SDK auto-paginates; 1000 per page covers the full 1441-doc index
)
for doc in results:
    sn = doc.get("show_name") or ""
    se = doc.get("season") or ""
    show_counts[sn] += 1
    season_counts[se] += 1

print(f"\n=== Unique show names in '{INDEX_NAME}' ({len(show_counts)} total) ===\n")
for name in sorted(show_counts):
    print(f"  {show_counts[name]:4d} docs  |  \"{name}\"")

print(f"\n=== Unique season values ({len(season_counts)} total) ===\n")
for se in sorted(season_counts, key=lambda x: (len(x), x)):
    print(f"  {season_counts[se]:4d} docs  |  season={se!r}")

print("\n--- Copy the show names above into _KNOWN_SHOWS in app/service.py ---\n")
