# Launch-Comparison Range Regression

## Task / Problem Summary

Investigate and fix a RAG answer regression for case 30:
`השווה את נקודות הפתיחה של פרקי ההשקה בין 'נינג'ה ישראל', 'חתונה ממבט ראשון' ו'המירוץ למיליון'.`

The Jun 30 Langfuse trace scored 2 because gpt-5.4-mini answered with only the peak `חתונה ממבט ראשון` launch value (`23.5%`) instead of representing the multi-season range expected by the gold answer.

## Root Cause

Retrieval was not the failing layer. The run had sufficient Excel coverage: 3 show-filter fetches, 369 raw rows, and 11 selected launch rows.

The failure was answer summarization. The model collapsed several launch rows for the same show into a single peak/latest-looking value. Older gpt-4o runs avoided the failure by listing all seasons, so the relevant 20-21% values remained visible.

## What Went Well

- The trace history clearly separated retrieval failure from model summarization failure.
- A focused regression test could reproduce the missing context contract without live Azure calls.
- A single-case judged eval verified the behavior change without rerunning the full 64-case suite.

## What Went Poorly

- The raw Excel table alone was too implicit for gpt-5.4-mini.
- Sorting selected rows by metric made the highest value visually dominant.
- The gold answer expects a broad comparative range while the retrieved data can include higher outlier seasons, so answer shape matters as much as data presence.

## How It Was Solved

`app/retrieval_plan.py` now adds a `### הנחיית השוואת השקות` section for multi-show launch comparisons. It explicitly says not to choose only the highest/latest row unless requested, and summarizes each show with a launch range and all values.

## Tradeoffs Or Alternatives Considered

- Hard-code case 30 expected values: rejected because it would overfit the dataset.
- Change row selection to drop high outliers: rejected because those rows are real evidence and may be needed for other questions.
- Prompt/context guidance: chosen because it preserves evidence while making the aggregation contract explicit.

## Tests Added Or Updated

- Added `test_broad_launch_comparison_context_warns_against_peak_only_summary`.
- Verified focused retrieval tests: 3/3 passed.
- Verified live judged eval for case 30: overall 82.4%, numeric 100%, grounded 100%, judge 4/5.

## Lessons Learned

For broad comparisons with multiple rows per entity, retrieval sufficiency is not enough. The context must state the aggregation contract: range/all values vs latest/highest/average. Model upgrades can expose these implicit contracts even when retrieval is unchanged.

## Follow-Up Actions

- Watch other cross-show or cross-season comparison cases after model changes.
- Consider adding a generic aggregation-summary layer for other metrics, not only launch opening points.
- Review gold answers that prefer a subset range when the retrieved evidence includes valid higher outliers.
