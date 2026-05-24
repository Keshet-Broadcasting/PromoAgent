"""
test_sharepoint_tool.py

Offline unit tests for SharePointSearchClient.search_in_library() KQL construction.

These tests patch `requests.post` so no live SharePoint or Azure calls are made.
They verify that folder_path and file_types parameters produce the correct KQL
querytext in the POST body, including URL-encoding of Hebrew folder names.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_sp_env(monkeypatch):
    """Set the minimum env vars required to instantiate SharePointSearchClient."""
    monkeypatch.setenv("SP_SITE_URL", "https://keshettv.sharepoint.com/sites/Promo")
    monkeypatch.setenv("SP_DOC_LIBRARY", "DocLib4")
    monkeypatch.setenv("AZURE_CREDENTIAL_TYPE", "cli")


def _make_mock_response(rows: list[dict] | None = None) -> MagicMock:
    """Return a mock requests.Response with a valid SharePoint REST Search payload."""
    rows = rows or []
    payload = {
        "d": {
            "query": {
                "PrimaryQueryResult": {
                    "RelevantResults": {
                        "Table": {
                            "Rows": {"results": rows}
                        }
                    }
                }
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = payload
    return mock_resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_sharepoint_tool_folder_path_injected(monkeypatch):
    """KQL querytext must include the URL-encoded folder path when folder_path is set."""
    _mock_sp_env(monkeypatch)

    captured_body: dict = {}

    def fake_post(url, headers, json, timeout):
        captured_body.update(json)
        return _make_mock_response()

    # Patch the credential so no 'az login' is needed
    mock_token = MagicMock()
    mock_token.token = "fake-token"
    mock_cred = MagicMock()
    mock_cred.get_token.return_value = mock_token

    with patch("requests.post", side_effect=fake_post), \
         patch("azure.identity.AzureCliCredential", return_value=mock_cred):
        # Force re-import so env vars are picked up
        import importlib
        import app.tools.sharepoint_tool as sp_mod
        importlib.reload(sp_mod)

        client = sp_mod.SharePointSearchClient()
        client.search_in_library(
            "תובנות קמפיין",
            folder_path="חתונה ממבט ראשון",
        )

    querytext = captured_body["request"]["Querytext"]
    # Hebrew chars must be URL-encoded (%D7%... style)
    assert "%D7" in querytext, f"Hebrew folder path not URL-encoded: {querytext}"
    # Folder name must appear in some form (encoded)
    assert "DocLib4" in querytext, f"Library name missing from KQL: {querytext}"
    assert "path:" in querytext, f"KQL path filter missing: {querytext}"


def test_sharepoint_tool_file_type_filter(monkeypatch):
    """KQL querytext must include FileExtension clauses when file_types is provided."""
    _mock_sp_env(monkeypatch)

    captured_body: dict = {}

    def fake_post(url, headers, json, timeout):
        captured_body.update(json)
        return _make_mock_response()

    mock_token = MagicMock()
    mock_token.token = "fake-token"
    mock_cred = MagicMock()
    mock_cred.get_token.return_value = mock_token

    with patch("requests.post", side_effect=fake_post), \
         patch("azure.identity.AzureCliCredential", return_value=mock_cred):
        import importlib
        import app.tools.sharepoint_tool as sp_mod
        importlib.reload(sp_mod)

        client = sp_mod.SharePointSearchClient()
        client.search_in_library(
            "אסטרטגיה",
            file_types=["docx", "xlsx", "pdf"],
        )

    querytext = captured_body["request"]["Querytext"]
    assert "FileExtension:docx" in querytext, f"docx filter missing: {querytext}"
    assert "FileExtension:xlsx" in querytext, f"xlsx filter missing: {querytext}"
    assert "FileExtension:pdf"  in querytext, f"pdf filter missing: {querytext}"
