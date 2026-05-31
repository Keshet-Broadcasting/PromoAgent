# Session Findings & Action Items — 2026-05-31

**Author:** Claude (pairing session with Amit)
**Scope:** Honest re-baseline of the judge eval, root-cause diagnosis of the 70% plateau,
a token-efficient eval workflow, and a newly-found production bug.

---

## 0. TL;DR (read this first)

- **True current judge score: ~48%** on the 62-case dataset (the "46.8/49%" you had was
  **stale** — measured before the May-28 fixes). This is reproducible within ±1pp noise.
- **70% is not reachable on this dataset/model by tuning retrieval or prompts.** Proven this
  session: even with complete, correct data *in context* and explicit instructions, GPT-4o
  won't reliably pick the launch/finale row or lead with the one number the short gold wants.
  The ceiling is **synthesis + gold quality + judge noise**, not retrieval.
- **The judge score stopped being informative around 48–53%.** Chasing it further is the
  source of the "stuck" feeling. The real success criterion (per your own docs) is a
  **promo-team side-by-side vs the Custom GPT** — that test has never been run.
- **Two concrete, real bugs found** (below) — fixing them improves the *product*, not just
  the metric.

---

## 1. The production bug (`new bug.md`) — ROOT CAUSE FOUND

**Symptom:** Asked "רוקדים עם כוכבים, last season, launch + ep2 + ep3 ratings", prod bot
replied **"פרק ההשקה — no data found"**, though the launch exists (פרק 1, 18.5.2025,
opening 25.0%, rating 21.2%).

**Two stacked causes:**

1. **Alias collision (the real culprit).** `expand_aliases` in `app/domain_catalog.py`
   rewrites the bare token `כוכב/כוכבים → הכוכב הבא`. That rule fires **inside other show
   names**:
   - `רוקדים עם כוכבים` → `רוקדים עם הכוכב הבאים` → `extract_show_names` returns
     **`['הכוכב הבא']`** (the Eurovision show — wrong show entirely)
   - `כוכבים בריבוע` → `הכוכב הבאים בריבוע` → **`['הכוכב הבא']`** (also wrong)

   So the agent can end up retrieving **הכוכב הבא לאירוויזיון** data for a
   **רוקדים עם כוכבים** question. In prod, semantic search still surfaced some real רוקדים
   rows (so the answer looked partly right) but missed the launch row.

2. **Retrieval incompleteness.** Even with the right show, semantic top-N (top-3/5) often
   misses the launch or finale row. Confirmed: the launch row IS in the index; it just
   wasn't retrieved.

