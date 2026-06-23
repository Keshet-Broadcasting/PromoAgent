from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DATASET_PATH = Path(__file__).resolve().parent.parent / "dataset.jsonl"

REQUIRED_FIELDS = {
    "id",
    "query",
    "cleaned_query",
    "answer",
    "cleaned_answer",
    "category",
    "answerable",
    "has_numeric_data",
    "has_comparison",
    "has_full_quote",
    "source_hint",
    "confidence",
    "needs_human_review",
}

ALLOWED_CATEGORIES = {
    "alias",
    "comparison",
    "cross_show",
    "factual",
    "no_answer",
    "numeric",
    "open_ended",
    "quote",
    "ranking",
    "strategy",
}

ALLOWED_CONFIDENCE = {"high", "medium", "low"}

BOOLEAN_FIELDS = {
    "answerable",
    "has_numeric_data",
    "has_comparison",
    "has_full_quote",
    "needs_human_review",
}

# Terms that materially change retrieval intent or answer scope. If a cleaned
# query drops one of these from the raw query, eval can silently test a different
# task than the user asked (case 57 regressed this way).
INTENT_TERM_GROUPS = (
    ("VIP",),
    ("נבחרת החלומות",),
    ("אולסטארס", "אולסטרס"),
    ("לקראת עונה חדשה",),
    ("עונה חדשה",),
    ("עונה חוזרת",),
    ("השקה", "השקת", "ההשקה"),
    ("גמר",),
    ("סיום",),
    ("טונייט", "טונייטים"),
    ("שוטף", "שוטפים"),
    ("לעומת", "השווה"),
    ("כוונות צפייה", "כוונות הצפייה", "כוונות הצפיה"),
    ("נקודת פתיחה", "נקודת הפתיחה", "רייטינג ההשקה"),
    ("רייטינג",),
)


def _load_dataset() -> list[dict[str, Any]]:
    assert DATASET_PATH.exists(), (
        "dataset.jsonl must be committed so CI validates the same eval set used locally"
    )
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(DATASET_PATH.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"dataset.jsonl line {line_no} is not valid JSON: {exc}") from exc
        assert isinstance(row, dict), f"dataset.jsonl line {line_no} must be a JSON object"
        rows.append(row)
    return rows


def _contains(text: str, term: str) -> bool:
    return term.lower() in text.lower()


def _season_mentions(text: str) -> set[str]:
    return set(re.findall(r"עונה\s+(\d{1,2})\b", text))


def test_eval_dataset_schema_and_ids_are_valid():
    rows = _load_dataset()

    assert len(rows) >= 64
    ids: list[str] = []
    for row in rows:
        missing = REQUIRED_FIELDS - set(row)
        assert not missing, f"case {row.get('id', '<missing>')} missing fields: {sorted(missing)}"

        case_id = row["id"]
        assert isinstance(case_id, str) and case_id.isdigit(), f"invalid id: {case_id!r}"
        ids.append(case_id)

        for field in ("query", "answer"):
            assert isinstance(row[field], str) and row[field].strip(), (
                f"case {case_id} must have non-empty {field}"
            )
        for field in ("cleaned_query", "cleaned_answer", "source_hint"):
            assert isinstance(row[field], str), f"case {case_id} field {field} must be a string"

        assert row["category"] in ALLOWED_CATEGORIES, (
            f"case {case_id} has unknown category {row['category']!r}"
        )
        assert row["confidence"] in ALLOWED_CONFIDENCE, (
            f"case {case_id} has unknown confidence {row['confidence']!r}"
        )
        for field in BOOLEAN_FIELDS:
            assert isinstance(row[field], bool), f"case {case_id} field {field} must be bool"

    assert len(ids) == len(set(ids)), "dataset ids must be unique"
    assert [int(case_id) for case_id in ids] == sorted(int(case_id) for case_id in ids), (
        "dataset ids should stay sorted for readable reviews"
    )


def test_cleaned_queries_preserve_retrieval_intent_terms():
    rows = _load_dataset()

    for row in rows:
        query = row["query"]
        cleaned = row["cleaned_query"] or query
        case_id = row["id"]

        missing_terms = []
        for terms in INTENT_TERM_GROUPS:
            if any(_contains(query, term) for term in terms) and not any(
                _contains(cleaned, term) for term in terms
            ):
                missing_terms.append("/".join(terms))
        assert not missing_terms, (
            f"case {case_id} cleaned_query dropped intent terms {missing_terms}: "
            f"query={query!r} cleaned_query={cleaned!r}"
        )

        missing_seasons = _season_mentions(query) - _season_mentions(cleaned)
        assert not missing_seasons, (
            f"case {case_id} cleaned_query dropped season/number terms {sorted(missing_seasons)}: "
            f"query={query!r} cleaned_query={cleaned!r}"
        )


def test_case_57_keeps_new_season_strategy_intent():
    rows = {row["id"]: row for row in _load_dataset()}
    case = rows["57"]

    assert "לקראת עונה חדשה" in case["query"]
    assert "לקראת עונה חדשה" in case["cleaned_query"]
    assert case["category"] == "strategy"
    assert "חידוש עונתי" in case["cleaned_answer"]
