"""Detect (and optionally delete) duplicate rows in the tv-promos index.

Background
----------
tv-promos accumulated ~45% duplicate rows because the document id used to include
the positional row index, and TWO pipelines (ingest_excel.py + ingest_json_to_azure.py)
wrote the same logical rows with different ids. The id generators are now
content-based (show|season|episode|date), so future ingestion is idempotent —
this script cleans the duplicates that already exist.

A logical row is identified by (show_name, season, episode_number, date). Among
duplicates, the copy with the RICHEST promo_text is kept (the JSON pipeline
builds a fuller text than the raw-Excel pipeline).

Usage
-----
    python scripts/dedup_tv_promos.py            # DRY RUN — reports only, no writes
    python scripts/dedup_tv_promos.py --apply    # actually delete the duplicates

The dry run writes the full keep/delete plan to dedup_tv_promos_plan.json so you
can review exactly which document ids would be removed before applying.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Corporate proxy uses a self-signed CA; route TLS through the OS trust store.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

load_dotenv()

from app.search_word_docs import _PROMOS_INDEX, _client  # noqa: E402

PLAN_PATH = _REPO_ROOT / "dedup_tv_promos_plan.json"
KEY_FIELDS = ("show_name", "season", "episode_number", "date")


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _key(doc: dict) -> tuple:
    return tuple(_s(doc.get(f)) for f in KEY_FIELDS)


def main() -> None:
    apply = "--apply" in sys.argv
    client = _client(_PROMOS_INDEX)

    docs = list(client.search(
        search_text="*",
        select=["id", "show_name", "season", "episode_number", "date", "promo_text"],
        top=100000,
    ))
    print(f"Scanned {len(docs)} documents in {_PROMOS_INDEX}.")

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for d in docs:
        groups[_key(d)].append(d)

    keep_ids: list[str] = []
    delete_ids: list[str] = []
    per_show_dupes: dict[str, int] = defaultdict(int)

    for key, members in groups.items():
        # Keep the richest promo_text; deterministic tie-break on id.
        members.sort(key=lambda d: (len(_s(d.get("promo_text"))), _s(d.get("id"))), reverse=True)
        keep_ids.append(members[0]["id"])
        for dup in members[1:]:
            delete_ids.append(dup["id"])
            per_show_dupes[_s(dup.get("show_name")) or "(blank)"] += 1

    print(f"Distinct logical rows: {len(groups)}")
    print(f"Duplicate copies to delete: {len(delete_ids)}")
    print(f"Rows after dedup: {len(keep_ids)}  (was {len(docs)})")
    print("\nDuplicates by show (top 15):")
    for show, n in sorted(per_show_dupes.items(), key=lambda x: -x[1])[:15]:
        print(f"  {show:<32} {n}")

    plan = {
        "index": _PROMOS_INDEX,
        "scanned": len(docs),
        "distinct_rows": len(groups),
        "to_delete": len(delete_ids),
        "delete_ids": delete_ids,
    }
    PLAN_PATH.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nFull plan written to {PLAN_PATH.name} ({len(delete_ids)} ids to delete).")

    if not apply:
        print("\nDRY RUN — nothing deleted. Re-run with --apply to delete the duplicates above.")
        return

    print(f"\n--apply set: deleting {len(delete_ids)} duplicate documents...")
    deleted = 0
    for i in range(0, len(delete_ids), 1000):
        batch = [{"id": doc_id} for doc_id in delete_ids[i:i + 1000]]
        client.delete_documents(documents=batch)
        deleted += len(batch)
        print(f"  deleted {deleted}/{len(delete_ids)}")
    print(f"Done. Deleted {deleted} duplicates; {len(keep_ids)} rows remain.")


if __name__ == "__main__":
    main()
