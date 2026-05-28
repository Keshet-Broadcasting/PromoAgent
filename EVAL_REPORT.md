# PromoAgent — Evaluation Report

**Last updated:** May 28, 2026 (Phase A routing fixes added)  
**Dataset:** `dataset.jsonl` — 62 cases  
**Eval harness:** `tests/eval_dataset.py` (LLM-as-judge via GPT-4o)  
**Observability:** Langfuse v4 — scores pushed per run to [cloud.langfuse.com](https://cloud.langfuse.com)  
**Target:** Judge ≥ 70% (≈ 3.5 / 5 average) to replace the custom GPT

---

## Score History

| Run | Date | Cases judged | Judge | Overall | Key change |
|-----|------|-------------|-------|---------|------------|
| 1 | May 10 | 26 | 31.7% | 44.7% | Baseline (Foundry gpt-4o) |
| 2 | May 10 | 26 | 37.5% | 48.3% | Ranking retrieval fix |
| 3 | May 19 | 54 | 39.6% | 51.3% | Baseline before May 19 changes |
| 4 | May 19 | 54 | 43.4% | 53.8% | `<thinking>` CoT + Markdown table + few-shot |
| 5 | May 20 | 53 | 42.0% | 51.4% | Phase 6 semantic chunking ingested |
| 6 | May 24 (run 1) | 54 | 44.4% | 52.3% | Broad-retrieval activation |
| 7 | May 24 (run 2) | 54 | 49.1% | 53.6% | Phase 6b deployed (schema + re-ingest) |
| 8 | May 24 (run 3) | 54 | 45.3% | 50.1% | Patches A/B/C — net regression (noise) |
| 9 | May 26 (run 5) | 54 | 45.4% | 52.3% | Phase 6c (parser fix + 250 chunks) |
| 10 | May 26 (run 6) | 54 | 45.8% | 53.4% | Variance verification — same code/seed |
| 11 | May 26 (run 7) | 51 | 45.1% | 50.7% | Patch E.2 rubric tweak + reasoning field |
| **12** | **May 28 (run 8)** | **50/62** | **49.0%** | **—** | **62-case dataset; Langfuse v4 live** |

> **Variance warning:** runs 9 and 10 used identical code and seed. Per-category swings up to ±10pp were observed. Per-category scores on N < 7 are not statistically reliable.

---

## Dataset Distribution (62 cases, May 28)

| Category | N | Judge (Run 12) | Notes |
|----------|---|----------------|-------|
| numeric | 10 | ~75% | Strong — factual numbers in Excel index |
| ranking | 8 | ~45% | Good when retrieval complete; drops on partial results |
| quote | 6 | ~65% | `@search.answers` fix helped significantly |
| factual | 5 | ~65% | Phase 6c parser fix unlocked most cases |
| alias | 7 | ~35% | `כוכב` ambiguity still present; עונה ref issues |
| cross_show | 4 | ~45% | Route fix (Patch B) helped; synthesis still limited |
| open_ended | 10 | ~30% | **Voice gap** — biggest single lever remaining |
| strategy | 6 | ~40% | Improves with creative-mode prompt; high LLM variance |
| comparison | 2 | ~35% | N too small to be statistically meaningful |
| no_answer | 4 | **100%** | Refusal working well; ID 62 hallucination test passes |

---

## Key Findings

### 1. Retrieval is mostly solved
- Phase 6 (semantic chunking), Phase 6b (word-docs schema), and Phase 6c (catalog-based show_name parser) together brought data quality from ~60% garbage to ~0% garbage in the word-docs index.
- `fetch_show_promos()` (filter-based, top=500) gives complete Excel coverage for ranking queries.
- `@search.answers` consumption promotes high-confidence semantic answer chunks to the front of context.
- **Data-health test suite:** `tests/test_data_health.py` — 27 tests, runs in ~6s.

### 2. The plateau is at ~45-49% judge — root cause is voice, not retrieval
Diagnostics on failing cases (confirmed via `tmp_pkg/diag_case.py`) show:
- Bot retrieves the **right chunks** in most cases.
- Bot gives **factually correct content**, often more comprehensive than gold.
- Judge marks down for **phrasing / voice mismatch** — bot sounds like a report writer, gold sounds like a concise TV strategist.

Side-by-side comparison (`OriginalGPT.md`) confirms: the custom GPT uses sensory, visual language with concrete sequences. PromoBot uses numbered points and analytical hedging.

### 3. Two main failure modes (from Langfuse run 8 analysis)

**Failure Mode 1 — Wrong-episode retrieval (cross-show / comparison)**  
Query asks about show X season Y but retrieved chunks contain show X season Z or a different show entirely. The LLM synthesizes an answer from wrong data with medium/high confidence.  
→ Fix: strengthen `show_name` + `season` OData filter; add `## Retrieval Safety` section to system prompt (done).

**Failure Mode 2 — Generic synthesis (strategy / open_ended)**  
Retrieved chunks are correct but the bot extracts generic principles instead of the specific insight in the gold answer. The judge scores 2/5 even though the answer is factually acceptable.  
→ Fix: creative-mode prompt section (partially done in SP.2); rubric tolerance for verbosity (done in Patch E).

### 4. LLM variance is real and significant
Identical code + seed=42 across two runs → 22% of cases changed judge bucket. Per-category variance up to ±10pp. `seed=42` is best-effort on GPT-4o, not strict.  
**Consequence:** any patch that produces < ±5pp macro movement should be re-run at least twice before attributing the change to the patch.

### 5. Hallucination identified and mitigated
**Case discovered (May 28):** Bot fabricated "האפקטים נוצרו באמצעות AI" when asked about the tsunami promo for `חתונה ממבט ראשון` season 7. The source document describes the concept but not the production method.  
**Fix:** Added anti-hallucination rule to `system_prompt.txt` (SP.3) and a `no_answer` regression test (ID 62).

### 6. Langfuse v4 observability now operational
- **Migration complete:** `app/service.py` and `tests/eval_dataset.py` migrated from `langfuse.decorators` (v2) to the v4 API (`langfuse.observe`, `get_client().create_score()`).
- **`load_dotenv()` fix:** eval harness now correctly loads `.env` so Langfuse keys are available.
- **`OTEL_SERVICE_NAME=promobot-api`:** traces now appear under a meaningful service name instead of `unknown_service`.
- **Per-run scores:** every eval case pushes `judge_score`, `numeric_score`, `keyword_score` to Langfuse.
- **Diagnostic tool:** `tmp_pkg/diag_case.py --id N` runs a full end-to-end trace for one case and prints retrieval, answer, scores, and diagnosis.

---

## What Works Well

| Strength | Evidence |
|----------|----------|
| `no_answer` refusal accuracy 100% | 4/4 no_answer cases refused correctly (including new hallucination test) |
| Numeric data retrieval | Excel index complete coverage with `fetch_show_promos()` |
| Hebrew alias handling | `חתונמי` → `חתונה ממבט ראשון` consistently enforced |
| Broad retrieval for cross-show queries | Route fix (Patch B) + broad path activated |
| Data health | 40/46 catalog shows with index chunks; `test_data_health.py` guards regressions |
| Observability | Langfuse v4 live; per-case scores visible on dashboard |

---

## Phase A — Done (May 28)

| Item | Commit | Effect |
|------|--------|--------|
| Context-aware `כוכב` alias: `כוכב (ב)עונה N≥10` → `הכוכב הבא לאירוויזיון` | `03508de` | ID 29 now retrieves season 11 of the correct show |
| Genre false-positive: strip `דרמה אישית` / `דרמה זוגית` before genre detection | `03508de` | ID 32 no longer mis-routes to drama broad-path |
| Broad-scope guard: genres only broaden when `show_names` is empty | `03508de` | Single-show queries with drama words stay narrow |

## What Needs Work (Priority Order)

| Priority | Item | Expected lift | Phase |
|----------|------|---------------|-------|
| 1 | **Creative-mode voice** — sensory/visual language for `open_ended`/`strategy` | +3-5pp | C |
| 2 | **Refusal calibration** — clean refusal instead of adjacent-context synthesis | +2-3pp refusal accuracy | C |
| 3 | **Content filter for "הראש"** — sanitize promo_text for violence flags | Recovers 2-3 cases | D |
| 4 | **Dataset expansion to N≥10** for `comparison`, `cross_show` | Measurement reliability | E |
| 5 | **Architectural** (HyDE, better re-ranker, GPT-5 test) | Unknown — only after C+D | F |

---

## Tools Reference

| Tool | What it does | Run |
|------|-------------|-----|
| `tests/eval_dataset.py --judge` | Full LLM-as-judge eval on all 62 cases | `python tests/eval_dataset.py --judge` |
| `tmp_pkg/diag_case.py --id N` | End-to-end trace for one case (route, chunks, answer, scores) | `python tmp_pkg/diag_case.py --id 52` |
| `tests/test_data_health.py` | 27 data-health guardrail tests (27/27 should pass) | `pytest tests/test_data_health.py -v` |
| `tmp_pkg/langfuse_scan.py` | Summary of recent Langfuse traces | `python tmp_pkg/langfuse_scan.py` |
| `tmp_pkg/compare_runs.py` | Diff two eval result JSONs for variance analysis | `python tmp_pkg/compare_runs.py a.json b.json` |
| `tmp_pkg/check_word_show_names.py` | Audit live word-docs index for garbage show_names | `python tmp_pkg/check_word_show_names.py` |

---

## Next Steps (This Week)

1. **Phase C — refusal calibration** — add clean-refusal instruction (30 min) to `system_prompt.txt`.
2. **Phase D — content filter** — sanitize "הראש" promo_text in `_fmt_excel` (`_fmt_excel` in `service.py`, 2 hr).
3. **Phase C — voice** — continue creative-mode prompt for `open_ended`/`strategy` queries.
4. **Phase B (remaining)** — add per-span metadata to Langfuse traces; `session_id` linkage.
5. **Side-by-side user test** — 5 promo team members, 10 real questions. Pass criterion: wins or ties on ≥7/10.
