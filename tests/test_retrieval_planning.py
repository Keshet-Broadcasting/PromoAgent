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


def test_date_based_launch_finale_marking():
    """Launch = earliest date, finale = latest date, within a (show, season) group —
    works even when episode_number is blank (the common case)."""
    import app.service as svc

    rows = [
        {"show_name": "X", "season": "1", "date": "20.5.2025", "episode_number": ""},
        {"show_name": "X", "season": "1", "date": "18.5.2025", "episode_number": ""},  # launch
        {"show_name": "X", "season": "1", "date": "30.7.2025", "episode_number": ""},  # finale
        {"show_name": "X", "season": "1", "date": "6.6.2025",  "episode_number": ""},
    ]
    svc._mark_launch_finale(rows)
    roles = {r["date"]: r.get("_role") for r in rows}
    assert roles["18.5.2025"] == "launch"
    assert roles["30.7.2025"] == "finale"
    assert roles["20.5.2025"] == "regular"
    # _is_launch_row / _is_finale_row honor the date-derived role
    launch = next(r for r in rows if r["date"] == "18.5.2025")
    finale = next(r for r in rows if r["date"] == "30.7.2025")
    assert svc._is_launch_row(launch) and not svc._is_finale_row(launch)
    assert svc._is_finale_row(finale) and not svc._is_launch_row(finale)


def test_launch_finale_same_date_tie_prefers_valid_metric():
    """When two rows share the latest date (e.g. החיים 18.11.2024 finale + a
    malformed same-night recap with a blank opening_point), the finale slot must
    go to the row WITH a valid metric, not the blank one."""
    import app.service as svc

    rows = [
        {"show_name": "Y", "season": "", "date": "23.9.2024",  "opening_point": "24.5"},  # launch
        {"show_name": "Y", "season": "", "date": "5.10.2024",  "opening_point": "15.0"},
        {"show_name": "Y", "season": "", "date": "18.11.2024", "opening_point": "16.5"},  # real finale
        {"show_name": "Y", "season": "", "date": "18.11.2024", "opening_point": ""},      # malformed recap
    ]
    svc._mark_launch_finale(rows)
    finale = next(r for r in rows if r["date"] == "18.11.2024" and r["opening_point"] == "16.5")
    malformed = next(r for r in rows if r["date"] == "18.11.2024" and r["opening_point"] == "")
    assert finale["_role"] == "finale"
    assert malformed["_role"] != "finale"
    assert next(r for r in rows if r["date"] == "23.9.2024")["_role"] == "launch"


def test_parse_date_key_formats():
    from app.service import _parse_date_key

    assert _parse_date_key("18.5.2025") == (2025, 5, 18)
    assert _parse_date_key("21.10.24") == (2024, 10, 21)
    assert _parse_date_key("6/6/2021") == (2021, 6, 6)
    assert _parse_date_key("20.5")[1:] == (5, 20)   # no year → year 0
    assert _parse_date_key("") is None
    assert _parse_date_key("not a date") is None


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


def test_drama_genre_query_targets_only_drama_shows(monkeypatch):
    """Regression (2026-06-03): a drama-only synthesis question (no show named)
    must scope retrieval to drama shows only. The prod bug leaked reality shows
    (מאסטר שף, חתונה ממבט ראשון) into a drama question because broad retrieval
    was off; here we assert the plan target is drama-only when it IS on."""
    monkeypatch.setenv("BROAD_RETRIEVAL_ENABLED", "true")
    import app.service as svc
    importlib.reload(svc)

    plan = svc._build_retrieval_plan(
        "hybrid",
        "סכם את כל התובנות של סדרות הדרמה עם הרייטינג הגבוה והבא את הפתרונות",
        ranking=False,
        season_filter=None,
    )

    assert plan.genres == ["drama"]
    assert plan.broad_scope is True
    assert plan.broad_word is True

    targets = plan.target_show_names
    assert "אור ראשון" in targets and "חולי אהבה" in targets  # drama shows present
    # No reality shows may leak into a drama-only plan:
    for reality_show in ("מאסטר שף", "חתונה ממבט ראשון", "רוקדים עם כוכבים", "הזמר במסכה"):
        assert reality_show not in targets


