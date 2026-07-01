# Eval Triage Before Fixes

## Task / Problem Summary

After investigating case 60 (`מחשבון חיזוי`) we found that the promo team's Custom GPT produced a calculator answer that differed from the current dataset gold. The user asked to add a rule requiring source-of-truth checks before changing prompts, retrieval, code, or gold answers.

## Root Cause

Some eval failures are not directly production bugs. They can be caused by stale/ambiguous gold answers, product expectation drift, source-document ambiguity, retrieval gaps, or model summarization. Jumping straight to prompt/retrieval changes risks overfitting the eval.

## What Went Well

- Custom GPT comparison exposed that case 60 may be a gold/product-alignment issue.
- The new Cursor rule makes the triage workflow persistent.
- A small drama slice (`1-5`) was run before broader changes, limiting cost and blast radius.

## What Went Poorly

- Partial case-60 code/prompt edits were made before the Custom GPT/source-doc checkpoint.
- The drama slice was not a clean pass: cases 2 and 3 stayed low, case 4 was middling.

## How It Was Solved

Created `.cursor/rules/eval-regression-triage-before-code.mdc`, requiring:

- Exact copy-paste question(s) for the Custom GPT baseline.
- Exact copy-paste question(s) for the Claude/source-document check.
- Langfuse trace comparison.
- Explicit root-cause decision before edits.

## Tradeoffs Or Alternatives Considered

- Continue fixing case 60 immediately: rejected because Custom GPT contradicted the existing gold.
- Revert all partial case-60 edits immediately: deferred; the safer next step is source/gold validation, then decide whether to keep or revert.
- Run full eval: rejected for now; targeted slice gave enough signal with lower token cost.

## Tests Added Or Updated

- No code tests were added for the rule itself.
- Ran `tests/eval_dataset.py --only 1,2,3,4,5 --judge`.
- Result: 0 errors, overall 58.9%, judge 60.0%; per-case judge 5/2/2/3/5.

## Lessons Learned

Before changing RAG behavior for a low score, establish whether the eval answer should match the promo team's actual Custom GPT and whether the source documents contain the needed evidence. This avoids optimizing for bad or ambiguous gold.

## Follow-Up Actions

- For cases 2, 3, and 4, ask the Custom GPT the same questions and ask Claude document-focused evidence questions before making fixes.
- For case 60, validate the 5 source series and calculator formula against the documents before deciding whether to update gold or keep/revert the partial prompt/context edits.
