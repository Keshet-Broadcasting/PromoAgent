# Session Findings & Fixes — 2026-06-03

**Author:** Claude (pairing session with Amit)
**Scope:** Root-caused and fixed a prod bug where a **drama-only** strategy question pulled
in **reality-show** content and got cut off mid-sentence. Source: the team's GPT-vs-PromoBot
comparison (`Obsidian Vault/improvement promoagent/GPT vs promobot.md`).

---

## 0. TL;DR

A promo-team question — *"summarize the insights from drama series with high seasonal
ratings and give the main solutions"* (no specific show named) — produced an answer that
(a) cited **reality** shows (מאסטר שף, חתונה ממבט ראשון) in a **drama** question, and
(b) was **truncated mid-sentence**. The Gemini judge flagged the genre mixing as the main
failure vs the Custom GPT.

Three root causes, all confirmed against Langfuse trace `303da7b75245ec4b04e3fddd683e9f35`
and the code. Two code fixes + one config flag. Verified by re-running the exact question.

---

## 1. Root causes

### 1.1 Genre contamination (PRIMARY) — `BROAD_RETRIEVAL_ENABLED` was off
The planner correctly classified the query as `genres=['drama']`, `broad_scope=True`,
`route=hybrid`. The drama-only show filter **exists** (`_RetrievalPlan.target_show_names` →
`shows_for_genres(['drama'])`, 17 drama shows), but it is gated behind the `broad_word` /
`broad_excel` properties, which require `_BROAD_RETRIEVAL` (`BROAD_RETRIEVAL_ENABLED`).

That flag was **not present in `.env`** (only `false` in `.env.example`; forced `true` only
in one test) → it defaulted to **off**. With it off, the broad path never ran, no `show_names`
filter was passed, and `search_word_docs()` did an **unfiltered** semantic search across all
4 GPT docs — so chunks from `מסמך ריאליטי GPT.docx` (reality) leaked into a drama question.
Excel was unfiltered too.

> Note: the roadmap marks broad retrieval "DONE (May 24, +2.4% judge)". The flag was most
> likely lost when `.env` was regenerated from `.env.example`. Because `.env` is gitignored,
> the loss left no git trace.

### 1.2 Answer truncation — `MAX_ANSWER_TOKENS=1000` shared with `<thinking>`
The system prompt mandates a `<thinking>` block emitted **before** the visible answer
(`system_prompt.txt`). Both share the `max_tokens` budget. A 6-section cross-show synthesis +
thinking exceeded 1000 tokens → `finish_reason=length` → answer cut at "· חושך. · קול".

### 1.3 Thin retrieval for synthesis questions — `strategic_intent` miss
`word_top` only rises to 12 when `strategic_intent` matches, but its regex
(`מה הייתי|מה היית|תמליץ|הצע|מה כדאי|כיצד הייתי|תחשוב מה`) did **not** match summarization
phrasing ("סכם את כל התובנות… והבא את הפתרונות"). The query got `word_top=6`.

---

## 2. Fixes applied

| Cause | Fix | File |
|---|---|---|
| 1.1 | `BROAD_RETRIEVAL_ENABLED=true` (added to `.env`) — activates the existing, tested drama-genre show filter for Word + Excel | `.env` (local) |
| 1.2 | `MAX_ANSWER_TOKENS` default **1000 → 1800** (shared with `<thinking>`) | `app/chat_provider.py` |
| 1.3 | Extended `strategic_intent` with synthesis triggers: `סכם`, `תובנות`, `פתרונות`, `דפוסים`, `מאפיין(ים)` → `word_top=12` | `app/service.py` |

---

## 3. Verification (re-ran the exact question)

**Before** (prod trace): `route=hybrid`, word docs from the reality doc, answer cites מאסטר שף
/ חתונמי, cut off mid-sentence.

**After** (local, flag on + both edits):
- `broad show-filter fetch: 17 show(s) → 140 doc(s)` — Excel filtered to drama shows.
- `Word hits: 5`, **all from `מסמך דרמות GPT.docx`** (the drama doc). Zero reality-doc chunks.
- Programmatic leak-check for `מאסטר שף / חתונמי / רוקדים / הזמר במסכה` → **none**.
- Answer ends with a complete `### מסקנה אסטרטגית` paragraph (no truncation). Examples cited:
  בקרוב אצלי, אף אחד לא עוזב את פאלו אלטו, חולי אהבה, להיות איתה, הראש — all dramas.

> On this query `word_top=12` did not increase hits (stayed 5): the binding constraint is the
> `show_names`+`doc_types`+`question_types` filter intersection, not top-k. The
> `strategic_intent` change still helps queries where top-k is the limiter; harmless here.

**Guard eval** (`--judge --only 45,46,12,43,5,34,41`, 7 cases, 0 errors):
Overall 51.2% · Judge 46.4% · Groundedness 85.7% · **Refusal 100%**. Within the documented
~45–49% noise band; refusal/no_answer path intact. Confirms **no regression** (small-N, so
not a measurable gain). `tests/test_retrieval_planning.py` 9/9 pass.

---

## 4. Action items

### P0 — make the fix reach production
- **Set `BROAD_RETRIEVAL_ENABLED=true` on the prod Container App** env vars. `.env` is local
  only; the live bug persists until this is set in prod. (Also confirm
  `WORD_METADATA_FILTERS_ENABLED=true` is set in prod — it must be on for the filter to apply.)
- Add `BROAD_RETRIEVAL_ENABLED=true` to the deployment/IaC so it can't silently drop again.

### P1 — guard against recurrence
- Consider a startup log line when `BROAD_RETRIEVAL_ENABLED=false` so a missing flag is
  visible, since this is a high-impact, easily-lost setting.

### Note
- This bug is the genre-filter capability (Phase 6b/BR) being **dormant due to a missing
  flag**, not a logic error — the filtering code was already correct and tested.
