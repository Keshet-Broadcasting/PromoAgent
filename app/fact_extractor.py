"""
fact_extractor.py

Extracts persistent user facts from multi-turn conversations.

After a conversation reaches 3+ turns, this module sends a lightweight
LLM call to identify any user preferences or facts worth remembering
(e.g., "the user works on חתונה ממבט ראשון", "the user prefers data tables").

Extracted facts are stored via memory.py (Azure Table Storage).
This runs asynchronously and never blocks the main response path.
"""

from __future__ import annotations

import json
import logging
import re
import threading

log = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """You are a fact extractor for a TV promo department chatbot.

Analyze the conversation below and extract any **user-specific facts** worth remembering for future sessions.

Rules:
- Only extract facts the USER explicitly states or clearly implies about themselves.
- Focus on: shows they work on, their role, preferences, recurring questions, shows of interest.
- Do NOT extract facts about TV shows (those come from the database).
- Return a JSON array of objects with "key" and "value" fields.
- Keys should be short English slugs (e.g., "primary_show", "role", "preferred_format").
- Values should be in Hebrew when relevant.
- If no user-specific facts are found, return an empty array: []
- Maximum 5 facts per extraction.

Example output:
[
  {"key": "primary_show", "value": "חתונה ממבט ראשון"},
  {"key": "role", "value": "עורך פרומו"}
]

Conversation:
{conversation}

Extract facts as JSON:"""

_MIN_TURNS_FOR_EXTRACTION = 3


def _extract_facts_sync(history: list[dict], provider) -> list[dict]:
    """Run the extraction LLM call (synchronous, meant to be called in a thread)."""
    if len(history) < _MIN_TURNS_FOR_EXTRACTION:
        return []

    conv_text = "\n".join(
        f"{'משתמש' if t['role'] == 'user' else 'בוט'}: {t['content'][:300]}"
        for t in history[-6:]
    )

    messages = [
        {"role": "system", "content": "You extract structured facts from conversations. Reply only with valid JSON."},
        {"role": "user", "content": _EXTRACTION_PROMPT.format(conversation=conv_text)},
    ]

    try:
        raw = provider.complete(messages)
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        facts = json.loads(match.group())
        if not isinstance(facts, list):
            return []
        valid = [
            {"key": f["key"], "value": f["value"]}
            for f in facts
            if isinstance(f, dict) and "key" in f and "value" in f
        ]
        return valid[:5]
    except Exception as exc:
        log.warning("Fact extraction failed: %s", exc)
        return []


def extract_and_store(user_oid: str, history: list[dict] | None) -> None:
    """Fire-and-forget: extract facts from history and store them.

    Runs in a background thread so it never adds latency to the response.
    Skips silently if history is too short or user_oid is missing.
    """
    if not user_oid or not history or len(history) < _MIN_TURNS_FOR_EXTRACTION:
        return

    def _worker():
        try:
            from .chat_provider import get_provider
            from .memory import get_memory_store

            facts = _extract_facts_sync(history, get_provider())
            if not facts:
                return

            store = get_memory_store()
            for fact in facts:
                store.upsert(user_oid, fact["key"], fact["value"], source="extracted")
            log.info("Extracted %d fact(s) for user %s", len(facts), user_oid[:8])
        except Exception as exc:
            log.warning("Background fact extraction failed: %s", exc)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
