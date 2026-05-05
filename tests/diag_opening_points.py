"""Fetch opening_point + rating for specific show launches from the index."""
import os, json, requests, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

EP = os.getenv("AZURE_SEARCH_ENDPOINT", "").rstrip("/")
KEY = os.getenv("AZURE_SEARCH_KEY", "")
HEADERS = {"api-key": KEY, "Content-Type": "application/json"}
API_VER = "2024-07-01"

def search_launches(show_name, top=20):
    url = f"{EP}/indexes/tv-promos/docs/search?api-version={API_VER}"
    body = {
        "search": f"{show_name} השקה",
        "filter": f"show_name eq '{show_name}'",
        "top": top,
        "orderby": "date desc",
        "select": "show_name,season,episode_number,date,opening_point,rating,promo_text,section",
    }
    r = requests.post(url, headers=HEADERS, json=body)
    r.raise_for_status()
    return r.json().get("value", [])

def search_all_episodes(show_name, top=50):
    url = f"{EP}/indexes/tv-promos/docs/search?api-version={API_VER}"
    body = {
        "search": "*",
        "filter": f"show_name eq '{show_name}'",
        "top": top,
        "select": "show_name,season,episode_number,date,opening_point,rating,promo_text,section",
    }
    r = requests.post(url, headers=HEADERS, json=body)
    r.raise_for_status()
    return r.json().get("value", [])

shows = [
    "חתונה ממבט ראשון",
    "המירוץ למיליון",
    "החיים הם תקופה קשה",
    "נוטוק",
    "הראש",
]

for show in shows:
    print(f"\n{'='*60}")
    print(f"  {show}")
    print(f"{'='*60}")
    docs = search_all_episodes(show, top=50)
    launches = [d for d in docs if "השקה" in (d.get("promo_text") or "").lower() or d.get("episode_number") == "1"]
    if launches:
        print(f"  LAUNCH episodes ({len(launches)}):")
        for d in sorted(launches, key=lambda x: x.get("date", "")):
            print(f"    season={d.get('season','?'):>3} ep={d.get('episode_number','?'):>3} "
                  f"date={d.get('date','?'):>12} opening_point={d.get('opening_point','?'):>6} "
                  f"rating={d.get('rating','?'):>6} text={str(d.get('promo_text',''))[:60]}")
    else:
        print("  No launch episodes found with filter")
    
    top5 = sorted(docs, key=lambda x: float(x.get("opening_point") or 0), reverse=True)[:5]
    print(f"\n  TOP 5 by opening_point:")
    for d in top5:
        print(f"    ep={d.get('episode_number','?'):>3} date={d.get('date','?'):>12} "
              f"opening_point={d.get('opening_point','?'):>6} rating={d.get('rating','?'):>6} "
              f"text={str(d.get('promo_text',''))[:60]}")
