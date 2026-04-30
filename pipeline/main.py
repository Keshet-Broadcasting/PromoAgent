"""Entry point — wires config, agents, and workflow together.

Two execution modes:
  1. Full async pipeline (PromoRetriever → PromoAnswer via WorkflowBuilder)
     Requires: aiohttp, agent-framework-foundry
     Run: python -m pipeline.main

  2. Fallback single-agent mode (existing service.py path, no aiohttp)
     Activated automatically when aiohttp is unavailable.
     Run: python -m pipeline.main --fallback

Usage
-----
    python -m pipeline.main
    python -m pipeline.main "מה הרייטינג הממוצע של חתונה ממבט ראשון?"
    python -m pipeline.main --fallback "שאלה כאן"
"""

from __future__ import annotations

import asyncio
import logging
import sys

from dotenv import load_dotenv

from pipeline.config import load_settings

DEFAULT_QUESTION = "מה הרייטינג הממוצע של חתונה ממבט ראשון?"
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Full async pipeline (PromoRetriever → PromoAnswer)
# ---------------------------------------------------------------------------

async def run_pipeline(question: str, settings) -> None:
    """Run the two-stage workflow using the Microsoft Agent Framework."""
    from azure.identity.aio import AzureCliCredential
    from agent_framework import AgentResponseUpdate
    from agent_framework.azure import AzureAIProjectAgentProvider

    from pipeline.agents import create_retriever, create_answer_agent
    from pipeline.workflow import build_pipeline

    credential = AzureCliCredential()

    async with AzureAIProjectAgentProvider(
        project_endpoint=settings.project_endpoint,
        credential=credential,
    ) as provider:
        logger.info("Registering agents in Foundry ...")
        retriever = await create_retriever(provider, model=settings.model_deployment)
        answerer  = await create_answer_agent(provider, model=settings.model_deployment)

        pipeline = build_pipeline(retriever, answerer)

        logger.info(f"\n{'=' * 60}")
        logger.info(f"Question: {question}")
        logger.info(f"{'=' * 60}\n")

        last_executor = None
        async for event in pipeline.run(question, stream=True):
            if event.type == "executor_invoked":
                exec_id = getattr(event, "executor_id", None)
                if exec_id and exec_id not in ("input-conversation", "end", None):
                    if last_executor:
                        logger.info(f"\n{'-' * 40}")
                    logger.info(f"\n[{exec_id}]:")
                    last_executor = exec_id

            if event.type == "output" and isinstance(event.data, AgentResponseUpdate):
                text = str(event.data)
                if text:
                    sys.stdout.write(text)
                    sys.stdout.flush()

        logger.info(f"\n\n{'=' * 60}\nPipeline complete.")

    await credential.close()


# ---------------------------------------------------------------------------
# Fallback single-agent mode (no aiohttp needed)
# ---------------------------------------------------------------------------

def run_fallback(question: str) -> None:
    """Run the existing service.py pipeline (sync, no aiohttp required)."""
    from app.service import run_query

    logger.info("\n[Fallback mode — using service.py directly]\n")
    result = run_query(question)
    logger.info(f"Answer:\n{result.answer}")
    logger.info(f"\n[route={result.route}  confidence={result.confidence}  sources={len(result.sources)}]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    settings = load_settings()

    import argparse
    ap = argparse.ArgumentParser(description="PromoAgent pipeline CLI")
    ap.add_argument("question", nargs="?", default=None, help="Question in Hebrew")
    ap.add_argument("--fallback", action="store_true",
                    help="Skip agent framework, use service.py directly")
    args = ap.parse_args()

    question = args.question or DEFAULT_QUESTION

    if args.fallback:
        run_fallback(question)
        return

    try:
        asyncio.run(run_pipeline(question, settings))
    except ImportError as exc:
        logger.error(f"\naiohttp or agent-framework-foundry not available: {exc}")
        logger.info("Falling back to service.py (sync mode)...\n")
        run_fallback(question)
    except KeyboardInterrupt:
        logger.info("\nInterrupted.")
        sys.exit(0)


if __name__ == "__main__":
    main()
