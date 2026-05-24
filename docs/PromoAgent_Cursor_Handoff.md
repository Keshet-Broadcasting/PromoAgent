# PromoAgent — SharePoint Integration: Cursor Engineering Handoff
**תאריך:** 20.05.2026  
**מסמך:** Operationalized Cursor brief — Phase 1 MVP

---

## A. Revised Diagnosis

The root cause is a **trigger mismatch**: SharePoint fires only on total Azure failure (`excel_docs == [] AND word_docs == []`), but the queries that need SharePoint most — `word_quote` routes asking for strategy, campaign insights, and תובנות — almost always get *something* back from Azure (even a low-relevance chunk), which silences the fallback.

The current implementation is structurally inverted: it treats SharePoint as a last resort when Azure completely fails, but SharePoint's value is precisely as a *confidence booster* when Azure returns something but it's not good enough. 

The fix is to change the trigger from **absence of Azure results** to **insufficiency of Azure results**, using the best available semantic signal — the `@search.answers` caption quality + reranker score — rather than a binary empty/non-empty check.

---

## B. Recommended MVP Trigger — Decision Table

> **Signal hierarchy (best to worst):**
> 1. `@search.answers` caption populated + score ≥ 0.85 → Azure is confident, **skip SP**
> 2. Reranker score (`d.get("score")`) < 0.70 with no caption → Azure is uncertain, **trigger SP enrichment**
> 3. word_docs empty entirely → **trigger SP enrichment** (stronger case than low score)
> 4. Show name detected in query but NOT in `_KNOWN_SHOWS` → **trigger SP discovery**
> 5. excel_numeric route → **never trigger SP** (SP has no numeric data)

> **Note on raw score vs. semantic signal:**
> Azure AI Search with semantic ranking returns a *reranker score* (0–4 scale, normalized to 0–1 in most SDK wrappers). If `search.get_answers` is enabled, the `caption` field is only populated when the model is confident. This makes caption presence the **best available signal** for high confidence. Raw score alone is a fallback when no caption is returned.

| Route | Azure Caption | Azure Top Score | Show in Known | Action | Reason |
|-------|--------------|-----------------|---------------|--------|--------|
| `excel_numeric` | any | any | any | ❌ Skip SP | SP has no numeric data |
| `word_quote` | populated | ≥ 0.85 | any | ❌ Skip SP | Azure confident |
| `word_quote` | empty | ≥ 0.85 | any | ⚠️ Skip SP (for now) | Score good, no caption — monitor |
| `word_quote` | empty / any | < 0.70 | any | ✅ SP Enrichment | Low confidence |
| `word_quote` | any | any | ✗ not found | ✅ SP Discovery | New show, not in index |
| `word_quote` | any | any | n/a (0 docs) | ✅ SP Enrichment | Zero word results |
| `hybrid` | populated | ≥ 0.85 | any | ❌ Skip SP | Azure word confident |
| `hybrid` | empty / any | < 0.70 | any | ✅ SP Enrichment | Word side weak |
| `unknown` | any | any | any | ❌ Keep existing fallback | No change |

**Trigger types distinguished:**

| Type | When | Folder hint |
|------|------|-------------|
| Zero-result fallback | `word_docs == []` | detected show name, else `עבודה ChatGPT` |
| Low-confidence enrichment | top score < 0.70 AND no caption | detected show name, else root |
| New-show discovery | show extracted but not in `_KNOWN_SHOWS` | show name as folder |
| Freshness-driven | *Deferred to Phase 2* — requires SP catalog sync | n/a |

---

## C. Cursor Planning Brief

**Before writing a single line of code, Cursor must:**

### Files to inspect first (in this order)
1. `app/service.py` — understand `_is_context_insufficient()`, `_fetch_sharepoint_fallback()`, `_retrieve()`, `_RetrievalResult`, `_KNOWN_SHOWS`
2. `app/tools/sharepoint_tool.py` — understand `search_in_library()`, KQL path construction, auth model
3. `app/search_word_docs.py` — understand what fields are returned in word-doc results, specifically: is `caption` / `@search.answers` text already included? What key does it come back under?
4. `app/query_router.py` — understand the 4 routes and their keywords
5. `tests/test_agent.py` — understand what tests exist and what must not break

