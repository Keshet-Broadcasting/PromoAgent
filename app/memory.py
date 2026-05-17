"""
memory.py

Per-user persistent memory backed by Azure Table Storage.

Each user (identified by their Entra ID oid) can have stored "facts" that
the agent remembers across sessions.  Facts are short key-value pairs
extracted from conversations (e.g., "preferred_show" → "חתונה ממבט ראשון").

Table schema (PartitionKey = user_oid, RowKey = fact slug):
    PartitionKey  str   Entra ID object ID
    RowKey        str   Fact key (slugified)
    value         str   Fact value
    source        str   How it was learned: "extracted" | "user_stated"
    updated_at    str   ISO timestamp

Environment variables
---------------------
    MEMORY_STORAGE_ACCOUNT   Storage account name (default: aistoragekeshet)
    MEMORY_TABLE_NAME        Table name (default: usermemory)
    MEMORY_STORAGE_KEY       Account key (if not using managed identity)

Usage
-----
    from app.memory import get_memory_store

    store = get_memory_store()
    store.upsert("user-oid-123", "preferred_show", "חתונה ממבט ראשון")
    facts = store.get_all("user-oid-123")
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_TABLE_NAME = os.getenv("MEMORY_TABLE_NAME", "usermemory")
_STORAGE_ACCOUNT = os.getenv("MEMORY_STORAGE_ACCOUNT", "aistoragekeshet")
_STORAGE_KEY = os.getenv("MEMORY_STORAGE_KEY", "")
_MAX_FACTS_PER_USER = 50


class MemoryStore:
    """Thin wrapper around Azure Table Storage for per-user facts."""

    def __init__(self) -> None:
        self._client = None

    def _get_table(self):
        if self._client is not None:
            return self._client
        try:
            from azure.data.tables import TableServiceClient
        except ImportError as exc:
            raise ImportError(
                "azure-data-tables is required for memory. "
                "Run: pip install azure-data-tables"
            ) from exc

        if _STORAGE_KEY:
            conn_str = (
                f"DefaultEndpointsProtocol=https;"
                f"AccountName={_STORAGE_ACCOUNT};"
                f"AccountKey={_STORAGE_KEY};"
                f"EndpointSuffix=core.windows.net"
            )
            service = TableServiceClient.from_connection_string(conn_str)
        else:
            from azure.identity import DefaultAzureCredential
            endpoint = f"https://{_STORAGE_ACCOUNT}.table.core.windows.net"
            service = TableServiceClient(endpoint=endpoint, credential=DefaultAzureCredential())

        self._client = service.create_table_if_not_exists(table_name=_TABLE_NAME)
        log.info("Memory store initialized: table=%s account=%s", _TABLE_NAME, _STORAGE_ACCOUNT)
        return self._client

    def upsert(self, user_oid: str, fact_key: str, fact_value: str, source: str = "extracted") -> None:
        table = self._get_table()
        entity = {
            "PartitionKey": user_oid,
            "RowKey": fact_key,
            "value": fact_value,
            "source": source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        table.upsert_entity(entity)
        log.info("Memory upsert: user=%s key=%s value=%s", user_oid[:8], fact_key, fact_value[:50])

    def get_all(self, user_oid: str) -> list[dict]:
        table = self._get_table()
        try:
            entities = table.query_entities(f"PartitionKey eq '{user_oid}'")
            return [
                {"key": e["RowKey"], "value": e["value"], "source": e.get("source", ""), "updated_at": e.get("updated_at", "")}
                for e in entities
            ]
        except Exception as exc:
            log.warning("Failed to retrieve memory for user=%s: %s", user_oid[:8], exc)
            return []

    def delete(self, user_oid: str, fact_key: str) -> None:
        table = self._get_table()
        try:
            table.delete_entity(partition_key=user_oid, row_key=fact_key)
        except Exception:
            pass

    def format_for_prompt(self, user_oid: str) -> str | None:
        """Return a compact string of user facts for injection into the system prompt.

        Returns None if the user has no stored facts.
        """
        facts = self.get_all(user_oid)
        if not facts:
            return None
        lines = [f"- {f['key']}: {f['value']}" for f in facts[:_MAX_FACTS_PER_USER]]
        return "## זיכרון משתמש\n\nעובדות שנשמרו מהשיחות הקודמות:\n" + "\n".join(lines)


_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    """Singleton accessor."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
