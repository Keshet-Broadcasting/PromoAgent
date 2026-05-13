# PromoAgent — Improvement Plan
## Goal: Replace the Custom GPT on OpenAI Subscription

**Written:** May 10, 2026  
**Current judge score:** 37.5% (≈ 2.3 / 5 — "finds topic, gives incomplete answers")  
**Target judge score:** ≥ 70% (≈ 3.5 / 5 — "correct, complete, well-phrased")

---

## 1. Why We Are Far From the Custom GPT

The custom GPT holds the original `.xlsx` and `.docx` files directly in its context window. When asked to rank all seasons of a show, it reads every row. When asked to synthesize insights, it reads the entire document.

Our system is a RAG pipeline over Azure AI Search:

| Layer | Custom GPT | PromoAgent |
|---|---|---|
| Excel data coverage | 100% — full file in context | Top-N semantic hits only |
| Word data coverage | 100% — full document in context | Top-10 semantic chunks |
| Conversation memory | Full thread history | Stateless — each call is independent |
| Retrieval errors | None — no retrieval step | Semantic search can miss exact rows |

This is the fundamental gap. Every other improvement is secondary until data coverage is fixed.

---

## 2. Gap Analysis by Eval Category

Based on `eval_judge_results.json` (26 cases, May 10 run):

| Category | N | Judge score | Primary failure |
|---|---|---|---|
| no_answer | 1 | **75%** ✅ | — |
| numeric | 5 | **50%** | Missing rows; agent gets top-30 of ~100+ per show |
| factual | 4 | **38%** | Chunk retrieval misses the exact quote |
| quote | 3 | **33%** | Fixed-size chunks break multi-paragraph insights |
| open_ended | 6 | **33%** | Limited cross-show synthesis; 10 chunks not enough |
| strategy | 1 | **25%** | Incomplete synthesis; missing cross-show patterns |
| comparison | 1 | **25%** | Comparison needs all values; semantic search misses some |
| ranking | 5 | **30%** | Only 30 of potentially 100+ rows retrieved per show |

---

## 3. Root Cause: Semantic Search Returns Top-N, Not All Rows

`search_excel_promos()` uses `QueryType.SEMANTIC` with `top=30` for ranking queries. For a show like "חתונה ממבט ראשון" with 7 seasons × ~20 episodes = ~140 rows in the `tv-promos` index, this retrieves at most 21% of the show's data.

**The index already has everything we need.** The `show_name` field is defined as:
```python
SearchableField(
    name="show_name",
    type=SearchFieldDataType.String,
    filterable=True,      # ← OData $filter is supported
    retrievable=True,
    analyzer_name="he.microsoft",
)
```

`filterable=True` means we can use `filter="show_name eq 'חתונה ממבט ראשון'"` with `top=500` to retrieve every row for a specific show — guaranteed complete coverage, no semantic cutoff.

---

## 4. Eval Harness Issues Found

### 4.1 Bug: Judge receives raw query, not cleaned query (FIXED)

**File:** `tests/eval_dataset.py`, line 388

**Problem:** The agent is called with `eval_query` (the self-contained, cleaned rephrasing), but the judge was called with `gold.query` (the raw, sometimes context-dependent question). For context-dependent cases like id=3 ("איך זה ביחס לדרמות אחרות. תשווה"), the judge saw a confusing incomplete question while evaluating an agent answer produced from the full rephrasing — artificially penalizing the agent.

**Fix applied:**
```python
# Before (bug):
r.judge_score = score_judge(gold.query, gold_text, answer)

# After (fix):
r.judge_score = score_judge(eval_query, gold_text, answer)
```

This fix alone may improve comparison and context-dependent scores in the next judge run.

### 4.2 Weight scheme is correct but non-obvious

`WEIGHTS` in `eval_dataset.py` are **relative weights**, not percentages. `compute_overall` normalizes by `sum(active_weights)`. This means:
- With judge enabled on a numeric case: judge contributes `0.40 / (0.35 + 0.25 + 0.20 + 0.40)` = **33%** of the overall score
- With judge enabled on a non-numeric case: judge contributes `0.40 / (0.25 + 0.20 + 0.40)` = **47%** of the overall score

This is intentional but should be documented clearly.

### 4.3 Dataset is too small for reliable priorities

With 26 cases, one wrong answer shifts the overall score by ~4%. The category rankings (which type to fix first) can flip from run to run due to LLM non-determinism. Expanding to 50–60 cases is required before trusting category-level conclusions.

### 4.4 Bug: `@search.answers` not consumed — false negatives in word_quote route

**Discovered:** May 12, 2026 — live investigation against `word-docs` index  
**Status:** FIXED (May 12, 2026) — `search_word_docs.py` now promotes `@search.answers` chunks with score >= 0.85; `system_prompt.txt` updated to allow citing cross-show comparative data.