### Assumptions to verify before coding
- [ ] What key does the Azure word-doc result use for the semantic caption? (`caption`? `@search.reranker_score`? Check `search_word_docs.py` return dict structure)
- [ ] Is `@search.answers` currently enabled in the Azure Search query in `search_word_docs.py`?
- [ ] What is the actual score range returned? (0–1? 0–4? Normalized?)
- [ ] Does `sharepoint_tool.py` work with `AzureCliCredential` in the Container App environment, or does it need `ManagedIdentityCredential`?
- [ ] Is `SP_SITE_URL` currently set in `.env` for the test environment?
- [ ] Are Hebrew folder path names URL-safe in the KQL `path:` filter as-is, or do they need encoding?

### Existing functions to trace
- `_is_context_insufficient(retrieval)` → understand current trigger logic (too conservative)
- `_fetch_sharepoint_fallback(query, top)` → will be replaced/extended, not deleted
- `_retrieve(route, query)` → this is where the enrichment call must be inserted
- `_extract_show_name(query)` → already extracts show from query — reuse for folder hint
- `_fmt_sharepoint(docs)` → already exists for formatting SP results

### What must remain UNCHANGED
- All 4 routing paths in `_retrieve()`: `excel_numeric`, `word_quote`, `hybrid`, `unknown`
- The existing `_fetch_sharepoint_fallback()` function and its call in `run_query()` (zero-result fallback path stays as-is)
- All Pydantic models in `models.py`
- `api.py` endpoints and response contract
- `query_router.py` — no changes
- `prompts.py` — no changes
- `tests/test_agent.py` existing test cases — must all pass

### What should be feature-flagged
- `SP_ENRICHMENT_ENABLED` — the entire new enrichment path
- `SP_SCORE_THRESHOLD` — the trigger threshold (tunable without code change)
- Everything new defaults to OFF

### Test coverage to preserve
- All existing `pytest tests/` must pass with `SP_ENRICHMENT_ENABLED=false` (default)
- New code must be tested with mocked SP client, not live SP calls

---

## D. MVP Implementation Scope

### In scope for MVP
- Add `folder_path` parameter to `sharepoint_tool.search_in_library()` for targeted search
- Add `_needs_sharepoint_enrichment()` decision function in `service.py`
- Add `_fetch_sharepoint_enrichment()` in `service.py` (distinct from existing fallback)
- Call enrichment inside `_retrieve()` for `word_quote` and `hybrid` routes only
- Feature flag `SP_ENRICHMENT_ENABLED` + `SP_SCORE_THRESHOLD`
- Add file extension filter to SP query (exclude jpg, png, mp4, lnk)
- 2 new unit tests (mocked)
- Update `.env.example`

### Out of scope for MVP
- Async/parallel SharePoint calls (synchronous is fine for MVP)
- New-show discovery via SP (defer — needs separate handling)
- Freshness-driven enrichment (defer — requires catalog sync)
- `פעם בחודש` pptx indexing
- Any changes to Azure index schema
- Any changes to `query_router.py`
- UI changes

### Deferred to Phase 2
- Periodic sync of `עבודה ChatGPT` → Azure word-docs index (highest ROI, zero runtime latency)
- Async parallel Azure + SP retrieval
- SP-based new-show discovery (expand `_KNOWN_SHOWS` automatically)
- Catalog endpoint: pre-built show → SP folder path map

---

## E. File-by-File Change Plan

### 1. `app/tools/sharepoint_tool.py` — minor extension

**Purpose:** Add folder scoping and file-type filtering to KQL query.

**Changes:**
```python
def search_in_library(
    self,
    query: str,
    library: str | None = None,
    top: int = 5,
    folder_path: str | None = None,       # NEW: scope to subfolder
    file_types: list[str] | None = None,  # NEW: e.g. ["docx", "xlsx"]
) -> list[dict]:
    lib = library or _DOC_LIBRARY
    # Use folder_path to scope the KQL path filter
    if folder_path:
        scope_path = f"{_SITE_URL}/{lib}/{folder_path}"
    else:
        scope_path = f"{_SITE_URL}/{lib}"
    
    # Build type filter
    type_filter = ""
    if file_types:
        parts = " OR ".join(f"FileExtension:{ext}" for ext in file_types)
        type_filter = f" ({parts})"
    
    querytext = f'{query} path:"{scope_path}"{type_filter}'
    ...
```

