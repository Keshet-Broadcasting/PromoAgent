# PromoAgent — Roadmap

**Last updated:** May 20, 2026

---

## Project Overview

PromoAgent is a RAG-based chatbot for Keshet TV's promo department, replacing a custom GPT that has full-file context. The agent uses Azure AI Search over Excel (tv-promos) and Word (word-docs) indexes, with GPT-4o via Azure AI Foundry.

**Goal:** Match the custom GPT experience — correct, complete, multi-turn answers with actionable business insights.

---

## Status Summary

| Phase | Description | Status | Impact |
|-------|------------|--------|--------|
| 1 | Show-complete retrieval (`fetch_show_promos`) | **DONE** | +15–20% ranking |
| 1b | Consume `@search.answers` for Word docs | **DONE** | +5–10% quote/factual |
| 2 | Fix eval: judge uses cleaned query | **DONE** | Accurate scoring |
| 3 | Few-shot examples in system prompt | **DONE** | +5–10% all categories |
| 4 | Conversation memory (multi-turn) | **DONE** | UX parity |
| 5 | Expand eval dataset to 54 cases | **DONE** | Reliable metrics |
| 5b | Chain-of-thought (`<thinking>`) + Markdown table context | **DONE** | +2.5% overall, +14% ranking |
| 5c | Gemini provider alternative | **DONE** | 3x faster, weaker quality — not for prod |
| 5d | Full Excel → JSON → Azure ingest pipeline | **DONE** | 1,462 records re-ingested with rich text chunks |
| 5e | SharePoint enrichment (score-gated, DocLib4) | **DONE** | Helps freshness/zero-result gaps; disabled by default |
| 6 | Word document semantic chunking | **DONE** | 721 semantic chunks (4 GPT docs); `header`, `show_name`, `season` metadata |
| 7 | Model verification (GPT-4o) | **DONE** | Confirmed GPT-4o deployed |
| 6b | Word-docs schema migration (add 4 metadata fields, re-ingest) | **DONE (May 24)** | +4.7% judge; quote +25, strategy +17, factual +10 |
| 6c | Route upgrade fix (unknown + broad_scope → hybrid) | **DONE (May 24)** | Cross_show queries now engage broad path |
| 6d | Alias expansion idempotency + extended route upgrade (excel_numeric + genres → hybrid) | **DONE (May 24)** | Fixes corrupted multi-show queries and Word-shadowed factual queries; impact pending re-eval |
| 6e | Tighten English-rejection rule in system_prompt.txt | **DONE (May 24)** | Hebrew queries with English tokens (e.g. Live+7/VOD) now answered, not refused |
| 8 | UI parity (streaming, threads, mobile) | TODO | UX |
| BR | Broad retrieval activation (`BROAD_RETRIEVAL_ENABLED=true`) | **DONE (May 24)** | +2.4% judge; alias +17%, ranking +10%, quote +13% |

---

## Completed Work

### Production Hardening (all items resolved)

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | Entra ID auth on `/query` | CRITICAL | FIXED |
| 2 | CORS wildcard warning | CRITICAL | FIXED |
| 3 | Provider singleton caching | CRITICAL | FIXED |
| 4 | Rate limiting (slowapi) | HIGH | FIXED |
| 5 | LLM call timeout (90s) | HIGH | FIXED |
| 6 | Debug gated by env var | HIGH | FIXED |
| 7 | Non-root Dockerfile | HIGH | FIXED |
| 8 | Uvicorn multi-worker | HIGH | FIXED |
| 9 | `.env.example` resource names | MEDIUM | Acknowledged |
| 10 | Handle None OpenAI content | MEDIUM | FIXED |
| 11 | Import-time credentials | MEDIUM | Acknowledged |
| 12 | Disable FastAPI docs in prod | MEDIUM | FIXED |

### UI/UX Fixes

| ID | Item | Status |
|----|------|--------|
| 1.1 | Remove unnecessary buttons from chat UI | DONE |
| 1.2 | Fix page scroll jump on bot response | DONE |

### Domain Knowledge

| ID | Item | Status |
|----|------|--------|
| 2.0 | Add show aliases (חתונמי, רוכדים, ארץ, זמר, כוכב) | DONE |

