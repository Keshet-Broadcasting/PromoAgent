"""
Standalone eval runner with LLM judge.
Writes progress to eval_judge_progress.log and final results to eval_judge_results.json.
Runs completely independently of any console — safe to detach.
"""
import json
import logging
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

PROGRESS_LOG = BASE / "eval_judge_progress.log"
RESULTS_FILE = BASE / "eval_judge_results.json"

# Log to a file so the process has no console dependencies
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.FileHandler(str(PROGRESS_LOG), encoding="utf-8", mode="w"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger(__name__)

DATASET_PATH = BASE / "dataset.jsonl"

from tests.eval_dataset import load_dataset, run_eval, results_to_json, CaseResult

cases = load_dataset(DATASET_PATH)
log.info("=== Eval with LLM Judge — %d cases ===\n", len(cases))

# Run all cases
results: list[CaseResult] = run_eval(cases, use_judge=True)

# Write final JSON results
json_str = results_to_json(results)
RESULTS_FILE.write_text(json_str, encoding="utf-8")
log.info("\nResults written to %s", RESULTS_FILE)

# Print summary
ok = [r for r in results if r.error is None]
errors = [r for r in results if r.error is not None]

def safe_avg(vals):
    vals = [v for v in vals if v is not None and v >= 0]
    return sum(vals) / len(vals) if vals else -1

avg_overall  = safe_avg([r.overall for r in ok])
avg_numeric  = safe_avg([r.numeric_score for r in ok])
avg_keyword  = safe_avg([r.keyword_score for r in ok])
avg_grounded = safe_avg([r.grounded_score for r in ok])
avg_refusal  = safe_avg([r.refusal_score for r in ok if r.refusal_score is not None])
avg_judge    = safe_avg([r.judge_score for r in ok])

log.info("\n" + "=" * 64)
log.info("EVAL SUMMARY — %d cases (%d errors)", len(ok), len(errors))
log.info("=" * 64)
log.info("  Overall score:    %.1f%%", avg_overall * 100)
log.info("  Numeric accuracy: %.1f%%", avg_numeric * 100)
log.info("  Keyword coverage: %.1f%%", avg_keyword * 100)
log.info("  Groundedness:     %.1f%%", avg_grounded * 100)
if avg_refusal >= 0:
    log.info("  Refusal accuracy: %.1f%%", avg_refusal * 100)
log.info("  LLM Judge:        %.1f%%", avg_judge * 100)
log.info("-" * 64)

# Per-category
by_cat: dict[str, list] = {}
for r in ok:
    by_cat.setdefault(r.category, []).append(r)

log.info("\nPer-category breakdown:")
for cat in sorted(by_cat):
    recs = by_cat[cat]
    n = len(recs)
    sc = safe_avg([r.overall for r in recs])
    jd = safe_avg([r.judge_score for r in recs])
    log.info("  %-14s  N=%d  Overall=%.0f%%  Judge=%.0f%%", cat, n, sc*100, jd*100)

avg_time = sum(r.elapsed_s for r in ok) / len(ok) if ok else 0
total_time = sum(r.elapsed_s for r in results)
log.info("\n  Avg latency: %.1fs  |  Total: %.0fs", avg_time, total_time)

if errors:
    log.info("\nERRORS:")
    for r in errors:
        log.info("  id=%s  %s", r.id, r.error)

log.info("\n=== DONE ===")