**Problem:**  
When querying the `word-docs` index with `queryType=semantic`, Azure AI Search returns **two ranked lists**:

- `@search.answers` — a semantic answer extraction that pulls the single most directly relevant text span. This is computed by a separate pipeline and is often more accurate than the reranker for specific factual questions.
- `value` — the standard ranked list scored by `@search.rerankerScore`.

The bot's retrieval layer reads **only from `value`** (top-5 by reranker score) and ignores `@search.answers` entirely.

**Concrete example observed:**  
Query: "מה היו התובנות של העונה האחרונה של רוקדים?"  
- `@search.answers[0]` → `chunk_332`, score **0.965**, content: "רוקדים עם כוכבים בעונה הראשונה בקשת — 44% כוונות בשלב הראשון של הקמפיין" ✅ directly answers the question  
- Bot's top-5 from `value` → `chunk_622`, `chunk_247`, `chunk_354`, `chunk_1_21`, `chunk_697_1` — all about MasterChef/הכוכב הבא, zero content about "רוקדים עם כוכבים"  
- Bot conclusion: "No data found for רוקדים עם כוכבים", confidence: **high** ❌ false negative

**Root cause:**  
The reranker ranked `chunk_332` below position 5 in the `value` list for this query, so it was never fed to the LLM. The semantic answer extractor correctly identified it, but its output is discarded.

**Impact:**  
Any `word_quote` or `factual` query where the best answer chunk ranks 6th or lower in the reranker but is surfaced by `@search.answers` will produce a false "no data found" — with **high** confidence, making it actively misleading.

**Fix:** See Phase 1b below.

---

## 5. Implementation Plan

### Phase 1 — Show-Complete Retrieval (2–3 days) ✅ DONE

**Expected judge gain: +15–20% on ranking, +10% on numeric/comparison**

**Problem:** For ranking and comparison questions, the agent retrieves the top-30 semantically similar Excel rows. For shows with many episodes, this misses most of the data.

**Solution:** Add `fetch_show_promos(show_name, top=500)` to `app/search_word_docs.py` using an OData `$filter` on the already-filterable `show_name` field.

```python
# New function in search_word_docs.py
def fetch_show_promos(show_name: str, season: str | None = None, top: int = 500) -> list[dict]:
    """Retrieve ALL promo rows for one show using a filter — bypasses semantic ranking.
    Used when ranking_intent is True and a show name is detected in the query.
    """
    client = _client(_PROMOS_INDEX)
    filter_expr = f"show_name eq '{show_name}'"
    if season:
        filter_expr += f" and season eq '{season}'"
    results = client.search(
        search_text="*",
        filter=filter_expr,
        top=top,
        select=[
            "show_name", "season", "episode_number", "date",
            "promo_text", "opening_point", "rating", "competition",
            "section", "source_file",
        ],
    )
    docs = []
    for r in results:
        docs.append({
            "show_name":      r.get("show_name", ""),
            "season":         r.get("season", ""),
            "episode_number": r.get("episode_number", ""),
            "date":           r.get("date", ""),
            "promo_text":     r.get("promo_text", ""),
            "opening_point":  r.get("opening_point", ""),
            "rating":         r.get("rating", ""),
            "competition":    r.get("competition", ""),
            "section":        r.get("section", ""),
            "tab_name":       r.get("source_file", ""),
            "score":          1.0,  # not semantic — all rows are equally relevant
        })
    return docs
```

**Show name extraction in `service.py`:** Maintain a `_KNOWN_SHOWS` list (official names from the alias table + additional shows known to be in the index). After alias expansion, scan the query for any known show name. When `ranking_intent=True` and a show is detected, call `fetch_show_promos()` instead of `search_excel_promos()`.

```python
_KNOWN_SHOWS = [
    "חתונה ממבט ראשון", "חתונה ממבט שני",
    "המירוץ למיליון", "נינג'ה ישראל",
    "הכוכב הבא", "מאסטר שף",
    "החיים הם תקופה קשה", "יצאת צדיק",
    "אור ראשון", "נוטוק", "הראש", "גוף שלישי", "חולי אהבה", "פאלו אלטו",
    # add more as discovered from the index
]

def _extract_show_name(query: str) -> str | None:
    for show in sorted(_KNOWN_SHOWS, key=len, reverse=True):  # longest match first
        if show in query:
            return show
    return None
```

Then in `_retrieve()`:
```python
if ranking_intent:
    detected_show = _extract_show_name(query)
    if detected_show:
        docs = fetch_show_promos(detected_show, top=500)
    else:
        docs = search_excel_promos(query, top=30)  # fallback
```

**Validation:** Run eval on ranking cases (ids 13–15, 17, 22) before and after. Expected: judge 30% → 50%+.

---

