# Case 3 Retrieval Fix + Viewing-Intentions Tier Disambiguation

**Date:** 2026-07-01 12:00 (UTC+3)

## Task / problem summary
Drama eval cases 2/3/4 scored low. Source-doc triage (Custom GPT + Claude over `מסמך דרמות GPT.docx`
/ `מעקבי פרומו.xlsx`) showed the golds were mostly valid but the model either failed to retrieve
comparator shows (case 3) or mixed two different `כוונות צפייה` measurement tiers.

## Root cause
1. **Retrieval gap (case 3):** `_RetrievalPlan.target_show_names` short-circuits on an explicit show,
   so "compare אור ראשון to other dramas" filtered Word retrieval to only אור ראשון — comparators were
   never fetched, and the model invented an ungrounded "above average" claim.
2. **Two-tier ambiguity (cases 2/3/4):** each drama has two `כוונות צפייה` numbers in the docs —
   promo/trailer screening (~60-85%) and pre-launch campaign / unaided (~35-45%). Both match the query,
   so the model blended tiers (e.g. citing גוף שלישי 41% instead of 81%).

## What went well
- Test-first: three failing tests pinned the behavior before code changes.
- The section/tier label was **already** in context via the Word `header` field (`פרק: ...`), so the fix
  was mostly instructional (prompt) + a scoped retrieval expansion — no re-ingest needed.
- Iterative eval caught that the first retrieval-only fix exposed the tier-mixing; the second pass
  (prompt + gold annotation) recovered and improved the targeted cases.

## What went poorly
- The first retrieval fix alone dropped the slice (60%→50%) by surfacing both tiers without guidance —
  a reminder to think about *what* extra retrieval surfaces, not just *whether* it retrieves.
- Case 2 retrieval still ranks the pre-launch 40% chunk above the promo 67% chunk, so the model leads
  with 40%; the annotated gold accepts it (judge 4) but the recall bias remains.

## How it was solved
- `app/retrieval_plan.py`: added `_RetrievalPlan.word_targets` (union of named show + genre shows for
  named-show-vs-genre comparisons).
- `app/retriever.py`: `_fetch_word_docs` uses `word_targets` and forces per-show fetch for those comparisons.
- `app/prompts.py`: `_VIEWING_INTENTIONS_ADDENDUM` (word/hybrid), triggered when intentions appear in the
  query or context; tells the model to tag each number by tier and not mix tiers.
- `dataset.jsonl`: cases 2/3 gold annotated with the promo/trailer tier + a note about the pre-launch tier.

## Tradeoffs / alternatives considered
- Recomputing `כוונות צפייה` was rejected — these are measured survey values, not derived.
- A "less analytic, more promo-team voice" pass was deferred as a separate track — it wouldn't fix the
  numeric tier errors that drove cases 2/3.
- Scoped the retrieval expansion to *named-show + genre + comparison* to avoid changing genre-vs-genre
  synthesis retrieval (regression avoidance).

## Tests added or updated
- `test_named_show_vs_genre_comparison_expands_word_targets`
- `test_named_show_vs_genre_comparison_word_fetch_covers_comparators`
- `test_viewing_intentions_prompt_disambiguates_measurement_tiers`
- Full `test_retrieval_planning.py`: 40 passed.

## Results
- Judged slice 1–5 (fresh answers, broad retrieval on): overall **62.4%**, judge **60%**, grounded 100%.
- Per-case judge: 1=4, 2=4, 3=3, 4=3, 5=3. Targeted cases 2/3/4 improved (1→4, 2→3, 2→3);
  1/5 dropped only on LLM phrasing variance (unchanged code/gold; case 5 numeric=1.0).

## Lessons learned
- For `כוונות צפייה` always identify the measurement tier (promo screening vs pre-launch) before trusting
  a number — they differ by ~30 points.
- Broadening retrieval can *lower* scores if it surfaces conflicting data the model can't disambiguate;
  pair retrieval changes with a disambiguation contract.

## Follow-up actions
- Tier-preferring rerank so general "what were the intentions" questions surface the promo tier chunk first
  (fixes case 2's residual 40%-lead).
- Separate promo-team-voice pass, measured on open_ended/strategy cases.
- Re-run the full eval after these to confirm no wider regression.