### Conversation Memory & Context

| ID | Item | Status |
|----|------|--------|
| 3.1 | Per-user session history (backend `history` field + frontend localStorage) | DONE |
| 3.2 | Intra-conversation context (multi-turn via `build_messages`) | DONE |
| 3.3 | Persistent user memory (Azure Table Storage via `app/memory.py`) | DONE |
| 3.4 | Fact extraction from conversations (`app/fact_extractor.py`) | DONE |

### Analytical Capabilities

| ID | Item | Status |
|----|------|--------|
| 4.1 | Cross-case analysis (system prompt enhancement) | DONE |
| 4.2 | Pattern recognition | DONE |
| 4.3 | Data-backed conclusions | DONE |
| 4.4 | Strategic & business-oriented insights | DONE |

### Response Structure

| ID | Item | Status |
|----|------|--------|
| 5.0 | Funnel-shaped response (Data→Patterns→Meaning→Conclusion) | DONE |

### Retrieval Improvements

| Item | Status |
|------|--------|
| `fetch_show_promos()` — filter-based retrieval for ranking queries (top=500) | DONE |
| `@search.answers` consumption with score threshold 0.85 | DONE |
| Dynamic `word_top` (15 for strategic, 10 for standard) | DONE |
| Temporal season filter (last/first season detection, per-show grouping) | DONE |
| Context-too-large retry with automatic trimming | DONE |

### Performance

| Item | Status |
|------|--------|
| History message cap (600 chars per turn) | DONE |
| LLM timeout increased to 90s | DONE |
| Dynamic `word_top` based on query intent | DONE |

### Eval & Quality

| Item | Status |
|------|--------|
| LLM-as-judge eval harness | DONE |
| Dataset expanded to 54 cases across all categories | DONE |
| Hebrew prefix stemming in keyword scorer | DONE |
| Judge uses cleaned query (not raw context-dependent form) | DONE |

### Prompt Engineering (May 19, 2026)

| Item | Status |
|------|--------|
| Mandatory `<thinking>` chain-of-thought block in system prompt | DONE |
| Tone, Style and Formatting rules (no filler, bold metrics, managerial tone) | DONE |
| Updated few-shot examples with `<thinking>` block | DONE |
| Nickname table: added `נוטוק`, upgraded חתונמי to CRITICAL ENTITY RULE | DONE |

### Context Formatting (May 19, 2026)

| Item | Status |
|------|--------|
| `_fmt_excel()` — Excel rows as structured Markdown table | DONE |
| `<thinking>` block stripping before returning answer to user | DONE |

### LLM Provider Alternatives (May 19, 2026)

| Item | Status |
|------|--------|
| `GeminiProvider` via `google-genai` SDK (CHAT_PROVIDER=gemini) | DONE — not for prod |
| Eval comparison: Foundry 53.8% vs Gemini 39.3% (Foundry wins) | DONE |

### Data Pipeline (May 19, 2026)

| Item | Status |
|------|--------|
| `scripts/convert_excel_to_json.py` — parse all 79 Excel sheets → JSON | DONE |
| `scripts/ingest_json_to_azure.py` — embed + upload 1,462 records to tv-promos | DONE |
| `scripts/debug_retrieval.py` — standalone retrieval debugger (no LLM) | DONE |

### Tools & Integrations

| Item | Status |
|------|--------|
| SharePoint MCP client (`app/tools/sharepoint_tool.py`) | DONE |
| Agent 365 MCP integration (SharePoint, OneDrive, Lists) | DONE |

### Word Document Semantic Chunking (May 20, 2026)

| Item | Status |
|------|--------|
| `scripts/preprocess_word_docs.py` — GPT-template detection + two-level semantic split | DONE |
| `scripts/preprocess_word_docs.py --doc` — single-doc preprocess flag (with `--preview-doc` dry-run) | DONE |
| `scripts/ingest_word_chunks.py --doc` — single-doc ingest with paginated delete-first | DONE |
| `scripts/diagnose_word_docs.py --source json` — inspect JSON blobs before ingest | DONE |
| Metadata extraction: `header`, `show_name`, `season`, `doc_type`, `question_type` | DONE |
| Re-ingest all 4 GPT Word docs — 721 semantic chunks total | DONE |