**Risk:** Hebrew folder names in KQL path — test first. If encoding is needed, use `urllib.parse.quote(folder_path, safe='/')`.

### 2. `app/service.py` — core enrichment logic

**Purpose:** Add score-gated enrichment path for word_quote/hybrid routes.

**Add near top (after existing SP imports):**
```python
_SP_ENRICHMENT = os.getenv("SP_ENRICHMENT_ENABLED", "false").lower() == "true"
_SP_SCORE_THRESHOLD = float(os.getenv("SP_SCORE_THRESHOLD", "0.70"))
_SP_ENRICHMENT_TOP = int(os.getenv("SP_ENRICHMENT_TOP", "3"))
_SP_ALLOWED_EXTENSIONS = ["docx", "xlsx", "pdf"]
```

**Add new function `_needs_sharepoint_enrichment()`:**
```python
def _needs_sharepoint_enrichment(
    route: str,
    word_docs: list[dict],
) -> bool:
    """Return True when SP enrichment should run for this query."""
    if not _SP_ENRICHMENT or not _SP_AVAILABLE:
        return False
    if route not in ("word_quote", "hybrid"):
        return False
    # Zero word results — definitely enrich
    if not word_docs:
        return True
    # Caption present + high score → Azure is confident → skip
    top_doc = word_docs[0]
    caption = (top_doc.get("caption") or "").strip()
    top_score = float(top_doc.get("score") or 0)
    if caption and top_score >= _SP_SCORE_THRESHOLD:
        return False
    # Low score or no caption → enrich
    return top_score < _SP_SCORE_THRESHOLD
```

**Add new function `_fetch_sharepoint_enrichment()`:**
```python
def _fetch_sharepoint_enrichment(
    query: str,
    show_name: str | None,
    top: int = _SP_ENRICHMENT_TOP,
) -> list[dict]:
    """Targeted SP enrichment — scoped to show folder. Never raises."""
    if not _SP_AVAILABLE:
        return []
    folder = show_name if show_name else "עבודה ChatGPT"
    try:
        client = _get_sp_client()
        return client.search_in_library(
            query,
            folder_path=folder,
            top=top,
            file_types=_SP_ALLOWED_EXTENSIONS,
        )
    except EnvironmentError:
        log.debug("SP enrichment skipped: credentials not configured")
        return []
    except Exception as exc:
        log.warning("SP enrichment failed: %s", exc)
        return []
```

**Modify `_retrieve()` — add enrichment call at end of word_quote and hybrid paths:**

In the `word_quote` branch, after `docs = search_word_docs(...)`:
```python
    if route == "word_quote":
        docs = search_word_docs(query, top=word_top)
        ...
        # NEW: SharePoint enrichment for low-confidence word results
        show_name = _extract_show_name(question)  # pass question, not route
        if _needs_sharepoint_enrichment(route, docs):
            log.info("  SP enrichment triggered: route=%s score_below_threshold", route)
            sp_docs = _fetch_sharepoint_enrichment(question, show_name)
            if sp_docs:
                sp_section = "\n\n=== מסמכי SharePoint (תובנות ומחקר) ===\n\n" + _fmt_sharepoint(sp_docs)
                return _RetrievalResult(
                    context=_fmt_word(docs) + sp_section,
                    word_docs=docs,
                    sharepoint_docs=sp_docs,
                )
        return _RetrievalResult(context=_fmt_word(docs), word_docs=docs)
```

> **Note:** `_retrieve()` currently receives `query` (already alias-expanded). But `_extract_show_name` needs `question` — confirm that `question` is in scope at the call site. In the current `_retrieve(route, query)` signature, the alias-expanded query is passed as `query`. Pass it to `_extract_show_name`.

### 3. `.env.example` — add 3 new vars

