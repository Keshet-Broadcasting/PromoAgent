"""
eval_dataset.py

Evaluation harness that scores the agent against dataset.jsonl gold answers.

Usage
-----
Full eval (all 25 cases, calls LLM for each):
    python tests/eval_dataset.py

With LLM-as-judge (uses an extra LLM call per case to score semantic quality):
    python tests/eval_dataset.py --judge

Single case by id:
    python tests/eval_dataset.py --id 5

JSON output:
    python tests/eval_dataset.py --json

Scoring dimensions
------------------
NUMERIC    Numbers from the gold answer appear in the model answer.
           Score = fraction of gold numbers found (0.0–1.0).

KEYWORD    Meaningful Hebrew terms from the gold answer appear in the model
           answer. Score = fraction found (0.0–1.0).

GROUNDED   Model answer contains source citations or grounding language.
           Binary 0 or 1.

REFUSAL    For answerable=false cases, the model correctly says "not found".
           Binary 0 or 1. Skipped for answerable=true cases.

JUDGE      (optional, --judge) LLM rates semantic quality 1–5 by comparing
           model answer to gold answer. Normalized to 0.0–1.0.

Overall case score = weighted average of applicable dimensions.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).resolve().parent.parent / "dataset.jsonl"

WEIGHTS = {
    "numeric":   0.35,
    "keyword":   0.25,
    "grounded":  0.20,
    "refusal":   0.20,
    "judge":     0.40,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class GoldCase:
    id: str
    query: str
    cleaned_query: str
    answer: str
    cleaned_answer: str
    category: str
    answerable: bool
    has_numeric_data: bool
    has_comparison: bool
    has_full_quote: bool
    source_hint: str
    confidence: str
    needs_human_review: bool

    @classmethod
    def from_dict(cls, d: dict) -> GoldCase:
        return cls(
            id=d["id"],
            query=d["query"],
            cleaned_query=d.get("cleaned_query", d["query"]),
            answer=d.get("answer", ""),
            cleaned_answer=d.get("cleaned_answer", ""),
            category=d.get("category", ""),
            answerable=d.get("answerable", True),
            has_numeric_data=d.get("has_numeric_data", False),
            has_comparison=d.get("has_comparison", False),
            has_full_quote=d.get("has_full_quote", False),
            source_hint=d.get("source_hint", ""),
            confidence=d.get("confidence", "medium"),
            needs_human_review=d.get("needs_human_review", False),
        )


@dataclass
class CaseResult:
    id: str
    category: str
    query: str
    numeric_score: float | None = None
    keyword_score: float | None = None
    grounded_score: float | None = None
    refusal_score: float | None = None
    judge_score: float | None = None
    overall: float = 0.0
    error: str | None = None
    elapsed_s: float = 0.0
    answer_preview: str = ""


# ---------------------------------------------------------------------------
# Number extraction
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"\d+(?:\.\d+)?%?")


def _extract_numbers(text: str) -> set[str]:
    """Extract numeric tokens (with optional % suffix) from text."""
    raw = _NUM_RE.findall(text)
    normalized: set[str] = set()
    for n in raw:
        bare = n.rstrip("%")
        if bare in ("0", "1", "2", "3", "4", "5"):
            continue
        normalized.add(bare)
    return normalized


def score_numeric(gold: str, predicted: str) -> float:
    """Fraction of gold-answer numbers found in the predicted answer.

    Uses a ±0.2 tolerance so that rounding differences (e.g. gold=22.5,
    predicted=22.4) do not count as misses.
    """
    gold_nums = _extract_numbers(gold)
    if not gold_nums:
        return 1.0
    pred_nums = _extract_numbers(predicted)
    hits = 0
    for gn in gold_nums:
        try:
            g = float(gn)
            if any(abs(float(pn) - g) <= 0.2 for pn in pred_nums):
                hits += 1
        except ValueError:
            if gn in pred_nums:
                hits += 1
    return hits / len(gold_nums)


# ---------------------------------------------------------------------------
# Keyword extraction and scoring
# ---------------------------------------------------------------------------

_STOP_WORDS = {
    "את", "של", "על", "עם", "לא", "הם", "היא", "הוא", "זה", "כי",
    "או", "גם", "רק", "מה", "אם", "כל", "יש", "אין", "עד", "בין",
    "אל", "מן", "לפי", "כמו", "כדי", "לפני", "אחרי", "בשל", "למרות",
    "שלה", "שלו", "שלי", "שלך", "היו", "היה", "הייתה", "להיות",
    "ה", "ב", "ל", "מ", "ו", "כ", "ש",
}

_WORD_RE = re.compile(r"[\u05d0-\u05ea]{2,}")

# Hebrew single-character prefixes that can be prepended to any word.
# Stripping them before comparison avoids false misses like "רייטינג" vs "ברייטינג".
_HE_PREFIXES = ("ה", "ב", "ל", "מ", "ו", "כ", "ש", "וה", "וב", "ול", "ומ")


def _stem_hebrew(word: str) -> str:
    """Strip a common Hebrew prefix so 'ברייטינג' matches 'רייטינג'."""
    for prefix in sorted(_HE_PREFIXES, key=len, reverse=True):
        if word.startswith(prefix) and len(word) > len(prefix) + 1:
            return word[len(prefix):]
    return word


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful Hebrew words (2+ chars, not stop words), stemmed."""
    words = set(_WORD_RE.findall(text))
    return {_stem_hebrew(w) for w in words - _STOP_WORDS}