### Phase 2 — Fix Eval: Judge Uses Cleaned Query (30 minutes) ✅ DONE

**Fix applied May 10, 2026.** The judge now receives `eval_query` (the cleaned, self-contained question) instead of `gold.query`. This ensures the judge evaluates the agent on the same question the agent actually answered.

**Next step:** Re-run judge eval to get updated comparison scores.

---

### Phase 1b — Consume `@search.answers` in Word Doc Retrieval (2–3 hours) ✅ DONE

**Expected judge gain: +5–10% on quote and factual**

**Problem:** See bug 4.4. The retrieval layer for Word documents ignores the `@search.answers` field returned by Azure AI Search's semantic pipeline, causing high-confidence false negatives when the best answer chunk doesn't rank in the top-5 by reranker score.

**Fix:** In `app/search_word_docs.py`, after receiving the search response, extract `@search.answers` and inject those chunks at the front of the context list, deduplicating against the `value` results.

```python
def search_word_docs(query: str, top: int = 5) -> list[dict]:
    response = client.search(
        search_text=query,
        query_type=QueryType.SEMANTIC,
        semantic_configuration_name="word-docs-semantic-config",
        query_caption=QueryCaptionType.EXTRACTIVE,
        query_answer=QueryAnswerType.EXTRACTIVE,   # ← must be enabled
        query_answer_count=3,
        top=top,
    )

    # Collect semantic answers first — these are highest-confidence hits
    answer_chunk_ids: set[str] = set()
    priority_docs: list[dict] = []
    for answer in (response.get_answers() or []):
        if answer.score >= 0.85:                   # only high-confidence answers
            answer_chunk_ids.add(answer.key)
            priority_docs.append({
                "chunk_id": answer.key,
                "chunk": answer.text,
                "score": answer.score,
                "source": "semantic_answer",
                # title/header filled in from value results below if available
            })

    # Add remaining value results, skipping chunks already in priority_docs
    value_docs: list[dict] = []
    for r in response:
        if r["chunk_id"] not in answer_chunk_ids:
            value_docs.append(_to_doc(r))

    # Semantic answers lead; value results fill remaining slots
    return (priority_docs + value_docs)[:top]
```

**Also fix confidence signalling:** When the agent concludes "no data found", that answer should never be `"confidence": "high"` if the underlying index has > 0 results (i.e., `@odata.count > 0`). Add a guard in `app/service.py`:

```python
if not docs and search_meta.get("total_count", 0) > 0:
    confidence = "medium"   # index has docs — retrieval may have missed something
```

**Validation:** Re-run the query "מה היו התובנות של העונה האחרונה של רוקדים?" and verify `chunk_332` appears in sources and the answer quotes the 44% intentions data.

---

### Phase 3 — Few-Shot Examples in System Prompt (4 hours) ⭐⭐

**Expected judge gain: +5–10% across all categories**

The LLM judge penalizes format mismatches even when content is correct. If the gold answer is a numbered ranked list and the agent returns prose, the judge scores it 2/5 even if the facts match.

Add one gold-standard example per mode directly in `app/system_prompt.txt`:

- **Ranking mode example:** Full numbered list with values, winner first, insight at end, source cited
- **Strategy mode example:** Numbered points, grounded claims, creative copy marked explicitly, strong closing recommendation
- **Quote mode example:** Full verbatim quote in quotes, document title, section header

These examples anchor the LLM's output format to what the judge expects.

---

### Phase 4 — Conversation Memory (3–5 days) ⭐⭐

**Expected impact:** Enables natural multi-turn Q&A — the primary UX gap vs. custom GPT

The custom GPT maintains a conversation thread. Our API is stateless — every question is answered from zero context. This forces users to write fully self-contained questions, which is unnatural.

**Implementation:**

1. Add `session_id: str | None` field to the `QueryRequest` Pydantic model in `app/models.py`
2. Add an in-memory session store in `app/api.py`: `_sessions: dict[str, list[dict]] = {}`
3. On each request, load the last 5 messages for the `session_id`, append them to the messages list before the LLM call, then save the new exchange
4. Return the `session_id` in the `QueryResponse` so the UI/client can persist it
5. Update `app/prompts.py` to prepend conversation history to the messages list

This directly enables the follow-up pattern the promo team uses (e.g., "and what about season 3?" after a season 5 question) without needing to manually rephrase every question.

---

### Phase 5 — Expand Eval Dataset (1–2 days) ⭐⭐

**Expected impact:** Reliable metrics — category scores become trustworthy

With 26 cases and 8 categories, the ranking/strategy/comparison categories have 1–5 cases each. A single LLM variance event changes category scores by 20–50%. Priorities based on these scores are unreliable.

