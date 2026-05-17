# PromoAgent — Roadmap

**Last updated:** May 13, 2026

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
| 6 | Word document semantic chunking | TODO | +5–10% quote/factual |
| 7 | Model verification (GPT-4o) | **DONE** | Confirmed GPT-4o deployed |
| 8 | UI parity (streaming, threads, mobile) | TODO | UX |

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

### Tools & Integrations

| Item | Status |
|------|--------|
| SharePoint MCP client (`app/tools/sharepoint_tool.py`) | DONE |
| Agent 365 MCP integration (SharePoint, OneDrive, Lists) | DONE |

---

## Remaining Work

### Phase 6 — Word Document Semantic Chunking

**Priority:** Medium | **Effort:** 1 week | **Expected gain:** +5–10% quote/factual

Current indexing uses fixed-size token chunking. Multi-paragraph insight sections get split across chunks, so the LLM only sees partial context.

**Plan:**
- Update `scripts/ingest_word_chunks.py` to split on Hebrew semantic boundaries (bold headings, section dividers, keywords like תובנות, אסטרטגיה, מסקנה)
- Min chunk: 3 sentences | Max chunk: 600 tokens | Overlap: 1 sentence
- Re-ingest all Word documents (no schema change needed)

### Phase 8 — UI Parity with Custom GPT

**Priority:** Medium | **Effort:** 1 week

| Feature | Status |
|---------|--------|
| Streaming responses (show text as generated) | TODO |
| Conversation threads (persistent sidebar) | TODO |
| Source document preview (click citation to view chunk) | TODO |
| Mobile-friendly layout | TODO |
| Copy/share button | TODO |

### SharePoint Integration — Production Setup

**Priority:** Low | **Effort:** 1 hour (Azure Portal)

The MCP client is implemented. For production:
- Add a client secret to Entra app `e75dd4ee-54f5-4183-86b9-35f53506925c`
- Set `SP_CLIENT_SECRET` env var on the Container App
- Integrate SharePoint search into the query pipeline as an additional context source

### Future Considerations

| Item | Notes |
|------|-------|
| Configurable alias map (JSON/DB instead of code) | Currently hardcoded in `service.py` |
| Query router LLM classification | Replace regex-based routing with LLM intent detection |
| Real-time index updates | Auto-ingest new Excel/Word files from SharePoint |
| A/B testing framework | Compare prompt variations on live traffic |

---

## Score Tracking

| Date | Mode | Overall | Judge | Notes |
|------|------|---------|-------|-------|
| May 7, 2026 | Automated | 48.2% | — | Baseline |
| May 7, 2026 | Automated | 55.7% | — | After 12 improvements |
| May 10, 2026 | Judge | 44.7% | 31.7% | First judge run |
| May 10, 2026 | Judge | 48.3% | 37.5% | After ranking fixes |

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
