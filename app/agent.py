"""
agent.py

CLI entry point for the Promo department agent.

All pipeline logic lives in service.py.
This file only handles argument parsing, encoding, and the interactive loop.

Usage (from project root)
--------------------------
    python -m app.agent "מה היה הרייטינג של נינג'ה ישראל עונה 5?"
    python -m app.agent --debug "שאלה מורכבת"
    python -m app.agent          # interactive loop (Ctrl+C to exit)

For the HTTP API instead:
    uvicorn app.api:app --reload
"""

from __future__ import annotations

import logging
import sys

# ---------------------------------------------------------------------------
# Re-export answer_question for backwards compatibility.
# The test suite imports it from here:  from app.agent import answer_question
# ---------------------------------------------------------------------------
from .service import answer_question  # noqa: F401  (re-export)
from .service import run_query

# ---------------------------------------------------------------------------
# Logging — only configure when running as CLI, not when imported as a module
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=logging.INFO,
    )

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    _args  = sys.argv[1:]
    _debug = "--debug" in _args
    _args  = [a for a in _args if a != "--debug"]

    if _debug:
        logging.getLogger().setLevel(logging.DEBUG)
        log.debug("Debug mode ON — full context will be printed before LLM call")

    if _args:
        q = " ".join(_args)
        log.info(f"\nשאלה: {q}\n")
        result = run_query(q, debug=_debug)
        log.info(result.answer)
        log.info(f"\n[route={result.route}  confidence={result.confidence}  "
                 f"sources={len(result.sources)}  trace={result.trace_id}]")
        if _debug and result.debug_trace:
            log.info("\n=== DEBUG TRACE ===")
            log.info(result.debug_trace)
            log.info("=== END TRACE ===")
    else:
        log.info("סוכן מחלקת הפרומו — מצב אינטראקטיבי (Ctrl+C ליציאה)\n")
        while True:
            try:
                q = input("שאלה: ").strip()
            except (KeyboardInterrupt, EOFError):
                log.info("\nיציאה.")
                break
            if not q:
                continue
            log.info("")
            result = run_query(q)
            log.info(result.answer)
            log.info(f"\n[route={result.route}  confidence={result.confidence}  "
                     f"sources={len(result.sources)}]")
            log.info("")
