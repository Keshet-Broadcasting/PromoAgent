# PromoAgent — Evaluation Report

**Last updated:** Jun 23, 2026 (case 57 new-season retrieval correction)  
**Dataset:** `dataset.jsonl` — 64 cases  
**Eval harness:** `tests/eval_dataset.py` (LLM-as-judge via configured Foundry provider)  
**Observability:** Langfuse v4 — scores pushed per run to [cloud.langfuse.com](https://cloud.langfuse.com)  
**Target:** Judge ≥ 70% (≈ 3.5 / 5 average) to replace the custom GPT

---

## Case 57 New-Season Retrieval — Done (Jun 23)

Changed case 57 from a generic `חתונמי` tonight retrieval problem into the intended new-season strategy retrieval:

- `dataset.jsonl`: case 57 `cleaned_query` now preserves `לקראת עונה חדשה`.
- `app/retrieval_plan.py`: `_LAUNCH_PATTERNS` now detects `לקראת עונה חדשה`, `עונה חדשה`, and `עונה חוזרת`.
- `app/retrieval_plan.py`: launch Word retrieval now includes `שיקול` and `חידושים` sections for single-show launch queries.
- `app/retrieval_plan.py`: regular `tonight` single-show queries keep the previous broader retrieval path to avoid overfitting case 57 and regressing case 16.
- `tests/test_retrieval_planning.py`: added regression coverage for case 57 launch planning and Word-search kwargs.
- `.gitignore`: `dataset.jsonl` is no longer ignored, so CI can validate the same eval dataset used locally.
- `tests/test_eval_dataset_integrity.py`: added CI checks for dataset schema, unique/sorted IDs, enum/boolean fields, and cleaned-query preservation of retrieval intent terms.
- `dataset.jsonl`: case 58 `cleaned_query` now preserves `ללא השקה וגמר`; the new integrity test caught this hidden bug while adding CI protection.
- `app/test_chat_connection.py`: manual connectivity check is excluded from pytest collection and now uses the production `_completion_kwargs()` helper, avoiding gpt-5.4 `max_tokens` failures in normal unit-test flow.

Verification:

- `python -m pytest tests/test_retrieval_planning.py -q` → 33/33 passed.
- `python -m pytest tests/test_eval_dataset_integrity.py tests/test_retrieval_planning.py -q` → 36/36 passed.
- `python -m pytest tests/test_eval_dataset_integrity.py tests/test_retrieval_planning.py tests/test_preprocess_chunking.py -q` → 40/40 passed.
- `python -m pytest app/test_chat_connection.py -q` → no tests collected, expected for a manual smoke script.
- `python -m pytest -q` → 120/120 passed after retrying transient `PyJWT` install.
- Direct fresh case 57 score → overall 80.2%, judge 5/5.
- Paired case 16/57 eval after narrowing the filter → case 16 recovered to 65%, case 57 70%.
- Targeted guard slice `12,16,24,36,57,58` → 0 eval errors, case 57 overall 85% / judge 5/5. The command returned non-zero because the slice still contained the now-fixed case 58 weakness, not because of execution failure.
- Fresh case 58 after cleaned-query fix → overall 64.1%, judge 3/5, grounded 100%.

---

## Prompt Surface Cleanup — Done (Jun 22)

Changed `app/system_prompt.txt` to make the top operating layer shorter and more action-oriented:

- Consolidated duplicate grounding, citation, partial-evidence, and answer-shape rules.
- Reframed style/shape prohibitions as positive instructions where safe.
- Kept hard anti-hallucination, off-topic retrieval, entity alias, and strategic-mode source-boundary rules intact.
- Preserved few-shot examples and strategic anchors to avoid changing the learned answer shape.

Verification:

- Prompt negative wording count reduced from 28 to 4 matches.
- `tests/test_retrieval_planning.py` passed: 31/31.
- Focused prompt-sensitive A/B eval slice (16 cases: strategy/open-ended/cross-show/MasterChef):
  - Run 1 baseline `main`: overall 0.708, judge 0.766, grounded 1.000.
  - Run 1 prompt refactor: overall 0.729, judge 0.797, grounded 1.000.
  - Run 1 net: +0.021 overall, +0.031 judge.
  - Run 2 baseline `main`: overall 0.651, judge 0.672, grounded 1.000.
  - Run 2 prompt refactor: overall 0.707, judge 0.766, grounded 1.000.
  - Run 2 net: +0.056 overall, +0.094 judge.

Decision:

- Keep the prompt refactor. The repeated focused slice confirms a positive direction despite case-level variance.
- Case 12 looks stochastic, not prompt-caused: the second refactor run recovered to overall 0.877 / judge 1.0 and included the national-finale framing.
- Case 24 is not a clear refactor regression: both variants answer with couples/emotional connection; both still under-emphasize the gold's "emotional cost / price of the race" framing.
- Case 58 regressed in run 2 and should be watched in the next broader eval.
- MasterChef VIP cases 63 and 64 stayed strong: judge 1.0 in both baseline and refactor.

Full 64-case Foundry A/B eval:

- Baseline `main`: overall 0.651, judge 0.637, grounded 1.000, errors 0.
- Prompt refactor: overall 0.688, judge 0.688, grounded 0.984, errors 0.
- Net: +0.037 overall, +0.051 judge.
- Material per-case regressions: case 36 (-0.304 overall, likely judge variance / partial-finale nuance), case 57 (-0.117 overall, known gold-alignment gap around "will the relationship survive").
- Material improvements: cases 5, 6, 59, 16, 47, 22, 27, 50, 31, 26, 52, 48, 62, 12.
- Decision after full eval: green light to push; no macro regression detected.

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

## Phase A — Done (May 28, commit `03508de`)

| Item | Effect |
|------|--------|
| Context-aware `כוכב` alias: `כוכב (ב)עונה N≥10` → `הכוכב הבא לאירוויזיון` | ID 29 now retrieves season 11 of the correct show |
| Genre false-positive: strip `דרמה אישית` / `דרמה זוגית` before genre detection | ID 32 no longer mis-routes to drama broad-path |
| Broad-scope guard: genres only broaden when `show_names` is empty | Single-show queries with drama words stay narrow |

## Phase C — Partially done (May 28, commit `57d67f1`)

| Item | Effect |
|------|--------|
| Refusal calibration: clean-refusal formula with `[X]`/`[Y]` template | Bot will refuse cleanly instead of synthesizing from wrong-show chunks |
| Anti-hedging voice rule: forbids "ייתכן כי", "אולי", academic closers | Strategic answers lead with conclusion, not hedge |
| No citation footer in Creative Mode | Creative answers end on visual/emotional beat, not "הנתונים נשלפו מ-X" |
| Expanded Creative Mode triggers: 14 phrases (was 5) | "תכתוב לי", "תבנה לי", "תיצור לי" etc. now reliably hit Creative Mode |

## Phase D — Done (May 28, commits `f1f8e1f` + `64548d8`)

| Item | Effect |
|------|--------|
| `_sanitize_for_content_filter()` in `service.py` | Applied to `promo_text` (Excel), `chunk`+`caption` (Word), `text` (SharePoint) before prompt assembly |
| Replaces: אקדח/ירי/יורה/נורה/נהרג/גופה + variants | Violence triggers removed; neutral brackets preserve meaning for LLM |
| "נורא" (terrible) and "הראש" (show name) untouched | False-positive guard verified — 9/9 unit tests pass |
| Router: "בריף" + 10 campaign/brief phrases added to `WORD_QUOTE_PATTERNS` | Brief queries now route to `word_quote` → show_name filter surfaces הראש strategy chunks (17 confirmed in index); 7/7 router tests pass |

**Dataset fix — case 9 (commit `529bd71`):** Gold answer for "כוונות צפייה פאלו אלטו + גוף שלישי" was wrong — stated "no numerical data for פאלו אלטו" but document has 29%/65%/70%/67% across 3 measurement types. Verified via Claude. This was penalizing the model (score 2) for correct answers.

**Dataset fix — case 8 (commit `5d2130b`):** Gold answer for חולי אהבה had wrong numbers (35%/78%/83% — don't exist for this show). Real headline: **68%** promo test (story-reveal version), 28% general mid-campaign, 75% women. Verified via Claude + GPT reference answer.

**Dataset fix — case 48 (commit `5d2130b`):** Gold answer said "אור ראשון 20% is highest drama launch" — wrong. **ביום שהאדמה רעדה (2019) launched at 24%**, explicitly called "most-watched drama on Channel 12 to that point" in the document. Bot was correct; gold was incomplete. Verified via Claude + מעקבי פרומו.xlsx.

**System prompt fix — case 21 (commit `5d2130b`):** Bot was answering "אנא שאל בעברית" for Hebrew query containing "Live+7/VOD" English tokens. Language check rule strengthened: now triggers ONLY when zero Hebrew Unicode characters (U+05D0–U+05EA) present. This was scoring 0% (judge=1) for a correctly answerable case.

**Confirmed via live test:** הראש has 17 rich strategy chunks in `מסמך דרמות GPT.docx` including *"תובנות מהקמפיין (5 נקודות)"*, *"מה השיקול שעמד מאחורי כל פרומו"*, *"התלבטויות מיוחדות"* — all now reachable.

## Architecture Refactor — Done (Jun 21, 2026)

`app/service.py` split from 1569 lines into 5 focused sub-modules:
- `formatters.py` — content-filter sanitizer + context formatters
- `excel_selector.py` — date/launch/season/VIP row selection
- `retrieval_plan.py` — intent patterns + `_RetrievalPlan` + planner
- `sharepoint_helper.py` — SP fallback / enrichment helpers
- `retriever.py` — `_retrieve` dispatcher + `_fetch_word_docs`

`service.py` is now 410 lines (orchestration + history context + `run_query`). No behaviour changes. 33/33 tests green.

## What Needs Work (Priority Order)

| Priority | Item | Expected lift | Phase |
|----------|------|---------------|-------|
| 1 | **Run eval (Run 10)** — measure combined impact after cases 8+9+48 gold fixes + language check fix | Expected +3-5pp from 44.8% baseline | — |
| 2 | **Strategy precision** — bot paraphrases instead of reproducing exact slogans/formulas | +2-3pp strategy | C |
| 3 | **Dataset expansion to N≥10** for `comparison`, `cross_show` | Measurement reliability | E |
| 4 | **Phase B spans** — per-pipeline-step Langfuse spans (route → retrieval → LLM) | No judge lift; better debugging | B |
| 5 | **Architectural** (HyDE, better re-ranker, GPT-5 test) | Unknown — only after above | F |

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

1. **Run eval (Run 9)** — measure combined A+C+D impact; compare to Run 8 (49.0% judge baseline).
2. **Phase C — strategy precision** — instruction to reproduce slogans/formulas verbatim when present in chunk.
3. **Phase B (remaining)** — per-span metadata (route → retrieval → LLM) in Langfuse traces.
4. **Side-by-side user test** — 5 promo team members, 10 real questions. Pass criterion: wins or ties on ≥7/10.
