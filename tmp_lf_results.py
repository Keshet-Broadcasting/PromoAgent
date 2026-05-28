from dotenv import load_dotenv
import os, json, base64, urllib.request
from datetime import datetime, timezone

load_dotenv('.env')
sk = os.environ.get('LANGFUSE_SECRET_KEY')
pk = os.environ.get('LANGFUSE_PUBLIC_KEY')
host = os.environ.get('LANGFUSE_BASE_URL', 'https://cloud.langfuse.com')
creds = base64.b64encode((pk+':'+sk).encode()).decode()

def api(path):
    req = urllib.request.Request(f'{host}/api/public/{path}',
        headers={'Authorization': 'Basic '+creds})
    return json.loads(urllib.request.urlopen(req, timeout=12).read())

today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

# Scores and traces
all_scores = []
for page in range(1, 5):
    d = api(f'scores?limit=100&page={page}')
    batch = d.get('data', [])
    if not batch: break
    all_scores.extend(batch)

today_scores = [s for s in all_scores if s.get('timestamp','').startswith(today)]
score_by_trace = {}
for s in today_scores:
    score_by_trace.setdefault(s['traceId'], {})[s['name']] = s['value']

traces_data = api('traces?limit=100&page=1')
all_traces = [t for t in traces_data.get('data',[]) if t.get('timestamp','').startswith(today)]
all_traces.sort(key=lambda t: t.get('timestamp',''))

# Filter to real eval cases (skip judge LLM traces which have 0 scores)
real_cases = []
for t in all_traces:
    sc = score_by_trace.get(t['id'], {})
    overall = sc.get('eval-overall', -1)
    if overall >= 0:  # real eval case
        real_cases.append({
            'id': t['id'][:8],
            'overall': overall,
            'keyword': sc.get('eval-keyword', 0),
            'grounded': sc.get('eval-grounded', 0),
            'judge': sc.get('eval-judge', -1),
            'input': (t.get('input') or '')[:50]
        })

print("=" * 60)
print("  PROMOBOT EVAL RESULTS — TODAY")
print("=" * 60)
print(f"\n  Cases evaluated: {len(real_cases)}")

# Overall averages
if real_cases:
    avg_overall  = sum(c['overall'] for c in real_cases) / len(real_cases)
    avg_keyword  = sum(c['keyword'] for c in real_cases) / len(real_cases)
    avg_grounded = sum(c['grounded'] for c in real_cases) / len(real_cases)
    judged = [c for c in real_cases if c['judge'] >= 0]
    avg_judge = sum(c['judge'] for c in judged) / len(judged) if judged else 0

    def bar(v, w=20): return '█'*int(v*w) + '░'*(w-int(v*w))

    print(f"\n  🎯 Overall   {bar(avg_overall)}  {avg_overall:.3f}")
    print(f"  🔤 Keyword   {bar(avg_keyword)}  {avg_keyword:.3f}")
    print(f"  📎 Grounded  {bar(avg_grounded)}  {avg_grounded:.3f}")
    if judged:
        print(f"  🤖 Judge     {bar(avg_judge)}  {avg_judge:.3f}  (target: 0.700)")
    print(f"\n  Gap to target (judge): {0.700 - avg_judge:+.3f}")

    # Distribution
    print("\n  Judge score distribution:")
    for lo, hi, label in [(0,.3,'poor'), (.3,.5,'fair'), (.5,.7,'good'), (.7,1.01,'great')]:
        cnt = sum(1 for c in judged if lo <= c['judge'] < hi)
        print(f"    {label:6s}  {'▮'*cnt}  {cnt}/{len(judged)}")

    # Best and worst cases
    judged_sorted = sorted(judged, key=lambda c: c['judge'])
    print("\n  ── WEAKEST cases (judge ≤ 0.25) ──")
    for c in judged_sorted:
        if c['judge'] <= 0.25:
            print(f"    {c['judge']:.2f}  {c['input']}")

    print("\n  ── STRONGEST cases (judge ≥ 0.75) ──")
    for c in reversed(judged_sorted):
        if c['judge'] >= 0.75:
            print(f"    {c['judge']:.2f}  {c['input']}")
