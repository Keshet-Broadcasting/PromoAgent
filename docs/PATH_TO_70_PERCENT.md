# PromoAgent — Path to 70% Judge Score (Handoff Plan)

**Written:** 2026-05-25 · **Revised:** 2026-07-01 (drama live-viewing cohort retrieval)
**Audience:** the next agent (or future self) picking up where we left off
**Current state:** judge **58.1%** (2026-06-11, 62 cases, all-time high), overall 57.0%
**Target:** judge ≥ 70% to declare ready for Custom GPT replacement
**Honest gap:** +12pp judge. **Bottleneck is now confirmed model-tier** (Langfuse-verified:
evidence in context, gpt-4o ignores it — see 2026-06-11 session insights §4). Next lever:
stronger Foundry deployment A/B, then the expanded ~200-question dataset, then the
promo-team side-by-side.

This document is the strategic roadmap from where we are now to a defensible "ready
to replace Custom GPT" state. It is not a list of tasks — it is reasoning about
which tasks matter, in what order, and why. **If you read only one section, read
Section 0 — the variance finding that changes everything below.**

---

## 0. CRITICAL UPDATE (2026-05-26) — Variance verification changes priorities

After writing the original plan, I ran the same eval twice with identical code,
identical seed, identical data. Results:

```
                  Run 5      Run 6       Δ
  Overall         52.3%      53.4%      +1.1
  Judge           45.4%      45.8%      +0.5    ← macro stable
  Groundedness    90.7%      90.7%       0.0
  Refusal         66.7%     100.0%     +33.3    ← BIG variance on 3 cases
```

**Macro is reproducible. Per-case is NOT.** Of 54 cases, **12 (22%) changed
their judge bucket** between identical-code runs. Per-category swings up to
±10pp. Refusal accuracy swung 33pp because 1 of 3 no_answer cases flipped its
refusal decision purely from LLM non-determinism (seed=42 is best-effort, not
strict on GPT-4o).

### What this means for everything below

**The session that produced the original plan (May 24-25) was operating in
noise.** Many "regressions" attributed to specific patches were probably half
LLM variance. The judge has a real plateau at ~45%, but individual
category drops we attributed to specific patches were inflated.

Concretely:
- "Quote regressed 71→42 after Phase 6c" — likely actually moved to ~50-55%
  with ±10pp band, not a stable 42%
- "Alias dropped 46→25" — likely actually ~30-35% band
- "Strategy jumped 16pp between Run 4→5" — pure noise (Patch E was scoring-only)
- 6h's premise was based on these noisy swings → 6h is essentially dead

### Revised priorities

**The original plan put routing fixes (Phase A) before dataset/observability.
That was wrong.** With ±10pp per-category variance on N=3-8, no routing patch
can be reliably measured. The corrected order is:

1. **E first** — expand eval dataset to N≥10 per category. Without this, every
   patch decision is fog.
2. **B observability** in parallel. Per-case variance tracked across runs.
3. **C voice/prompt** — biggest real lever, retrieval is fine.
4. **A routing fixes** — last priority, may not even matter.

### Prompt surface cleanup (2026-06-22)

Status: **DONE (branch: `refactor/shorten-system-prompt-positive-rules`, commit pending)**.

| Item | Result | Diagnostic |
|---|---|---|
| Shorten top-level operating rules | Consolidated duplicate grounding, citation, partial-evidence, and answer-shape instructions in `app/system_prompt.txt` | Prompt remains 421 lines / 30,479 chars because few-shot examples and strategic mode are intentionally preserved |
| Reframe negative style rules positively | Operational negative wording reduced from 28 matches to 4 remaining hard/example cases | `rg` count for `DO NOT`/`Never`/similar: 4 |
| Preserve prompt behavior anchors | Kept strategic-mode anchors (`מסקנה אסטרטגית`, `קשת הקמפיין`, `עוגן מרכזי`, `Coverage Mode`, `thesis`) | `tests/test_retrieval_planning.py` passed: 31/31 |
| Focused A/B eval slice | Prompt refactor slightly beat baseline on 16 prompt-sensitive cases | Baseline overall/judge: 0.708/0.766; refactor: 0.729/0.797; regressions to inspect: 12, 24 |
| Repeated focused A/B eval slice | Prompt refactor beat baseline again on the same 16 cases | Baseline overall/judge: 0.651/0.672; refactor: 0.707/0.766; case 12 regression did not repeat; case 24 is not clearly prompt-caused |
| Full 64-case A/B eval | Prompt refactor beat baseline on the full dataset | Baseline overall/judge: 0.651/0.637; refactor: 0.688/0.688; errors: 0; green light to push |

Decision: merge is recommended. Watch case 57 in future prompt work because both variants still miss the "will the relationship survive" framing.

### Eval triage rule + drama slice check (2026-07-01)

Status: **DONE (local changes; commit pending)**.

