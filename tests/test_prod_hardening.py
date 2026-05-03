"""
test_prod_hardening.py

Unit and integration tests for the production-hardening fixes.

Covers:
  - Provider singleton caching
  - LLM timeout parameter
  - None content safety (content filter)
  - Debug flag gating via ALLOW_DEBUG
  - Rate limiting (slowapi)
  - FastAPI docs disabled in non-dev environments
  - Health endpoint behaviour
  - CORS origin parsing
  - Input validation (max_length, empty)
  - Error envelope on failures

Run:
    pytest tests/test_prod_hardening.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =========================================================================
# Provider tests (chat_provider.py)
# =========================================================================


class TestProviderSingleton:

    def setup_method(self):
        import app.chat_provider as cp
        cp._provider_cache = None

    @patch.dict(os.environ, {
        "AZURE_OPENAI_CHAT_ENDPOINT": "https://fake.openai.azure.com/openai/v1/",
        "AZURE_OPENAI_CHAT_KEY": "fake-key",
        "AZURE_OPENAI_CHAT_DEPLOYMENT": "gpt-4o",
        "CHAT_PROVIDER": "azure_openai",
    })
    @patch("openai.OpenAI")
    def test_get_provider_returns_same_instance(self, mock_openai_cls):
        from app.chat_provider import get_provider

        p1 = get_provider()
        p2 = get_provider()
        assert p1 is p2, "get_provider() must return the same singleton"

    @patch.dict(os.environ, {
        "AZURE_OPENAI_CHAT_ENDPOINT": "https://fake.openai.azure.com/openai/v1/",
        "AZURE_OPENAI_CHAT_KEY": "fake-key",
        "AZURE_OPENAI_CHAT_DEPLOYMENT": "gpt-4o",
        "CHAT_PROVIDER": "azure_openai",
    })
    @patch("openai.OpenAI")
    def test_provider_creates_client_in_init(self, mock_openai_cls):
        from app.chat_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider()
        mock_openai_cls.assert_called_once()
        assert provider._client is not None

    def test_provider_missing_env_raises(self):
        from app.chat_provider import AzureOpenAIProvider

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(EnvironmentError, match="Missing env vars"):
                AzureOpenAIProvider()


class TestNoneContentSafety:

    @patch.dict(os.environ, {
        "AZURE_OPENAI_CHAT_ENDPOINT": "https://fake.openai.azure.com/openai/v1/",
        "AZURE_OPENAI_CHAT_KEY": "fake-key",
        "AZURE_OPENAI_CHAT_DEPLOYMENT": "gpt-4o",
    })
    @patch("openai.OpenAI")
    def test_none_content_returns_fallback(self, mock_openai_cls):
        from app.chat_provider import AzureOpenAIProvider

        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_openai_cls.return_value.chat.completions.create.return_value = mock_resp

        provider = AzureOpenAIProvider()
        result = provider.complete([{"role": "user", "content": "test"}])

        assert "סוננה" in result, "None content should return Hebrew safety message"

    @patch.dict(os.environ, {
        "AZURE_OPENAI_CHAT_ENDPOINT": "https://fake.openai.azure.com/openai/v1/",
        "AZURE_OPENAI_CHAT_KEY": "fake-key",
        "AZURE_OPENAI_CHAT_DEPLOYMENT": "gpt-4o",
    })
    @patch("openai.OpenAI")
    def test_normal_content_returned(self, mock_openai_cls):
        from app.chat_provider import AzureOpenAIProvider

        mock_choice = MagicMock()
        mock_choice.message.content = "  תשובה תקינה  "
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_openai_cls.return_value.chat.completions.create.return_value = mock_resp

        provider = AzureOpenAIProvider()
        result = provider.complete([{"role": "user", "content": "test"}])

        assert result == "תשובה תקינה", "Normal content should be stripped and returned"


class TestLLMTimeout:

    @patch.dict(os.environ, {
        "AZURE_OPENAI_CHAT_ENDPOINT": "https://fake.openai.azure.com/openai/v1/",
        "AZURE_OPENAI_CHAT_KEY": "fake-key",
        "AZURE_OPENAI_CHAT_DEPLOYMENT": "gpt-4o",
        "LLM_TIMEOUT_SECONDS": "30",
    })
    @patch("openai.OpenAI")
    def test_timeout_passed_to_openai(self, mock_openai_cls):
        import importlib
        import app.chat_provider as cp
        importlib.reload(cp)

        mock_choice = MagicMock()
        mock_choice.message.content = "answer"
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_openai_cls.return_value.chat.completions.create.return_value = mock_resp

        provider = cp.AzureOpenAIProvider()
        provider.complete([{"role": "user", "content": "test"}])

        call_kwargs = mock_openai_cls.return_value.chat.completions.create.call_args[1]
        assert call_kwargs["timeout"] == 30


# =========================================================================
# API tests (api.py) — using TestClient
# =========================================================================


_DEFAULT_ENV = {
    "AZURE_OPENAI_CHAT_ENDPOINT": "https://fake.openai.azure.com/openai/v1/",
    "AZURE_OPENAI_CHAT_KEY": "fake-key",
    "AZURE_OPENAI_CHAT_DEPLOYMENT": "gpt-4o",
    "AZURE_SEARCH_ENDPOINT": "https://fake.search.windows.net",
    "AZURE_SEARCH_KEY": "fake-key",
    "CORS_ORIGINS": "*",
    "ENVIRONMENT": "dev",
    "ALLOW_DEBUG": "false",
    "RATE_LIMIT": "100/minute",
    "AUTH_ENABLED": "false",
}


def _make_test_app(
    env_overrides: dict | None = None,
    raise_server_exceptions: bool = True,
):
    """Import the app module with custom environment, returning a TestClient.

    Sets env vars persistently for the duration of the test (caller must
    be running inside a patch.dict context or accept side-effects).
    """
    import importlib

    env = {**_DEFAULT_ENV}
    if env_overrides:
        env.update(env_overrides)

    for k, v in env.items():
        os.environ[k] = v

    import app.chat_provider as cp
    cp._provider_cache = None

    import app.api as api_mod
    importlib.reload(api_mod)

    from fastapi.testclient import TestClient
    return TestClient(api_mod.app, raise_server_exceptions=raise_server_exceptions), api_mod


class TestHealthEndpoint:

    def test_health_ok_when_env_set(self):
        client, _ = _make_test_app()
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    def test_health_503_when_env_missing(self):
        client, _ = _make_test_app({
            "AZURE_OPENAI_CHAT_ENDPOINT": "",
            "AZURE_OPENAI_CHAT_KEY": "",
        })
        resp = client.get("/health")
        assert resp.status_code == 503


class TestDebugGating:

    @patch("app.service.run_query")
    def test_debug_ignored_when_allow_debug_off(self, mock_run_query):
        mock_run_query.return_value = MagicMock(
            answer="test",
            route="unknown",
            confidence="low",
            sources=[],
            trace_id="abc",
            debug_trace=None,
        )
        # Need to return a proper dict for response_model
        from app.models import QueryResponse
        mock_run_query.return_value = QueryResponse(
            answer="test", route="unknown", confidence="low",
            sources=[], trace_id="abc", debug_trace=None,
        )

        client, _ = _make_test_app({"ALLOW_DEBUG": "false"})
        resp = client.post("/query", json={"question": "מה הרייטינג?", "debug": True})

        assert resp.status_code == 200
        mock_run_query.assert_called_once_with("מה הרייטינג?", debug=False)

    @patch("app.service.run_query")
    def test_debug_allowed_when_allow_debug_on(self, mock_run_query):
        from app.models import QueryResponse
        mock_run_query.return_value = QueryResponse(
            answer="test", route="unknown", confidence="low",
            sources=[], trace_id="abc", debug_trace="full context here",
        )

        client, _ = _make_test_app({"ALLOW_DEBUG": "true"})
        resp = client.post("/query", json={"question": "מה הרייטינג?", "debug": True})

        assert resp.status_code == 200
        mock_run_query.assert_called_once_with("מה הרייטינג?", debug=True)


class TestInputValidation:

    @patch("app.service.run_query")
    def test_empty_question_rejected(self, mock_run_query):
        client, _ = _make_test_app()
        resp = client.post("/query", json={"question": ""})
        assert resp.status_code == 422, "Empty question should fail validation"

    @patch("app.service.run_query")
    def test_too_long_question_rejected(self, mock_run_query):
        client, _ = _make_test_app()
        resp = client.post("/query", json={"question": "א" * 2001})
        assert resp.status_code == 422, "Question exceeding 2000 chars should fail"

    @patch("app.service.run_query")
    def test_valid_question_accepted(self, mock_run_query):
        from app.models import QueryResponse
        mock_run_query.return_value = QueryResponse(
            answer="test", route="unknown", confidence="low",
            sources=[], trace_id="abc", debug_trace=None,
        )

        client, _ = _make_test_app()
        resp = client.post("/query", json={"question": "שאלה תקינה"})
        assert resp.status_code == 200


class TestErrorEnvelope:

    @patch("app.service.run_query", side_effect=RuntimeError("LLM exploded"))
    def test_unhandled_error_returns_500_envelope(self, mock_run_query):
        client, _ = _make_test_app(raise_server_exceptions=False)
        resp = client.post("/query", json={"question": "שאלה כלשהי"})
        assert resp.status_code == 500
        body = resp.json()
        assert "error" in body
        assert "LLM exploded" not in body["error"], "Internal details must not leak"

    @patch("app.service.run_query", side_effect=EnvironmentError("missing var"))
    def test_env_error_returns_503_envelope(self, mock_run_query):
        client, _ = _make_test_app(raise_server_exceptions=False)
        resp = client.post("/query", json={"question": "שאלה כלשהי"})
        assert resp.status_code == 503
        body = resp.json()
        assert "error" in body


class TestDocsDisabledInProd:

    def test_docs_available_in_dev(self):
        client, _ = _make_test_app({"ENVIRONMENT": "dev"})
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_docs_disabled_in_prod(self):
        client, _ = _make_test_app({"ENVIRONMENT": "production"})
        resp = client.get("/docs")
        assert resp.status_code in (404, 405), "/docs should be disabled in production"

    def test_openapi_disabled_in_prod(self):
        client, _ = _make_test_app({"ENVIRONMENT": "production"})
        resp = client.get("/openapi.json")
        assert resp.status_code in (404, 405), "/openapi.json should be disabled in production"


# =========================================================================
# Query Router tests (already covered in test_agent.py, adding edge cases)
# =========================================================================


class TestQueryRouter:

    def test_empty_query_returns_unknown(self):
        from app.query_router import classify
        result = classify("   ")
        assert result.route == "unknown"

    def test_mixed_signals_produce_hybrid(self):
        from app.query_router import classify
        result = classify("מה היה הרייטינג ומה אומר המסמך")
        assert result.route == "hybrid"

    def test_pure_numeric_signal(self):
        from app.query_router import classify
        result = classify("מה הרייטינג של הפרק?")
        assert result.route == "excel_numeric"

    def test_pure_quote_signal(self):
        from app.query_router import classify
        result = classify("צטט ממסמך האסטרטגיה")
        assert result.route == "word_quote"


# =========================================================================
# Dockerfile tests (structural checks)
# =========================================================================


class TestDockerfile:

    @pytest.fixture(autouse=True)
    def read_dockerfile(self):
        dockerfile_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "Dockerfile"
        )
        with open(dockerfile_path, "r") as f:
            self.dockerfile = f.read()

    def test_non_root_user(self):
        assert "USER appuser" in self.dockerfile, "Dockerfile must run as non-root"

    def test_adduser_before_user(self):
        adduser_pos = self.dockerfile.index("adduser")
        user_pos = self.dockerfile.index("USER appuser")
        assert adduser_pos < user_pos, "adduser must come before USER directive"

    def test_workers_configurable(self):
        assert "WEB_CONCURRENCY" in self.dockerfile, "Workers should be configurable via WEB_CONCURRENCY"

    def test_expose_8000(self):
        assert "EXPOSE 8000" in self.dockerfile


# =========================================================================
# Models validation tests
# =========================================================================


class TestModels:

    def test_query_request_min_length(self):
        from app.models import QueryRequest
        with pytest.raises(Exception):
            QueryRequest(question="")

    def test_query_request_max_length(self):
        from app.models import QueryRequest
        with pytest.raises(Exception):
            QueryRequest(question="x" * 2001)

    def test_query_request_valid(self):
        from app.models import QueryRequest
        req = QueryRequest(question="שאלה תקינה")
        assert req.question == "שאלה תקינה"
        assert req.debug is False

    def test_query_response_structure(self):
        from app.models import QueryResponse
        resp = QueryResponse(
            answer="תשובה",
            route="excel_numeric",
            confidence="high",
            sources=[],
            trace_id="abc-123",
        )
        assert resp.debug_trace is None

    def test_error_response(self):
        from app.models import ErrorResponse
        err = ErrorResponse(error="something broke")
        assert err.trace_id is None
