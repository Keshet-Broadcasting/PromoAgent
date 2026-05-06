"""
chat_provider.py

Provider abstraction for the chat/LLM execution layer only.

Everything upstream of this file (routing, retrieval, formatting, prompt
assembly) is unchanged.  Only the final "send messages → get text" step
is delegated to the provider selected by CHAT_PROVIDER.

Providers
---------
azure_openai  (default)
    Wraps the current Azure OpenAI path via the openai SDK.
    Auth: API key from AZURE_OPENAI_CHAT_KEY.

foundry
    Wraps Azure AI Foundry via AIProjectClient (azure-ai-projects).
    Gets an OpenAI-compatible client from the project and calls
    chat.completions.create() — same message format, no aiohttp required.
    Auth: Azure credential (AzureCliCredential locally,
          ManagedIdentityCredential / DefaultAzureCredential on Azure).
    Requires: pip install azure-ai-projects azure-identity

Environment variables
---------------------
CHAT_PROVIDER                   azure_openai | foundry  (default: azure_openai)
AZURE_CREDENTIAL_TYPE           cli | managed_identity | default
                                (default: cli, Foundry only)

Azure OpenAI provider
    AZURE_OPENAI_CHAT_ENDPOINT
    AZURE_OPENAI_CHAT_KEY
    AZURE_OPENAI_CHAT_DEPLOYMENT

Foundry provider
    AZURE_AI_PROJECT_ENDPOINT        Foundry project endpoint URL.
                                     Format: https://<resource>.services.ai.azure.com/api/projects/<project>
                                     Example: https://Keshet-Foundry.services.ai.azure.com/api/projects/Keshet-AI-Foundry
    AZURE_AI_MODEL_DEPLOYMENT_NAME   deployment name in Foundry (e.g. gpt-4o-1)

    Aliases accepted as fallbacks:
    FOUNDRY_PROJECT_ENDPOINT
    FOUNDRY_MODEL_DEPLOYMENT_NAME
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class ChatProvider(ABC):
    """Minimal contract: accept a messages list, return the answer string.

    The messages list is in standard OpenAI format:
        [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]

    build_messages() in prompts.py always produces exactly this shape.
    """

    @abstractmethod
    def complete(self, messages: list[dict]) -> str:
        """Send messages to the model and return the response text."""


# ---------------------------------------------------------------------------
# Azure OpenAI implementation  (current default)
# ---------------------------------------------------------------------------


_LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))


class AzureOpenAIProvider(ChatProvider):
    """Azure OpenAI via the openai SDK — key-based auth, no changes to existing logic."""

    def __init__(self) -> None:
        missing = [v for v in [
            "AZURE_OPENAI_CHAT_ENDPOINT",
            "AZURE_OPENAI_CHAT_KEY",
            "AZURE_OPENAI_CHAT_DEPLOYMENT",
        ] if not os.getenv(v)]
        if missing:
            raise EnvironmentError(
                f"Missing env vars for azure_openai provider: {', '.join(missing)}"
            )
        self.endpoint   = os.environ["AZURE_OPENAI_CHAT_ENDPOINT"]
        self.api_key    = os.environ["AZURE_OPENAI_CHAT_KEY"]
        self.deployment = os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"]

        from openai import OpenAI
        self._client = OpenAI(base_url=self.endpoint, api_key=self.api_key)

    def complete(self, messages: list[dict]) -> str:
        resp = self._client.chat.completions.create(
            model=self.deployment,
            messages=messages,
            temperature=0,
            max_tokens=1500,
            timeout=_LLM_TIMEOUT,
        )
        content = resp.choices[0].message.content
        if not content:
            return "התשובה סוננה על ידי מערכת הבטיחות. נסה לנסח מחדש את השאלה."
        return content.strip()


# ---------------------------------------------------------------------------
# Microsoft Foundry implementation  (azure-ai-projects)
# ---------------------------------------------------------------------------


class FoundryProvider(ChatProvider):
    """Azure AI Foundry via AIProjectClient (azure-ai-projects).

    Uses the sync AIProjectClient to obtain an OpenAI-compatible client,
    then calls chat.completions.create() with the same messages format as
    AzureOpenAIProvider — zero changes to the pipeline upstream.

    This approach matches the pattern shown in the Azure AI Foundry portal:

        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
        openai_client = client.get_openai_client()
        response = openai_client.chat.completions.create(model=..., messages=...)

    No aiohttp, no asyncio bridging, no agent_framework package required.
    """

    def __init__(self) -> None:
        self.endpoint = (
            os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
            or os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
            or ""
        )
        self.model = (
            os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
            or os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME")
            or ""
        )
        if not self.endpoint or not self.model:
            raise EnvironmentError(
                "Foundry provider requires:\n"
                "  AZURE_AI_PROJECT_ENDPOINT  (or FOUNDRY_PROJECT_ENDPOINT)\n"
                "  AZURE_AI_MODEL_DEPLOYMENT_NAME  (or FOUNDRY_MODEL_DEPLOYMENT_NAME)"
            )
        self._credential = None   # lazy init
        self._openai_client = None  # cached across requests — avoids per-call AIProjectClient overhead

    def _get_credential(self):
        """Return the Azure credential instance, created once per provider lifetime.

        AZURE_CREDENTIAL_TYPE=cli               → AzureCliCredential  (requires: az login)
        AZURE_CREDENTIAL_TYPE=managed_identity  → ManagedIdentityCredential  (Azure-hosted)
        AZURE_CREDENTIAL_TYPE=default           → DefaultAzureCredential  (auto-chain, recommended for prod)
        """
        if self._credential is not None:
            return self._credential

        try:
            from azure.identity import (
                AzureCliCredential,
                DefaultAzureCredential,
                ManagedIdentityCredential,
            )
        except ImportError as exc:
            raise ImportError(
                "azure-identity is required for the Foundry provider. "
                "Run: pip install azure-identity"
            ) from exc

        cred_type = os.getenv("AZURE_CREDENTIAL_TYPE", "default").lower()
        if cred_type == "managed_identity":
            self._credential = ManagedIdentityCredential()
            log.info("Foundry auth: ManagedIdentityCredential")
        elif cred_type == "default":
            self._credential = DefaultAzureCredential()
            log.info("Foundry auth: DefaultAzureCredential")
        else:
            self._credential = AzureCliCredential()
            log.info("Foundry auth: AzureCliCredential (run 'az login' if not authenticated)")

        return self._credential

    def _get_openai_client(self):
        """Return the OpenAI-compatible client, created once and reused.

        Building AIProjectClient + calling get_openai_client() on every request
        adds ~2–5 s of overhead (HTTP handshake + endpoint discovery).  Caching
        it here keeps that cost as a one-time startup payment.
        """
        if self._openai_client is not None:
            return self._openai_client

        try:
            from azure.ai.projects import AIProjectClient
        except ImportError as exc:
            raise ImportError(
                "azure-ai-projects is required for the Foundry provider. "
                "Run: pip install azure-ai-projects"
            ) from exc

        credential = self._get_credential()
        project_client = AIProjectClient(
            endpoint=self.endpoint,
            credential=credential,
        )
        self._openai_client = project_client.get_openai_client()
        log.info("Foundry OpenAI client initialized and cached")
        return self._openai_client

    def complete(self, messages: list[dict]) -> str:
        openai_client = self._get_openai_client()
        resp = openai_client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0,
            max_tokens=1500,
            timeout=_LLM_TIMEOUT,
        )
        content = resp.choices[0].message.content
        if not content:
            return "התשובה סוננה על ידי מערכת הבטיחות. נסה לנסח מחדש את השאלה."
        return content.strip()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


_provider_cache: ChatProvider | None = None


def get_provider() -> ChatProvider:
    """Return the configured provider instance (singleton).

    The instance is created on first call and reused for all subsequent
    requests, keeping the underlying HTTP connection pool alive.
    """
    global _provider_cache
    if _provider_cache is None:
        name = os.getenv("CHAT_PROVIDER", "azure_openai").lower()
        if name == "foundry":
            _provider_cache = FoundryProvider()
        else:
            _provider_cache = AzureOpenAIProvider()
        log.info("Chat provider initialized: %s", type(_provider_cache).__name__)
    return _provider_cache
