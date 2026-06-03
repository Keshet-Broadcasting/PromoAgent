"""Regression tests for word-doc semantic chunking guardrails.

Guards the 2026-06-03 fix: short but real labeled Q&A sections (e.g. פאלו אלטו's
114-char 'מה האסטרטגיה' answer) must NOT be discarded by the min-size filter,
while genuinely headerless fragments still are. The fix must stay additive —
chunks already >= the min size are unaffected.
"""
from __future__ import annotations

from scripts.preprocess_word_docs import (
    SEMANTIC_CHUNK_MIN_CHARS,
    _apply_semantic_guardrails,
    _is_meaningful_short_section,
)


def _chunk(header: str, body: str) -> dict:
    return {
        "chunk_id": "x_chunk_0", "header": header, "chunk": body,
        "title": "t", "source_file": "s", "parent_id": "p",
        "show_name": "אף אחד לא עוזב את פאלו אלטו", "season": "1",
        "doc_type": "השקה", "question_type": "אסטרטגיה",
    }


def test_short_headed_qa_section_survives_guardrails():
    """A real labeled section under the min size must be kept (palo alto repro)."""
    body = "איריס אברמוב חוקרת מקרה רצח שעלול להבעיר את כל חיפה והיא משלמת מחיר משפחתי ואישי כבד"
    assert len(body) < SEMANTIC_CHUNK_MIN_CHARS  # this is the failing condition
    c = _chunk("מה האסטרטגיה של הסדרה אף אחד לא עוזב את פאלו אלטו עונה 1?", body)
    assert _is_meaningful_short_section(c) is True
    out = _apply_semantic_guardrails([c])
    assert len(out) == 1
    assert "מקרה רצח" in out[0]["chunk"]


def test_short_headerless_fragment_is_discarded():
    """Genuinely trivial fragments (no recognized header) are still dropped."""
    c = _chunk("", "שורה קצרה כלשהי")
    assert _is_meaningful_short_section(c) is False
    assert _apply_semantic_guardrails([c]) == []


def test_min_size_fix_is_additive_for_large_chunks():
    """Chunks already >= the min size are unaffected by the fix."""
    body = "א" * (SEMANTIC_CHUNK_MIN_CHARS + 50)
    c = _chunk("תובנות מהקמפיין", body)
    out = _apply_semantic_guardrails([c])
    assert len(out) == 1 and out[0]["chunk"] == body


def test_slogan_section_recognized_as_meaningful():
    """'מה הסלוגן' is a real anchor — its short answer must survive too."""
    c = _chunk("מה הסלוגן?", "פאלו אלטו – דרמת המתח החדשה של ערוץ 12")
    assert _is_meaningful_short_section(c) is True
    assert len(_apply_semantic_guardrails([c])) == 1
