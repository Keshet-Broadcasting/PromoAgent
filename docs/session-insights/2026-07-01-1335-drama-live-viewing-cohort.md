# Drama Live-Viewing Cohort Retrieval

**Date:** 2026-07-01 13:35 (UTC+3)

## Task / Problem Summary
PromoBot produced a strong creative answer for a drama live-viewing / binge problem, but the examples were ordered like a flat high-rating list. It let `להיות איתה` and `צומת מילר` dominate while underweighting `נוטוק`, `אור ראשון`, and `פאלו אלטו`.

## Root Cause
The query combines two axes that the context did not distinguish:

- **High-rating successes:** examples that prove broadcast drama can still win.
- **Live/binge learning cases:** examples that directly teach how to fight delayed viewing, completions, spoilers, or lack of urgency.

The catalog also keeps `נוטוק` under `entertainment`, so plain `drama` targeting excluded it even though source-truth triage says it is central to this business problem.

## What Went Well
- We followed the eval/regression triage rule before code: Custom GPT, source-doc check, and Gemini-as-judge all agreed the answer shape was good but evidence prioritization needed refinement.
- We checked the prior Jun 3 fix and reused its lesson: broad retrieval + per-show coverage + strategy-section bias, rather than replacing the architecture.
- The fix stayed scoped to a specific business intent; `נוטוק` was not globally reclassified as drama.

## What Went Poorly
- The previous regression guard only prevented reality shows from leaking into drama queries; it did not protect against a subtler “wrong drama cohort / wrong ranking axis” failure.
- Direct shell diagnostics with Hebrew literals were unreliable due to console encoding, so UTF-8 file-backed diagnostics were safer.

## How It Was Solved
- Added `drama_live_viewing` intent in `app/retrieval_plan.py` for drama questions containing live/binge/completion/spoiler terms.
- Expanded the target set for this intent with `אור ראשון`, `נוטוק`, `אף אחד לא עוזב את פאלו אלטו`, and `הראש`.
- Added `### הנחיית צפייה בלייב בדרמות` to broad context, instructing the model to split rating winners from live-viewing learning cases and not let `צומת מילר` dominate only because of rating.
- Updated `app/retriever.py` so per-show Word fetch for this intent prefers `תובנות`, `אסטרטגיה`, and `מחקר`.

## Tradeoffs / Alternatives Considered
- Reclassifying `נוטוק` globally as drama was rejected. It may be relevant to this problem, but that does not mean every drama query should treat it as a drama.
- Hard-blocking `צומת מילר` was rejected. It can remain a supporting rating/historical example, but should not be the main solution unless Word-drama evidence supports it.

## Tests Added Or Updated
- `test_drama_live_viewing_query_adds_priority_learning_cases`
- `test_drama_live_viewing_context_splits_rating_and_learning_axes`

## Verification
- Focused new tests first failed, then passed.
- Full `tests/test_retrieval_planning.py`: 42 passed.
- Exact-prompt live retrieval with `BROAD_RETRIEVAL_ENABLED=true`: `נוטוק` and `פאלו אלטו` appeared in both Excel and Word docs; `אור ראשון` appeared in Word; guidance appeared in context.

## Lessons Learned
- “Highest rating” and “best case for the strategy problem” are different ranking axes.
- For open-ended promo strategy questions, the retrieval layer sometimes needs to express the business cohort explicitly, not only the source taxonomy.
- When a previous fix solved contamination, a later regression may still be about prioritization inside the now-correct cohort.

## Follow-Up Actions
- Run the full answer once through the app/LLM and compare against the Gemini judgment: keep PromoBot’s eventization/practical formula while ensuring the first examples include `אור ראשון`, `נוטוק`, and `פאלו אלטו`.
- Consider adding this query as an eval case if it becomes a recurring product benchmark.