def score_keyword(gold: str, predicted: str) -> float:
    """Fraction of gold-answer Hebrew keywords found in the predicted answer.

    Both sides are stemmed so 'ברייטינג' matches the gold keyword 'רייטינג'.
    """
    gold_kw = _extract_keywords(gold)
    if not gold_kw:
        return 1.0
    pred_kw = _extract_keywords(predicted)
    hits = sum(1 for kw in gold_kw if kw in pred_kw)
    return hits / len(gold_kw)


# ---------------------------------------------------------------------------
# Groundedness check
# ---------------------------------------------------------------------------

_GROUNDING_MARKERS = [
    "xlsx", "docx", "מסמך", "מעקבי", "קובץ", "נשלף", "נשלפו",
    "קטע", "[מקור", "על פי המידע", "על פי הנתונ", "בהתבסס על",
    "שנשלף", "שנשלפ", "ממסמך", "לפי המידע", "בהתאם למידע",
]

_NOT_FOUND_MARKERS = [
    "לא נמצא", "לא נמצאו", "אין מידע", "לא קיים", "לא נשלף",
    "לא קיימים", "אין נתון", "אין נתונים", "לא מופיע", "לא זמין",
    "לא נמצאו נתונים", "לא נמצא מידע", "לא ניתן למצוא",
    "אין במסמך", "אין בנתונים", "לא מוזכר", "לא מוזכרת",
]


def score_grounded(predicted: str) -> float:
    """1.0 if model answer cites sources or says not-found; 0.0 otherwise."""
    for marker in _GROUNDING_MARKERS + _NOT_FOUND_MARKERS:
        if marker in predicted:
            return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# Refusal accuracy (for answerable=false cases)
# ---------------------------------------------------------------------------


def score_refusal(predicted: str, answerable: bool) -> float | None:
    """For unanswerable questions: 1.0 if model refuses, 0.0 if it answers.
    Returns None for answerable questions (not applicable)."""
    if answerable:
        return None
    for marker in _NOT_FOUND_MARKERS:
        if marker in predicted:
            return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# LLM-as-judge  (optional)
# ---------------------------------------------------------------------------

_JUDGE_PROMPT = """You are an evaluation judge. Compare the MODEL ANSWER to the GOLD ANSWER for the given question.

Rate the model answer on a scale of 1-5:
  1 = Completely wrong, irrelevant, or hallucinated
  2 = Partially relevant but missing key facts or contains errors
  3 = Mostly correct but incomplete or imprecise
  4 = Good — covers the key facts with minor omissions
  5 = Excellent — accurate, complete, well-grounded

The answers are in Hebrew. Focus on factual accuracy, not style.

QUESTION: {question}

GOLD ANSWER: {gold}

MODEL ANSWER: {predicted}

Respond with ONLY a single integer (1-5), nothing else."""


def score_judge(question: str, gold: str, predicted: str) -> float:
    """Use the configured LLM to rate the answer 1-5, normalized to 0-1."""
    from app.chat_provider import get_provider

    prompt = _JUDGE_PROMPT.format(
        question=question, gold=gold, predicted=predicted,
    )
    messages = [
        {"role": "system", "content": "You are a strict evaluation judge."},
        {"role": "user", "content": prompt},
    ]
    try:
        raw = get_provider().complete(messages).strip()
        score = int(re.search(r"[1-5]", raw).group())  # type: ignore[union-attr]
        return (score - 1) / 4.0
    except Exception as exc:
        log.warning("  Judge failed: %s — defaulting to 0.5", exc)
        return 0.5


