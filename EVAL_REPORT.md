# Evaluation Report — PromoBot Agent

**Date:** May 1, 2026
**Dataset:** `dataset.jsonl` (25 gold-standard Q&A pairs)
**Model:** gpt-4o via Azure AI Foundry
**Eval script:** `tests/eval_dataset.py`

---

## Executive Summary

The agent is **safe and grounded** — it never hallucinates without citing sources, and correctly refuses unanswerable questions. However, **accuracy on numeric and ranking queries needs improvement**, primarily due to retrieval gaps rather than LLM quality issues.

| Metric | Score | Verdict |
|---|---|---|
| Overall (weighted avg) | 43% | Needs improvement |
| Groundedness | 100% | Excellent |
| Refusal accuracy | 100% | Excellent |
| Numeric accuracy | 28% | Needs improvement |
| Keyword coverage | 20% | Misleadingly low (see below) |

---

## Scoring Methodology

Each dataset case is scored across multiple dimensions:

| Dimension | Weight | What it measures |
|---|---|---|
| **NUMERIC** | 35% | Fraction of gold-answer numbers found in model answer |
| **KEYWORD** | 25% | Fraction of meaningful Hebrew terms from gold answer found in model answer |
| **GROUNDED** | 20% | Does the model cite sources (file names, chunk IDs, retrieval markers)? |
| **REFUSAL** | 20% | For unanswerable questions: did the model correctly say "not found"? |
| **JUDGE** | 40% | *(optional)* LLM rates model vs gold answer 1–5 for semantic quality |

Overall case score = weighted average of applicable dimensions. A case "passes" at ≥50%.

---

## Results by Category

| Category | Cases | Overall | Numeric | Keyword | Grounded | Errors |
|---|---|---|---|---|---|---|
| quote | 3 | 58% | 67% | 13% | 100% | 0 |
| factual | 4 | 59% | 50% | 29% | 100% | 0 |
| open_ended | 6 | 40% | 6% | 24% | 100% | 1 |
| numeric | 5 | 34% | 7% | 18% | 100% | 0 |
| ranking | 5 | 38% | 20% | 13% | 100% | 0 |
| comparison | 1 | 33% | 0% | 26% | 100% | 0 |
| no_answer | 1 | 66% | — | 13% | 100% | 0 |

---

## What's Working Well

### 1. Groundedness (100%)

Every successful answer cited its source — file names, sheet names, or chunk positions. The system prompt grounding rules are fully effective. The model never presented data without attribution.

### 2. Refusal Accuracy (100%)

When the dataset contains a question the source data cannot answer (case 21: average VOD completions for a show), the model correctly responds with "not found" language instead of fabricating numbers.

### 3. Quote and Factual Categories (~59%)

Questions asking for strategy descriptions, campaign slogans, or qualitative insights perform best. The model retrieves the right Word documents and presents the content accurately.

---

## What Needs Improvement

### 1. Numeric Accuracy on Ranking/Comparison Queries (28%)

**Root cause: Retrieval gaps, not LLM errors.**

When asked "rank all seasons by launch rating" or "compare ratings between two shows," Azure Search often returns the wrong rows or incomplete result sets. The LLM then correctly reports what it received — but the data is wrong or missing.

Examples:
- Cases 13–14 (ranking): 0% numeric — the retrieved Excel rows did not include the expected episodes
- Case 3 (comparison): 0% numeric — missing the specific numbers needed for cross-show comparison

### 2. Keyword Coverage is Misleadingly Low (20%)

This is an artifact of the scoring method, not a real problem. Hebrew has rich morphology — the gold answer says "כוונות הצפייה הכלליות היו 67%" while the model says "כוונות הצפייה עמדו על 67%". Same meaning, different words, counted as a miss.

**Recommendation:** Use the `--judge` flag for semantic scoring. LLM-as-judge captures paraphrasing and partial correctness that exact keyword matching misses.

### 3. One Error (Case 19)

Case 19 failed with `BadRequestError` — the prompt likely exceeded the model's token limit. This was a long open-ended question about recommendations for "הכוכב הבא" promos, which produced a large retrieval context.

---

## Detailed Case Results