def test_coverage_intent_set_for_all_dramas_query(monkeypatch):
    """Regression (2026-06-03): 'quote ALL the dramas' must set plan.coverage so
    retrieval fetches per-show (every drama represented) instead of a single
    top-N that omitted אף אחד לא עוזב את פאלו אלטו despite its 33 mentions."""
    monkeypatch.setenv("BROAD_RETRIEVAL_ENABLED", "true")
    import app.service as svc
    importlib.reload(svc)

    plan = svc._build_retrieval_plan(
        "word_quote",
        "צטט במדוייק את האסטרטגיות מכירה של כל הדרמות בשנה האחרונה",
        ranking=False,
        season_filter=None,
    )
    assert plan.coverage is True
    assert plan.broad_word is True
    assert len(plan.target_show_names) > 1
    # A single-show quote must NOT trigger coverage (stays a focused lookup):
    narrow = svc._build_retrieval_plan(
        "word_quote", "צטט את אסטרטגיית ההשקה של הראש", ranking=False, season_filter=None
    )
    assert narrow.coverage is False


def test_per_show_fetch_falls_back_when_filters_disabled(monkeypatch):
    """Without the show_name filter, per-show calls would all return the same
    unfiltered set — so the helper must fall back to a single search instead."""
    import app.search_word_docs as swd

    calls = {"n": 0}

    def fake_search(query, top=5, **kwargs):
        calls["n"] += 1
        return [{"chunk_id": f"c{calls['n']}", "show_name": "X"}]

    monkeypatch.setattr(swd, "_WORD_METADATA_FILTERS_ENABLED", False)
    monkeypatch.setattr(swd, "search_word_docs", fake_search)

    docs = swd.fetch_word_docs_per_show("q", ["A", "B", "C"], top_per_show=2)
    # One fallback search, not one-per-show:
    assert calls["n"] == 1
    assert len(docs) == 1


def test_synthesis_phrasing_triggers_strategic_intent():
    """Regression (2026-06-03): summarization/synthesis phrasing must raise
    word_top to 12. Previously only recommendation phrasing matched, so
    'סכם את התובנות' got the thin 6-chunk path."""
    from app.service import _STRATEGIC_INTENT_PATTERNS

    for q in (
        "סכם את כל התובנות של סדרות הדרמה והבא את הפתרונות המרכזיים",
        "מה הדפוסים החוזרים בפרומואים המצליחים?",
        "מה מאפיין את הקמפיינים שהביאו לצפייה בלייב?",
    ):
        assert _STRATEGIC_INTENT_PATTERNS.search(q), q
    # A plain numeric lookup must NOT trigger the strategic (wide) path:
    assert not _STRATEGIC_INTENT_PATTERNS.search("מה היה הרייטינג של הראש בעונה 1?")


def test_campaign_retrospective_phrasing_routes_out_of_unknown():
    """Real promo-team campaign phrasing must not fall into shallow unknown retrieval.

    Regression (2026-06-17): MasterChef VIP / "נבחרת החלומות" questions like
    "why did we call it X and not Y" and "were there dishes in those promos"
    routed to unknown, so they only got top-3 shallow retrieval instead of
    campaign-analysis context.
    """
    from app.query_router import ROUTE_HYBRID, ROUTE_WORD, classify

    naming = classify("למה בעונה הקודמת של מאסטר שף VIP קראנו לזה נבחרת החלומות ולא אולסטרס?")
    promo_usage = classify("היו בפרומואים של העונה הזו מנות?")

    assert naming.route == ROUTE_WORD
    assert promo_usage.route == ROUTE_HYBRID


def test_campaign_term_normalization_covers_allstars_variant():
    """Users write אולסטרס, while source docs may use אולסטארס."""
    from app.domain_catalog import expand_aliases

    normalized = expand_aliases("למה לא קראנו לזה אולסטרס?")

    assert "אולסטארס" in normalized
    assert "אולסטרס" not in normalized


def test_followup_retrieval_query_uses_recent_campaign_context():
    """Retrieval should see the prior campaign when the user asks 'העונה הזו'."""
    from app.service import _contextualize_followup_query

    history = [
        {
            "role": "user",
            "content": "למה בעונה הקודמת של מאסטר שף VIP קראנו לזה נבחרת החלומות ולא אולסטרס?",
        },
        {
            "role": "assistant",
            "content": "השם נבחר כדי לבדל את עונת ה-VIP כעונה מלאה ולא כספין-אוף.",
        },
    ]

    contextualized = _contextualize_followup_query("היו בפרומואים של העונה הזו מנות?", history)

    assert contextualized.startswith("היו בפרומואים של העונה הזו מנות?")
    assert "מאסטר שף" in contextualized
    assert "נבחרת החלומות" in contextualized
    assert "VIP" in contextualized
    assert "אולסטארס" in contextualized