```env
# SharePoint enrichment (Phase 1 — disabled by default)
SP_ENRICHMENT_ENABLED=false
SP_SCORE_THRESHOLD=0.70
SP_ENRICHMENT_TOP=3
```

### 4. `tests/test_agent.py` — add 2 new tests (mocked)

```python
def test_sp_enrichment_disabled_by_default(monkeypatch):
    """SP enrichment must not fire when SP_ENRICHMENT_ENABLED is not set."""
    monkeypatch.delenv("SP_ENRICHMENT_ENABLED", raising=False)
    from app.service import _needs_sharepoint_enrichment
    assert _needs_sharepoint_enrichment("word_quote", []) is False

def test_sp_enrichment_fires_on_low_score(monkeypatch):
    """Enrichment fires when word_docs score is below threshold."""
    monkeypatch.setenv("SP_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("SP_SCORE_THRESHOLD", "0.70")
    from importlib import reload
    import app.service as svc
    reload(svc)
    low_score_doc = {"title": "test", "score": 0.55, "caption": ""}
    assert svc._needs_sharepoint_enrichment("word_quote", [low_score_doc]) is True

def test_sp_enrichment_skipped_on_high_caption(monkeypatch):
    """Enrichment skipped when Azure returns caption + high score."""
    monkeypatch.setenv("SP_ENRICHMENT_ENABLED", "true")
    from importlib import reload
    import app.service as svc
    reload(svc)
    high_conf_doc = {"title": "test", "score": 0.90, "caption": "תוכן רלוונטי"}
    assert svc._needs_sharepoint_enrichment("word_quote", [high_conf_doc]) is False
```

---

## F. Minimal JSON Contracts

### F1. Planner Output (internal log struct, not exposed to API)

```json
{
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "route": "word_quote",
  "detected_show": "חתונה ממבט ראשון",
  "azure_word_doc_count": 3,
  "azure_top_score": 0.61,
  "azure_caption_present": false,
  "sp_enrichment_triggered": true,
  "sp_trigger_reason": "low_score",
  "sp_folder_hint": "חתונה ממבט ראשון"
}
```

### F2. SharePoint Lookup Request (internal to `search_in_library()`)

```json
{
  "query": "אסטרטגיית קמפיין ההשקה",
  "site_url": "https://keshettv.sharepoint.com/sites/Promo",
  "library": "DocLib4",
  "folder_path": "חתונה ממבט ראשון",
  "top": 3,
  "file_types": ["docx", "xlsx", "pdf"],
  "kql_querytext": "אסטרטגיית קמפיין ההשקה path:\"https://keshettv.sharepoint.com/sites/Promo/DocLib4/חתונה ממבט ראשון\" (FileExtension:docx OR FileExtension:xlsx OR FileExtension:pdf)"
}
```

### F3. SharePoint Evidence Package (returned by `search_in_library()`)

```json
[
  {
    "title": "תובנות השקה חתונה ממבט ראשון עונה 7",
    "url": "https://keshettv.sharepoint.com/sites/Promo/DocLib4/חתונה ממבט ראשון/עונה 7/השקה/תובנות ומחקר/תובנות השקה חתונה ממבט ראשון עונה 7.docx",
    "text": "תובנות ה-launch — סלוגן: 'מינדי לא תוותר'...",
    "score": 0.95
  },
  {
    "title": "מסמך ריאליטי GPT.docx",
    "url": "https://keshettv.sharepoint.com/sites/Promo/DocLib4/עבודה ChatGPT/מסמך ריאליטי GPT.docx",
    "text": "שימור ידע – חתונה ממבט ראשון: האסטרטגיה המרכזית...",
    "score": 0.90
  }
]
```

### F4. Merged Evidence Package (passed to `build_messages()`)

```
=== מסמכי Word (Azure) ===

[1] [מקור: מסמך ריאליטי GPT] | קטע מס': 3_112 | רלוונטיות: 0.61
תוכן מלא: ...

---

=== מסמכי SharePoint (תובנות ומחקר) ===

[1] תובנות השקה חתונה ממבט ראשון עונה 7  |  https://keshettv.sharepoint.com/...
תובנות ה-launch — סלוגן: 'מינדי לא תוותר'...
```

---

## G. Feature Flag and Logging