**The index itself is fine** — `רוקדים עם כוכבים` has clean seasons 1–4 (no phantom
"season 9"; that was a diagnostic artifact caused by cause #1 pulling הכוכב הבא's season 9).
There are some **duplicate rows** in season 4 (minor data-quality issue, not fatal).

### Fix for the prod bug
- **Guard the `כוכב` alias** so it does NOT fire when the token is part of a known
  multi-word show name (`רוקדים עם כוכבים`, `כוכבים בריבוע`). Simplest: in
  `expand_aliases`, detect catalog show names that contain `כוכב` **first** and protect
  them before applying the bare-`כוכב` → `הכוכב הבא` rule. (~5–10 lines, offline-testable.)
- Then the complete-fetch change (already made this session, see §4) returns all season-4
  rows incl. the launch, and the answer is correct.

---

## 1b. Second production bug (`NextBugFromBot.md`) — history contamination — FIXED

**Symptom:** Asked about **הזמר במסכה** (finale ratings), the bot refused with
*"לא נמצאו נתונים על **רוקדים עם כוכבים**..."* — a show that wasn't in the question, but
WAS the subject of the **previous** turn.

**Root cause:** the clean-refusal template (`Retrieval Safety` section) was filled with the
**off-topic show pulled from conversation history**. The history made the model think the
subject was still רוקדים, so it treated the (correct) הזמר chunks as off-topic and refused.
Probabilistic (LLM-variance-driven) — didn't reproduce every run.

**Verified on current code:**
- Single-turn: answers correctly AND now retrieves **all 4 seasons** (RC-A complete-fetch;
  prod only got season 3). Season 3 finale = no rating (correct), S2 = 27.3%, S4 = 20.1%.
- With the רוקדים turn in history: no longer mentions רוקדים; answers הזמר correctly.

**Fix shipped:** added a prompt guard in `system_prompt.txt` — "the subject is defined by the
CURRENT question, never by earlier turns; before any clean refusal, confirm `[X]` is the show
named in the current question, not one carried over from history."

---

## 2. Honest state of the 70% goal

| Lever | Tested this session | Result |
|---|---|---|
| Complete retrieval for single-show queries (RC-A) | Yes (5 cases) | Data sub-scores up; **judge neutral** |
| Synthesis-precision prompt rules | Yes (15 cases + full run) | **Judge neutral** (within noise) |
| Fixing a wrong gold answer (case 36) | Yes | **0.25 → 0.75** (clean win) |

**Conclusion:** the only thing that reliably moved the judge was correcting a **wrong gold**.
Retrieval completeness and prompt phrasing are both judge-neutral because the failures are
the LLM not selecting the right row / not leading with the precise number — a reasoning
ceiling, not a data or instruction gap.

**Realistic honest ceiling on this dataset/model: ~50–55%.** Reaching meaningfully higher
needs one of: (a) deterministic evidence-pack engineering (pre-label & filter launch/finale
rows *by date in code* before the LLM sees them), (b) systematic gold cleanup, or (c) a
stronger model — all bigger commitments with their own risks.

---

## 3. Action items (prioritized)

### P0 — fixes that improve the real product
1. **Fix the `כוכב` alias collision** (§1). Highest value: fixes a live prod bug and
   eval id=27. Add an offline test asserting `extract_show_names("רוקדים עם כוכבים") ==
   ["רוקדים עם כוכבים"]` and same for `כוכבים בריבוע`.
2. **Run the promo-team side-by-side test.** 5 real questions, PromoBot vs Custom GPT, 3
   people. This is the actual ship/no-ship signal — not the judge score. (Scoring sheet:
   ask Claude to generate it.)
3. **De-duplicate Excel rows** in `tv-promos` (season 4 of רוקדים has doubled rows). Minor,
   but it inflates row counts and can skew "complete fetch".

### P1 — cheap judge gains (proven lever)
4. **Verify more disputed golds via the Custom GPT** (it reads the full files = ground truth).
   This session: 1 of 5 verified golds was wrong (case 36). Candidates to verify next:
   **id=54** (גוף שלישי trailer test %), **id=15 / id=38** (חתונמי per-season launch ratings),
   **id=13** (המירוץ פרק 26), **id=50** (פאלו אלטו launch/finale). Workflow: you ask the GPT
   → Claude fixes the gold → `--rejudge --only <id>` (≈0 agent cost).

### P2 — only if pushing the number further is worth it
5. **Deterministic launch/finale selection in code.** In `_select_excel_rows_for_plan`,
   identify launch = earliest-date row and finale = latest-date row **per season**, label
   them, and pre-filter for "regular/שוטף/except launch&finale" queries — instead of relying
   on the LLM to do it. This is the only thing that would move the ranking/alias cases.
6. **Re-test a stronger model** (GPT-4o is current). Only after P0/P1.

### Do NOT do
- Don't keep re-running the full 62-case judge eval to chase ±1–2pp — it's within noise.
- Don't tune prompts to the judge; it's a proxy. Optimize for the side-by-side instead.

---

## 4. What changed locally this session (UNCOMMITTED — review before keeping)

- `app/service.py` — **RC-A**: single-show *rating* queries (not just "ranking") now use
  complete `fetch_show_promos` instead of semantic top-5; season filter applied to the
  complete set. Added `_RATING_INTENT_PATTERNS`. *Correctness win; judge-neutral.*
  **Note:** this is undermined by the alias bug (§1) for `כוכב`-containing shows — fix the
  alias first.
- `app/system_prompt.txt` — new **"Episode Identity & Answer Precision"** section
  (answer-first; launch=earliest date / finale=latest date; exclude them for "regular";
  don't refuse when qualitative data exists). *Judge-neutral; kept for UX.*
- `tests/eval_dataset.py` — **token-efficient eval**: full-answer cache, `--rejudge`
  (re-score cached answers, no agent calls), `--only <ids>` (re-run a subset), and
  `load_dotenv()` so the CLI works standalone.
- `dataset.jsonl` — **case 36 gold corrected** (GPT-verified: no season-3 finale rating
  exists; available finale ratings are S2 27.3%, S4 20.1%). Judge 0.25 → 0.75.
- `tmp_pkg/seed_cache_from_langfuse.py` — seeds the answer cache from Langfuse traces
  (uses `truststore` to get past the corporate-proxy SSL wall).
- `eval_answers_cache.json` — 62 cached agent answers (for free re-judging).

---

## 5. Token-efficient eval workflow (built this session)

```bash
# Re-score after a GOLD or RUBRIC change — NO agent calls (only judge LLM):
.venv/Scripts/python.exe tests/eval_dataset.py --rejudge --only 36,54,15

# Re-run only the cases a CODE change affects (live agent), not all 62:
.venv/Scripts/python.exe tests/eval_dataset.py --judge --only 27,13,22

# Refresh the answer cache from the last full run's Langfuse traces:
LF_HOURS=3 .venv/Scripts/python.exe tmp_pkg/seed_cache_from_langfuse.py
```

This turns each iteration from ~124 LLM calls into ~1–10.

---

## 6. The reframe (why this isn't "stuck")

The judge number was a phantom target. This session proved the agent retrieves the right
data and answers correctly far more often than the judge credits — and that some "failures"
were the *gold* being wrong (case 36), not the bot. The next move isn't another eval run;
it's putting the bot in front of the team and letting their reaction be the metric. That
test is 30 minutes and tells you the one thing 27 judge scores can't.

---

## 7. Data-health audit (read-only, 2026-05-31)

Quantified the data layer because almost every prod bug traced to data/retrieval, not the LLM.

**tv-promos (Excel) — 2,888 rows:**
- **~45% duplicates** — 1,302 extra copies; only 1,586 distinct logical rows
  `(show, season, episode, date)`. Verified on רוקדים: 220 rows → 112 distinct.
- **`episode_number` blank on 65%** of rows → launch/finale must be detected by DATE,
  not episode number.
- `season` blank on 12% — but these are **single-season shows** (tabs without "עונה N":
  המירוץ למיליון, גוף שלישי, חולי אהבה, פאלו אלטו, החיים…). Blank season is CORRECT for
  them; do NOT "fix" it.

**word-docs — 667 chunks (healthy):** 99% show_name coverage, 0 garbage tags. But **6 catalog
shows have ZERO chunks** (רוקדים עם כוכבים, המטבח המנצח, הבוגדים, ישמח חתני, מבחן ההורים) and
**6 are sparse (≤3 chunks)** — the thin-section condition behind the חולי-אהבה cross-show
contamination.

### Root cause of the duplication (confirmed)
The document id hashed the **positional row index** (`show|season|episode|index`), and **two
pipelines** (`ingest_excel.py` + `ingest_json_to_azure.py`) wrote the same source rows with
different ids → duplicates instead of upserts. Proof: the two copies of one row had different
ids, identical ratings, but different `promo_text` length (263 vs 403 chars = two pipelines).

### Fix shipped
- Both id-generators now hash **content** (`show|season|episode|date`, dropping `index`),
  identical across pipelines → re-runs and cross-pipeline writes UPSERT, never duplicate.
- `scripts/dedup_tv_promos.py` — dedups the existing index (dry-run by default; `--apply`
  to delete). Keeps the richest `promo_text` copy. Dry-run result: 2,888 → 1,586 (−1,302).

### ⚠ Sequencing footgun
The kept docs still carry OLD positional ids. A future ingest with the new content-based
keys would create non-matching ids → re-duplication. **After a dedup, tv-promos re-ingestion
MUST be delete-all-first** (full replace), or do a one-time clean re-ingest instead.

### Excel structure reference (`Obsidian/Prod/ExelMaping.md`)
Tabs are per-(show, season) (e.g. "רוקדים עם כוכבים עונה 4"); within a tab `תאריך` is the row
key. Real row counts sum to ~1,440 (matches 1,586 distinct minus section/special rows).
Edge cases that break naive parsing: `אור ראשון` (single merged note, no episode rows),
`היורשת`/`נוטוק`/`מאסטר שף VIP` (data in the header row), `מאסטר שף`/`המטבח` (sectioned tabs).

### Note on prod vs local
The רוקדים / הזמר / חולי אהבה / החיים prod failures the team hit are **already fixed in the
committed code** (alias, history-anchor, single-show Word scoping, complete fetch) — they
need a **deploy** to take effect in prod. Local verification passes on all four.
**(Deployed to prod 2026-05-31.)**

---

## 8. The 6 word-docs zero-chunk shows — CONTENT gap, not a bug

Audit flagged 6 catalog shows with 0 chunks in `word-docs`: רוקדים עם כוכבים, המטבח המנצח,
המטבח המנצח VIP, הבוגדים, ישמח חתני, מבחן ההורים הגדול. Full-text search of the word index
for each name shows they appear **only as comparison mentions inside OTHER shows' chunks**
(e.g. רוקדים's 8 text-matches are all tagged המירוץ/הזמר/מאסטר שף; הבוגדים has 0 mentions
anywhere). None has its own dedicated strategy section.

**Verdict: a content-coverage gap, NOT an engineering bug.** These shows ARE tracked in the
Excel index (`tv-promos`) with full ratings/promo data — they're simply not written up in the
4 GPT strategy Word docs. Nothing is mis-tagged, mis-ingested, or broken.

Consequences (correct behavior):
- **Ratings/numeric questions** about these shows → answered from Excel (works; the dedup +
  alias + date-launch/finale fixes apply to them too).
- **Strategy/insight questions** → no Word data. The single-show Word scoping shipped today
  scopes to the show's `show_name`, finds 0 chunks, and correctly returns "no data" — instead
  of grabbing those comparison mentions from other shows and mis-attributing them.

**Only way to add strategy coverage:** author the content into the source Word docs and
re-ingest — a content/business task, out of engineering scope. No code change recommended.
