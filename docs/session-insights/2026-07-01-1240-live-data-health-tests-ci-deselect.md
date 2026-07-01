# Live Data-Health Tests: Deselect vs Skip in CI

**Date:** 2026-07-01 12:40 (UTC+3)

## Task / problem summary
The Azure DevOps pipeline (`kst-Promo-Agent-ci-cd`) permanently reported **9 skipped**
tests from `tests/test_data_health.py`. They are `@pytest.mark.live` integration tests
that hit Azure Cognitive Search (`word-docs`, `tv-promos` indexes) and self-skip when
`AZURE_SEARCH_ENDPOINT` / `AZURE_SEARCH_KEY` are absent. Goal: stop the noisy skips
without weakening the tests, and let them run where credentials exist.

## Root cause
- The tests were written to validate the **real** index (schema fields, ≥80% show_name
  coverage, ≥30 catalog overlap, per-show row counts). They intentionally require creds.
- In CI those creds aren't in the test step's environment → `pytest.skip` on every run.
- The pipeline delegates the actual `pytest` command to a shared template
  (`templates/stages/ci-cd.yml@pipelines`) in another repo, so the test-step environment
  can't be changed from this repo.

## Why not the "obvious" fixes
- **Mocking the Search client (rejected):** these are data-health tests; a mock makes
  every assertion validate the mock, not the index — false green, zero regression value.
- **Dedicated per-CI integration stage (rejected as overkill):** index changes only on
  ingest/catalog edits, not typical code PRs. Adding a stage means editing a prod-deploying
  templated pipeline, pinning an agent pool, linking a variable group, mapping a secret, and
  ensuring egress — ongoing cost/risk for a check that rarely needs to fire on code changes.

## How it was solved
- `tests/conftest.py`: added `pytest_collection_modifyitems` that **deselects** (not skips)
  `live` tests when creds are absent, so CI shows `0 skipped`. They still run automatically
  when `AZURE_SEARCH_*` are present, or when `RUN_LIVE_TESTS=1`.
- `tests/test_data_health.py`: DRY'd the duplicated creds/skip logic into `_require_search_creds()`
  + `_live_index_client()`. Under `RUN_LIVE_TESTS=1`, missing creds now **fail loudly**
  (`pytest.fail`) instead of skipping, so a misconfigured integration run can't pass silently.
- Documented the integration gate: `RUN_LIVE_TESTS=1 pytest tests/test_data_health.py -m live`,
  to be run after any ingest / catalog change (natural checkpoint), not on every code build.

## Tradeoffs / alternatives considered
- `deselect` vs `skip`: deselect keeps the summary clean (`N passed, M deselected, 0 skipped`)
  and is honest ("these belong to a different run"), whereas skip implies "tried and gave up".
- Left `azure-pipelines.yml` untouched to avoid risk to the shared-template prod pipeline.
- A **nightly scheduled** integration run is the recommended future automation if desired —
  cheaper and safer than a per-build stage.

## Tests added or updated
- `tests/conftest.py` — new collection hook + `live_creds_present()` helper.
- `tests/test_data_health.py` — `_require_search_creds()` / `_live_index_client()`; fail-loud
  under `RUN_LIVE_TESTS=1`; updated docstring.

## Verification
- CI-simulation (creds cleared in-process, no file mutation): `18 passed, 9 deselected, 0 skipped`.
- With local `.env` creds: `27 passed` (all 9 live tests run and pass; index reachable).

## Lessons learned
- For integration tests that require external services, prefer **deselect-when-unconfigured**
  over self-skip so CI summaries stay meaningful.
- Don't mock away the thing a test exists to verify.
- When the pipeline is a template consumer, in-repo test-collection behavior is the reliable
  lever; heavy pipeline surgery is usually the wrong first move.

## Follow-up actions
- Optional: nightly scheduled pipeline running `RUN_LIVE_TESTS=1 pytest -m live` if automated
  index monitoring is wanted.
- Ensure whoever runs an ingest runs the integration gate command afterward.