| Item | Result | Diagnostic |
|---|---|---|
| Add source-of-truth checkpoint before fixes | `.cursor/rules/eval-regression-triage-before-code.mdc` now requires exact copy-paste Custom GPT and Claude/document-focused questions, plus Langfuse trace comparison, before changing prompts, retrieval, code, model config, or gold answers | Prevents overfitting eval failures before confirming whether the product baseline or source docs support the gold |
| Pause case 60 code fix | Custom GPT produced a different calculator than the existing gold, so case 60 is now treated as a gold/product-alignment question until document checks confirm the intended answer | Partial local case-60 context/prompt edits remain in the working tree but should not be considered validated production behavior yet |
| Run small drama judged slice | Cases `1,2,3,4,5` ran with LLM-as-judge via `CHAT_PROVIDER=azure_openai` | 0 execution errors; overall `58.9%`, judge `60.0%`; cases 1 and 5 strong, cases 2/3 low, case 4 middling |
| Next action | Do not fix cases 2/3/4 directly yet | First ask Custom GPT and Claude/source-doc questions to determine whether these are retrieval failures, model summarization failures, or bad/obsolete gold |

### Drama live-viewing cohort retrieval (2026-07-01)

Status: **DONE (local changes; commit pending)**.

| Item | Result | Diagnostic |
|---|---|---|
| Root cause | The bot answered a live-viewing drama strategy question as one flat high-rating list, letting `להיות איתה` / `צומת מילר` dominate and underweighting `נוטוק` / `פאלו אלטו` / `אור ראשון` | Custom GPT + source-doc checks showed two axes: rating winners vs live/binge learning cases |
| Prior-art check | Reused the Jun 3 genre-contamination fix rather than replacing it | Broad retrieval/per-show coverage already solved reality leakage and missing `פאלו אלטו`; this adds the missing business-intent cohort and answer contract |
| Retrieval/context fix | `app/retrieval_plan.py` detects drama + live/binge/completion/spoiler intent, expands targets with `אור ראשון`, `נוטוק`, `פאלו אלטו`, `הראש`, and adds a two-axis guidance block | Keeps `נוטוק` catalogued as entertainment globally; only this intent pulls it into the drama-live-viewing cohort |
| Word fetch | `app/retriever.py` biases per-show Word retrieval toward `תובנות` / `אסטרטגיה` / `מחקר` for this intent | Mirrors the Jun 3 strategy-section bias that recovered `פאלו אלטו` |
| Verification | `tests/test_retrieval_planning.py`: 42 passed; exact-prompt live retrieval includes `נוטוק` and `פאלו אלטו` in Excel+Word, `אור ראשון` in Word, guidance in context | `אור ראשון` lacks row-level Excel promo data, so Word is the expected source |

### Case 30 launch-comparison range calibration (2026-06-30)

Status: **DONE (local changes; commit pending)**.

| Item | Result | Diagnostic |
|---|---|---|
| Identify regression mode | Retrieval was healthy (3 show-filter fetches, 369 raw Excel rows, 11 selected launch rows), but gpt-5.4-mini collapsed `חתונה ממבט ראשון` to the peak launch row `23.5%` | Langfuse trace `c0bb61c6bf287a090ecbde74f9d5dd6a` scored 2 because the gold expected a cross-season range around `20-21%`, not only the highest season |
| Encode answer-shape contract in context | `app/retrieval_plan.py` now adds `### הנחיית השוואת השקות` for multi-show launch comparisons, including per-show ranges and all launch values | The model sees the aggregate/range before the raw table and is explicitly told not to choose only highest/latest unless requested |
| Add regression coverage | `tests/test_retrieval_planning.py` checks the anti-peak-only instruction and per-show summary for the `נינג'ה ישראל` / `חתונמי` / `המירוץ למיליון` case | Prevents future prompt/context changes from silently removing the guard |
| Verify | Focused tests passed; fresh judged eval case 30 recovered | `pytest ... 3 passed`; `tests/eval_dataset.py --id 30 --judge`: overall `82.4%`, numeric `100%`, grounded `100%`, judge `4/5` |

### Case 57 new-season retrieval correction (2026-06-23)

Status: **DONE (local changes; commit pending)**.

| Item | Result | Diagnostic |
|---|---|---|
| Preserve case 57 intent | `dataset.jsonl` cleaned query now keeps `לקראת עונה חדשה` instead of collapsing it into a generic tonight question | Root cause: eval used `cleaned_query`, so the launch/new-season signal was removed before retrieval |
| Route new-season language to launch retrieval | `_LAUNCH_PATTERNS` in `app/retrieval_plan.py` now matches `לקראת עונה חדשה`, `עונה חדשה`, and `עונה חוזרת` | Case 57 plan now has `event_intent == "launch"` |
| Prefer launch/novelty evidence | Launch Word retrieval now includes `שיקול` and `חידושים` question types for single-show launch queries | Retrieved chunks include `חידושים בעונה חוזרת הוא קריטי`, `כיף מנצח`, and character/dilemma passages |
| Guard regular tonight behavior | Normal `tonight` single-show queries keep the broader pre-existing Word search path | Case 16 recovered in paired eval after narrowing the filter change |
| Add dataset CI protection | `dataset.jsonl` is no longer ignored; `tests/test_eval_dataset_integrity.py` validates schema, IDs, categories, booleans, sorted IDs, and cleaned-query intent preservation | The new guard caught case 58 dropping `ללא השקה וגמר`; fixed locally |
| Keep manual smoke script out of CI unit flow | `app/test_chat_connection.py` sets `__test__ = False` and uses `_completion_kwargs()` so manual gpt-5.4 checks do not fail on `max_tokens` | `pytest -q app/test_chat_connection.py` reports no collected tests, as intended |
| PR #26 review follow-up | Split launch regex into named components; added SDK error logging in the manual chat smoke script while preserving raised failures | Type-hint review note was already satisfied in the PR code |
| Verification | `tests/test_retrieval_planning.py`: 33/33; `tests/test_eval_dataset_integrity.py`: 3/3; focused non-auth subset: 40/40; PR follow-up focused test: 36/36; full local pytest: 120/120; targeted eval `12,16,24,36,57,58`: case 57 overall 85%, judge 5/5, 0 eval errors; case 58 fresh eval after cleaned-query fix: 64.1% | Initial local PyPI 403 installing `PyJWT` cleared on retry |