# ---------------------------------------------------------------------------
# Weighted overall score
# ---------------------------------------------------------------------------


def compute_overall(result: CaseResult, use_judge: bool) -> float:
    """Weighted average of applicable dimensions."""
    parts: list[tuple[float, float]] = []

    if result.numeric_score is not None:
        parts.append((result.numeric_score, WEIGHTS["numeric"]))
    if result.keyword_score is not None:
        parts.append((result.keyword_score, WEIGHTS["keyword"]))
    if result.grounded_score is not None:
        parts.append((result.grounded_score, WEIGHTS["grounded"]))
    if result.refusal_score is not None:
        parts.append((result.refusal_score, WEIGHTS["refusal"]))
    if use_judge and result.judge_score is not None:
        parts.append((result.judge_score, WEIGHTS["judge"]))

    if not parts:
        return 0.0
    total_weight = sum(w for _, w in parts)
    return sum(s * w for s, w in parts) / total_weight


# ---------------------------------------------------------------------------
# Main eval loop
# ---------------------------------------------------------------------------


def load_dataset(path: Path) -> list[GoldCase]:
    cases: list[GoldCase] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(GoldCase.from_dict(json.loads(line)))
    return cases


def run_eval(
    cases: list[GoldCase],
    use_judge: bool = False,
) -> list[CaseResult]:
    from app.service import run_query

    results: list[CaseResult] = []
    total = len(cases)

    for i, gold in enumerate(cases, 1):
        log.info("\n[%d/%d] id=%s  category=%s", i, total, gold.id, gold.category)
        log.info("  Q: %s", gold.query[:90])

        # Use the cleaned_query (self-contained rephrasing) when available so
        # that follow-up questions like "איך זה ביחס לדרמות אחרות" work as
        # standalone queries.  Fall back to raw query when they are identical.
        eval_query = gold.cleaned_query if gold.cleaned_query and gold.cleaned_query != gold.query else gold.query
        if eval_query != gold.query:
            log.info("  Q(clean): %s", eval_query[:90])

        t0 = time.time()
        try:
            resp = run_query(eval_query)
            answer = resp.answer
        except Exception as exc:
            elapsed = time.time() - t0
            log.error("  ERROR: %s (%.1fs)", exc, elapsed)
            results.append(CaseResult(
                id=gold.id, category=gold.category, query=gold.query,
                error=str(exc), elapsed_s=elapsed,
            ))
            continue
        elapsed = time.time() - t0

        gold_text = gold.cleaned_answer or gold.answer

        r = CaseResult(
            id=gold.id,
            category=gold.category,
            query=gold.query,
            elapsed_s=elapsed,
            answer_preview=answer[:250],
        )

        if gold.has_numeric_data:
            r.numeric_score = score_numeric(gold_text, answer)
        r.keyword_score = score_keyword(gold_text, answer)
        r.grounded_score = score_grounded(answer)
        r.refusal_score = score_refusal(answer, gold.answerable)

        if use_judge:
            r.judge_score = score_judge(eval_query, gold_text, answer)

        r.overall = compute_overall(r, use_judge)
        results.append(r)

        log.info("  NUM=%.2f  KW=%.2f  GND=%.0f  REF=%s  JDG=%s  => %.2f  (%.1fs)",
                 r.numeric_score if r.numeric_score is not None else -1,
                 r.keyword_score if r.keyword_score is not None else -1,
                 r.grounded_score if r.grounded_score is not None else -1,
                 f"{r.refusal_score:.0f}" if r.refusal_score is not None else "n/a",
                 f"{r.judge_score:.2f}" if r.judge_score is not None else "off",
                 r.overall, elapsed)
        log.info("  A: %s%s", answer[:200], "…" if len(answer) > 200 else "")

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_summary(results: list[CaseResult], use_judge: bool) -> None:
    ok = [r for r in results if r.error is None]
    errors = [r for r in results if r.error is not None]

    if not ok:
        log.info("\nNo successful cases to report.")
        return

    avg_overall = sum(r.overall for r in ok) / len(ok)
    avg_numeric = _safe_avg([r.numeric_score for r in ok if r.numeric_score is not None])
    avg_keyword = _safe_avg([r.keyword_score for r in ok if r.keyword_score is not None])
    avg_grounded = _safe_avg([r.grounded_score for r in ok if r.grounded_score is not None])
    avg_refusal = _safe_avg([r.refusal_score for r in ok if r.refusal_score is not None])
    avg_judge = _safe_avg([r.judge_score for r in ok if r.judge_score is not None])

    log.info("\n" + "=" * 64)
    log.info("EVAL SUMMARY — %d cases (%d errors)", len(ok), len(errors))
    log.info("=" * 64)
    log.info("  Overall score:    %.1f%%", avg_overall * 100)
    log.info("  Numeric accuracy: %.1f%%", avg_numeric * 100)
    log.info("  Keyword coverage: %.1f%%", avg_keyword * 100)
    log.info("  Groundedness:     %.1f%%", avg_grounded * 100)
    if avg_refusal >= 0:
        log.info("  Refusal accuracy: %.1f%%", avg_refusal * 100)
    if use_judge:
        log.info("  LLM Judge:        %.1f%%", avg_judge * 100)
    log.info("-" * 64)

    by_cat: dict[str, list[CaseResult]] = {}
    for r in ok:
        by_cat.setdefault(r.category, []).append(r)

    log.info("\nPer-category breakdown:")
    log.info("  %-14s  %5s  %5s  %5s  %5s  %s",
             "Category", "N", "Score", "NUM", "KW", "GND")
    log.info("  " + "-" * 56)
    for cat in sorted(by_cat):
        cat_results = by_cat[cat]
        n = len(cat_results)
        sc = sum(r.overall for r in cat_results) / n
        nm = _safe_avg([r.numeric_score for r in cat_results if r.numeric_score is not None])
        kw = _safe_avg([r.keyword_score for r in cat_results if r.keyword_score is not None])
        gd = _safe_avg([r.grounded_score for r in cat_results if r.grounded_score is not None])
        log.info("  %-14s  %5d  %4.0f%%  %4.0f%%  %4.0f%%  %4.0f%%",
                 cat, n, sc * 100, nm * 100, kw * 100, gd * 100)

    avg_time = sum(r.elapsed_s for r in ok) / len(ok)
    total_time = sum(r.elapsed_s for r in results)
    log.info("\n  Avg latency: %.1fs  |  Total: %.0fs", avg_time, total_time)

    if errors:
        log.info("\n  ERRORS:")
        for r in errors:
            log.info("    id=%s  %s", r.id, r.error)


