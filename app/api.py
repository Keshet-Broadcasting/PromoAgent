"""
api.py

FastAPI application for the Promo department agent.

Endpoints
---------
    GET  /health       — liveness / readiness check
    POST /query        — main question-answering endpoint

Running locally
---------------
    uvicorn app.api:app --reload --host 0.0.0.0 --port 8000

Environment variables
---------------------
    CORS_ORIGINS   comma-separated allowed origins, default "*" (restrict in production)
                   Example: https://yourtenant.sharepoint.com,https://yourtenant-admin.sharepoint.com
    API_HOST       bind address (default 0.0.0.0)
    API_PORT       port        (default 8000)

Authentication
--------------
    Entra ID bearer-token validation is NOT yet wired — a placeholder comment marks
    the insertion point.  Add azure-identity + a FastAPI dependency that validates
    the Authorization: Bearer <token> header before the /query handler runs.

SharePoint integration notes
-----------------------------
    1. Set CORS_ORIGINS to your SharePoint tenant domain(s).
    2. The response JSON is intentionally flat and JS-friendly.
    3. The trace_id field lets you correlate browser-side errors with server logs.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .auth import require_auth
from .models import ErrorResponse, QueryRequest, QueryResponse
from .service import run_query

load_dotenv()

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

_ENVIRONMENT = os.getenv("ENVIRONMENT", "dev").lower()
_ALLOW_DEBUG = os.getenv("ALLOW_DEBUG", "false").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# CORS — read allowed origins from env so nothing is hard-coded
# ---------------------------------------------------------------------------

_raw_origins = os.getenv("CORS_ORIGINS", "*")
_CORS_ORIGINS: list[str] = (
    ["*"] if _raw_origins.strip() == "*"
    else [o.strip() for o in _raw_origins.split(",") if o.strip()]
)

if _CORS_ORIGINS == ["*"] and _ENVIRONMENT != "dev":
    log.warning(
        "CORS_ORIGINS is set to '*' in a non-dev environment (%s). "
        "Set CORS_ORIGINS to your SharePoint domain(s) for production.",
        _ENVIRONMENT,
    )

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

_RATE_LIMIT = os.getenv("RATE_LIMIT", "10/minute")

limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    log.info("Promo Agent API starting — env=%s  CORS origins: %s", _ENVIRONMENT, _CORS_ORIGINS)
    yield
    log.info("Promo Agent API shutting down")


_docs_kwargs: dict = {}
if _ENVIRONMENT != "dev":
    _docs_kwargs = dict(docs_url=None, redoc_url=None, openapi_url=None)

app = FastAPI(
    title="Promo Agent API",
    version="1.0.0",
    description="Internal RAG agent for the Promo department. Answers questions from Excel and Word sources.",
    lifespan=_lifespan,
    **_docs_kwargs,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


# ---------------------------------------------------------------------------
# Auth — Entra ID bearer-token validation (see app/auth.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Exception handlers — always return the ErrorResponse envelope
# ---------------------------------------------------------------------------


@app.exception_handler(EnvironmentError)
async def env_error_handler(request: Request, exc: EnvironmentError) -> JSONResponse:
    log.error("Configuration error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=ErrorResponse(error=str(exc)).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error processing request")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(error="Internal server error — check server logs").model_dump(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["ops"])
async def health() -> dict:
    """Liveness / readiness probe.

    Returns 200 when the service is running and config is present.
    Used by load balancers, Azure App Service health checks, etc.
    """
    cfg_ok = all([
        os.getenv("AZURE_OPENAI_CHAT_ENDPOINT"),
        os.getenv("AZURE_OPENAI_CHAT_KEY"),
        os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        os.getenv("AZURE_SEARCH_ENDPOINT"),
        os.getenv("AZURE_SEARCH_KEY"),
    ])
    if not cfg_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="One or more required environment variables are missing",
        )
    return {"status": "ok", "service": "promo-agent", "version": app.version}


@app.post(
    "/query",
    response_model=QueryResponse,
    tags=["agent"],
    summary="Ask the Promo Agent a question",
    response_description="Grounded answer with source citations and routing metadata",
    dependencies=[Depends(require_auth)],
)
@limiter.limit(_RATE_LIMIT)
def query(request: Request, req: QueryRequest) -> QueryResponse:
    """Run the full RAG pipeline and return a structured answer.

    Declared as a plain ``def`` (not ``async def``) so FastAPI automatically
    runs it in a thread-pool via ``run_in_executor``.  This prevents the
    synchronous LLM call from blocking the uvicorn event loop.
    """
    effective_debug = req.debug and _ALLOW_DEBUG
    if req.debug and not _ALLOW_DEBUG:
        log.info("POST /query  debug requested but ALLOW_DEBUG is off — ignoring")
    log.info("POST /query  question=%r  debug=%s", req.question[:80], effective_debug)
    return run_query(req.question, debug=effective_debug)