**Section 6 (Pragmatic Sequence) has been rewritten below to reflect this.**

### Frontend UX cleanup (2026-06-23)

Status: **DONE (local changes; commit pending)**.

| Item | Result | Diagnostic |
|---|---|---|
| Friendly Hebrew API errors | `promobot-ui/src/services/api.ts` maps authentication, validation, rate-limit, unavailable-service, server, and connection failures to non-technical Hebrew messages | Chat state carries an optional contextual action label, such as re-login for auth failures |
| Contextual error actions | `ChatWindow`, `MessageList`, and `ErrorState` pass the action label through the UI and retry auth errors by calling `login()` | Retry button text is no longer one-size-fits-all |
| Render assistant formatting | `MessageBubble` parses assistant Markdown for headings, bold spans, ordered lists, unordered lists, and paragraphs | Assistant answers no longer expose raw `##` / `**` markers in the chat bubble |
| Keep MSAL iframe config typed | `promobot-ui/src/config/msal.ts` uses a local compatibility type for iframe and timeout options instead of `any` | Build-time TypeScript accepts the existing runtime config |
| Verification | Frontend lint and production build pass | `npm run lint`; `npm run build` passed, with only the existing Next.js multiple-lockfile workspace-root warning |

### Prompt Cache + Partial-Coverage Calibration (2026-06-30)

Status: **DONE (local changes; commit pending)**.

| Item | Result | Diagnostic |
|---|---|---|
| Investigate repeated prompt-cache miss | Langfuse trace `3799af40e9541aa56d8df47a40d69d45` repeated the same broad/hybrid question and still reported `input_cached_tokens=0` | Same current prompt hash as prior miss; 15 Excel docs, 12 Word docs, ~14.6k context chars |
| Compare against known cache-hit trace | Older generation `05d3e020eeddcfa8` reported `input_cached_tokens=9472` without explicit cache controls | Confirms provider caching can work, but current prod routing is unreliable without a stable cache key |
| Add explicit cache routing controls | `app/chat_provider.py` now sends `prompt_cache_key` and `prompt_cache_retention` for Azure/OpenAI and Foundry chat completions | Default key: `promobot:<deployment>:system-prompt`; default retention: `24h`; env overrides available |
| Explain and fix "המידע שנשלף חלקי" overstatement | `app/system_prompt.txt` and `app/retrieval_plan.py` now make partial disclaimers conditional on explicitly missing requested coverage | Root cause: broad-retrieval context plus prompt rule made the model treat broad evidence packs as inherently partial |
| Verification | Focused tests added for cache kwargs and broad-retrieval wording | Commit hash pending until this local change is committed |

### What's actually real (validated across multiple runs)

| Signal | Verdict |
|---|---|
| Macro judge stuck at ~45-46% | ✅ Real plateau |
| Phase 6c unlocked retrieval (cross_show 19→38-44) | ✅ Real (Δ too big for noise) |
| Phase 6b unlocked filter capability (quote 46→62-71) | ✅ Real direction |
| Patches A/B/C/D shipped without breaking things | ✅ Real (macro stable through them) |
| Phase 6c "regressed" quote/ranking/alias | ❌ Mostly variance (cases averaged across runs are ~stable) |
| Strategy jumping ±16pp between runs | ❌ Pure noise on N=3 |
| Refusal swinging 33pp run-to-run | ❌ Binary LLM non-determinism on 3 cases |

### The unfortunate math

70% on the **current 62-case dataset** is probably mathematically unreachable
even with perfect bot behavior:
- Judge scores are 1/2/3/4/5 (= 0/0.25/0.5/0.75/1.0 normalized)
- Bot would need average 3.5/5 to hit 70%
- ±10pp per-case variance means single runs swing wildly
- ~25% of cases consistently score 2/5 due to gold-answer brevity mismatch (Section 5 issue)

**70% becomes realistically achievable only after Phase E** (expanded dataset +
rubric refinement). Until then, **target 55-58% with high confidence** and
validate via real-user side-by-side.

---

## 1. What we know about the plateau

