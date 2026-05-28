"""Pytest configuration shared across all tests in this folder."""
from dotenv import load_dotenv

# Load .env from the repo root so live tests can read AZURE_SEARCH_* etc.
# Without this, pytest runs with an empty environment and every live test
# self-skips via `pytest.skip("Azure Search credentials not configured")`.
load_dotenv()


def pytest_configure(config):
    """Register custom markers so `-m live` filtering doesn't emit warnings."""
    config.addinivalue_line(
        "markers",
        "live: integration tests that hit live Azure services "
        "(skip with `-m \"not live\"`)",
    )
