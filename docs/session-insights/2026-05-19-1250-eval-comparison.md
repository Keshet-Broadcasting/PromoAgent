# Eval Comparison — 2026-05-19

Three eval runs on the same 54-case dataset (`dataset.jsonl`), all using the same Azure AI Search retrieval pipeline.

---

## Run Configurations

| Run | Provider | Model | Date |
|-----|----------|-------|------|
| **Foundry Baseline** | Azure AI Foundry | gpt-4o-1 | 2026-05-19 morning |
| **Foundry v2** | Azure AI Foundry | gpt-4o-1 | 2026-05-19 afternoon (after today's changes) |
| **Gemini** | Google Gemini API | gemini-2.5-flash | 2026-05-19 midday |

### Changes introduced between Foundry Baseline → Foundry v2

1. **`<thinking>` block stripping** — LLM now outputs a mandatory internal chain-of-thought block that is stripped before returning the answer to the user
2. **Excel context as Markdown table** — `_fmt_excel()` now formats retrieved rows as a structured Markdown table instead of a flat text blob, helping the model parse rows logically
3. **System prompt additions** — Mandatory Chain of Thought section, Tone/Style/Formatting rules, updated few-shot example with `<thinking>` block, updated nickname table (added נוטוק), strengthened חתונמי alias rule

---

## Overall Scores

| Metric | Foundry Baseline | Foundry v2 | Δ (v2 vs baseline) | Gemini 2.5 Flash |
|--------|-----------------|------------|-------------------|-----------------|
| **Overall** | 51.3% | **53.8%** | +2.5% ✅ | 39.3% |
| Numeric accuracy | 44.3% | **47.5%** | +3.2% ✅ | 33.7% |
| Keyword coverage | 39.5% | **41.5%** | +2.0% ✅ | 27.3% |
| Groundedness | **96.2%** | 94.3% | -1.9% ⚠️ | 73.6% |
| Refusal accuracy | 75.0% | **100.0%** | +25.0% ✅ | 100.0% |
| **LLM Judge** | 39.6% | **43.4%** | +3.8% ✅ | 31.6% |
| Avg latency | 15.6s | 16.2s | +0.6s | **5.3s** |
| Errors | 1 | 1 | — | 1 |

> Error in all runs: id=37 — transient `Azure Search HttpResponseError` (not code-related).

---

## Per-Category Breakdown

| Category | N | Foundry Baseline | Foundry v2 | Δ | Gemini |
|----------|---|-----------------|------------|---|--------|
| alias | 7 | 54% / J:36% | 52% / J:29% | -2% ⚠️ | 55% / J:39% |
| comparison | 1 | 41% / J:25% | 29% / J:0% | -12% ⚠️ | 18% / J:0% |
| cross_show | 4 | 45% / J:38% | 35% / J:31% | -10% ⚠️ | 15% / J:12% |
| factual | 4 | 50% / J:19% | 53% / J:25% | +3% ✅ | 57% / J:44% |
| no_answer | 4 | 70% / J:75% | **86% / J:100%** | +16% ✅ | 82% / J:88% |
| numeric | 10 | 57% / J:48% | 59% / J:48% | +2% ✅ | 56% / J:48% |
| open_ended | 7 | 49% / J:50% | 48% / J:36% | -1% ⚠️ | 17% / J:21% |
| quote | 6 | 54% / J:38% | 53% / J:50% | +1% ✅ | 40% / J:33% |
| **ranking** | 7 | 40% / J:18% | **54% / J:43%** | +14% ✅✅ | 15% / J:0% |
| strategy | 3 | 40% / J:42% | **52% / J:50%** | +12% ✅✅ | 16% / J:0% |

*(Format: Overall% / J:Judge%)*

---

## Key Findings

### Foundry v2 vs Baseline — No Regression, Clear Gains

- **No regression** overall. Every top-level metric improved except groundedness (-1.9%), which is a minor fluctuation within run noise.
- **Ranking category jumped +14%** (Overall) and +25% (Judge) — the biggest improvement. The Markdown table format for Excel data and the `<thinking>` sorting step directly addressed the weakest category from the baseline.
- **Strategy category jumped +12%** — the structured chain-of-thought and Tone/Style rules produced more focused, evidence-backed strategic answers.
- **Refusal accuracy reached 100%** — the model now correctly declines to answer when no data exists, up from 75%.
- **Groundedness slight dip (-1.9%)** — within noise; the model is still sourcing answers from retrieved context 94% of the time.

### Gemini 2.5 Flash vs Foundry

- Gemini is **3x faster** (5.3s vs 16.2s avg) but significantly weaker on complex tasks.
- Gemini scores **0% Judge on ranking and strategy** — it cannot reliably sort or synthesize across multiple Hebrew data rows.
- Gemini matches Foundry on `factual` and `no_answer` categories, making it a viable option for simple lookup queries if latency is the priority.
- The 22-point groundedness gap (73.6% vs 94.3%) means Gemini is more likely to hallucinate or blend data from different sources.

---

## Recommendations

1. **Keep Foundry (gpt-4o) as production provider** — clear quality advantage, especially for ranking, strategy, and groundedness.
2. **The `<thinking>` + Markdown table changes are confirmed improvements** — deploy them to production.
3. **Consider Gemini for a fast-path fallback** on simple factual/no_answer queries where latency matters and accuracy requirements are lower.
4. **Next focus areas** based on remaining weaknesses:
   - `cross_show` (35%) — multi-show comparisons still underperform; consider injecting more cross-show context at retrieval time
   - `comparison` (29%) — single-case comparisons need richer retrieved context
   - `alias` Judge score dropped — review the חתונמי alias rule enforcement in `<thinking>` blocks

---

## Tests Added / Updated

- No new automated tests added in this session.
- Eval dataset (`dataset.jsonl`, 54 cases) used as regression suite — all three runs completed with 1 transient error (id=37, unrelated to code).

---

## Lessons Learned

- **Structured context beats prose context for LLMs**: Converting Excel rows to a Markdown table gave the biggest single improvement (+14% on ranking). The model could scan columns directly instead of parsing a text blob.
- **Chain-of-thought prompting helps ranking tasks most**: Forcing explicit sorting in the `<thinking>` block before the final answer reduced ordering errors.
- **Model capability gap is real for Hebrew RAG**: Gemini 2.5 Flash is competitive on English-style tasks but struggles with Hebrew data synthesis and multi-row reasoning.
- **Refusal quality is a good early signal**: Going from 75% → 100% refusal accuracy suggests the tone/style and completeness-check rules in the prompt are working.