**Target:** 50–60 total cases covering:
- 8–10 numeric cases (currently 5)
- 8–10 ranking cases (currently 5)
- 6–8 factual cases (currently 4)
- 6–8 quote cases (currently 3)
- 8–10 open_ended cases (currently 6)
- 4–5 strategy cases (currently 1)
- 4–5 comparison cases (currently 1)
- 3–4 no_answer cases (currently 1)

**Source:** Real questions and answers from `feedback from promo team.md`, plus adversarial cases (questions about shows not in the index, ambiguous season references) to test refusal.

**Format:** Each new case needs `query`, `cleaned_query`, `answer`, `cleaned_answer`, `category`, `answerable`, `has_numeric_data`, `source_hint`.

---

### Phase 6 — Word Document Semantic Chunking (1 week) ⭐

**Expected judge gain: +5–10% on quote and factual**

Current indexing in `scripts/ingest_word_chunks.py` uses fixed-size token chunking. A multi-paragraph insight section like "תובנות מהקמפיין" can be split across 2 chunks, so the LLM only sees the setup without the conclusion, or vice versa.

**Solution:** Update `scripts/ingest_word_chunks.py` to split on Hebrew semantic boundaries:
- **Primary split points:** Bold headings, section dividers, Hebrew keywords: `תובנות`, `אסטרטגיה`, `גמר`, `השקה`, `מסקנה`, `המלצות`
- **Minimum chunk size:** 3 sentences
- **Maximum chunk size:** 600 tokens  
- **Overlap:** 1 sentence between adjacent chunks

This requires re-ingesting all Word documents into the `word-docs` index. No schema change needed — only the chunk content changes.

---

### Phase 7 — Model Verification (1 hour) ⭐

**Expected judge gain: +10–15% for free if not on GPT-4o**

The custom GPT explicitly uses GPT-4o, which excels at Hebrew. If the Azure Foundry deployment uses an older or smaller model, upgrading would be the highest-ROI change available.

**Check the current deployment:**
```powershell
az cognitiveservices account deployment list `
  --name Keshet-Foundry `
  --resource-group <resource-group-name> `
  --output table
```

If not GPT-4o, switch to it in the Foundry deployment settings.

---

### Phase 8 — UI Parity with Custom GPT (1 week) ⭐

**Expected impact:** UX — makes the tool feel as natural as the OpenAI interface

Key gaps in `promobot-ui` compared to the custom GPT experience:

1. **Streaming responses** — show text as it's generated, not all at once after 7s
2. **Conversation threads** — persistent sidebar with named chats (not single-question mode)
3. **Source document preview** — click a source citation to see the relevant chunk
4. **Mobile-friendly layout** — custom GPT is accessible from phone; unclear if current UI is
5. **Copy / share button** — one-click to copy the answer or share a permalink

---

## 6. Expected Score Trajectory

| After phase | Change | Estimated judge score |
|---|---|---|
| **Baseline** (May 10) | — | **37.5%** |
| Phase 1 + 2 (show-complete retrieval + judge fix) | Data coverage fixed | **~52–55%** |
| Phase 1 + 1b + 2 (+ semantic answers fix) | Eliminates false negatives in word_quote | **~55–58%** |
| Phase 1–3 (+ few-shot examples) | Format alignment | **~60–64%** |
| Phase 1–4 (+ conversation memory) | UX parity | **~60–65%** |
| Phase 1–5 (+ 50+ eval cases) | Reliable measurement | **~60–65% (reliable)** |
| Phase 1–7 (+ chunking + model) | Full quality stack | **~70–75%** |

At **70% judge score** (≈ 3.5/5 average), the agent gives correct and complete answers with minor omissions. This is the threshold where the promo team would realistically consider switching from the custom GPT.

---

## 7. What Is NOT in This Plan

These were considered and explicitly deferred:

| Item | Why deferred |
|---|---|
| Loading Excel files from Blob Storage | Not needed — data is already indexed in `tv-promos`. The filter-based `fetch_show_promos()` achieves the same result within the existing architecture. |
| Re-indexing Excel data | Current `show_name`/`season` schema is already correct and filterable. No schema change needed for Phase 1. |
| Changing the query router | Current routing is correct. The gap is in retrieval depth, not routing. |
| Adding new data sources | After Phase 1, assess if coverage is the remaining gap. Premature without first fixing retrieval. |

---

## 8. Execution Order

```
Week 1:  Phase 1 (fetch_show_promos) + Phase 1b (@search.answers fix) + Phase 3 (few-shot examples)
         → Re-run judge eval to validate +15–20% gain

Week 2:  Phase 4 (conversation memory) + Phase 5 (expand dataset)
         → Validate multi-turn behavior with promo team

Week 3:  Phase 6 (re-chunking Word docs) + Phase 7 (model check)
         → Re-run judge eval, target 70%

Week 4+: Phase 8 (UI parity) + promo team user testing
         → Decision point: ready to replace custom GPT?
```
