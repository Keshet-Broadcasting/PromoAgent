# 2026-06-21 — service.py Architecture Refactor

## Task / Problem Summary

`app/service.py` had grown to 1569 lines with 8+ distinct responsibilities mixed together:
content-filter sanitizer, context formatters, date parsing, launch/finale tagging, season/VIP
filtering, retrieval planning patterns, SharePoint helpers, the retrieval dispatcher, and the
main `run_query` pipeline.  This made it nearly unmaintainable — a single file could not be
read end-to-end, tested in isolation, or evolved by more than one engineer at a time.

## Root Cause

No architectural boundary was enforced as features accumulated over 6+ months of rapid
iteration.  Each new feature (content filter, VIP retrieval, SharePoint enrichment, etc.) was
appended inline because the existing code was already there.

## How It Was Solved

Incremental 6-step extraction into new focused modules, with `pytest` run after each step:

| Step | New module | Lines | What moved |
|---|---|---|---|
| 1 | `app/formatters.py` | ~130 | `_CF_REPLACEMENTS`, `_sanitize_for_content_filter`, `_fmt_excel`, `_fmt_word`, `_fmt_sharepoint`, `_chunk_pos` |
| 2 | `app/excel_selector.py` | ~250 | Date parsing, `_mark_launch_finale`, launch/finale/tonight/season/VIP filters, `_select_excel_rows_for_plan` |
| 3 | `app/retrieval_plan.py` | ~220 | All compiled regex patterns, `_RetrievalResult`, `_RetrievalPlan`, `_build_retrieval_plan`, plan-level helpers |
| 4 | `app/sharepoint_helper.py` | ~100 | SP availability flag, feature flags, `_is_context_insufficient`, `_fetch_sharepoint_fallback`, `_needs_sharepoint_enrichment`, `_fetch_sharepoint_enrichment` |
| 5 | `app/retriever.py` | ~250 | `_fetch_word_docs`, `_retrieve` dispatcher |
| 6 | `app/service.py` cleanup | — | Removed `_KNOWN_SHOWS` dead list, `_SHOW_ALIASES` dead list, `_BROAD_RETRIEVAL` duplicate, redundant imports |

Result: `service.py` went from 1569 → 410 lines.  It now contains only:
- env/Langfuse setup
- `_expand_aliases`, `_extract_show_name`, `_safe_history_content`, `_contextualize_followup_query`
- `_retrieve` (thin wrapper)
- `_is_hebrew_query`, `_build_sources`, `_confidence`
- `run_query` (the public pipeline entry point)
- `answer_question` (backwards-compat alias)

## What Went Well

- Strict incremental approach (one module at a time, tests after each) made every step safe.
- All new modules have zero circular dependencies (pure imports from leaf → `domain_catalog` → `search_word_docs` → `retrieval_plan` → `retriever` → `service`).
- No test failures except one: the VIP retrieval tests monkeypatched `svc.fetch_show_promos`
  which no longer had effect when the real call moved to `retriever.py`.  Caught immediately.

## What Went Poorly

- The monkeypatch issue required updating two tests to patch `app.retriever.*` instead of
  `app.service.*`.  This was expected but easy to miss if tests had been more fragmented.

## Tradeoffs / Alternatives

- Could have created a single `app/retrieval/` package instead of flat modules.  Chose flat
  for simplicity — fewer `__init__.py` files, easier imports for tests.
- Could have made `_retrieve` accept all collaborators as injected callables (pure DI).
  Chose to pass only `extract_show_name_fn` because that was the only one needed to break
  the circular-import risk.

## Tests Added or Updated

- `tests/test_retrieval_planning.py`: two tests updated to patch `app.retriever.fetch_show_promos`
  and `app.retriever.search_excel_promos` / `search_word_docs` (instead of `app.service.*`).

## Lessons Learned

1. **Monkeypatching tests break on module moves.**  When extracting code to a new module,
   search for `monkeypatch.setattr(svc, "...")` on the moved names and update to the new home.
2. **Feature flag duplication is easy to miss.**  `_BROAD_RETRIEVAL` was defined in `service.py`
   AND re-derived in `retrieval_plan.py` — both needed to stay consistent.  Removing the
   duplicate from `service.py` was the right call.
3. **Circular import risk from `_extract_show_name`.**  The function lived in `service.py` but
   was needed by `retriever.py` (to look up the show for SP enrichment).  Solved by injecting
   it as a callable rather than importing from `service`.

## Follow-Up Actions

- Consider adding per-module `__all__` lists to avoid accidental re-export pollution.
- The Hebrew pattern consolidation (Phase 7: `text_patterns.py`) is still pending — the refactor
  moved patterns into `retrieval_plan.py` but a cross-module consolidation is still worthwhile.
- Add a test that imports each sub-module in isolation to catch future circular-import regressions.
