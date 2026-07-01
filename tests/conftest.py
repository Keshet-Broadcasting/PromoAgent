"""Pytest configuration shared across all tests in this folder."""
import os

import pytest
from dotenv import load_dotenv

# Load .env from the repo root so live tests can read AZURE_SEARCH_* etc.
# Without this, pytest runs with an empty environment and every live test
# self-skips via `pytest.skip("Azure Search credentials not configured")`.
load_dotenv()


# Env vars a `live` (integration) test needs to hit Azure Cognitive Search.
_LIVE_ENV_VARS = ("AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_KEY")


def live_creds_present() -> bool:
    """True when both Azure Search creds are set (non-empty)."""
    return all(os.getenv(var) for var in _LIVE_ENV_VARS)


def pytest_configure(config):
    """Register custom markers so `-m live` filtering doesn't emit warnings."""
    config.addinivalue_line(
        "markers",
        "live: integration tests that hit live Azure services "
        "(auto-deselected when AZURE_SEARCH_* creds are absent; "
        "force with RUN_LIVE_TESTS=1)",
    )


def pytest_collection_modifyitems(config, items):
    """Keep CI summaries clean: **deselect** (not skip) `live` integration tests
    when Azure Search credentials are absent.

    Rationale
    ---------
    The `live` data-health tests assert properties of the *real* search index
    (schema fields, show_name coverage, per-show row counts). They can only run
    where creds exist. Previously they self-skipped, producing a permanent
    "9 skipped" line in every CI run that hid whether they were meaningful.

    Behaviour now:
    - creds present (local `.env` or a CI stage that injects them) → run them.
    - `RUN_LIVE_TESTS=1` → run them (and fail loudly if creds are missing, so a
      misconfigured integration stage cannot pass silently).
    - otherwise → deselect them, so the unit run reports `0 skipped`.
    """
    if live_creds_present() or os.getenv("RUN_LIVE_TESTS") == "1":
        return

    selected: list = []
    deselected: list = []
    for item in items:
        if item.get_closest_marker("live"):
            deselected.append(item)
        else:
            selected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected
