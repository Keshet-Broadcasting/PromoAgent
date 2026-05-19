"""
sharepoint_tool.py

SharePoint integration via Microsoft Agent 365 MCP endpoints.

Connects to the hosted MCP servers at agent365.svc.cloud.microsoft to
search and retrieve documents from the Keshet SharePoint tenant.  Auth
uses MSAL with a confidential client (or device flow for local dev).

MCP servers used:
    mcp_SharePointRemoteServer   — general SharePoint search/read
    mcp_SharePointListsTools     — SharePoint lists access

Environment variables
---------------------
    SP_TENANT_ID         Entra tenant ID (default: Keshet tenant)
    SP_CLIENT_ID         Entra app client ID for MCP access
    SP_CLIENT_SECRET     Client secret (for confidential client flow)
    SP_SITE_URL          SharePoint site URL (default: https://keshettv.sharepoint.com/)
    SP_MCP_SERVER        MCP server ID to use (default: mcp_SharePointRemoteServer)

Usage
-----
    from app.tools.sharepoint_tool import get_sharepoint_client

    client = get_sharepoint_client()
    tools = client.list_tools()
    result = client.call_tool("search_files", {"query": "פרומו חתונמי"})
"""

from __future__ import annotations

import json
import logging
import os

import msal
import requests

log = logging.getLogger(__name__)

_TENANT_ID = os.getenv("SP_TENANT_ID", "")
_CLIENT_ID = os.getenv("SP_CLIENT_ID", "")
_CLIENT_SECRET = os.getenv("SP_CLIENT_SECRET", "")
_SITE_URL = os.getenv("SP_SITE_URL", "")
_MCP_SERVER = os.getenv("SP_MCP_SERVER", "mcp_SharePointRemoteServer")

_MCP_BASE = "https://agent365.svc.cloud.microsoft/agents/servers"

_SCOPES = [
    "https://agent365.svc.cloud.microsoft/McpServers.SharePoint.All",
    "https://agent365.svc.cloud.microsoft/McpServers.Files.All",
    "https://agent365.svc.cloud.microsoft/McpServers.SharepointLists.All",
    "https://agent365.svc.cloud.microsoft/McpServers.OneDrive.All",
]


def _parse_mcp_response(text: str) -> list[dict]:
    """Parse SSE-style or plain JSON responses from MCP endpoints."""
    items = []
    for line in text.splitlines():
        if line.startswith("data: "):
            raw = line[6:]
            try:
                items.append(json.loads(raw))
            except json.JSONDecodeError:
                items.append({"raw": raw})
    if items:
        return items
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return [json.loads(stripped)]
        except json.JSONDecodeError:
            pass
    return [{"raw": text}]


class SharePointMCPClient:
    """Client for Microsoft Agent 365 MCP SharePoint endpoints."""

    def __init__(self) -> None:
        if not _TENANT_ID or not _CLIENT_ID:
            raise EnvironmentError(
                "SharePoint MCP requires SP_TENANT_ID and SP_CLIENT_ID environment variables"
            )
        if not _SITE_URL:
            raise EnvironmentError(
                "SharePoint MCP requires SP_SITE_URL environment variable"
            )
        self._token: str | None = None
        self._msal_app = None

    def _get_msal_app(self):
        if self._msal_app is not None:
            return self._msal_app

        authority = f"https://login.microsoftonline.com/{_TENANT_ID}"
        if _CLIENT_SECRET:
            self._msal_app = msal.ConfidentialClientApplication(
                _CLIENT_ID,
                authority=authority,
                client_credential=_CLIENT_SECRET,
            )
        else:
            self._msal_app = msal.PublicClientApplication(
                _CLIENT_ID,
                authority=authority,
            )
        return self._msal_app

    def _acquire_token(self) -> str:
        """Acquire an access token for the MCP endpoints.

        Uses client credentials (confidential) when SP_CLIENT_SECRET is set,
        otherwise attempts silent token acquisition from cache.
        """
        if self._token:
            return self._token

        app = self._get_msal_app()

        if _CLIENT_SECRET:
            result = app.acquire_token_for_client(scopes=_SCOPES)
        else:
            accounts = app.get_accounts()
            if accounts:
                result = app.acquire_token_silent(_SCOPES, account=accounts[0])
            else:
                log.error("No cached accounts and no client secret — cannot acquire token silently.")
                raise RuntimeError(
                    "SharePoint MCP requires SP_CLIENT_SECRET for server-to-server auth, "
                    "or a cached token from a prior device-flow login."
                )

        if not result or "access_token" not in result:
            error = result.get("error_description", "Unknown error") if result else "No result"
            raise RuntimeError(f"Failed to acquire MCP token: {error}")

        self._token = result["access_token"]
        log.info("SharePoint MCP token acquired")
        return self._token

    def _call_mcp(self, method: str, params: dict | None = None) -> list[dict]:
        """Send a JSON-RPC request to the configured MCP server."""
        token = self._acquire_token()
        url = f"{_MCP_BASE}/{_MCP_SERVER}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        }
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": method,
            "params": {**(params or {}), "siteUrl": _SITE_URL},
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            log.error("MCP call failed: %d %s", resp.status_code, resp.text[:200])
            raise RuntimeError(f"MCP call failed with status {resp.status_code}")
        return _parse_mcp_response(resp.text)

    def list_tools(self) -> list[dict]:
        """Discover available tools on the MCP server."""
        items = self._call_mcp("tools/list")
        for item in items:
            if isinstance(item, dict) and "result" in item:
                tools = item["result"].get("tools", [])
                return tools
        return []

    def call_tool(self, tool_name: str, arguments: dict | None = None) -> list[dict]:
        """Invoke a specific MCP tool by name."""
        params = {"name": tool_name}
        if arguments:
            params["arguments"] = arguments
        return self._call_mcp("tools/call", params)

    def search_files(self, query: str, top: int = 5) -> list[dict]:
        """Search SharePoint files using the MCP search tool.

        Returns a simplified list of results.
        """
        try:
            results = self.call_tool("search_files", {"query": query, "top": top})
            return results
        except Exception as exc:
            log.warning("SharePoint search failed: %s", exc)
            return []


_client: SharePointMCPClient | None = None


def get_sharepoint_client() -> SharePointMCPClient:
    """Singleton accessor."""
    global _client
    if _client is None:
        _client = SharePointMCPClient()
    return _client
