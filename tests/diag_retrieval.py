"""
Diagnostic script: compare what Azure Search returns vs what the gold answer expects.
Run: python tests/diag_retrieval.py
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from app.search_word_docs import search_excel_promos, search_word_docs
from app.query_router import classify

DATASET = os.path.join(os.path.dirname(__file__), "..", "dataset.jsonl")

FAILING_IDS = {"2", "3", "5", "6", "7", "8", "9", "11", "13", "14", "17", "22"}

def load_cases():
    with open(DATASET, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def diagnose_case(case):
    cid = case["id"]
    query = case["cleaned_query"]
    gold = case["cleaned_answer"]
    category = case["category"]

    route_result = classify(query)
    route = route_result.route
    print(f"\n{'='*70}")
    print(f"CASE {cid} | category={category} | route={route}")
    print(f"Query: {query}")
    print(f"Gold answer (excerpt): {gold[:200]}")
    print(f"-"*70)

    # Always check both indexes to see full picture
    excel_docs = search_excel_promos(query, top=8)
    print(f"\n  EXCEL results ({len(excel_docs)} hits, top=8):")
    for i, d in enumerate(excel_docs):
        text_preview = (d.get("promo_text") or "")[:100].replace("\n", " ")
        print(f"    [{i+1}] show={d['show_name']} season={d['season']} "
              f"date={d['date']} rating={d['rating']} "
              f"section={d['section']} score={d['score']:.2f}")
        print(f"         text: {text_preview}")

    word_docs = search_word_docs(query, top=5)
    print(f"\n  WORD results ({len(word_docs)} hits):")
    for i, d in enumerate(word_docs):
        chunk_preview = (d.get("chunk") or "")[:150].replace("\n", " ")
        print(f"    [{i+1}] title={d['title']} header={d['header']} score={d['score']:.2f}")
        print(f"         chunk: {chunk_preview}")

    print()


def main():
    cases = load_cases()
    target_ids = FAILING_IDS
    if len(sys.argv) > 1:
        target_ids = set(sys.argv[1:])

    for case in cases:
        if case["id"] in target_ids:
            diagnose_case(case)

if __name__ == "__main__":
    main()
