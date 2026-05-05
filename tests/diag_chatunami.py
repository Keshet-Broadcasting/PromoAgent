"""Get חתונמי launch data."""
import os, requests, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

EP = os.getenv("AZURE_SEARCH_ENDPOINT", "").rstrip("/")
KEY = os.getenv("AZURE_SEARCH_KEY", "")
url = f"{EP}/indexes/tv-promos/docs/search?api-version=2024-07-01"

body = {
    "search": "חתונה ממבט ראשון השקה",
    "filter": "show_name eq '\u05d7\u05ea\u05d5\u05e0\u05d4 \u05de\u05de\u05d1\u05d8 \u05e8\u05d0\u05e9\u05d5\u05df'",
    "top": 50,
    "select": "show_name,season,episode_number,date,opening_point,rating,promo_text",
}
r = requests.post(url, headers={"api-key": KEY, "Content-Type": "application/json"}, json=body)
docs = r.json().get("value", [])

print(f"Total חתונמי results: {len(docs)}")
for d in sorted(docs, key=lambda x: x.get("date", "")):
    txt = (d.get("promo_text") or "")[:80]
    op = d.get("opening_point") or "?"
    rt = d.get("rating") or "?"
    s = d.get("season") or "?"
    ep = d.get("episode_number") or "?"
    dt = d.get("date") or "?"
    is_launch = "השקה" in txt.lower()
    mark = " <<< LAUNCH" if is_launch else ""
    print(f"  s={s:>3} ep={ep:>3} dt={dt:>12} op={op:>6} rt={rt:>6} {txt}{mark}")
