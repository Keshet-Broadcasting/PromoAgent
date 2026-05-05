"""Check Azure Search index schemas and sample docs."""
import os, json, requests
from dotenv import load_dotenv
load_dotenv()

ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "").rstrip("/")
KEY = os.getenv("AZURE_SEARCH_KEY", "")
HEADERS = {"api-key": KEY, "Content-Type": "application/json"}
API_VER = "2024-07-01"

def get_index_schema(index_name):
    url = f"{ENDPOINT}/indexes/{index_name}?api-version={API_VER}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()

def get_sample_docs(index_name, top=3):
    url = f"{ENDPOINT}/indexes/{index_name}/docs/search?api-version={API_VER}"
    body = {"search": "*", "top": top, "count": True}
    r = requests.post(url, headers=HEADERS, json=body)
    r.raise_for_status()
    return r.json()

def print_schema(schema):
    name = schema["name"]
    fields = schema.get("fields", [])
    print(f"\n=== INDEX: {name} ===")
    print(f"Fields ({len(fields)}):")
    for f in fields:
        attrs = []
        if f.get("searchable"): attrs.append("searchable")
        if f.get("filterable"): attrs.append("filterable")
        if f.get("sortable"): attrs.append("sortable")
        if f.get("facetable"): attrs.append("facetable")
        print(f"  {f['name']:30s} {f['type']:30s} [{', '.join(attrs)}]")

    semantic = schema.get("semantic", {})
    if semantic:
        configs = semantic.get("configurations", [])
        for cfg in configs:
            print(f"\nSemantic config: {cfg['name']}")
            pc = cfg.get("prioritizedFields", {})
            if pc.get("titleField"):
                print(f"  Title: {pc['titleField']['fieldName']}")
            for kf in pc.get("contentFields", []):
                print(f"  Content: {kf['fieldName']}")
            for kf in pc.get("keywordFields", []):
                print(f"  Keyword: {kf['fieldName']}")

for idx in ["tv-promos", "word-docs"]:
    try:
        schema = get_index_schema(idx)
        print_schema(schema)
        sample = get_sample_docs(idx, top=2)
        count = sample.get("@odata.count", "?")
        print(f"\nTotal docs: {count}")
        for doc in sample.get("value", []):
            keys = {k: (str(v)[:80] if v else "NULL") for k, v in doc.items() if not k.startswith("@")}
            print(f"  Sample: {json.dumps(keys, ensure_ascii=False)}")
    except Exception as e:
        print(f"\nERROR on {idx}: {e}")