Across the last 5 eval runs:

```
Run 1 (broad retrieval activation, May 24)              judge 44.4%
Run 2 (Phase 6b — word-docs schema + re-ingest)         judge 49.1%
Run 3 (Patches A/B/C — alias / route / English rule)    judge 45.3%
Run 4 (Phase 6c — parser fix + 250 chunks recovered)    judge 45.4%
Run 5 (Patch E — groundedness rubric fix)               judge 45.4%
```

We shipped **major retrieval improvements** (Phase 6b unlocked 22 catalog shows,
Phase 6c unlocked another 18). The macro judge metric did NOT move materially.
This is not a coincidence and not pure noise — it's a real plateau.

### Diagnosis

| Layer | State | Evidence |
|---|---|---|
| **Retrieval** | Solved | `test_data_health.py` passes 27/27; 40/46 catalog shows now have chunks; `id=40` returns 5/5 when retrieval delivers the right chunk |
| **Routing** | Partially regressed | Phase 6c made broad path more effective; over-fires on narrow queries (`quote` 71→42, `ranking` 50→38) |
| **Voice / synthesis** | Bottleneck | ChatGPT-vs-PromoBot side-by-side (`שאלה ותשובה של GPT.md`) shows model is capable; prompt steers it toward strategy-doc voice |
| **Eval rubric** | Too strict | Gold answers expect one specific insight; bot gives comprehensive answers; judge scores 3/5 even when factually correct |
| **Variance** | High on small-N categories | Strategy (N=3) jumped +16pp between runs 4→5 despite no behavior-affecting code change → seed=42 is best-effort not strict |

### What this means

**The 45-52% range is not the model's ceiling, nor is it pure noise.** It is the
combined effect of:
1. **One known bug** (over-broadening for narrow queries) suppressing ~5pp
2. **One known prompt gap** (creative-mode voice) suppressing ~3-5pp
3. **Eval methodology limits** (small-N + strict rubric) creating a fog of
   uncertainty that mathematically can't be defeated without dataset changes

---

## 2. Realistic ceiling math

Looking at per-category judge scores and what each could realistically reach
with focused effort, not optimism:

| Category | N | Run 5 | Realistic ceiling | What gets us there |
|---|---|---|---|---|
| no_answer | 4 | 100% | 100% | already maxed |
| numeric | 10 | 57% | ~75% | minor format fixes + cross-source for non-Excel-only shows |
| ranking | 8 | 41% | ~65% | broad-scope refinement (todo `6h`) |
| quote | 6 | 42% | ~70% | broad-scope refinement |
| factual | 5 | 45% | ~65% | already unlocked by Phase 6c; needs prompt depth |
| cross_show | 4 | 44% | ~60% | synthesis bound; variance dominates |
| strategy | 6 | 58% | ~70% | voice fix + N=3 noise (could be 70% already) |
| open_ended | 10 | 32% | ~55% | creative-mode prompt (biggest single lever) |
| alias | 7 | 25% | ~60% | context-aware `כוכב` rule + general fix for missed cases |
| comparison | 2 | 25% | N/A | N=1 — meaningless |

**Stacked realistic ceiling on current dataset: ~58-62% judge.** Not 70%.

Hitting 70% requires:
- All the above
- AND model upgrade (untested, +3-8pp if Hebrew is good)
- OR eval dataset/rubric refresh (some gold answers are debatable)
- OR architectural change (graph RAG, query decomposition)

**Be honest about this number** with stakeholders. The team-facing replacement
criterion ("users prefer PromoBot over Custom GPT") is more relevant than judge
score on 54 historical cases.

---

## 3. The phased plan

Five phases, each with a concrete success criterion. Do them in order — each
phase's value depends on the previous phase landing first.

### Phase A — Plateau-breaking routing fixes ✅ DONE (May 28)

**Commit:** `03508de`

| Item | File | Status | Detail |
|---|---|---|---|
| **A.3 — broad-scope guard** | `app/service.py` `_build_retrieval_plan` | **DONE** | `bool(genres) and len(show_names)==0` — genres only broaden when no single show constrains the query. Single-show+drama-word queries stay narrow. |
| **A.2 — exclude content-type phrases** | `app/domain_catalog.py` `genres_for_query` | **DONE** | `_DRAMA_CONTENT_TYPE_RE` strips "דרמה אישית"/"דרמה זוגית" etc. before pattern matching. Fixes id=32. |
| **A.1 — context-aware `כוכב` alias** | `app/domain_catalog.py` `expand_aliases` | **DONE** | `_KOCHAV_SEASON_RE`: `כוכב (ב)עונה N≥10` → `הכוכב הבא לאירוויזיון`; N<10 → `הכוכב הבא`. Fixes id=29. |

**Diagnostic results (May 28):**
- ID 29: retrieval plan now correctly targets `הכוכב הבא לאירוויזיון` season 11. Remaining score gap is answer format (average vs launch/finale specifics) — separate issue.
- ID 32: no longer mis-routes to drama broad-path. Low score remains because cross-show promo-type comparison data isn't explicitly tagged in the index (Phase E item).

