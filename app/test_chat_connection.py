"""
test_chat_connection.py

Minimal connectivity test for Azure OpenAI chat completions.

Verifies that:
    1. Required env vars are present
    2. The AzureOpenAI client can reach the endpoint
    3. The chat deployment responds to a simple prompt

Usage:
    python test_chat_connection.py
"""

from __future__ import annotations

import os
import sys
import logging

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

AZURE_OPENAI_CHAT_ENDPOINT   = os.getenv("AZURE_OPENAI_CHAT_ENDPOINT", "")
AZURE_OPENAI_CHAT_KEY        = os.getenv("AZURE_OPENAI_CHAT_KEY", "")
AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "")


def get_chat_client() -> OpenAI:
    """Build and return an OpenAI client pointing at the Azure chat endpoint."""
    required = {
        "AZURE_OPENAI_CHAT_ENDPOINT":   AZURE_OPENAI_CHAT_ENDPOINT,
        "AZURE_OPENAI_CHAT_KEY":        AZURE_OPENAI_CHAT_KEY,
        "AZURE_OPENAI_CHAT_DEPLOYMENT": AZURE_OPENAI_CHAT_DEPLOYMENT,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}.\n"
            "Please set them in your .env file."
        )

    return OpenAI(
        base_url=AZURE_OPENAI_CHAT_ENDPOINT,
        api_key=AZURE_OPENAI_CHAT_KEY,
    )


def test_chat(prompt: str = "Say 'hello' in Hebrew in one word.") -> str:
    """Send a single chat message and return the assistant reply."""
    client = get_chat_client()
    response = client.chat.completions.create(
        model=AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=50,
        temperature=0,
    )
    return response.choices[0].message.content.strip()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    logger.info("Azure OpenAI Chat — connectivity test")
    logger.info("=" * 40)
    logger.info(f"  Endpoint:   {AZURE_OPENAI_CHAT_ENDPOINT}")
    logger.info(f"  Deployment: {AZURE_OPENAI_CHAT_DEPLOYMENT}")
    logger.info(f"  Base URL:   {AZURE_OPENAI_CHAT_ENDPOINT}")
    logger.info("")

    try:
        reply = test_chat()
        logger.info(f"Response: {reply}")
        logger.info("\nChat connection is working.")
    except EnvironmentError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        sys.exit(1)