**Index state after Phase 6 (May 20, 2026):**

| Document | Chunks | Sections (header populated) | show_name coverage |
|---|---|---|---|
| מסמך ריאליטי GPT.docx | 423 | 407 (96%) | 97% |
| מסמך דרמות GPT.docx | 174 | 145 (83%) | 98% |
| GPT מסמך בידור.docx | 45 | 16 (36%) | 100% |
| GPT מסמך תוכניות נוספות.docx | 25 | 9 (36%) | 100% |
| **Total** | **667** | **577 (86%)** | **~98%** |

> **Note:** `show_name`, `season`, `doc_type`, `question_type` are stored in JSON blobs but not yet in the Azure Search index schema — pending schema migration (follow-up task).

---

## Remaining Work

### Phase 8 — UI Parity with Custom GPT

**Priority:** Medium | **Effort:** 1 week

| Feature | Status |
|---------|--------|
| Streaming responses (show text as generated) | TODO |
| Conversation threads (persistent sidebar) | TODO |
| Source document preview (click citation to view chunk) | TODO |
| Mobile-friendly layout | TODO |
| Copy/share button | TODO |

### SharePoint Enrichment — Production Activation

**Priority:** Low | **Effort:** 30 min**

SP enrichment is implemented and feature-flagged (`SP_ENRICHMENT_ENABLED=false`). To activate in production:
1. Verify `az login` or managed identity has `Sites.Read.All` on `keshettv.sharepoint.com/sites/Promo`
2. Set `SP_ENRICHMENT_ENABLED=true` on the Container App env vars
3. Monitor logs for `SP enrichment triggered` rate — target 10–30% of `word_quote` queries
4. Run `python tests/eval_dataset.py` with enrichment on; compare quote/strategy slice scores

**What it helps:** freshness gaps (docs not yet re-ingested into Azure), zero-result fallback cases.
**What it does NOT help:** synthesis failures caused by bad chunking (those are fixed by Phase 6, which is now DONE).

### Phase 6b — Word Document Schema Migration (next slice, blocks strategy/cross_show)

**Priority:** HIGH (was Low — promoted after May 24 worst-case analysis) | **Effort:** 1–2 hours

The `show_name`, `season`, `doc_type`, `question_type` metadata fields are extracted during Phase 6 and stored in JSON blobs with 96–100% coverage (validated `tmp_pkg/check_json_metadata.py`). They are NOT yet added to the live `word-docs` Azure Search index schema (validated `tmp_pkg/check_word_schema.py` against prod — 0 of 4 fields present).

**Code state — no code changes needed:**
- `scripts/create_word_docs_index.py` already declares all 4 fields as filterable+retrievable (lines 116-140).
- `scripts/ingest_word_chunks.py` already uploads all 4 fields (strips only `_atomic`, lines 267-280).
- `app/search_word_docs.py` already builds the OData filter (`_build_word_filter`, lines 89-109).
- `app/service.py` already wires broad-word retrieval to call with `show_names`/`doc_types`/`question_types` filters.

**Steps to deploy:**
1. `python scripts/create_word_docs_index.py` (additive — `create_or_update_index` on existing index)
2. `python tmp_pkg/check_word_schema.py` — expect 4 fields present
3. Re-ingest per-doc with `--doc` flag (delete-first to clear stale chunks):
   - `python scripts/ingest_word_chunks.py --doc "מסמך ריאליטי GPT.docx"`
   - `python scripts/ingest_word_chunks.py --doc "מסמך דרמות GPT.docx"`
   - `python scripts/ingest_word_chunks.py --doc "GPT מסמך בידור.docx"`
   - `python scripts/ingest_word_chunks.py --doc "GPT מסמך תוכניות נוספות.docx"`
4. `python tmp_pkg/check_word_schema.py` — expect ~97% `show_name` non-empty on 667 chunks
5. Set `WORD_METADATA_FILTERS_ENABLED=true` (in `.env` for local, or Container App env vars for prod)
6. `python run_eval_judge.py` — measure delta on strategy / cross_show / comparison / factual