def _safe_avg(values: list[float]) -> float:
    if not values:
        return -1.0
    return sum(values) / len(values)


def results_to_json(results: list[CaseResult]) -> str:
    rows = []
    for r in results:
        rows.append({
            "id": r.id,
            "category": r.category,
            "overall": round(r.overall, 3),
            "numeric": round(r.numeric_score, 3) if r.numeric_score is not None else None,
            "keyword": round(r.keyword_score, 3) if r.keyword_score is not None else None,
            "grounded": round(r.grounded_score, 3) if r.grounded_score is not None else None,
            "refusal": round(r.refusal_score, 3) if r.refusal_score is not None else None,
            "judge": round(r.judge_score, 3) if r.judge_score is not None else None,
            "error": r.error,
            "elapsed_s": round(r.elapsed_s, 1),
        })
    return json.dumps(rows, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    use_judge = "--judge" in sys.argv
    json_out = "--json" in sys.argv

    case_id = None
    for i, arg in enumerate(sys.argv):
        if arg == "--id" and i + 1 < len(sys.argv):
            case_id = sys.argv[i + 1]

    if not DATASET_PATH.exists():
        log.error("Dataset not found: %s", DATASET_PATH)
        sys.exit(1)

    cases = load_dataset(DATASET_PATH)
    log.info("Loaded %d cases from %s", len(cases), DATASET_PATH.name)

    if case_id is not None:
        cases = [c for c in cases if c.id == case_id]
        if not cases:
            log.error("No case with id=%s", case_id)
            sys.exit(1)

    results = run_eval(cases, use_judge=use_judge)

    if json_out:
        print(results_to_json(results))
    else:
        print_summary(results, use_judge)

    failed = sum(1 for r in results if r.error is not None)
    low = sum(1 for r in results if r.error is None and r.overall < 0.5)
    sys.exit(1 if (failed + low) > 0 else 0)