**Phase A success criterion (to measure after next eval run):** judge ≥ 50% with `quote` ≥ 55% and `ranking` ≥ 45%.

### Phase B — Observability upgrade (4-6 hours, no direct judge lift but enables everything else)

**Goal:** turn the black box into a glass box. Every future patch becomes
measurable; failures become diagnosable in minutes instead of hours.

Based on the user's proposal (`docs/improvement promoagent/רעיון לשיפור.md`),
which is correct: separate operational tracing (Langfuse) from curated
engineering notes (Obsidian).

| Item | Effort | Why it matters |
|---|---|---|
| **One Langfuse trace per `run_query` call** with named spans for: alias expansion → router → retrieval plan → Excel fetch → Word fetch → SP enrichment decision → prompt assembly → LLM call → post-processing → final answer | 2 hr | Today everything is named `OpenAI-generation`. Spans let us see "the agent decided X at step Y" without re-running |
| **session_id linking agent ↔ judge traces** in eval harness | 1 hr | One of the May 24 Langfuse review items. Lets us click from a failing eval case → both the agent and judge traces |
| **Structured metadata on every trace**: `route`, `planner_output`, `azure_hits_count`, `best_reranker_score`, `sp_triggered`, `retrieved_show_names`, `missing_entities`, `prompt_version` (commit hash), `model_name`, `final_confidence`, `refusal_flag` | 1 hr | Enables dashboard queries like "show me all traces where Patch B fired AND judge was ≤ 2" |
| **Push judge scores via `langfuse.score(trace_id, name="judge", value=N)`** | 30 min | Makes the Scores tab actually populated for aggregation |
| **Weekly distillation script** — pulls top failure clusters from Langfuse, generates an Obsidian-ready markdown summary, opens for human curation. NOT raw session dumps | 1 hr | Engineering memory, not log archive |

**Phase B success criterion:** can answer "why did this specific case fail?" from
the Langfuse dashboard alone, no re-running diag scripts. Score backfill working.

**Why Phase B before more patches:** without it, the next 5pp gain (or loss) will
be just as ambiguous as the last 5pp. Every patch from this point is more
expensive to evaluate without observability.

### Phase C — Voice and prompt ✅ PARTIAL (May 28, commit `57d67f1`)

**Goal:** close the ChatGPT-vs-PromoBot voice gap.

| Item | Status | Detail |
|---|---|---|
| **C.1 Refusal calibration** | **DONE** | Clean-refusal formula in `Retrieval Safety` section: "לא נמצאו נתונים על [X]... הנתונים שנשלפו מתייחסים ל-[Y]". Forbids synthesizing from off-topic chunks. |
| **C.2 Anti-hedging voice rule** | **DONE** | Tone section: forbids "ייתכן כי", "אולי", academic closers; requires leading with conclusion in strategic answers. No citation footer in Creative Mode. |
| **C.3 Creative Mode triggers** | **DONE** | Expanded from 5 → 14 trigger phrases; now covers "תכתוב לי", "תבנה לי", "תיצור לי", "תעזור לי לפתח", "איך היית מקמפיין". |
| **Citation rule strengthening** | TODO | Require explicit file/source reference in every non-creative answer. |
| **Strategy precision** | TODO | Bot paraphrases exact slogans/formulas from source docs instead of quoting them. Diag on ID 56 confirmed: right doc retrieved, wrong level of specificity in answer. |

**Phase C success criterion:** judge ≥ 53%. Side-by-side blind test with 5 promo
team members on 10 creative questions: PromoBot competitive on ≥6/10.

### Phase D — Content filter mitigation ✅ DONE (May 28, commit `f1f8e1f`)

| Item | Status | Detail |
|---|---|---|
| **D.1 Sanitize all text sources** | **DONE** | `_sanitize_for_content_filter()` applied to `promo_text` (Excel), `chunk`+`caption` (Word), `text` (SharePoint) before prompt assembly. Replaces אקדח/ירי/יורה/נורה/נהרג/גופה + conjugated forms with neutral brackets. |

**False-positive guards:** "נורא" (terrible) unchanged ✅, "הראש" show name unchanged ✅.  
**Test coverage:** 9/9 unit tests pass (`tmp_test_content_filter.py`).  
**Phase D success criterion:** eval cases mentioning "הראש" no longer hit Error 400. ✅ (to confirm in next eval run)

**D.3 — Dataset case 9 gold answer fix (commit `529bd71`):**  
Case 9 gold answer said "no numerical data for פאלו אלטו in document" — verified as wrong via Claude reading מסמך דרמות GPT.docx directly. Document contains: 29% general sample, 65% among promo-exposed (82% women), 70%/67% in screening test by version. Gold answer corrected to include all 3 measurement types for both shows. Model was being penalized score 2 for accurate, comprehensive answers.

**D.2 — Router brief fix (commit `64548d8`):**  
Added "בריף" + 10 brief/campaign phrases to `WORD_QUOTE_PATTERNS`. Brief queries now route to `word_quote` → show_name filter retrieves the הראש strategy chunks. Live verification: 17 הראש chunks confirmed in `מסמך דרמות GPT.docx` (תובנות, שיקול, התלבטויות, רייטינג sections). 7/7 router tests pass.