### Flag names
```env
SP_ENRICHMENT_ENABLED=false      # master switch
SP_SCORE_THRESHOLD=0.70          # trigger threshold (float)
SP_ENRICHMENT_TOP=3              # max SP docs appended
```

### What to log (existing `log.info` pattern)
```python
# When triggered:
log.info("[%s] SP enrichment triggered: route=%s show=%r score=%.2f caption=%s",
         trace_id, route, show_name, top_score, bool(caption))

# When result returns:
log.info("[%s] SP enrichment: %d doc(s) returned, folder=%r",
         trace_id, len(sp_docs), folder)

# When skipped:
log.debug("[%s] SP enrichment skipped: %s", trace_id, reason)
```

### Metrics to capture (in trace logs, grep-able)

| Metric | How to capture | Target |
|--------|---------------|--------|
| SP enrichment trigger rate | `grep "SP enrichment triggered"` / total queries | Target: 10–30% of word_quote |
| SP enrichment hit rate | `grep "SP enrichment:.*doc(s) returned"` where count > 0 | Target: ≥ 70% when triggered |
| SP latency | `time.time()` around `_fetch_sharepoint_enrichment` | Target: < 2.5s |
| SP-only queries (Azure miss) | Existing fallback log line | Should be rare |

### How to tell if SP is triggered too often
- If trigger rate > 50% of word_quote queries: threshold is too low → raise `SP_SCORE_THRESHOLD` to 0.80
- If SP latency consistently > 3s: add hard timeout, consider async in Phase 2

### How to tell if SP is improving answers
- Run `eval_dataset.py` with `SP_ENRICHMENT_ENABLED=true` on `quote` and `strategy` eval slices
- Compare judge score on these categories before/after
- Look for improvement on dataset ids: 1, 10, 11, 20, 26, 41, 42 (all cite SP-resident docs)

---

## H. Test and Eval Plan

### Unit tests (offline, no LLM)

| Test | File | What it checks |
|------|------|---------------|
| `test_sp_enrichment_disabled_by_default` | `test_agent.py` | Flag defaults to False |
| `test_sp_enrichment_fires_on_low_score` | `test_agent.py` | Trigger fires at score < threshold |
| `test_sp_enrichment_skipped_on_high_caption` | `test_agent.py` | Caption + high score suppresses trigger |
| `test_sp_enrichment_never_fires_for_excel_numeric` | `test_agent.py` | Route guard works |
| `test_sharepoint_tool_folder_path_injected` | new `test_sharepoint_tool.py` | KQL contains folder path |
| `test_sharepoint_tool_file_type_filter` | new `test_sharepoint_tool.py` | KQL contains FileExtension filter |

### Integration tests (require live SP)

| Test | When to run | What it checks |
|------|-------------|---------------|
| `test_sp_search_hebrew_folder` | Pre-prod | Hebrew folder names resolve in KQL |
| `test_sp_search_scoped_results` | Pre-prod | Results are scoped to requested folder |
| `test_full_pipeline_word_quote_with_enrichment` | Staging | End-to-end: low Azure score → SP fires → answer improves |

### Eval slices to monitor

| Slice | Dataset IDs | Why |
|-------|------------|-----|
| Quote (strategy docs) | 1, 11, 20, 41, 42 | Source docs live in SP `עבודה ChatGPT` |
| Strategy synthesis | 26, 45, 46 | Require cross-show knowledge from SP |
| Cross-show | 30, 31, 32 | Require synthesis across multiple SP docs |
| Alias + no-answer | 27–29, 33–35, 36, 50 | Must not regress |

### Expected improvement
- Quote/strategy categories: +5–15% judge score
- No regression on numeric/ranking/alias categories (SP not triggered for these)

---

