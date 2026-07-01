"""
Offline tests for the per-model-family completion parameter style in
app/chat_provider.py.

Regression context (2026-06-11): switching the Foundry deployment to a gpt-5
family model (e.g. gpt-5.4-mini) breaks with HTTP 400 if the provider keeps
sending temperature=0 / seed / max_tokens — reasoning models require
max_completion_tokens and default temperature. The name heuristic must catch
gpt-5*/o-series names WITHOUT misclassifying gpt-4o / gpt-4o-mini.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.chat_provider import _completion_kwargs, _is_reasoning_model, _prompt_cache_kwargs  # noqa: E402


CLASSIC_NAMES = ["gpt-4o", "gpt-4o-1", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-35-turbo"]
REASONING_NAMES = ["gpt-5.4-mini", "gpt-5-4-mini", "gpt-5.4", "gpt-5", "gpt5-nano", "o1", "o3-mini", "o4-mini", "keshet-o3"]


def test_classic_names_not_detected_as_reasoning(monkeypatch):
    monkeypatch.delenv("MODEL_PARAM_STYLE", raising=False)
    for name in CLASSIC_NAMES:
        assert not _is_reasoning_model(name), name


def test_reasoning_names_detected(monkeypatch):
    monkeypatch.delenv("MODEL_PARAM_STYLE", raising=False)
    for name in REASONING_NAMES:
        assert _is_reasoning_model(name), name


def test_classic_kwargs_shape(monkeypatch):
    monkeypatch.delenv("MODEL_PARAM_STYLE", raising=False)
    kw = _completion_kwargs("gpt-4o-1")
    assert kw["temperature"] == 0
    assert "seed" in kw and "max_tokens" in kw
    assert "max_completion_tokens" not in kw and "reasoning_effort" not in kw


def test_reasoning_kwargs_shape(monkeypatch):
    monkeypatch.delenv("MODEL_PARAM_STYLE", raising=False)
    kw = _completion_kwargs("gpt-5.4-mini")
    assert "max_completion_tokens" in kw
    # reasoning models reject these:
    assert "temperature" not in kw and "seed" not in kw and "max_tokens" not in kw


def test_param_style_env_override(monkeypatch):
    # A deployment named without the family (e.g. "promo-chat-prod") can be
    # forced to the reasoning style, and vice versa.
    monkeypatch.setenv("MODEL_PARAM_STYLE", "reasoning")
    assert _is_reasoning_model("promo-chat-prod")
    monkeypatch.setenv("MODEL_PARAM_STYLE", "classic")
    assert not _is_reasoning_model("gpt-5.4-mini")


def test_prompt_cache_kwargs_enabled_by_default(monkeypatch):
    """Repeated prod prompts should route toward the same prompt-cache shard."""
    monkeypatch.delenv("PROMPT_CACHE_ENABLED", raising=False)
    monkeypatch.delenv("PROMPT_CACHE_KEY", raising=False)
    monkeypatch.delenv("PROMPT_CACHE_RETENTION", raising=False)

    kw = _prompt_cache_kwargs("gpt-5.4-mini")

    assert kw == {
        "extra_body": {
            "prompt_cache_key": "promobot:gpt-5.4-mini:system-prompt",
            "prompt_cache_retention": "24h",
        }
    }


def test_prompt_cache_kwargs_can_be_disabled_or_overridden(monkeypatch):
    monkeypatch.setenv("PROMPT_CACHE_ENABLED", "false")
    assert _prompt_cache_kwargs("gpt-5.4-mini") == {}

    monkeypatch.setenv("PROMPT_CACHE_ENABLED", "true")
    monkeypatch.setenv("PROMPT_CACHE_KEY", "custom-key")
    monkeypatch.setenv("PROMPT_CACHE_RETENTION", "in_memory")

    assert _prompt_cache_kwargs("promo-chat-prod") == {
        "extra_body": {
            "prompt_cache_key": "custom-key",
            "prompt_cache_retention": "in_memory",
        }
    }
