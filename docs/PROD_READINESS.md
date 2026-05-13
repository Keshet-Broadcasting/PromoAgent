# Production Readiness Review — PromoAgent

**Date:** 2026-04-30
**Reviewer:** AI Code Review
**Status:** Complete — all critical and high items resolved (May 2026)

---

## CRITICAL (must fix before prod)

### 1. No Authentication — API is open to the internet
- **File:** `app/api.py` lines 94–107
- **Issue:** The `/query` endpoint has no auth. Anyone who knows the Container App URL can call it, consume Azure OpenAI tokens, and read internal promo data.
- **Impact:** Unlimited API abuse, token cost, data exfiltration.
- **Fix:** Add Entra ID bearer token validation, or at minimum restrict via Container App IP rules / API key header.
- **Status:** FIXED — Entra ID JWT validation via `app/auth.py` + `Depends(require_auth)` in `api.py`.

### 2. CORS defaults to `*` (allow all origins)
- **File:** `app/api.py` line 57
- **Issue:** If `CORS_ORIGINS` env var is not set, any website can call the API.
- **Impact:** Cross-origin data theft from any browser.
- **Fix:** Warn at startup when `CORS_ORIGINS=*` and `ENVIRONMENT != dev`. Set `CORS_ORIGINS=https://keshettv.sharepoint.com` on the Container App.
- **Status:** FIXED — startup warning added.

### 3. OpenAI client created on every request
- **File:** `app/chat_provider.py` lines 96–105, 215–223
- **Issue:** `get_provider()` creates a new provider + HTTP client per request. Under load this exhausts file descriptors.
- **Impact:** Connection pool exhaustion, service crash under concurrent load.
- **Fix:** Cache provider as a module-level singleton.
- **Status:** FIXED — singleton caching added.

---

## HIGH (should fix before prod)

### 4. No rate limiting
- **File:** `app/api.py`
- **Issue:** No rate limit on `/query`. A single user can fire hundreds of requests, burning Azure OpenAI quota.
- **Impact:** Quota exhaustion, 429 cascades, service degradation.
- **Fix:** Add `slowapi` rate limiter (10 req/min per IP default).
- **Status:** FIXED — slowapi added.

### 5. No request timeout on LLM calls
- **File:** `app/chat_provider.py` lines 99, 201
- **Issue:** `chat.completions.create()` has no timeout. A hung Azure OpenAI response blocks the worker indefinitely.
- **Impact:** All uvicorn workers stuck → app unresponsive.
- **Fix:** Add `timeout=60` to OpenAI calls.
- **Status:** FIXED.

### 6. `debug_trace` leaks full retrieval context
- **File:** `app/service.py` line 269, `app/models.py`
- **Issue:** The `debug` flag is a public API parameter. Anyone can set `"debug": true` and get full raw context.
- **Impact:** Internal data leakage (Excel data, Word doc chunks).
- **Fix:** Gate debug behind `ALLOW_DEBUG=true` env var (off by default in prod).
- **Status:** FIXED.

### 7. Dockerfile runs as root
- **File:** `Dockerfile`
- **Issue:** No `USER` directive — container runs as root.
- **Impact:** RCE in any dependency gives attacker full container access.
- **Fix:** Add non-root `appuser`.
- **Status:** FIXED.

### 8. Uvicorn runs with 1 worker
- **File:** `Dockerfile`
- **Issue:** Default single worker limits concurrent request handling.
- **Impact:** Poor throughput under real traffic.
- **Fix:** Use `WEB_CONCURRENCY` env var, default to 2 workers.
- **Status:** FIXED.

---

## MEDIUM (good to fix)

### 9. `.env.example` contains real resource names
- **File:** `.env.example`
- **Issue:** Real Azure resource names (`ai-search-keshet`, `azureopenaipilot`) reveal infrastructure layout.
- **Impact:** Low — not secrets, but aids reconnaissance.
- **Status:** Acknowledged — cosmetic.

### 10. `resp.choices[0].message.content` can be `None`
- **File:** `app/chat_provider.py` lines 105, 207
- **Issue:** If OpenAI content filter triggers, `.content` is `None` and `.strip()` crashes with `AttributeError`.
- **Impact:** Unhandled crash on filtered responses.
- **Fix:** `(content or "").strip()` with fallback message.
- **Status:** FIXED.

### 11. Search credentials read at module import time
- **File:** `app/search_word_docs.py` lines 32–33
- **Issue:** If env vars are injected after import, search fails silently with empty credentials.
- **Impact:** Low in containerized environments.
- **Status:** Acknowledged.

### 12. FastAPI docs exposed in production
- **File:** `app/api.py`
- **Issue:** `/docs` and `/openapi.json` reveal full API schema to anyone.
- **Impact:** API reconnaissance, schema leakage.
- **Fix:** Disable in non-dev environments via env var.
- **Status:** FIXED.

---

## What's Already Good (no changes needed)

- Input validation — `QueryRequest` has `min_length=1, max_length=2000`
- `.env` in `.gitignore` and `.dockerignore` — secrets won't leak
- Exception handlers return safe error envelopes without stack traces
- Search queries use parameterized SDK calls — no injection risk
- Azure Search has `connection_timeout` and `read_timeout` configured
- Test suite is thorough with multiple check types
- System prompt has strong grounding rules against hallucination

---

## Fix Priority

| # | Issue | Severity | Effort | Status |
|---|-------|----------|--------|--------|
| 1 | Add auth (Entra ID or API key) | CRITICAL | Medium | FIXED |
| 2 | CORS wildcard warning | CRITICAL | 5 min | FIXED |
| 3 | Cache provider singleton | CRITICAL | 10 min | FIXED |
| 4 | Add rate limiting | HIGH | 30 min | FIXED |
| 5 | Add LLM call timeout | HIGH | 5 min | FIXED |
| 6 | Gate debug in prod | HIGH | 10 min | FIXED |
| 7 | Non-root Dockerfile | HIGH | 5 min | FIXED |
| 8 | Uvicorn workers | HIGH | 5 min | FIXED |
| 9 | `.env.example` resource names | MEDIUM | — | Acknowledged |
| 10 | Handle None OpenAI content | MEDIUM | 2 min | FIXED |
| 11 | Import-time credentials | MEDIUM | — | Acknowledged |
| 12 | Disable FastAPI docs in prod | MEDIUM | 5 min | FIXED |
