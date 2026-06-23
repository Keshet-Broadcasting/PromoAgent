# Case 57 New-Season Retrieval — 2026-06-23

## Task / Problem Summary

Case 57 (`חתונה ממבט ראשון` tonights לקראת עונה חדשה) stayed low after updating the gold answer. The user asked whether to leave it low or solve it, and provided Claude/doc evidence from `מסמך ריאליטי`.

## Root Cause

Two issues combined:

- `dataset.jsonl` case 57 `cleaned_query` removed `לקראת עונה חדשה`, so eval asked a generic tonight question.
- `_detect_event_intent()` prioritized `טונייט` and did not recognize `עונה חדשה` as launch/new-season intent, so retrieval missed launch/novelty sections unless the raw query survived.
- A later CI-protection pass found the same class of bug in case 58: raw query excluded `השקה וגמר`, but `cleaned_query` dropped that exclusion.

## What Went Well

- We verified source support before changing behavior.
- We added failing tests first for launch planning and Word-search kwargs.
- We avoided prompt hardening after prior evidence showed it caused regressions.
- We narrowed the retrieval filter after case 16 showed sensitivity.

## What Went Poorly

- The first fix applied section filters to all single-show event queries and temporarily hurt case 16.
- Langfuse/OTel trace export produced noisy SSL/context messages during local eval.
- Single-case judge results varied: case 57 scored 70-85 depending on run.

## How It Was Solved

- Preserved `לקראת עונה חדשה` in case 57 `cleaned_query`.
- Preserved `ללא השקה וגמר` in case 58 `cleaned_query`.
- Added new-season phrases to `_LAUNCH_PATTERNS`.
- Added `שיקול` and `חידושים` to launch question types.
- Applied doc/question-type filters to single-show launch queries, but kept regular `tonight` queries on the older broad search path.
- Removed `dataset.jsonl` from `.gitignore` so CI can validate the actual eval dataset.
- Added `tests/test_eval_dataset_integrity.py` for schema, IDs, enums, booleans, sorted order, and cleaned-query intent preservation.
- Marked `app/test_chat_connection.py` as a manual smoke script (`__test__ = False`) and reused production `_completion_kwargs()` so normal pytest does not perform a live chat call or use stale `max_tokens` parameters.

## Tradeoffs Or Alternatives Considered

- Prompt rule/few-shot: rejected for now because the earlier hardening attempt regressed the 16-case slice.
- Gold-only change: insufficient because source evidence exists and retrieval can reach it.
- Full 64-case eval: deferred due cost/time; targeted guard slice used known watch cases.

## Tests Added Or Updated

- `test_new_season_tonight_query_gets_launch_retrieval_plan`
- `test_new_season_tonight_word_fetch_prefers_launch_and_novelty_sections`
- `tests/test_eval_dataset_integrity.py` with three CI-safe dataset integrity checks.

## Verification

- `python -m pytest tests/test_retrieval_planning.py -q` -> 33/33 passed.
- `python -m pytest tests/test_eval_dataset_integrity.py tests/test_retrieval_planning.py -q` -> 36/36 passed.
- `python -m pytest tests/test_eval_dataset_integrity.py tests/test_retrieval_planning.py tests/test_preprocess_chunking.py -q` -> 40/40 passed.
- `python -m pytest app/test_chat_connection.py -q` -> no tests collected, expected.
- `python -m pytest -q` -> 120/120 passed after retrying the transient `PyJWT` install.
- Fresh direct case 57 score -> 80.2% overall, judge 5/5.
- Paired case 16/57 eval -> case 16 65%, case 57 70%.
- Targeted guard slice `12,16,24,36,57,58` -> 0 eval errors; case 57 85%, judge 5/5. Known case 58 remains weak and unrelated.
- Fresh case 58 after `cleaned_query` fix -> 64.1% overall, judge 3/5, grounded 100%.

## Lessons Learned

- Eval `cleaned_query` can erase the very signal a case is designed to test.
- CI should validate dataset intent preservation, not only Python syntax and runtime behavior.
- Manual connectivity scripts should not be named/structured like CI unit tests unless they self-skip live calls.
- Retrieval fixes should be intent-specific; broad section filtering can improve one case and hurt adjacent ones.
- For small eval slices, inspect retrieved chunks and full answers before changing prompts.

## Follow-Up Actions

- Revisit case 58 separately if needed; the cleaned-query exclusion is fixed, but the answer still has some factual mismatch in top-row interpretation.
- Consider suppressing local Langfuse/OTel export noise during eval-only commands.
