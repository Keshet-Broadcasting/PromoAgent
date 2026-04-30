"""
update_indexer_to_txt.py

Updates the Azure AI Search indexer "search-1775984451728-indexer" to:
  - dataSourceName  -> "word-txt-datasource"   (plain-text pre-processed files)
  - skillsetName    -> "word-docs-skillset"     (unchanged)
  - targetIndexName -> "word-docs"              (unchanged)
  - outputFieldMappings -> []                   (projections handle all field mapping)
  - indexStorageMetadataOnlyForOversizedDocuments -> False

All other settings are preserved from the live indexer definition.

After updating, the indexer is reset (clears high-water mark) and then run.
Status is polled every 15 seconds until a terminal state is reached.

Usage:
    python update_indexer_to_txt.py
"""

import os
import time
import warnings
import logging
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")

INDEXER_NAME = "search-1775984451728-indexer"
DATASOURCE_NAME = "word-txt-datasource"
SKILLSET_NAME = "word-docs-skillset"
TARGET_INDEX = "word-docs"

API_VERSION = "2024-09-01-preview"
POLL_INTERVAL_S = 15
MAX_WAIT_MIN = 60


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _headers() -> dict:
    return {"Content-Type": "application/json", "api-key": AZURE_SEARCH_KEY}


def _url(path: str) -> str:
    return f"{AZURE_SEARCH_ENDPOINT.rstrip('/')}{path}?api-version={API_VERSION}"


def _get(path: str) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = requests.get(_url(path), headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def _put(path: str, body: dict) -> requests.Response:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = requests.put(_url(path), headers=_headers(), json=body, timeout=30)
    return r


def _post(path: str) -> requests.Response:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = requests.post(_url(path), headers=_headers(), timeout=30)
    return r


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    if not AZURE_SEARCH_ENDPOINT or not AZURE_SEARCH_KEY:
        raise EnvironmentError(
            "AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY must be set in .env"
        )

    # -----------------------------------------------------------------------
    # 1. Fetch current indexer definition
    # -----------------------------------------------------------------------
    logger.info(f"Fetching current definition of '{INDEXER_NAME}' ...")
    indexer = _get(f"/indexers/{INDEXER_NAME}")

    logger.info(f"  dataSourceName  : {indexer.get('dataSourceName')!r}  ->  {DATASOURCE_NAME!r}")
    logger.info(f"  targetIndexName : {indexer.get('targetIndexName')!r}  ->  {TARGET_INDEX!r}")
    logger.info(f"  skillsetName    : {indexer.get('skillsetName')!r}  ->  {SKILLSET_NAME!r}")

    # -----------------------------------------------------------------------
    # 2. Apply changes
    # -----------------------------------------------------------------------
    indexer["dataSourceName"] = DATASOURCE_NAME
    indexer["targetIndexName"] = TARGET_INDEX
    indexer["skillsetName"] = SKILLSET_NAME
    indexer["outputFieldMappings"] = []

    # Ensure /document/content is always populated in the enrichment tree
    config = indexer.setdefault("parameters", {}).setdefault("configuration", {})
    config["indexStorageMetadataOnlyForOversizedDocuments"] = False

    # Strip read-only fields that must not be sent in a PUT body
    for key in ("@odata.context", "@odata.etag"):
        indexer.pop(key, None)

    # -----------------------------------------------------------------------
    # 3. PUT the updated definition
    # -----------------------------------------------------------------------
    logger.info(f"\nUpdating indexer '{INDEXER_NAME}' ...")
    r = _put(f"/indexers/{INDEXER_NAME}", indexer)

    if r.status_code == 201:
        logger.info("  Indexer created (HTTP 201).")
    elif r.status_code in (200, 204):
        logger.info(f"  Indexer updated (HTTP {r.status_code}).")
    else:
        logger.error(f"  ERROR {r.status_code}:\n{r.text}")
        r.raise_for_status()

    # -----------------------------------------------------------------------
    # 4. Reset (forces reprocessing of all documents)
    # -----------------------------------------------------------------------
    logger.info("\nResetting indexer ...")
    r = _post(f"/indexers/{INDEXER_NAME}/reset")
    if r.status_code == 204:
        logger.info("  Reset OK (204).")
    else:
        logger.error(f"  ERROR {r.status_code}: {r.text}")
        r.raise_for_status()

    # -----------------------------------------------------------------------
    # 5. Run
    # -----------------------------------------------------------------------
    logger.info("\nTriggering indexer run ...")
    r = _post(f"/indexers/{INDEXER_NAME}/run")
    if r.status_code == 202:
        logger.info("  Run accepted (202). Starting to poll ...\n")
    else:
        logger.error(f"  ERROR {r.status_code}: {r.text}")
        r.raise_for_status()

    # -----------------------------------------------------------------------
    # 6. Poll until terminal state
    # -----------------------------------------------------------------------
    TERMINAL = {"success", "transientFailure", "error"}
    deadline = time.monotonic() + MAX_WAIT_MIN * 60
    last_result: dict = {}

    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_S)

        status_data = _get(f"/indexers/{INDEXER_NAME}/status")
        last_result = status_data.get("lastResult") or {}
        run_status = last_result.get("status", "-")
        processed = last_result.get("itemsProcessed", 0)
        failed = last_result.get("itemsFailed", 0)

        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        logger.info(
            f"  [{ts} UTC]  status={run_status:<16}  "
            f"processed={processed}  failed={failed}"
        )

        if run_status in TERMINAL:
            break
    else:
        logger.warning(f"\nTimed out after {MAX_WAIT_MIN} minutes — check the portal for status.")
        return

    # -----------------------------------------------------------------------
    # 7. Final summary
    # -----------------------------------------------------------------------
    run_status = last_result.get("status", "unknown")
    processed = last_result.get("itemsProcessed", 0)
    failed = last_result.get("itemsFailed", 0)
    end_time = last_result.get("endTime", "")
    errors = last_result.get("errors") or []
    run_warnings = last_result.get("warnings") or []

    logger.info(f"\n{'=' * 52}")
    logger.info(f"  Final status   : {run_status}")
    logger.info(f"  Docs processed : {processed}")
    logger.info(f"  Docs failed    : {failed}")
    if end_time:
        logger.info(f"  Completed at   : {end_time}")
    if errors:
        logger.info(f"\n  Errors ({len(errors)}):")
        for e in errors[:5]:
            logger.info(f"    - {e.get('errorMessage', e)}")
        if len(errors) > 5:
            logger.info(f"    ... and {len(errors) - 5} more")
    if run_warnings:
        logger.info(f"\n  Warnings ({len(run_warnings)}):")
        for w in run_warnings[:5]:
            logger.info(f"    - {w.get('message', w)}")
        if len(run_warnings) > 5:
            logger.info(f"    ... and {len(run_warnings) - 5} more")
    logger.info("=" * 52)


if __name__ == "__main__":
    main()