### Phase E — Statistical power and rubric (1-2 days, unlocks measurement)

**Goal:** stop arguing with noise. The current dataset (54 cases, often N=3-7
per category) makes ±10pp moves on individual categories indistinguishable from
LLM variance.

| Item | Effort | Expected lift |
|---|---|---|
| **Expand eval dataset to N≥10 per category** (target ~80 cases). Source new cases from real promo team queries (already in `Obsidian Vault/שאלה ותשובה של GPT.md` and similar) | 1-2 days | no judge lift, but unmasks real lift from A/C/F |
| **Adjust LLM judge rubric** — current rubric strictly penalizes length mismatches. Add length-tolerance: "score on factual coverage and core insight, not verbosity" | 2 hr | +3-5 (some currently-3/5 answers become 4/5) |
| **Add `reasoning` field to judge structured output** | 1 hr | enables debugging — see WHY judge scored 3 not 4 |

**Phase E success criterion:** within-run category variance < ±5pp on N=10 cases.
Judge rubric reasoning visible per case.

### Phase F — Architectural ceiling lift (1-2 weeks, +3-8pp)

**Only after Phases A-E.** These are larger commitments — pick at most ONE first
and measure before stacking.

| Item | Effort | Expected lift | When |
|---|---|---|---|
| **Re-test Gemini 2.5 on clean data** | 1 hour | unknown | The May 19 Gemini test (39.3% vs Foundry 53.8%) ran on a broken substrate (60% garbage show_name, 18/40 catalog shows with 0 chunks). On post-Phase-6c data it may behave very differently. Cheap to verify — `CHAT_PROVIDER=gemini` and re-run eval. Even if it loses, the comparison is honest now. |
| **Better re-ranker** — Cohere ReRank or BGE-Reranker-v2 on top-50 Azure results | 1-2 days | +3-5 on quote/factual | If precision is the gap |
| **HyDE retrieval** — LLM generates hypothetical answer, embeds it, retrieves on the hypothetical | 1-2 days | +2-4 on open_ended/strategy | If vague queries are the gap |
| **Query decomposition** for multi-show questions | 2-3 days | +5-8 on cross_show | If synthesis is the gap |
| **Test GPT-5 / Foundry o-series** on cross_show + strategy slices via controlled A/B | 1 day | +3-8 IF Hebrew is good | Only after exhausting prompt fixes |
| **Graph RAG (Cognee or LightRAG)** | 1-2 weeks | +5-10 on cross-show/strategy | Only if the corpus grows beyond 4 docs / 667 chunks. **Currently overkill.** |

**Phase F success criterion:** judge ≥ 60% with rigorous A/B test confirming the
specific change drove the lift.

---

## 4. What NOT to do

These are tempting but have wrong cost-benefit:

| Anti-pattern | Why not |
|---|---|
| **Activate SP MCP enrichment** (`SP_ENRICHMENT_ENABLED=true`) | Solves freshness (new docs not yet in Azure), NOT synthesis. Doesn't move judge. Activate in production when content updates start lagging ingest. |
| **Upgrade to Gemini 2.5 *without re-testing first*** | The May 19 test (Gemini 39.3% vs Foundry 53.8%) was on broken pre-Phase-6c data. Don't assume that result still holds. Re-test on clean substrate (Phase F item) before any production decision. The 1-hour cost of a fair re-test is worth it. |
| **Upgrade to GPT-5 before Phases A-C** | Would mask whether routing/prompt issues were the real problem. Test only after exhausting cheaper levers. |
| **Hyper-tune on the current eval** | The eval is a proxy. Real-user side-by-side is the truth. Don't game judge at the cost of real quality. |
| **Treat small-N category swings as signal** | Strategy (N=3) jumped +16pp between two runs with no behavior change. That's noise. Only macro and N≥7 movements are signal. |

---

## 5. The non-negotiable: real user testing

Whatever the judge score says, the actual replacement criterion is:

> The promo team prefers PromoBot's answer over Custom GPT's in a side-by-side
> blind test on 10 questions they actually ask.

This test should happen at the end of every phase:

| Test | Sample size | Pass criterion |
|---|---|---|
| **End of Phase A** | 10 questions, 3 team members | PromoBot wins or ties on ≥5/10 |
| **End of Phase C** | 10 questions, 5 team members | PromoBot wins or ties on ≥7/10 |
| **End of Phase E** | 20 questions, all team | PromoBot wins or ties on ≥14/20 |

**If end-of-Phase-C test passes ≥7/10, ship to production at 55-60% judge.**
The judge metric is engineering rigor; team adoption is product success.

Sample queries to use (real, from team comparison file):
- "אם היית איש קריאייטיב, איך היית פותח את הפרומו של המירוץ העונה החדשה?"
- "מה הטונייט הכי טוב בחתונמי עונה 7?"
- "השווה את אסטרטגיות ההשקה של דרמה לעומת ריאליטי"
- "מה היו כוונות הצפיה של אור ראשון?"
- "מה הסלוגן של גמר נינג'ה עונה 5?"

