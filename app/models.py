"""
models.py

Pydantic request / response types shared between the FastAPI layer
and the service layer.  Import these in api.py and service.py — never
import api.py or service.py from here.
"""

from __future__ import annotations

import os
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

# Maximum question length — set via MAX_QUESTION_LENGTH env var (default 500).
# 500 chars covers virtually all real user questions while preventing
# prompt-injection payloads and runaway token costs.
MAX_QUESTION_LENGTH: int = int(os.getenv("MAX_QUESTION_LENGTH", "500"))


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="User's question in Hebrew (or any language)")
    debug: bool = Field(False, description="If true, include full retrieval trace in response")

    @field_validator("question")
    @classmethod
    def check_question_length(cls, v: str) -> str:
        if len(v) > MAX_QUESTION_LENGTH:
            raise ValueError(
                f"Question is too long ({len(v)} chars). Maximum allowed is {MAX_QUESTION_LENGTH} characters."
            )
        return v


# ---------------------------------------------------------------------------
# Outbound — individual source citation
# ---------------------------------------------------------------------------


class SourceDoc(BaseModel):
    type: Literal["excel", "word"]
    title: str = Field("", description="File name or document title")
    reference: str = Field("", description="chunk_id for Word docs; 'show / season / date' for Excel")
    score: float = Field(0.0, description="Azure Search reranker score")


# ---------------------------------------------------------------------------
# Outbound — full query response
# ---------------------------------------------------------------------------


class QueryResponse(BaseModel):
    answer: str = Field(..., description="Grounded answer in Hebrew")
    route: str = Field(..., description="Router classification: excel_numeric | word_quote | hybrid | unknown")
    confidence: Literal["high", "medium", "low"] = Field(
        ...,
        description=(
            "Derived from retrieval quality. "
            "high: top source score > 0.85 | "
            "medium: any sources found | "
            "low: no relevant sources"
        ),
    )
    sources: list[SourceDoc] = Field(default_factory=list,
                                     description="Retrieved source citations")
    trace_id: str = Field(..., description="UUID for log correlation")
    debug_trace: str | None = Field(
        None,
        description="Full retrieval context (only present when debug=true)"
    )


# ---------------------------------------------------------------------------
# Error envelope  (used in exception handlers in api.py)
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    error: str
    trace_id: str | None = None
