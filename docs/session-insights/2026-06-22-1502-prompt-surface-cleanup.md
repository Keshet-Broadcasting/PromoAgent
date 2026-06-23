# Prompt Surface Cleanup — Positive Operating Rules

## Task / Problem Summary

The team reviewed notes suggesting that system prompts should prefer positive instructions over repeated "do not" style prohibitions. `app/system_prompt.txt` had grown to 438 lines with many accumulated bug-patch rules, including 28 negative-rule matches.

## Root Cause

The prompt had become a layered incident log: each production issue added another local prohibition. That preserved behavior, but increased prompt surface area and attention competition between core behavior, style rules, and edge-case patches.

## What Went Well

- Treated positive phrasing as a heuristic, not a dogma.
- Preserved hard grounding, entity, and retrieval-safety boundaries.
- Avoided rewriting few-shot examples in the first pass because they encode answer shape.
- Kept existing strategic-mode anchors required by prompt regression tests.

## What Went Poorly

- The prompt is still long because strategic synthesis and examples remain large.
- Small A/B slices are noisy: case-level regressions can disappear on repeat even when macro direction is stable.

## How It Was Solved

- Consolidated duplicate top-level instructions for grounding, citation, partial retrieval, off-topic chunks, and answer ordering.
- Reframed style and answer-shape prohibitions into direct positive instructions.
- Left a small number of negative/hard-boundary cases where contrast is important, such as alias disambiguation and source-bound factual limits.

## Tradeoffs Or Alternatives Considered

- Full rewrite: rejected for this pass because it would risk losing hard-won domain behavior.
- Delete examples: rejected because examples likely drive tone and answer structure more reliably than abstract rules.
- Split prompt by route: useful future option, but requires broader `prompts.py` changes and eval coverage.

## Tests Added Or Updated

No tests were added. Existing prompt/retrieval tests were run:

- `tests/test_retrieval_planning.py::test_word_prompt_enforces_single_campaign_retrospective_shape`
- `tests/test_retrieval_planning.py::test_word_prompt_guards_campaign_role_overstatement`
- `tests/test_retrieval_planning.py::test_strategic_mode_prompt_triggers_match_retrieval_triggers`
- Full `tests/test_retrieval_planning.py` suite: 31/31 passed.

Focused LLM-as-judge A/B eval was run twice on the same 16 prompt-sensitive cases:

| Variant | Overall | Judge | Grounded |
|---|---:|---:|---:|
| Run 1 baseline `main` | 0.708 | 0.766 | 1.000 |
| Run 1 prompt refactor | 0.729 | 0.797 | 1.000 |
| Run 2 baseline `main` | 0.651 | 0.672 | 1.000 |
| Run 2 prompt refactor | 0.707 | 0.766 | 1.000 |

Run 1 largest improvements: cases 56, 58, 57, 46, 31.
Run 1 largest regressions: cases 12 and 24.

Run 2 again favored the refactor overall (+0.056 overall, +0.094 judge). Case 12's regression did not repeat; the refactor scored 0.877 / judge 1.0 and included the national-finale framing. Case 24 remained close and is not clearly prompt-caused; both variants under-emphasize the gold's "emotional cost / price of the race" framing. Case 58 regressed in run 2 and should be watched in the next broader eval.

Full 64-case Foundry A/B eval was also run:

| Variant | Overall | Judge | Grounded | Errors |
|---|---:|---:|---:|---:|
| Baseline `main` | 0.651 | 0.637 | 1.000 | 0 |
| Prompt refactor | 0.688 | 0.688 | 0.984 | 0 |

Macro result: +0.037 overall, +0.051 judge. The only material per-case regressions were case 36 and case 57. Case 36 appears likely judge variance / partial-finale nuance because the answer did state that some finale rows lacked rating data. Case 57 remains a real gold-alignment gap: both variants miss the sharper "will this relationship survive?" frame.

## Lessons Learned

- Negative instructions are not automatically bad. They are appropriate for safety boundaries and high-cost hallucination failures.
- Positive phrasing is better for style, answer order, tone, and behavioral defaults.
- Prompt length matters less than prompt focus. The biggest risk was duplicated and competing instructions, not raw line count alone.
- For small slices, decide from repeated macro direction plus full-answer inspection, not a single judge reason.

## Follow-Up Actions

- Merge is recommended based on two positive focused A/B runs and a positive full 64-case A/B run.
- Track case 57 in future prompt work.
- Consider a later route-specific prompt split so numeric, quote, strategic, and creative modes receive smaller prompt addenda.
- Revisit few-shot examples only after the first pass is measured.
