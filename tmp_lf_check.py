from dotenv import load_dotenv
import os, json, base64, urllib.request
from datetime import datetime, timezone

load_dotenv('.env')
sk = os.environ.get('LANGFUSE_SECRET_KEY')
pk = os.environ.get('LANGFUSE_PUBLIC_KEY')
host = os.environ.get('LANGFUSE_HOST', 'https://cloud.langfuse.com')
creds = base64.b64encode((pk+':'+sk).encode()).decode()

def api_get(path):
    req = urllib.request.Request(
        f'{host}/api/public/{path}',
        headers={'Authorization': 'Basic '+creds}
    )
    return json.loads(urllib.request.urlopen(req, timeout=12).read())

today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

# Fetch all today's traces (up to 100)
print("=== TODAY'S TRACES ===")
data = api_get('traces?limit=100&page=1')
traces = data.get('data', [])
today_traces = [t for t in traces if t.get('timestamp','').startswith(today)]
print(f'Traces today: {len(today_traces)}')

# Fetch all today's scores (multiple pages if needed)
all_scores = []
for page in range(1, 5):
    data = api_get(f'scores?limit=100&page={page}')
    s = data.get('data', [])
    if not s:
        break
    all_scores.extend(s)

today_scores = [s for s in all_scores if s.get('timestamp','').startswith(today)]
print(f'Scores today: {len(today_scores)}')

# Group by name
by_name = {}
for s in today_scores:
    by_name.setdefault(s['name'], []).append(s['value'])

print('\n=== SCORE SUMMARY ===')
for name, vals in sorted(by_name.items()):
    avg = sum(vals)/len(vals)
    mn, mx = min(vals), max(vals)
    print(f'  {name:25s}: avg={avg:.3f}  min={mn:.2f}  max={mx:.2f}  n={len(vals)}')

n_completed = len(by_name.get('eval-overall', []))
print(f'\nCases completed: {n_completed}/61')

# Show distribution
overalls = by_name.get('eval-overall', [])
if overalls:
    ranges = [('0.0-0.3', 0, 0.3), ('0.3-0.5', 0.3, 0.5), ('0.5-0.7', 0.5, 0.7), ('0.7-1.0', 0.7, 1.01)]
    print('\nDistribution:')
    for label, lo, hi in ranges:
        cnt = sum(1 for v in overalls if lo <= v < hi)
        print(f'  {label}: {"#"*cnt} ({cnt})')
