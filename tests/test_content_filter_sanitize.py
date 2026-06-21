"""Regression tests for the content-filter sanitizer.

Guards the 2026-06-03 quote-corruption fix: the bare 'ירי' (shooting) pattern
must NOT match inside benign Hebrew words/names (it was turning the name
'איריס אברמוב' into 'אס' and 'מכירים' into 'מכ[תקיפה]ם' in quoted strategy text),
while real shooting terms are still masked.
"""
from app.formatters import _sanitize_for_content_filter as san


def test_iris_name_is_not_corrupted():
    # 'איריס' contains the substring 'ירי' — must be left intact.
    assert san("איריס אברמוב חוקרת מקרה רצח") == "איריס אברמוב חוקרת מקרה רצח"


def test_makirim_word_is_not_corrupted():
    # 'מכירים' contains 'ירי' — must be left intact.
    assert "מכירים" in san("מכירים סיפורי סינדרלה?")
    assert "[תקיפה]" not in san("מכירים סיפורי סינדרלה?")


def test_real_shooting_terms_still_masked():
    assert "[תקיפה]" in san("ירי לעבר השוטר")
    assert "[תקיפה]" in san("נשמעו יריות באוויר")
    assert "[תקיפה]" in san("הייתה ירייה ברחוב")


def test_other_violence_masking_unchanged():
    assert "[נשק]" in san("הוא שלף אקדח")
    assert "[קורבן]" in san("נמצאה גופה במלון")
