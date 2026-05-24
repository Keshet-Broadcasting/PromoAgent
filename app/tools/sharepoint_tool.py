"""
sharepoint_tool.py

SharePoint document search using the SharePoint REST Search API.

Auth uses the same Azure credential as the Foundry provider — no separate
Entra app registration or client secret required.  Set AZURE_CREDENTIAL_TYPE
(already configured for Foundry):

    cli               → AzureCliCredential  (requires: az login, for local dev)
    managed_identity  → ManagedIdentityCredential  (for Azure-hosted deployments)
    default           → DefaultAzureCredential  (tries all credential types)

Environment variables
---------------------
    SP_SITE_URL       Full SharePoint site URL, e.g.
                      https://keshettv.sharepoint.com/sites/Promo
    SP_DOC_LIBRARY    Document library name to scope searches (default: DocLib4)
    AZURE_CREDENTIAL_TYPE
                      Same variable used by the Foundry provider.
                      cli | managed_identity | default  (default: cli)

Usage
-----
    from app.tools.sharepoint_tool import get_sharepoint_client

    client = get_sharepoint_client()
    results = client.search_in_library("פרומו חתונמי")
    # returns list of dicts: [{title, url, text, score}, ...]
"""

from __future__ import annotations

import logging
import os
import re
import urllib.parse

import requests

log = logging.getLogger(__name__)

_SITE_URL    = os.getenv("SP_SITE_URL", "").rstrip("/")
_DOC_LIBRARY = os.getenv("SP_DOC_LIBRARY", "DocLib4")
_CRED_TYPE   = os.getenv("AZURE_CREDENTIAL_TYPE", "cli").lower()

# SharePoint REST API token scope — always the root tenant, not the site path.
_SP_SCOPE = "https://keshettv.sharepoint.com/.default"


def _get_credential():
    """Return an azure-identity credential matching AZURE_CREDENTIAL_TYPE."""
    if _CRED_TYPE == "managed_identity":
        from azure.identity import ManagedIdentityCredential
        return ManagedIdentityCredential()
    if _CRED_TYPE == "default":
        from azure.identity import DefaultAzureCredential
        return DefaultAzureCredential()
    # Default: cli
    from azure.identity import AzureCliCredential
    return AzureCliCredential()


def _extract_cells(row: dict) -> dict:
    """Flatten a SharePoint search result row (Cells.results list) into a dict."""
    out: dict = {}
    cells = row.get("Cells", {})
    if isinstance(cells, dict):
        cells = cells.get("results", [])
    for cell in cells:
        if isinstance(cell, dict) and "Key" in cell:
            out[cell["Key"]] = cell.get("Value", "")
    return out


class SharePointSearchClient:
    """Searches a SharePoint document library via the SharePoint REST Search API."""

    def __init__(self) -> None:
        if not _SITE_URL:
            raise EnvironmentError(
                "SharePoint search requires the SP_SITE_URL environment variable."
            )
        self._credential = _get_credential()

    def _get_token(self) -> str:
        token = self._credential.get_token(_SP_SCOPE)
        return token.token

    def search_in_library(
        self,
        query: str,
        library: str | None = None,
        top: int = 5,
        folder_path: str | None = None,
        file_types: list[str] | None = None,
    ) -> list[dict]:
        """Search within a document library using SharePoint REST Search.

        Parameters
        ----------
        query       : Hebrew (or any language) search query
        library     : document library name (default: SP_DOC_LIBRARY env var)
        top         : maximum number of results
        folder_path : optional subfolder within the library to scope the search,
                      e.g. "חתונה ממבט ראשון".  Hebrew names are URL-encoded.
        file_types  : optional list of file extensions to include,
                      e.g. ["docx", "xlsx", "pdf"]. Excludes media/link files.

        Returns
        -------
        list of dicts, each with keys: title, url, text, score
        """
        lib = library or _DOC_LIBRARY

        # Build the KQL path scope, URL-encoding Hebrew folder names.
        if folder_path:
            encoded_folder = urllib.parse.quote(folder_path, safe="/")
            scope_path = f"{_SITE_URL}/{lib}/{encoded_folder}"
        else:
            scope_path = f"{_SITE_URL}/{lib}"

        # Build optional file-type filter: (FileExtension:docx OR FileExtension:pdf …)
        type_clause = ""
        if file_types:
            parts = " OR ".join(f"FileExtension:{ext}" for ext in file_types)
            type_clause = f" ({parts})"

        querytext = f'{query} path:"{scope_path}"{type_clause}'

        endpoint = f"{_SITE_URL}/_api/search/postquery"
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
        }
        body = {
            "request": {
                "__metadata": {"type": "Microsoft.Office.Server.Search.REST.SearchRequest"},
                "Querytext": querytext,
                "RowLimit": top,
                "SelectProperties": {
                    "results": [
                        "Title",
                        "Path",
                        "HitHighlightedSummary",
                        "FileExtension",
                        "LastModifiedTime",
                        "Author",
                    ]
                },
                "TrimDuplicates": True,
            }
        }

        try:
            resp = requests.post(endpoint, headers=headers, json=body, timeout=15)
        except requests.RequestException as exc:
            log.warning("SharePoint search request failed: %s", exc)
            return []

        if resp.status_code != 200:
            log.warning(
                "SharePoint search returned HTTP %d: %s",
                resp.status_code,
                resp.text[:300],
            )
            return []

        try:
            data = resp.json()
        except ValueError as exc:
            log.warning("SharePoint search response is not JSON: %s", exc)
            return []

        # Navigate the nested OData verbose response:
        # d.query.PrimaryQueryResult.RelevantResults.Table.Rows.results
        try:
            rows = (
                data["d"]["query"]
                ["PrimaryQueryResult"]["RelevantResults"]
                ["Table"]["Rows"]["results"]
            )
        except (KeyError, TypeError):
            log.debug("SharePoint: unexpected response shape — %s", str(data)[:300])
            return []

        results: list[dict] = []
        for i, row in enumerate(rows):
            cells = _extract_cells(row)
            title   = cells.get("Title") or ""
            url     = cells.get("Path") or ""
            snippet = cells.get("HitHighlightedSummary") or ""
            # Strip HTML-style highlight markers SharePoint injects
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            results.append({
                "title": title,
                "url":   url,
                "text":  snippet[:900],
                "score": 1.0 - (i * 0.05),  # rank-based pseudo-score (1.0 → 0.55)
            })

        log.info(
            "SharePoint search '%s' in %s → %d result(s)",
            query[:60], lib, len(results),
        )
        return results


_client: SharePointSearchClient | None = None


def get_sharepoint_client() -> SharePointSearchClient:
    """Singleton accessor — raises EnvironmentError if SP_SITE_URL is not set."""
    global _client
    if _client is None:
        _client = SharePointSearchClient()
    return _client
