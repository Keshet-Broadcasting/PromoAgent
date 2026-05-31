from __future__ import annotations

import importlib


def test_alias_extraction_returns_multiple_shows():
    from app.domain_catalog import expand_aliases, extract_show_names

    query = "תשווה בין נינג'ה ישראל, חתונמי והמירוץ למיליון"
    expanded = expand_aliases(query)
    shows = extract_show_names(expanded)

    assert "נינג'ה ישראל" in shows
    assert "חתונה ממבט ראשון" in shows
    assert "המירוץ למיליון" in shows


def test_kochav_alias_does_not_corrupt_other_show_names():
    """The 'כוכב' alias must not rewrite the 'כוכב' inside other show names.

    Regression: 'רוקדים עם כוכבים' / 'כוכבים בריבוע' were being turned into
    'הכוכב הבאים', making the agent retrieve הכוכב הבא לאירוויזיון by mistake.
    """
    from app.domain_catalog import extract_show_names

    assert extract_show_names("מה היה הרייטינג של רוקדים עם כוכבים בעונה האחרונה?") == [
        "רוקדים עם כוכבים"
    ]
    assert extract_show_names("מה רייטינג הגמר של כוכבים בריבוע?") == ["כוכבים בריבוע"]
    # The intended expansions must still work:
    assert extract_show_names("רוקדים") == ["רוקדים עם כוכבים"]
    assert "הכוכב הבא" in extract_show_names("מה הרייטינג של כוכב")


def test_genre_detection_for_broad_query():
    from app.domain_catalog import genres_for_query, shows_for_genres

    genres = genres_for_query("מה ההבדל בין אסטרטגיית השקה של דרמה לעומת ריאליטי?")

    assert "drama" in genres
    assert "reality" in genres
    assert "אור ראשון" in shows_for_genres(["drama"])
    assert "חתונה ממבט ראשון" in shows_for_genres(["reality"])


def test_broad_retrieval_plan_for_drama_reality_comparison(monkeypatch):
    monkeypatch.setenv("BROAD_RETRIEVAL_ENABLED", "true")
    import app.service as svc
    importlib.reload(svc)

    plan = svc._build_retrieval_plan(
        "word_quote",
        "מה ההבדל בין אסטרטגיית השקה של דרמה לעומת ריאליטי?",
        ranking=False,
        season_filter=None,
    )

    assert plan.broad_scope is True
    assert plan.comparison is True
    assert plan.broad_word is True
    assert "drama" in plan.genres
    assert "reality" in plan.genres


def test_launch_selector_keeps_launch_rows_first():
    import app.service as svc

    plan = svc._RetrievalPlan(
        route="excel_numeric",
        query="איזו סדרה השיקה הכי גבוה מבין כל הדרמות?",
        event_intent="launch",
        broad_scope=True,
    )
    docs = [
        {"show_name": "אור ראשון", "episode_number": 2, "opening_point": 12, "promo_text": "שוטף"},
        {"show_name": "הראש", "episode_number": 1, "opening_point": 18, "promo_text": "השקה"},
        {"show_name": "נוטוק", "episode_number": 1, "opening_point": 17, "promo_text": "השקה"},
    ]

    selected = svc._select_excel_rows_for_plan(docs, plan)

    assert [d["show_name"] for d in selected] == ["הראש", "נוטוק"]


def test_word_metadata_filter_construction():
    from app.search_word_docs import _build_word_filter

    filt = _build_word_filter(
        show_names=["חתונה ממבט ראשון", "נינג'ה ישראל"],
        doc_types=["השקה"],
        question_types=["תובנות"],
    )

    assert "show_name eq 'חתונה ממבט ראשון'" in filt
    assert "show_name eq 'נינג''ה ישראל'" in filt
    assert "doc_type eq 'השקה'" in filt
    assert "question_type eq 'תובנות'" in filt
    assert " and " in filt
