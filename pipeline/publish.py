"""Publish PromoAgent pipeline to Azure AI Foundry.

Usage
-----
    # Step 1 — register individual agents in Foundry (needs aiohttp)
    python -m pipeline.publish --register-agents

    # Step 2 — register the workflow YAML as a WorkflowAgent (sync, works now)
    python -m pipeline.publish --register

    # Step 3 — publish as a managed Agent Application (sync)
    python -m pipeline.publish

    # Verify the deployed workflow responds correctly
    python -m pipeline.publish --verify

Required environment variables (.env)
--------------------------------------
    AZURE_AI_PROJECT_ENDPOINT       your Foundry project endpoint
    AZURE_AI_MODEL_DEPLOYMENT_NAME  model deployment name
    AZURE_SUBSCRIPTION_ID           Azure subscription ID       (publish only)
    AZURE_RESOURCE_GROUP            resource group name         (publish only)

Optional
--------
    AZURE_ACCOUNT_NAME   override the account name (auto-derived from endpoint)
    AZURE_PROJECT_NAME   override the project name (auto-derived from endpoint)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import httpx
from azure.identity import AzureCliCredential, DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import WorkflowAgentDefinition
from dotenv import load_dotenv

from pipeline.config import load_settings

YAML_PATH = Path(__file__).parent / "promo-pipeline.yaml"
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

WORKFLOW_AGENT = "PromoPipeline"
APP_NAME       = "promo-pipeline-app"
DEPLOY_NAME    = "promo-pipeline-deployment"
ARM_API_VER    = "2025-10-01-preview"
AI_API_VER     = "2025-11-15-preview"


def _get_credential():
    cred_type = os.getenv("AZURE_CREDENTIAL_TYPE", "cli").lower()
    if cred_type == "default":
        return DefaultAzureCredential()
    return AzureCliCredential()


def _derive_names(endpoint: str):
    """Extract account and project names from the Foundry endpoint URL."""
    host    = endpoint.split("/")[2]                       # e.g. Keshet-Foundry.services.ai.azure.com
    account = os.environ.get("AZURE_ACCOUNT_NAME") or host.split(".")[0]
    project = os.environ.get("AZURE_PROJECT_NAME") or endpoint.rstrip("/").split("/")[-1]
    return account, project


# ---------------------------------------------------------------------------
# Step 1: register individual prompt agents (async — needs aiohttp)
# ---------------------------------------------------------------------------

async def register_agents(settings):
    """Register PromoRetriever and PromoAnswer in Foundry.

    Requires aiohttp and agent-framework-foundry.
    If aiohttp is blocked by your network, register the agents manually
    in the Foundry portal using the instructions from pipeline/agents.py.
    """
    try:
        from azure.identity.aio import AzureCliCredential as AsyncCliCredential
        from agent_framework.azure import AzureAIProjectAgentProvider
        from pipeline.agents import create_retriever, create_answer_agent
    except ImportError as exc:
        logger.error(
            f"\nCannot import async dependencies: {exc}\n"
            "  → Register agents manually in the Foundry portal instead:\n"
            "      1. Go to https://ai.azure.com → your project → Agents\n"
            "      2. Create 'PromoRetriever' with instructions from pipeline/agents.py\n"
            "      3. Create 'PromoAnswer'     with instructions from pipeline/agents.py\n"
        )
        return

    credential = AsyncCliCredential()
    async with AzureAIProjectAgentProvider(
        project_endpoint=settings.project_endpoint,
        credential=credential,
    ) as provider:
        logger.info("Registering PromoRetriever ...")
        retriever = await create_retriever(provider, model=settings.model_deployment)
        logger.info(f"  ✓ PromoRetriever registered (id={getattr(retriever, 'id', '?')})")

        logger.info("Registering PromoAnswer ...")
        answerer = await create_answer_agent(provider, model=settings.model_deployment)
        logger.info(f"  ✓ PromoAnswer registered (id={getattr(answerer, 'id', '?')})")

    await credential.close()


# ---------------------------------------------------------------------------
# Step 2: register the workflow YAML as a WorkflowAgent (sync)
# ---------------------------------------------------------------------------

def register_workflow(settings, credential) -> str:
    """Register promo-pipeline.yaml as a WorkflowAgent in Foundry.

    Uses the sync AIProjectClient — no aiohttp required.
    Returns the registered version string (e.g. 'PromoPipeline:1').
    """
    client = AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=credential,
    )
    yaml_text = YAML_PATH.read_text(encoding="utf-8")
    version = client.agents.create_version(
        agent_name=WORKFLOW_AGENT,
        definition=WorkflowAgentDefinition(workflow=yaml_text),
    )
    vid = f"{version.name}:{version.version}"
    logger.info(f"  ✓ Workflow agent registered: {vid}")
    return vid


# ---------------------------------------------------------------------------
# Step 3: publish as a managed Agent Application (sync via httpx)
# ---------------------------------------------------------------------------

def publish_app(settings, credential, version_id: str):
    """Publish the workflow as a managed Agent Application in Foundry.

    Requires AZURE_SUBSCRIPTION_ID and AZURE_RESOURCE_GROUP in .env.
    """
    sub = settings.subscription_id
    rg  = settings.resource_group
    if not sub or not rg:
        logger.warning(
            "\n  ⚠  AZURE_SUBSCRIPTION_ID and AZURE_RESOURCE_GROUP are required to publish.\n"
            "     Add them to .env and re-run without --register.\n"
            "     The workflow agent is already registered and usable via the Foundry portal."
        )
        return

    ep      = settings.project_endpoint.rstrip("/")
    account, project = _derive_names(ep)

    arm_base = (
        f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}"
        f"/providers/Microsoft.CognitiveServices/accounts/{account}/projects/{project}"
    )
    ai_base = f"https://{account}.services.ai.azure.com/api/projects/{project}"

    token = credential.get_token("https://management.azure.com/.default").token
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    agent_name, agent_ver = version_id.rsplit(":", 1)

    steps = [
        (
            f"{arm_base}/applications/{APP_NAME}?api-version={ARM_API_VER}",
            {
                "properties": {
                    "displayName": "Promo Pipeline",
                    "agents": [{"agentName": agent_name}],
                }
            },
        ),
        (
            f"{arm_base}/applications/{APP_NAME}/agentdeployments/{DEPLOY_NAME}"
            f"?api-version={ARM_API_VER}",
            {
                "properties": {
                    "deploymentType": "Managed",
                    "protocols": [{"protocol": "responses", "version": "1.0"}],
                    "agents": [{"agentName": agent_name, "agentVersion": agent_ver}],
                }
            },
        ),
    ]

    with httpx.Client(timeout=60) as client:
        for url, body in steps:
            r = client.put(url, headers=headers, json=body)
            assert r.status_code in (200, 201), f"ERROR {r.status_code}: {r.text[:300]}"

    invoke_url = (
        f"{ai_base}/openai/responses?api-version={AI_API_VER}"
    )
    logger.info(f"  ✓ Published — invoke via:\n     POST {invoke_url}")
    logger.info(f'     body: {{"input": "שאלה כאן", "agent": {{"name": "{agent_name}", "type": "agent_reference"}}}}')


# ---------------------------------------------------------------------------
# Verify: send a test question to the deployed workflow
# ---------------------------------------------------------------------------

async def verify(settings, credential):
    token = credential.get_token("https://ai.azure.com/.default").token
    ep = settings.project_endpoint.rstrip("/")
    account, project = _derive_names(ep)
    ai_base = f"https://{account}.services.ai.azure.com/api/projects/{project}"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120) as c:
        conv = (
            await c.post(
                f"{ai_base}/openai/conversations?api-version={AI_API_VER}",
                headers=headers, json={},
            )
        ).json()["id"]

        r = await c.post(
            f"{ai_base}/openai/responses?api-version={AI_API_VER}",
            headers=headers,
            json={
                "input": "מה הרייטינג הממוצע של חתונה ממבט ראשון?",
                "agent": {"name": WORKFLOW_AGENT, "type": "agent_reference"},
                "store": True,
                "conversation": {"id": conv},
            },
        )
    assert r.status_code == 200, f"ERROR {r.status_code}: {r.text[:300]}"
    logger.info(json.dumps(r.json(), indent=2)[:3000])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Publish PromoAgent pipeline to Foundry")
    ap.add_argument("--register-agents", action="store_true",
                    help="Register PromoRetriever + PromoAnswer agents (needs aiohttp)")
    ap.add_argument("--register", action="store_true",
                    help="Register the workflow YAML only (sync, no aiohttp)")
    ap.add_argument("--verify", action="store_true",
                    help="Send a test question to the deployed workflow")
    args = ap.parse_args()

    settings   = load_settings()
    credential = _get_credential()

    if args.register_agents:
        asyncio.run(register_agents(settings))
        return

    if args.verify:
        asyncio.run(verify(settings, credential))
        return

    logger.info("\nPublishing PromoAgent pipeline to Foundry")
    logger.info(f"  endpoint : {settings.project_endpoint}")
    logger.info(f"  model    : {settings.model_deployment}\n")

    version_id = register_workflow(settings, credential)

    if args.register:
        logger.info("\nDone — workflow registered. Run without --register to also publish as an App.")
        return

    publish_app(settings, credential, version_id)
    logger.info("\nDone.")


if __name__ == "__main__":
    main()
