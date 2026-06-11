# PromoAgent

An internal RAG (Retrieval-Augmented Generation) agent for the Promo department at Keshet.
Answers questions in Hebrew from two structured data sources:

- **Excel files** — broadcast ratings, season statistics, episode-level metrics (`tv-promos` index)
- **Word documents** — strategy briefs, campaign slogans, marketing phrasing (`word-docs` index)

The system routes each question to the right source automatically and returns grounded, cited answers — no hallucinations. It supports multi-turn conversations with per-user memory persistence.

---

## Architecture

```
User (Next.js UI / CLI)
        │
        ▼
┌──────────────────┐
│  Entra ID Auth   │  JWT validation (bearer token)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  FastAPI + Rate  │  /query, /health — slowapi rate limiting
│  Limiter         │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Query Router    │  rule-based: excel_numeric / word_quote / hybrid / unknown
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────┐
│  Retrieval                       │
│  ├── Azure AI Search (tv-promos) │  Excel ratings, seasons, episodes
│  ├── Azure AI Search (word-docs) │  Strategy docs, @search.answers
│  └── SharePoint MCP (Agent 365)  │  Org documents (keshettv.sharepoint.com)
└────────┬─────────────────────────┘
         │
         ▼
┌──────────────────┐
│  Prompt Builder  │  system_prompt.txt + history + route addendum + few-shot examples
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  GPT-4o          │  Azure AI Foundry (Keshet-Foundry, GlobalStandard 3500 TPM)
└────────┬─────────┘
         │
         ├──► Grounded Hebrew answer + source citations + confidence
         │
         └──► Fact Extractor (background thread)
                    │
                    ▼
              Azure Table Storage (per-user memory)
```

### Key files

| Path | Role |
|------|------|
| **Backend** | |
| `app/api.py` | FastAPI service — `POST /query`, `GET /health`, auth + rate limiting |
| `app/auth.py` | Entra ID JWT validation |
| `app/service.py` | Core RAG pipeline (`run_query`) |
| `app/query_router.py` | Rule-based query classifier |
| `app/prompts.py` | Prompt assembly with conversation history support |
| `app/system_prompt.txt` | System prompt (grounding rules, few-shot examples, funnel structure) |
| `app/chat_provider.py` | Provider abstraction: Azure OpenAI or Foundry |
| `app/models.py` | Pydantic request/response models |
| `app/search_word_docs.py` | Azure AI Search helpers — `fetch_show_promos`, `fetch_many_show_promos` (broad retrieval), `_build_word_filter` (Phase 6b metadata filter) |
| `app/domain_catalog.py` | Single source of truth — show names, aliases, genre patterns, alias expansion (`expand_aliases`), show extraction (`extract_show_names`), genre detection (`genres_for_query`) |
| `app/memory.py` | Persistent user memory via Azure Table Storage |
| `app/fact_extractor.py` | Background fact extraction from multi-turn conversations |
| `app/tools/sharepoint_tool.py` | SharePoint MCP client (Agent 365 integration) |
| `app/agent.py` | CLI entry point |
| **Frontend** | |
| `promobot-ui/` | Next.js + React + Tailwind chat UI |
| **Scripts** | |
| `scripts/ingest_excel.py` | Standard Excel tab ingestion |
| `scripts/ingest_excel_special_tabs.py` | Sectioned / positional Excel tab ingestion (`--retab` flag) |
| `scripts/preprocess_word_docs.py` | Word → JSON chunks via Document Intelligence or stdlib fallback |
| `scripts/ingest_word_chunks.py` | Embed JSON chunks and upload to `word-docs` index |
| `scripts/diagnose_excel_tabs.py` | Read-only: which Excel tabs are missing from the index |
| `scripts/diagnose_word_docs.py` | Read-only: chunk quality report for `word-docs` index |
| `scripts/list_show_names.py` | Print unique show names in `tv-promos` (used to populate `SHOWS` in `app/domain_catalog.py`) |
| **Tests & Eval** | |
| `tests/test_agent.py` | Regression tests (router, live LLM, conversation history) |
| `tests/test_prod_hardening.py` | Production hardening tests (auth, rate limiting, debug gating) |
| `tests/test_retrieval_planning.py` | Unit tests for alias expansion, genre detection, broad-scope planner |
| `tests/test_data_health.py` | Data-quality guardrails — catalog integrity, word-docs index health (no doc-type-as-show_name garbage, ≥80% show_name coverage, ≥30 catalog overlap), tv-promos sanity. Mix of offline + `@pytest.mark.live` |
| `tests/test_sharepoint_tool.py` | SharePoint client tests (KQL construction, folder scoping) |
| `tests/eval_dataset.py` | Evaluation harness against `dataset.jsonl` (numeric + LLM-as-judge) |
| `tests/conftest.py` | Pytest config — loads `.env` so live tests can read Azure creds, registers `live` marker |
| `run_eval_judge.py` | Wrapper to run judge eval in a detached process (Windows-safe) |
| `dataset.jsonl` | Gold-standard evaluation dataset (54 cases) |
| **Docs** | |
| `docs/ROADMAP.md` | Consolidated roadmap — status of all features and improvements |
| `docs/improvement-plan.md` | Original phased improvement plan |
| `docs/eval-improvements.md` | Eval changelog and score history |
| `docs/PROD_READINESS.md` | Production readiness checklist (all critical items resolved) |