---

## 6. Pragmatic sequence — what to do this week (REVISED 2026-05-26)

The original Day 1-5 plan put Phase A first. **That was wrong** — the
verification run showed Phase A is chasing noise. Revised sequence:

```
Day 1 (Monday) — STOP CHASING NOISE
  - Read Section 0 (variance verification finding) carefully.
  - Pick 10-15 weak cases from each of: quote, ranking, alias, factual, open_ended.
    Collect real team queries from `Obsidian Vault/שאלה ותשובה של GPT.md` and
    similar files; aim for natural language the team actually uses.
  - Write gold answers in a CONSISTENT style:
      * 2-4 sentences (not 1-sentence haiku, not paragraph)
      * Include the key insight AND a representative number/quote if relevant
      * Match the bot's actual answer style so judge doesn't penalize verbosity

Day 2 (Tuesday) — Phase E.1: dataset expansion  ✅ DONE (May 28)
  - Push the new cases into dataset.jsonl. Target N=10 per category minimum.  ✅ DONE: 62 cases total; strategy=6, open_ended=10, alias=7, ranking=8, numeric=10.
  - Re-run eval on expanded dataset to establish honest new baseline.
  - The macro number may go UP or DOWN — both are signal, both are honest.

Day 3 (Wednesday) — Phase E.2 + Phase B start
  - Adjust LLM judge rubric to be tolerant of length differences.
    Specifically: "score on factual coverage and core insight, not verbosity".
    Add a `reasoning` field to the judge output so failures are diagnosable.
  - Re-run eval. Compare to Day 2 baseline.
  - Begin Phase B (Langfuse observability) — add spans + metadata to run_query.

Day 4 (Thursday) — Phase B complete + Phase C start
  - Finish Phase B: session_id linkage between agent and judge traces.
    Score backfill via langfuse.score().
  - Begin Phase C creative-mode prompt section.

Day 5 (Friday) — Phase C complete + side-by-side
  - Finish Phase C creative-mode + citation rule.
  - Re-eval. Measure against expanded-dataset baseline from Day 3.
  - **First side-by-side test with 3 team members on 10 real questions.**
    This is the ACTUAL success criterion, not judge score.

Phase A.6h, 6f, alias context-fix: deferred. May not happen at all if
Phase B observability reveals the routing isn't actually the bottleneck.
```

**By end of week 1:** realistic target is judge **55-60%** on the EXPANDED
dataset with cleanly-measurable improvements, plus real-user side-by-side
data on whether the bot is ready to ship.

### Why dataset expansion (E) comes before everything else

With ±10pp per-category variance on N=3-8 cases:
- A patch that lifts a category by +5pp can be invisible (noise band)
- A patch that drops a category by -5pp can look catastrophic (noise band)
- We can't reliably measure ANY change at the current dataset size

Expanding to N≥10 narrows the variance band to ~±5pp via central limit theorem.
Suddenly +5pp moves become detectable. **Every patch after Day 2 is measurable.
Every patch before Day 2 is gambling.**

### Why prompt/voice (C) before routing (A)

We confirmed via diagnostics today:
- Bot retrieves the right chunks (id=41 has the correct content)
- Bot synthesizes the right concepts (matches gold semantically)
- Judge marks down for verbosity / phrasing mismatch
- The voice gap (ChatGPT vs PromoBot side-by-side) is the real product gap

Routing fixes target a different problem (cross-show synthesis) that's already
mostly solved by Phase 6c. Diminishing returns there.

---

## 7. Decision points

After Phase C (creative-mode + re-eval + side-by-side):

- **If side-by-side passes ≥7/10:** ship. Move to production hardening. Defer
  remaining phases as iterative improvements.
- **If side-by-side passes 5-6/10:** continue to Phase D/E. The qualitative gap
  is closeable.
- **If side-by-side fails (≤4/10):** the issue is voice/depth, not facts. Move
  to Phase F architectural changes, starting with HyDE or better re-ranker.
  Reconsider model upgrade.

After Phase E (dataset + rubric):

- **If judge ≥ 60% on expanded N=80 dataset:** ship the engineering case.
- **If judge plateaus at 55-58%:** the limit is the LLM. Phase F architectural
  options, GPT-5 test.
- **If judge regresses on expanded dataset:** the current eval was over-fit.
  Embrace the lower honest number; focus on real-user metrics.

---

## 8. What's already done and shipped (status reference)

So the next agent doesn't redo our work:

| Phase | Status | Files |
|---|---|---|
| 1 — show-complete Excel retrieval | DONE | `app/search_word_docs.py` `fetch_show_promos` |
| 1b — `@search.answers` consumption | DONE | `app/search_word_docs.py` |
| 6 — Word semantic chunking | DONE | `scripts/preprocess_word_docs.py` |
| 6b — word-docs schema migration | DONE (May 24) | `scripts/create_word_docs_index.py`, ingest |
| 6c — show_name parser fix (catalog-based) | DONE (May 25) | `scripts/preprocess_word_docs.py`, `app/domain_catalog.py` (+6 shows) |
| Patch A — alias expansion idempotency | DONE (May 24) | `app/domain_catalog.py` `expand_aliases` |
| Patch B — route upgrade unknown/excel_numeric+broad→hybrid | DONE (May 24) | `app/service.py` `_retrieve` |
| Patch C — English-rejection rule scope | DONE (May 24) | `app/system_prompt.txt` |
| Patch D — LLM seed=42 | DONE (May 24) | `app/chat_provider.py` |
| Patch E — groundedness rubric loosened | DONE (May 25) | `tests/eval_dataset.py` `_GROUNDING_MARKERS` |
| Data-health tests | DONE (May 25) | `tests/test_data_health.py` — 27 tests, run with `pytest tests/test_data_health.py -v` |

All of this is verified working — the live index has 0 garbage `show_name`
values, 40/46 catalog shows have matching chunks, and the test suite is the
guardrail. **Do not undo any of this work.** Use it as the foundation.

---

## 9. References

- `docs/eval-improvements.md` — detailed history of every session change with
  judge scores
- `docs/ROADMAP.md` — phase-by-phase status table
- `docs/PROD_READINESS.md` — production hardening items (all done)
- `tests/test_data_health.py` — the regression guardrail
- `tmp_pkg/diag_case.py` — per-case diagnostic
- `tmp_pkg/check_word_show_names.py` — live word-docs metadata audit
- `tmp_pkg/langfuse_scan.py` — Langfuse trace summary (Phase B starter)
- `tmp_pkg/langfuse_find.py` — find a trace by query substring
- `tmp_pkg/rescore_grounded.py` — re-score groundedness against new markers
- User-curated notes in `C:\Users\amit.rosen\Documents\Obsidian Vault\improvement promoagent\`

---

## TL;DR for the next agent (REVISED 2026-05-26)

**The original TL;DR put Phase A first. Read Section 0 — the variance finding
flipped that priority. Below is the corrected guidance.**

1. **READ SECTION 0 FIRST.** The May 24-25 session attributed many "regressions"
   to specific patches that were actually LLM variance on small-N categories.
   Don't repeat that mistake — variance is real and significant on this dataset.

2. **70% on the current 62-case dataset is mathematically uncertain.** Expand
   to N≥10 per category (Phase E) before believing any small-N category move.

3. **The actual priority order (CORRECTED):**
   - **E first**: dataset expansion + judge rubric tweak (1-2 days). Makes
     every future change measurable.
   - **B**: Langfuse observability (4-6 hr). Per-case variance trackable.
   - **C**: Creative-mode prompt (1-2 hr). Real quality lever, closes the
     ChatGPT-vs-PromoBot voice gap.
   - **D**: Content filter mitigation for `הראש` (2-4 hr). Recovers 2-3 cases.
   - **A**: Routing fixes (6h, 6f, alias context-fix). May not even matter —
     diagnostics show retrieval is fine. Last priority.
   - **F**: Architectural (re-ranker, HyDE, query decomp, GPT-5). Only if
     E+B+C+D doesn't reach the side-by-side win threshold.

4. **Use `tests/test_data_health.py`** as the guardrail before/after every
   ingest or catalog change. 27 tests, runs in ~6s, catches data regressions.

5. **Side-by-side test with real users at end of every phase.** The judge is
   a proxy with significant noise; team adoption is the truth.

6. **Trust macro metrics, distrust per-category metrics on small N.** A 5pp
   move on a category with N=3 is statistically meaningless. A 1pp move on
   macro judge across 54 cases IS meaningful.

7. **Don't ship a patch based on a single eval run.** Re-run twice with the
   same code and seed; if scores swing >5pp, that's your noise floor for the
   patch's expected effect.

---

## Appendix — Tools available for the next agent

Built during May 24-26 sessions, all in `tmp_pkg/` or `tests/`:

| Tool | What it does |
|---|---|
| `tests/test_data_health.py` | Catalog + index health guardrails (27 tests, run in 6s) |
| `tmp_pkg/diag_case.py` | Diagnose one eval case end-to-end (`--id N`) |
| `tmp_pkg/check_word_show_names.py` | Audit live word-docs index for garbage show_names |
| `tmp_pkg/check_json_metadata.py` | Audit JSON blobs before ingest |
| `tmp_pkg/find_ungrounded.py` | Find cases marked ungrounded in eval results |
| `tmp_pkg/rescore_grounded.py` | Re-score groundedness against new markers |
| `tmp_pkg/verify_6h_hypothesis.py` | Check what triggers broad_scope for each case |
| `tmp_pkg/compare_runs.py` | Diff two eval_judge_results JSONs for variance verification |
| `tmp_pkg/langfuse_scan.py` | Summary of recent Langfuse traces |
| `tmp_pkg/langfuse_find.py` | Find a Langfuse trace by query substring |
| `tmp_pkg/langfuse_runs_compare.py` | Identify eval runs in Langfuse and compare them |
| `tmp_pkg/eval_run5_backup.json` | The pre-variance-verification eval baseline |

All tools designed to be cheap, fast, and informative. None require running
the full LLM eval.