def test_followup_retrieval_query_handles_empty_or_malformed_history():
    """Malformed client history should not break retrieval contextualization."""
    from app.service import _contextualize_followup_query

    query = "היו בפרומואים של העונה הזו מנות?"

    assert _contextualize_followup_query(query, []) == query

    contextualized = _contextualize_followup_query(
        query,
        [
            None,
            "bad-turn",
            {"role": "user", "content": None},
            {"role": "user", "content": "מאסטר שף VIP נבחרת החלומות\x00\x01" * 300},
        ],
    )

    assert "מאסטר שף" in contextualized
    assert "נבחרת החלומות" in contextualized
    assert "\x00" not in contextualized
    assert "\x01" not in contextualized


def test_hybrid_prompt_guards_against_campaign_role_overstatement():
    """Case 64 regression: appearing in promos does not prove central campaign role."""
    from app.prompts import build_messages

    messages = build_messages(
        "hybrid",
        "ctx",
        "במאסטר שף VIP / נבחרת החלומות, האם היו בפרומואים מנות ומה היה התפקיד שלהן בקמפיין?",
    )

    system = messages[0]["content"]
    assert "הופיע בפרומואים" in system
    assert "עוגן מרכזי" in system
    assert "קמפיין ההשקה" in system


def test_word_prompt_enforces_single_campaign_retrospective_shape():
    """Campaign retrospectives should open with the thesis, not a source dump."""
    from app.prompts import build_messages

    messages = build_messages(
        "word_quote",
        "ctx",
        "למה בעונה הקודמת של מאסטר שף VIP קראנו לזה נבחרת החלומות ולא אולסטארס?",
    )

    system = messages[0]["content"]
    assert "מסקנה אסטרטגית" in system
    assert "קשת הקמפיין" in system
    assert "ציטוטים" in system


def test_strategic_mode_prompt_triggers_match_retrieval_triggers():
    """Regression (2026-06-11): the retrieval layer widens for synthesis phrasing
    (סכם/תובנות/פתרונות), but the prompt-level Strategic Synthesis Mode trigger
    list contained only recommendation phrasing — so the model received 12 wide
    chunks and still answered in Coverage/summary style instead of thesis-first
    strategy (the 'analyst vs strategist' gap vs the team's Custom GPT). The
    prompt section must keep the synthesis triggers and the precedence rule over
    Coverage Mode."""
    from app.prompts import SYSTEM_PROMPT

    start = SYSTEM_PROMPT.index("## Strategic Synthesis Mode")
    section = SYSTEM_PROMPT[start:]

    # Synthesis phrasing from _STRATEGIC_INTENT_PATTERNS must appear as triggers:
    for phrase in ("סכם", "תובנות", "פתרונות", "דפוסים", "מאפיין"):
        assert phrase in section, f"synthesis trigger missing from prompt: {phrase}"
    # Precedence over Coverage Mode and thesis-first must be stated:
    assert "Coverage Mode" in section
    assert "thesis" in section


def test_per_show_fetch_prefers_strategy_section(monkeypatch):
    """Regression (2026-06-03): for a 'quote the strategies' coverage query, each
    show's strategy chunk must be pulled FIRST — short strategy answers rank low
    semantically, so without the prefer bias the (now-indexed) פאלו אלטו strategy
    chunk was retrieved-but-not-surfaced."""
    import app.search_word_docs as swd

    monkeypatch.setattr(swd, "_WORD_METADATA_FILTERS_ENABLED", True)

    calls = []

    def fake_search(query, top=5, **kwargs):
        calls.append(kwargs.get("question_types"))
        qt = kwargs.get("question_types")
        if qt == ["אסטרטגיה", "סלוגן"]:
            return [{"chunk_id": "strat", "question_type": "אסטרטגיה", "show_name": "S"}]
        return [{"chunk_id": "tovanot", "question_type": "תובנות", "show_name": "S"}]

    monkeypatch.setattr(swd, "search_word_docs", fake_search)

    docs = swd.fetch_word_docs_per_show(
        "q", ["S"], top_per_show=1, prefer_question_types=["אסטרטגיה", "סלוגן"]
    )
    # The strategy chunk was preferred over the higher-ranked 'תובנות' chunk:
    assert docs and docs[0]["chunk_id"] == "strat"
    assert ["אסטרטגיה", "סלוגן"] in calls  # tier-1 preferred fetch happened first


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
