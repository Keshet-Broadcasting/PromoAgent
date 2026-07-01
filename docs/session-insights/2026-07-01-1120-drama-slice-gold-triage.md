# Drama Slice Gold Triage (cases 2/3/4)

**Date:** 2026-07-01 11:20 (UTC+3)

## Task / problem summary
The judged drama slice (cases 1–5) left cases 2, 3, and 4 low-scoring. Following the new
`eval-regression-triage-before-code.mdc` rule, we ran source-of-truth checks (promo-team Custom GPT +
Claude over `מסמך דרמות GPT.docx` / `מעקבי פרומו.xlsx`) *before* touching any code, retrieval, or gold.

## Root cause (per case)
- **Case 2** (אור ראשון pre-launch intentions): gold is correct. Custom GPT confirms 67% general,
  "נמוך יחסית", weak among women/young. The low eval score is answer-framing (bot omits the relative
  "lower than other dramas" point), not a gold defect.
- **Case 3** (compare אור ראשון vs other dramas): gold is correct and grounded. Claude found the
  comparator numbers in `מסמך דרמות GPT.docx` at the **promo-screening tier** (הראש 73/78, נוטוק 72,
  גוף שלישי 69/81). The bug is a **retrieval gap** — only the subject's numbers reach the context, so
  the model fabricates "above average". A second, much lower **pre-launch campaign tier (~39–41%)**
  exists in the same doc, so any retrieval fix must avoid mixing the two tiers.
- **Case 4** (intentions vs actual rating): gold was **wrong**. Claude's document check showed (1) the
  הראש launch rating in the gold (14–15%) contradicts the docs (opening 18 / rating 16.2), and (2) the
  gold paired promo-test intentions (67/73/72%) with a "70%+ → 16–17%" multiplier that **does not exist**
  anywhere in the documents. The intentions that actually pair with launch ratings are the pre-launch
  campaign tier (~40% for all three), and the same ~40% produced very different ratings (20 / 18 / 15.7),
  i.e. no fixed conversion ratio.

## What went well
- The triage rule paid off immediately: the case 4 document check caught a factual error and a fabricated
  heuristic in the gold that would otherwise have driven a wrong "prediction calculator" production change.
- Custom GPT + Claude answers were cross-checked against the dataset gold and each other, which exposed the
  two-tier (promo-test vs pre-launch) measurement ambiguity.

## What went poorly
- The original case 4 gold silently mixed two different measurement tiers and invented a multiplier —
  a reminder that "high confidence" gold can still be internally inconsistent.

## How it was solved
- Case 4 gold rewritten on the pre-launch campaign tier (~40% all three) paired with actual ratings,
  stating explicitly there is no fixed conversion multiplier; `confidence` → `medium`,
  `needs_human_review=true`. Verified the JSONL still parses.
- Cases 2 and 3 left unchanged (valid gold); case 3 retrieval fix planned but deliberately not implemented
  yet.

## Tradeoffs / alternatives considered
- Case 4: could have kept the promo-test tier (67/73/72%) and only fixed the rating error, but that tier
  never pairs with launch in the docs. The pre-launch tier is the like-for-like, grounded choice (user
  decision).

## Tests added or updated
- None (dataset-gold correction, not a code change). JSONL parse verified via a one-liner.

## Lessons learned
- When a case involves "כוונות צפייה", first identify **which measurement tier** the number belongs to
  (promo/trailer screening vs pre-launch campaign). Different tiers differ by ~30 points.
- A "prediction multiplier" should never be invented from mixed-tier data — confirm the multiplier exists
  in the source before encoding it in gold or prompts.

## Follow-up actions
- Implement the case 3 retrieval fix (broaden per named show + prompt guard, keep tiers unmixed), with a
  regression test first.
- Optionally enrich case 2 gold with the post-revision 71% figure and confirm the 65% women number in the doc.
- Re-run the 1–5 judged slice after the case 3 fix and after the case 4 gold correction to confirm no regression.
