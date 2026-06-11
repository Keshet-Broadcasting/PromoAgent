# 2026-06-11 — Strategic Synthesis rebuild, judge 58.1% (all-time high), and the model-ceiling evidence

**TL;DR:** A side-by-side comparison against the promo team's Custom GPT exposed a routing
desync: synthesis questions ("סכם את התובנות... והבא פתרונות") got WIDE retrieval but were
answered in Coverage/summary style because the prompt-level Strategic Synthesis Mode never
fired. Fixing that (plus thesis-first structure and `MAX_ANSWER_TOKENS` 1800→3000) took the
full-62 judge from ~49% to **58.1%** — past the previous ~50-55% ceiling estimate. The
remaining gap to the Custom GPT is **model-tier, with Langfuse receipts**: gpt-4o ignores
in-context counter-evidence and drops outcome numbers from synthesis answers even under
explicit, exampled instructions.

---

## 1. The diagnosis — bot vs Custom GPT ("קורל")

Comparison source: Amit's Obsidian note with both bots' answers to the live-viewing drama
question, plus a Gemini-authored critique. Root causes traced to the repo:

1. **Trigger desync (the big one).** `_STRATEGIC_INTENT_PATTERNS` (service.py) was widened
   on 2026-06-03 to include סכם/תובנות/פתרונות — but the prompt's Strategic Synthesis Mode
   trigger list still contained only recommendation phrasing (מה הייתי/תמליץ/הצע). Result:
   the model received 12 wide chunks and summarized them as an analyst. Worse, Coverage
   Mode's "Quote, don't synthesize" rule explicitly FORBADE the cross-show themes (FOMO,
   רגש) that made the Custom GPT's answer good.
2. **Data-first mandate vs thesis-first.** Three prompt locations pushed raw data before
   conclusions; the Custom GPT opens with the thesis and uses data as proof.
3. **Token cap.** 1800 shared with `<thinking>` could not hold a קורל-length answer.
4. **The Custom GPT's instructions contain NO strategist prompting.** Its instruction file
   (Amit's vault: "ChatBot Instructions.md") is pure data-discipline — wide search,
   double-check, cite sheet, full quotes — most of which our prompt already had verbatim.
   Its strategist voice = frontier base model + full documents in context. Nothing to copy.

## 2. What changed (prompt v1→v3, all in `app/system_prompt.txt`)

- **v1:** Strategic Synthesis Mode now fires on BOTH trigger families (recommendation +
  synthesis phrasing); precedence rule over Coverage Mode (mirrored in Coverage Mode item 6);
  thesis-first ("the Why", funnel runs inside `<thinking>`, visible answer in REVERSE);
  merged insight+solution action principles (kills the תובנות/פתרונות duplication);
  transferable-principle extraction; counter-example contrast; premise-challenging.
  Plus: `MAX_ANSWER_TOKENS` 1800→3000 (`chat_provider.py`), sync comment in `service.py`,
  regression test `test_strategic_mode_prompt_triggers_match_retrieval_triggers`
  (tests/test_retrieval_planning.py) enforcing prompt↔regex alignment.
- **v2:** "Let the documents overrule your promo instincts" (mandatory `<thinking>`
  counter-evidence check) + "Concrete Specifics Rule applies in Strategic Synthesis Mode".
- **v3:** verbatim-slogan + every-outcome-number completeness check; **inline citations
  required in strategic answers** — fixed a v2 regression where the storyboard ending made
  the model treat answers as Creative Mode and skip citations (GND 1→0→1 on id=56).

## 3. Results

| Run | Scope | Overall | Judge | Notes |
|---|---|---|---|---|
| Morning full (prompt-v1) | 62 cases | **57.0%** | **58.1%** | All-time high; +9pp judge vs Run 8 |
| Guard (prompt-v3) | 20 strategic-adjacent | 52.9% | 57.5% | strategy 46→51, open_ended 50→52, cross_show 61→58 (noise); v3 kept |

Cost/latency via Langfuse API: full run = 124 traces, **$2.11**, avg 9.7s, zero answers near
the 3000 cap (max 1428). One outlier flagged for follow-up: a ranking+strategy hybrid
question pushed **45k input tokens** (fetches every promo row for the show).

## 4. The model-ceiling evidence (most important finding)

Custom GPT cross-check of 4 weak cases (Amit pasted answers back):

- **id=26 (pregnancy campaign):** GPT agrees with gold (emotional payoff, NOT a promo hook).
  Langfuse trace shows our context HAD the evidence ("כיף מנצח רגש סנטימנטלי", the anti-scoop
  warning, the Mindy precedent) — gpt-4o still recommended teaser-mystery hype, through TWO
  rounds of explicit prompt instructions (second round made it worse: judge 0.50→0.25).
- **id=56 (Shmela campaign):** slogan, Kobe-poster, "18.5" were ALL in context; gpt-4o
  paraphrased the slogan and never produced the number, despite an instruction containing
  the literal example "18.5%". (v3 did recover poster/learnings content + citation: 0.50→0.52.)
- **id=46 (low-rating season):** the Custom GPT ALSO missed the gold's נינג'ה-עונה-5 anchor →
  **gold too narrow, fix the gold**, then `--rejudge --only 46`.
- **id=57 (do/don't list):** GPT synthesized its own list, didn't match gold either →
  gold likely anchored to one of several lists in the corpus; re-anchor or loosen.

**Conclusion:** "retrieval miss" was disproven twice by reading the GENERATION observation
input via the Langfuse API (PowerShell `Invoke-RestMethod`, basic auth — no truststore needed
outside Python). The failures are composition-level and resistant to prompting on gpt-4o.
**Next experiment: stronger Foundry deployment, A/B on the 20 strategic-adjacent cases —
not more prompt surgery.** Amit is provisioning the model; an expanded ~200-question dataset
is planned for the next evaluation round.

## 5. Gemini 2.5 Flash A/B — parked, with blockers documented

- Run completed (62 cases, no judge): numeric 49.8%/grounded 91.9% beat gpt-4o; strategy 41%
  and cross_show 41% worse. Avg latency similar (10.5s).
- **Blocker 1 — thinking leak:** 15/62 answers leak chain-of-thought (bare `thinking\n`
  prefix or unclosed `<thinking>`), evading `re.sub(r'<thinking>.*?</thinking>')` in
  service.py (~line 1393). Needs strip hardening + suppressing the prompt-CoT for Gemini
  (2.5 models think natively).
- **Blocker 2 — judge coupling:** `score_judge()` uses `get_provider()` — same provider as
  the agent. Fair A/B = generate with new provider WITHOUT `--judge`, then `--rejudge` under
  the default provider. Caches preserved: `eval_answers_cache.gpt4o-2026-06-11.json` (active
  copy restored) and `eval_answers_cache.gemini-2.5-flash-2026-06-11.json`.
- Also fixed: `slowapi` was missing from the venv (in requirements.txt), which failed 13
  offline tests; stale `MAX_ANSWER_TOKENS` docs in api.py/README corrected.

## 6. Follow-ups

1. Stronger Foundry deployment A/B on ids 4,12,16,19,23,24,26,30,31,32,43,45,46,52,55,56,57,58,59,61 (~$1).
2. Fix golds for 46 + 57 → `--rejudge --only 46,57` (≈free).
3. Gemini leak fix if the Gemini option stays alive after the stronger-model test.
4. 45k-token context outlier on ranking+strategy hybrids (spawned as separate task).
5. Expanded ~200-question dataset (Amit/team) → re-baseline.
6. The REAL test per team docs: side-by-side blind test with the promo team vs the Custom GPT.