**Expected impact:** Unblocks ~15 of the 25 worst eval cases (strategy 25% → ~45%+, cross_show 19% → ~40%+, factual 30% → ~45%+).

**Rollback:** Set `WORD_METADATA_FILTERS_ENABLED=false` — broad-word path falls back to unfiltered semantic search (`search_word_docs.py:160-162`). Fields remain in schema but are ignored. No code change.

### Future Considerations

| Item | Notes |
|------|-------|
| Configurable alias map (JSON/DB instead of code) | Currently hardcoded in `service.py` |
| Query router LLM classification | Replace regex-based routing with LLM intent detection |
| Real-time index updates | Auto-ingest new Excel/Word files from SharePoint |
| A/B testing framework | Compare prompt variations on live traffic |

---

## Score Tracking

| Date | Provider | Overall | Judge | Notes |
|------|----------|---------|-------|-------|
| May 7, 2026 | Azure OpenAI | 48.2% | — | Baseline (26 cases) |
| May 7, 2026 | Azure OpenAI | 55.7% | — | After 12 improvements |
| May 10, 2026 | Foundry gpt-4o | 44.7% | 31.7% | First judge run (26 cases) |
| May 10, 2026 | Foundry gpt-4o | 48.3% | 37.5% | After ranking fixes |
| May 19, 2026 | Foundry gpt-4o | 51.3% | 39.6% | Baseline before today's changes (54 cases) |
| May 19, 2026 | Gemini 2.5 Flash | 39.3% | 31.6% | Provider comparison — 3x faster, weaker quality |
| May 19, 2026 | Foundry gpt-4o | **53.8%** | **43.4%** | After `<thinking>` + Markdown table + prompt updates |
| May 20, 2026 | Foundry gpt-4o | **51.4%** | **42.0%** | 53 cases (1 transient error); numeric +3.2%, keyword +5.5% |
| May 20, 2026 | — | — | — | Phase 6 semantic chunking ingested — next eval will measure impact |
| May 24, 2026 | Foundry gpt-4o | **52.3%** | **44.4%** | Broad-retrieval checkpoint — `BROAD_RETRIEVAL_ENABLED=true`; 54 cases, 0 errors; alias +17%, ranking +10%, quote +13%; **Phase 6b not yet deployed** — strategy 25% / cross_show 19% / comparison 0% remain blocked |
| May 24, 2026 (run 2) | Foundry gpt-4o | **53.6%** | **49.1%** | Phase 6b deployed (schema + re-ingest); quote 71% (+25pp), strategy 42% (+17pp), factual 40% (+10pp); cross_show unchanged 19% — routing bug discovered, patched (`route=unknown` + `broad_scope` → upgrade to `hybrid`); not yet measured post-fix |

**Target:** ≥ 70% judge score (≈ 3.5/5) — threshold for replacing the custom GPT.

---

## Architecture

```
User → Next.js UI → FastAPI (/query) → Query Router → Retrieval
                                                        ├── Azure AI Search (tv-promos index)
                                                        ├── Azure AI Search (word-docs index)
                                                        └── SharePoint MCP (Agent 365)
                                                    ↓
                                              Prompt Builder → GPT-4o (Azure AI Foundry)
                                                    ↓
                                              Structured Response (answer + sources + confidence)
```

**Key files:**
- `app/api.py` — FastAPI entry point with auth, rate limiting
- `app/service.py` — Core RAG pipeline (`run_query`)
- `app/query_router.py` — Rule-based query classification
- `app/prompts.py` — Prompt construction with history support
- `app/system_prompt.txt` — LLM system prompt (grounding rules, few-shot examples)
- `app/search_word_docs.py` — Azure AI Search retrieval
- `app/memory.py` — Azure Table Storage for user facts
- `app/fact_extractor.py` — Background fact extraction from conversations
- `app/tools/sharepoint_tool.py` — SharePoint MCP client
- `tests/eval_dataset.py` — Eval harness with LLM-as-judge
- `dataset.jsonl` — 54-case evaluation dataset