---

## Prerequisites

- Python 3.10+
- Node.js 18+ (for the frontend UI)
- Azure subscription with:
  - **Azure AI Foundry** — GPT-4o chat deployment
  - **Azure OpenAI** — embeddings deployment
  - **Azure AI Search** — `tv-promos` and `word-docs` indexes
  - **Azure Blob Storage** — Excel/Word source files + static website hosting for the UI
  - **Azure Table Storage** — per-user memory persistence
  - **Entra ID** — app registration for API auth (JWT validation)
- (Optional) Microsoft 365 MCP — SharePoint/OneDrive access via Agent 365

---

## Setup

### 1. Clone and create virtual environment

```bash
git clone https://github.com/Amitro1234/PromoAgent.git
cd PromoAgent
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> **Corporate network note:** If `zipp` / `importlib-metadata` are blocked by a proxy,
> install the Foundry-related packages with `--no-deps`:
> ```bash
> pip install agent-framework-core agent-framework-openai agent-framework-foundry \
>             azure-ai-inference azure-ai-projects azure-identity \
>             opentelemetry-api importlib-metadata msal --no-deps
> ```

### 3. Configure environment

```bash
cp .env.example .env
# Fill in your values in .env — never commit this file
```

Required variables:

| Variable | Description |
|----------|-------------|
| `AZURE_SEARCH_ENDPOINT` | Azure AI Search service URL |
| `AZURE_SEARCH_KEY` | Admin API key |
| `AZURE_OPENAI_ENDPOINT` | Embeddings resource endpoint |
| `AZURE_OPENAI_KEY` | Embeddings API key |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model name |
| `AZURE_OPENAI_CHAT_ENDPOINT` | Chat resource endpoint |
| `AZURE_OPENAI_CHAT_KEY` | Chat API key |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Chat model deployment name |

Optional variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTH_TENANT_ID` | Entra ID tenant for JWT validation | — |
| `AUTH_CLIENT_ID` | Entra ID app (audience) for JWT validation | — |
| `MEMORY_STORAGE_ACCOUNT` | Azure Storage account for user memory | `aistoragekeshet` |
| `MEMORY_TABLE_NAME` | Table name for user facts | `usermemory` |
| `MEMORY_STORAGE_KEY` | Storage account key (if not using managed identity) | — |
| `SP_TENANT_ID` | Entra tenant for SharePoint MCP auth | Keshet tenant |
| `SP_CLIENT_ID` | App ID for MCP access | — |
| `SP_CLIENT_SECRET` | Client secret for server-to-server MCP auth | — |
| `SP_SITE_URL` | SharePoint site URL | `https://keshettv.sharepoint.com/` |
| `CORS_ORIGINS` | Comma-separated allowed origins | `*` (warns in prod) |
| `ALLOW_DEBUG` | Enable debug trace in responses | `false` |
| `LLM_TIMEOUT_SECONDS` | LLM call timeout | `90` |
| `LLM_SEED` | Seed for chat completions (best-effort reproducibility) | `42` |
| `MAX_ANSWER_TOKENS` | Max tokens per LLM answer (shared with the `<thinking>` block) | `3000` |
| `ENVIRONMENT` | `dev` / `staging` / `production` | `dev` |
| `CHAT_PROVIDER` | `azure_openai` (default) / `foundry` / `gemini` | `azure_openai` |
| **Retrieval flags** | | |
| `BROAD_RETRIEVAL_ENABLED` | Activate broad-Excel + broad-Word retrieval for cross-show / genre queries | `false` |
| `WORD_METADATA_FILTERS_ENABLED` | Allow `search_word_docs` to filter by `show_name`/`season`/`doc_type`/`question_type` (requires Phase 6b schema migration) | `false` |
| `SP_ENRICHMENT_ENABLED` | Score-gated SharePoint enrichment for low-confidence Word queries | `false` |
| `SP_SCORE_THRESHOLD` | Azure reranker score below which SP enrichment fires (0–4 scale) | `2.5` |
| `SP_ENRICHMENT_TOP` | Max SP docs appended to context | `3` |
| **Langfuse (optional)** | | |
| `LANGFUSE_PUBLIC_KEY` | Public key for trace export | — |
| `LANGFUSE_SECRET_KEY` | Secret key for trace export | — |
| `LANGFUSE_HOST` | Self-hosted URL or leave unset for cloud | `https://cloud.langfuse.com` |