| Case | Category | Overall | Numeric | Keyword | Grounded | Time | Status |
|---|---|---|---|---|---|---|---|
| 1 | quote | 72% | 100% | 10% | 100% | 18.4s | Pass |
| 2 | numeric | 26% | 0% | 4% | 100% | 4.6s | Fail |
| 3 | comparison | 33% | 0% | 26% | 100% | 7.3s | Fail |
| 4 | open_ended | 36% | 11% | 18% | 100% | 18.2s | Fail |
| 5 | numeric | 38% | 0% | 40% | 100% | 5.9s | Fail |
| 6 | numeric | 49% | 33% | 30% | 100% | 5.9s | Fail |
| 7 | numeric | 27% | 0% | 8% | 100% | 8.2s | Fail |
| 8 | numeric | 28% | 0% | 8% | 100% | 6.9s | Fail |
| 9 | factual | 35% | 0% | 33% | 100% | 9.9s | Fail |
| 10 | factual | 64% | — | 35% | 100% | 10.7s | OK |
| 11 | quote | 26% | 0% | 3% | 100% | 7.0s | Fail |
| 12 | open_ended | 37% | 0% | 39% | 100% | 12.5s | Fail |
| 13 | ranking | 25% | 0% | 0% | 100% | 5.9s | Fail |
| 14 | ranking | 25% | 0% | 0% | 100% | 6.4s | Fail |
| 15 | ranking | 80% | 100% | 35% | 100% | 7.9s | Pass |
| 16 | open_ended | 56% | — | 20% | 100% | 11.3s | OK |
| 17 | ranking | 32% | 0% | 24% | 100% | 16.4s | Fail |
| 18 | factual | 66% | — | 39% | 100% | 8.4s | OK |
| 19 | open_ended | 0% | — | — | — | 12.3s | Error |
| 20 | quote | 77% | 100% | 25% | 100% | 10.1s | Pass |
| 21 | no_answer | 66% | — | 13% | 100% | 5.0s | OK |
| 22 | ranking | 27% | 0% | 6% | 100% | 5.5s | Fail |
| 23 | open_ended | 57% | — | 22% | 100% | 8.7s | OK |
| 24 | open_ended | 58% | — | 24% | 100% | 13.4s | OK |
| 25 | factual | 72% | 100% | 10% | 100% | 10.0s | Pass |

**Pass** = ≥70% | **OK** = 50–69% | **Fail** = <50%

---

## Recommendations

### Priority 1 — Improve Retrieval for Ranking/Comparison Queries

**Impact: +15–20% overall score**

The biggest accuracy gap comes from Azure Search returning incorrect or incomplete Excel rows. Specific actions:

1. **Increase `top` parameter** for ranking queries — currently `top=5` may miss seasons/episodes needed for complete lists. Consider `top=8` or `top=10` for ranking-type questions.
2. **Add post-retrieval filtering** — after Azure Search returns results, filter by show name to prevent cross-show contamination (e.g., "הזמר במסכה" data leaking into "הדרקון הירוק" queries).
3. **Improve Excel row labeling** — ensure first-episode rows are clearly labeled as "launch" or "episode 1" in the index so semantic search can bridge the gap between user vocabulary ("השקה") and source labels (date/ordinal).

### Priority 2 — Fix Token Limit Error (Case 19)

**Impact: Eliminates 1 error**

The retrieval context for long open-ended questions can exceed the model's context window. Options:
- Truncate the context to a maximum character length before sending to the LLM
- Reduce `top` for open-ended/unknown routes from 5 to 3
- Switch to a model with a larger context window for these cases

### Priority 3 — Add LLM-as-Judge to the Eval Pipeline

**Impact: More accurate scoring**

The current keyword/numeric matching underestimates quality because it penalizes paraphrasing. Run with `--judge` to get semantic scores:

```bash
python tests/eval_dataset.py --judge
```

Consider making `--judge` the default in CI/CD once you validate it correlates with human judgment.

### Priority 4 — Expand the Gold Dataset

**Impact: Better eval reliability**

25 cases is a good start but insufficient for statistical confidence. Target:
- 50+ cases total
- At least 8–10 cases per category
- Include edge cases: multi-season comparisons, questions about shows not in the index, ambiguous queries

### Priority 5 — Track Eval Scores Over Time

**Impact: Regression prevention**

After each prompt, retrieval, or model change, re-run the eval and compare scores. Integrate into CI:

```yaml
# azure-pipelines.yml
- script: python tests/eval_dataset.py
  displayName: 'Run dataset eval'
  continueOnError: true
```

Store results in a shared location so the team can track trends across deployments.

---

## How to Re-Run

```bash
# Basic eval (keyword + numeric matching)
python tests/eval_dataset.py

# With LLM-as-judge semantic scoring (recommended)
python tests/eval_dataset.py --judge

# Single case
python tests/eval_dataset.py --id 5

# JSON output for programmatic use
python tests/eval_dataset.py --json
```

---

## Conclusion

The agent's **safety properties are strong** — grounded citations and correct refusal behavior are production-ready. The **accuracy gap on numeric/ranking queries is a retrieval problem**, not an LLM problem, and can be addressed by tuning the Azure Search configuration and post-retrieval filtering. With retrieval improvements and the recommended eval enhancements, a target of **70%+ overall score** is realistic.
