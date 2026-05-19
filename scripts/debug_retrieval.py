"""
debug_retrieval.py

Standalone debugging script that bypasses the LLM and prints raw Azure AI Search
chunks for a given query.  Use this to inspect retrieval quality directly.

Usage:
    python scripts/debug_retrieval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv
load_dotenv(BASE / ".env")

# ═══════════════════════════════════════════════════════════════════════════════
# HARDCODE YOUR QUERY HERE
# ═══════════════════════════════════════════════════════════════════════════════
QUERY = "מה היה הפרק עם הרייטינג הכי גבוה של נינג'ה ישראל עונה 5?"
# ═══════════════════════════════════════════════════════════════════════════════

from app.query_router import classify
from app.service import _expand_aliases
from app.search_word_docs import search_word_docs, search_excel_promos, fetch_show_promos


def _separator():
    print("\n" + "═" * 80 + "\n")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"Query (raw):      {QUERY}")
    expanded = _expand_aliases(QUERY)
    if expanded != QUERY:
        print(f"Query (expanded): {expanded}")
    print()

    route_result = classify(expanded)
    print(f"Route:    {route_result.route}")
    print(f"Details:  {route_result.summary}")
    _separator()

    route = route_result.route

    if route in ("excel_numeric", "hybrid", "unknown"):
        print(">>> EXCEL INDEX (tv-promos) RESULTS <<<")
        _separator()
        excel_docs = search_excel_promos(expanded, top=10)
        if not excel_docs:
            print("  (no results)")
        for i, doc in enumerate(excel_docs, 1):
            print(f"  [{i}]  Score: {doc.get('score', 'N/A'):.4f}")
            print(f"       Show:    {doc.get('show_name', '—')}")
            print(f"       Season:  {doc.get('season', '—')}")
            print(f"       Episode: {doc.get('episode_number', '—')}")
            print(f"       Date:    {doc.get('date', '—')}")
            print(f"       Opening: {doc.get('opening_point', '—')}%")
            print(f"       Rating:  {doc.get('rating', '—')}%")
            print(f"       Tab:     {doc.get('tab_name', '—')}")
            print(f"       Section: {doc.get('section', '—')}")
            text = (doc.get("promo_text") or "").strip()[:600]
            if text:
                print(f"       Text:    {text}")
            print("  " + "-" * 76)
        _separator()

    if route in ("word_quote", "hybrid", "unknown"):
        print(">>> WORD DOCS INDEX (word-docs) RESULTS <<<")
        _separator()
        word_docs = search_word_docs(expanded, top=10)
        if not word_docs:
            print("  (no results)")
        for i, doc in enumerate(word_docs, 1):
            print(f"  [{i}]  Score: {doc.get('score', 'N/A'):.4f}")
            print(f"       Title:    {doc.get('title', '—')}")
            print(f"       Header:   {doc.get('header', '—')}")
            print(f"       ChunkID:  {doc.get('chunk_id', '—')}")
            caption = (doc.get("caption") or "").strip()[:300]
            if caption:
                print(f"       Caption:  {caption}")
            chunk = (doc.get("chunk") or "").strip()[:800]
            if chunk:
                print(f"       Chunk:\n         {chunk[:800]}")
            print("  " + "-" * 76)
        _separator()

    print("Done.")


if __name__ == "__main__":
    main()