---

## Running

### CLI — interactive REPL

```powershell
.venv\Scripts\python.exe -m app.agent
```

Type your question in Hebrew at the `שאלה:` prompt. Press Enter twice to exit.

### CLI — single question

```powershell
.venv\Scripts\python.exe -m app.agent "מה הרייטינג הממוצע של חתונה ממבט ראשון?"
```

Add `--debug` for full retrieval trace:

```powershell
.venv\Scripts\python.exe -m app.agent --debug "מה הסלוגן של עונה 3?"
```

### API server

```bash
uvicorn app.api:app --reload --host 0.0.0.0 --port 8000
```

Then (with auth):

```bash
curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <entra-id-token>" \
     -d '{"question": "מה הרייטינג הממוצע של חתונה ממבט ראשון?", "history": []}'
```

API request/response:

```json
// Request
{
  "question": "מה הרייטינג הממוצע של חתונה ממבט ראשון?",
  "history": [
    {"role": "user", "content": "previous question"},
    {"role": "assistant", "content": "previous answer"}
  ],
  "debug": false
}

// Response
{
  "answer": "...",
  "route": "excel_numeric",
  "confidence": "high",
  "sources": [{ "type": "excel", "title": "מעקבי פרומו.xlsx", "reference": "...", "score": 0.95 }],
  "trace_id": "uuid"
}
```

The `history` field supports up to 10 previous turns for multi-turn conversations. Each message content is capped at 600 characters to prevent prompt bloat.

Health check: `GET /health`

### Frontend UI

```bash
cd promobot-ui
npm install
npm run dev
```

The UI is a Next.js app with:
- Chat interface with conversation history persisted in `localStorage`
- "New Chat" button to start a fresh conversation
- Smooth auto-scroll on new messages
- Deployed as a static site on Azure Blob Storage

---

## Chat Provider

Controlled by the `CHAT_PROVIDER` environment variable:

| Value | Description |
|-------|-------------|
| `azure_openai` | Default. Uses `AZURE_OPENAI_CHAT_*` variables + openai SDK |
| `foundry` | Microsoft Agent Framework via `FoundryChatClient` |

### Switching to Foundry

```env
CHAT_PROVIDER=foundry
AZURE_AI_PROJECT_ENDPOINT=https://<resource-name>.services.ai.azure.com/api/projects/<project-name>
AZURE_AI_MODEL_DEPLOYMENT_NAME=<deployment-name>
AZURE_CREDENTIAL_TYPE=cli          # cli (local) | managed_identity (Azure-hosted)
```

Run `az login` before using `cli` credential locally.

---

## Tests

```bash
# Fast offline tests (router + data-health + catalog — no Azure calls)
python -m pytest tests/ -m "not live" -v

# Full tests including live Azure (LLM + Azure Search — costs tokens)
python -m pytest tests/ -v

# Data-health only (catalog integrity + index health — ~7s with live, no LLM cost)
python -m pytest tests/test_data_health.py -v
```

The `test_data_health.py` suite is the canonical guardrail against catalog/index
drift: it asserts that the live word-docs index has no `'השקה'`/`'גמר'`/etc.
garbage as `show_name`, that show_name coverage stays ≥80%, and that ≥30
catalog shows have at least one matching chunk. Run it any time you touch
`scripts/preprocess_word_docs.py`, `app/domain_catalog.py`, or after re-ingest.

## Evaluation

The project includes a gold-standard evaluation dataset (`dataset.jsonl`) and two scoring modes:

```bash
# Numeric scoring only (fast, no LLM cost)
python tests/eval_dataset.py

# With LLM-as-judge (slower, costs tokens — recommended for quality assessment)
python run_eval_judge.py
```

Results are written to `eval_judge_results.json`. See `docs/ROADMAP.md` for the consolidated status of all features and improvements.

## Re-indexing

After changing ingestion scripts, re-index with:

```bash
# Re-index all standard Excel tabs (always re-uploads everything)
python scripts/ingest_excel.py

# Re-index special/sectioned Excel tabs (skips already-indexed; use --retab to force)
python scripts/ingest_excel_special_tabs.py
python scripts/ingest_excel_special_tabs.py --retab "מסמך שם" "מסמך שם 2"

# Re-chunk Word documents (Document Intelligence + fallback) then upload to index
python scripts/preprocess_word_docs.py --overwrite
python scripts/ingest_word_chunks.py

# Diagnostics (read-only)
python scripts/diagnose_excel_tabs.py
python scripts/diagnose_word_docs.py
```

---

## Deployment

The backend runs as a Docker container on **Azure Container Apps**, deployed via `azure-pipelines.yml` (pipeline: `kst.ai_pipelines`).

The frontend is a static site hosted on **Azure Blob Storage** (`aistoragekeshet`).

```bash
# Build and deploy frontend manually
cd promobot-ui
npm run build
az storage blob upload-batch \
  --source out \
  --destination '$web' \
  --account-name aistoragekeshet \
  --overwrite
```

---

## Security

- `.env` is git-ignored — never commit it.
- All secrets are read from environment variables at runtime.
- **Authentication:** Entra ID JWT validation on all `/query` requests (`app/auth.py`).
- **Rate limiting:** slowapi — per-IP limits on `/query`.
- **CORS:** Configurable via `CORS_ORIGINS` env var; warns at startup if set to `*` in non-dev environments.
- **Debug gating:** `ALLOW_DEBUG=true` required to include retrieval traces in responses.
- **Container security:** Dockerfile runs as non-root `appuser`.
- **FastAPI docs:** Disabled in non-dev environments.
- For production: prefer **Managed Identity** over API keys where possible.

---

## Project structure

```
PromoAgent/
├── app/
│   ├── agent.py              # CLI entry point
│   ├── api.py                # FastAPI service (auth, rate limiting, /query, /health)
│   ├── auth.py               # Entra ID JWT validation
│   ├── chat_provider.py      # Provider abstraction (Azure OpenAI / Foundry)
│   ├── fact_extractor.py     # Background fact extraction from conversations
│   ├── memory.py             # Persistent user memory (Azure Table Storage)
│   ├── models.py             # Pydantic models (QueryRequest with history support)
│   ├── prompts.py            # Prompt assembly with conversation history
│   ├── query_router.py       # Rule-based router
│   ├── search_word_docs.py   # Azure AI Search helpers (incl. fetch_show_promos)
│   ├── service.py            # Core RAG pipeline (alias expansion, retrieval, LLM)
│   ├── system_prompt.txt     # System prompt (grounding rules, few-shot, funnel structure)
│   └── tools/
│       └── sharepoint_tool.py  # SharePoint MCP client (Agent 365)
├── promobot-ui/              # Next.js + React + Tailwind chat frontend
│   ├── src/
│   │   ├── components/chat/  # ChatWindow, MessageList, EmptyState
│   │   └── services/api.ts   # API client (sends history, auth token)
│   └── ...
├── scripts/
│   ├── create_index.py               # Create tv-promos index schema
│   ├── create_word_docs_index.py     # Create word-docs index schema
│   ├── ingest_excel.py               # Standard Excel tab ingestion
│   ├── ingest_excel_special_tabs.py  # Sectioned/positional tab ingestion
│   ├── preprocess_word_docs.py       # Word → JSON chunks (DI + fallback)
│   ├── ingest_word_chunks.py         # Embed + upload word chunks
│   ├── diagnose_excel_tabs.py        # Diagnostic: missing Excel tabs
│   ├── diagnose_word_docs.py         # Diagnostic: word chunk quality
│   └── list_show_names.py            # Print unique show names in index
├── docs/
│   ├── ROADMAP.md              # Consolidated roadmap and status tracking
│   ├── PROD_READINESS.md       # Production readiness checklist
│   ├── improvement-plan.md     # Original phased improvement plan
│   └── eval-improvements.md    # Eval changelog and score history
├── tests/
│   ├── test_agent.py           # Regression tests (router, LLM, conversation)
│   ├── test_prod_hardening.py  # Production hardening tests (auth, rate limiting)
│   └── eval_dataset.py         # Evaluation harness (numeric + LLM judge)
├── run_eval_judge.py           # Detached wrapper for judge eval
├── dataset.jsonl               # Gold-standard eval dataset (54 cases)
├── Dockerfile                  # Container image (non-root, multi-worker)
├── azure-pipelines.yml         # CI/CD pipeline template
├── .env.example                # Environment variable template
├── requirements.txt
└── README.md
```