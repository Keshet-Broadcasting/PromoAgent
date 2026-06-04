# Session Summary — 2026-06-03 (handoff for the next agent)

**Branch:** `fix/genre-contamination-truncation` (pushed, **not yet merged to `main`**).
Merging deploys via Azure DevOps CI/CD (staging → prod). See ROADMAP "Pending to prod".

This session chased one promo-team complaint — *"quote the sales strategies of all the
dramas"* returned ~3 shows and omitted אף אחד לא עוזב את פאלו אלטו — down through **seven
layers**, each a real fix. Two companion docs go deeper:
`2026-06-03-genre-contamination-and-truncation.md`, `2026-06-03-word-index-extraction-gap.md`.

---

## The seven layers (all fixed)

1. **Genre contamination** — drama questions pulled reality content. Cause: `BROAD_RETRIEVAL_ENABLED`
   was off. Flag activates the genre→show filter.
2. **Answer truncation** — `MAX_ANSWER_TOKENS` 1000 → 1800 (shared with the `<thinking>` block).
3. **"All dramas" under-coverage** — a single semantic top-N let a few shows crowd out the rest.
   Added **per-show Word fetch** (`fetch_word_docs_per_show`) + **Coverage Mode** prompt +
   **strategy-section bias** (`prefer_question_types`). 3 → ~15 shows.
4. **פאלו אלטו strategy missing from the index (ROOT)** — the strategy chunk IS extracted but is
   114 chars, and `_apply_semantic_guardrails` discarded everything < `SEMANTIC_CHUNK_MIN_CHARS`
   (150). ~369 short *labeled* Q&A sections were lost across the GPT docs. Fix: keep short chunks
   that are real labeled sections (`_is_meaningful_short_section`). **Re-ingested** the two large
   docs (>4 MB use the python-docx fallback path; the small docs use Document Intelligence and were
   unaffected): index **667 → 934** (drama 174→262, reality 423→602).
5. **Ingest robustness** — embedding aborted a whole doc on one transient proxy stall (60 s, no
   retry), briefly leaving a doc with 0 chunks. Now 180 s timeout + 4-attempt backoff.
6. **Quote corruption** — the content-filter sanitizer's bare `ירי` matched inside benign words/
   names (אי**ירי**ס → "אס", מכ**ירי**ם → "מכ[תקיפה]ם"). Word-bounded it.
7. **Eval underselling the bot** — see next section.

Plus: **startup warning** when broad retrieval is off; **deploy flags** wired into
`azure-pipelines.yml` (staging+prod); **SharePoint fallback** config wired (off, see below).

---

## Eval / judge findings (this is important for the next agent)

The judge was **penalizing correct, grounded answers**:
- **Short golds**: id=1 ("quote ALL dramas") had a gold listing only **2** dramas. The bot
  correctly gave more (groundedness 1.0), and the judge mislabeled the extra *correct* dramas as
  "hallucinations" → 0.25. Fixed by rewriting id=1's gold to the full documented set (~15).
- **Rubric**: clarified that the **GOLD is a PARTIAL reference** — additional grounded shows/
  details are NOT hallucinations; only penalize genuine fabrication/contradiction. Effect on the
  6-case cluster: **judge 54.2% → 66.7%** (`--rejudge`; id=52 0.5→0.75, id=56 0.5→1.0).
- **`Overall` is misleading** for non-numeric cases — it averages in `Numeric=0%`. Read **LLM
  Judge**, not Overall.
- **Judge is noisy**: the same cached answer re-judged swung ±2 (id=26 0.75→0.25, id=56 0.5→1.0).
  Trust the macro, distrust single-case scores. (Matches `PATH_TO_70` §0.)

**id=1 still ~0.50 even after all fixes** — the model prefers thematic synthesis (6 shows +
"FOMO/branding/emotion") over a 15-show verbatim list, because the prompt's "Analytical Depth /
Funnel / Strategic Synthesis" sections outweigh Coverage Mode for a `צטט` query. Fully fixing it
is a prompt mode-arbitration job (suppress synthesis on quote-all queries) — **low ROI vs the
team side-by-side; not chased further.**

**Dataset recommendation:** the short-gold + harsh-rubric pattern likely affects more than id=1.
Apply the same gold-comprehensiveness pass to other coverage/strategy/quote cases. The rubric fix
(committed) is the highest-leverage change.

---

## Open items / leftovers (also in ROADMAP "Pending to prod")

1. **Merge the branch to `main`** → deploys code + flags. Until then prod runs the old behavior.
2. **SharePoint fallback**: config wired, `SP_ENRICHMENT_ENABLED=false`. To enable: grant the
   Container App **managed identity** `Sites.Selected` on `/sites/Promo` (no client secret —
   `sharepoint_tool.py` uses MI), then flip the flag. **Until then the agent CANNOT retrieve
   SharePoint-only data at runtime** (the M365 MCP is a Claude-session tool, NOT wired into the
   app).
3. **Source typo** "בפר הזיום" → "בפרק הסיום" in `מסמך דרמות GPT.docx` (הראש strategy). Author typo;
   fix in the doc + re-ingest if it matters.
4. **Gemini evaluation** — re-test on clean post-fix data (cheap; see ROADMAP). The May-19
   comparison (Foundry 53.8% vs Gemini 39.3%) ran on broken pre-Phase-6c data — not valid now.
5. id=56's absolute 18.5% rating lives in **Excel**; the word-only route misses it. A
   "analyze campaign + why it succeeded" query arguably should route **hybrid** (word + excel).

---

## Files touched (high level)
- `app/service.py` — broad-retrieval gating, per-show coverage, coverage/strategy-bias, sanitizer
  `ירי` fix, `_STRATEGIC_INTENT_PATTERNS`, `_COVERAGE_INTENT_PATTERNS`, `_is_meaningful_short_section`
- `app/search_word_docs.py` — `fetch_word_docs_per_show` (+ `prefer_question_types`)
- `app/chat_provider.py` — `MAX_ANSWER_TOKENS` 1800
- `app/system_prompt.txt` — Coverage Mode, Concrete Specifics Rule
- `scripts/preprocess_word_docs.py` — min-size guardrail keeps labeled short sections
- `scripts/ingest_word_chunks.py` — embedding timeout + retry
- `tests/eval_dataset.py` — judge rubric (gold is partial); `dataset.jsonl` id=1 gold
- `azure-pipelines.yml` — retrieval flags + SP config (staging+prod)
- Tests: `test_preprocess_chunking.py`, `test_content_filter_sanitize.py`, additions to
  `test_retrieval_planning.py` (~22 offline tests, green)