## I. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Hebrew folder names break KQL path filter | High | Test in isolation before wiring into pipeline; add URL encoding fallback |
| SP credential not configured in Container App | High | `SP_ENRICHMENT_ENABLED=false` default; log EnvironmentError at INFO not ERROR |
| Azure caption field key is different from `d.get("caption")` | Medium | Verify in `search_word_docs.py` return dict before assuming field name |
| Token budget overflow with 3 extra SP docs | Medium | Existing context-trim retry handles it; cap SP text at 600 chars (not 900) |
| Duplicate content: same doc in Azure and SP | Medium | Add title-based dedup before appending SP section |
| SP latency spikes (2–5s) | Medium | Add `timeout=10` to SP request; log latency; monitor P95 |
| `_retrieve()` signature doesn't pass `question` to `_extract_show_name()` | Low | `_retrieve(route, query)` already receives alias-expanded query — use that |
| Score scale mismatch (Azure semantic score 0–4 vs 0–1) | Low | Verify exact scale in `search_word_docs.py` return; adjust threshold accordingly |

---

## J. Final Recommendation — Cursor Execution Order

```
Step 1 — Verify assumptions (no code yet)
    → Read app/search_word_docs.py: confirm caption field key and score scale
    → Read app/tools/sharepoint_tool.py: understand KQL construction
    → Check if SP_SITE_URL is set and valid in .env

Step 2 — app/tools/sharepoint_tool.py
    → Add folder_path param
    → Add file_types filter to KQL
    → Add URL encoding for Hebrew paths
    → Manual test: search_in_library("תובנות", folder_path="חתונה ממבט ראשון")

Step 3 — .env.example
    → Add SP_ENRICHMENT_ENABLED, SP_SCORE_THRESHOLD, SP_ENRICHMENT_TOP

Step 4 — app/service.py
    → Add _SP_ENRICHMENT, _SP_SCORE_THRESHOLD, _SP_ENRICHMENT_TOP constants
    → Add _needs_sharepoint_enrichment() function
    → Add _fetch_sharepoint_enrichment() function
    → Wire into _retrieve() for word_quote branch
    → Wire into _retrieve() for hybrid branch
    → Add structured log lines

Step 5 — tests/test_agent.py
    → Add 3 unit tests (all offline/mocked)
    → Run full test suite: pytest tests/ -m "not live" -v
    → Verify all existing tests still pass

Step 6 — Smoke test
    → SP_ENRICHMENT_ENABLED=true
    → python -m app.agent --debug "מה הייתה אסטרטגיית ההשקה של חתונמי עונה 7?"
    → Verify SP section appears in debug_trace
    → Verify total latency < 5s

Step 7 — Eval run
    → python tests/eval_dataset.py (with SP enabled)
    → Compare overall score and quote/strategy slice scores vs baseline
```

---

## Cursor Handoff Block

---

**Cursor, do not code yet. First investigate and produce an implementation plan.**

You are working on `PromoAgent` — a RAG system for Keshet TV's promo department. The goal is to add SharePoint as a second-stage enrichment source for `word_quote` and `hybrid` queries.

**Context:** The existing `_fetch_sharepoint_fallback()` in `service.py` fires only when both Azure indexes return zero results. This is almost never triggered. The fix is a new `_fetch_sharepoint_enrichment()` path that fires when Azure word-doc confidence is low (score < 0.70 or no `@search.answers` caption).

**Before writing any code:**

1. Open `app/search_word_docs.py` — find the exact field name used for the semantic caption/answer from `@search.answers`. Is it `caption`, `text`, `answer`? What is the score field name and its numeric range?

2. Open `app/tools/sharepoint_tool.py` — understand the KQL `path:` construction. Confirm whether Hebrew folder names in path strings need URL encoding. Confirm auth credential type used.

3. Open `app/service.py` — trace the full `_retrieve()` function. Note where `word_docs` are returned. Note that `question` (alias-expanded) is in scope via `query` parameter. Note the existing `_fetch_sharepoint_fallback()` call in `run_query()` — this must NOT be removed.

4. Open `tests/test_agent.py` — list all existing tests. None of them may break.

**Then produce a plan** listing: (a) exact line numbers to change in each file, (b) new functions to add, (c) the 3 unit tests to add, (d) one shell command to verify the SP folder path works. Only after I approve the plan should you write code.

**Feature flag:** Everything new is behind `SP_ENRICHMENT_ENABLED=false`. Default is off.

**Must not change:** `query_router.py`, `api.py`, `models.py`, `prompts.py`, existing test cases, existing `_fetch_sharepoint_fallback()` logic.
