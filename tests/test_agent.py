"""
test_agent.py

Lightweight smoke and regression suite for the Promo agent.

Two modes
---------
Fast (default) — router checks only, no network calls:
    python tests/test_agent.py

Live — full end-to-end including LLM responses (costs tokens, ~60–120 s):
    python tests/test_agent.py --live

Check types
-----------
ROUTE    : classify(query).route matches expected — deterministic, no network
SHAPE    : answer is a non-empty string
HEBREW   : answer contains at least 10 Hebrew Unicode characters
KEYWORD  : a known anchor word appears in the response
           (structural signal — not a semantic assertion)
SOURCE   : for grounded routes — answer contains a file/sheet/source citation,
           or explicitly says the data was not found (both are grounded)
CAUTION  : for unknown/negative routes — answer contains hedging language
           (grounds in retrieved data, admits insufficient evidence, asks for
           clarification, or qualifies with uncertainty)
CHUNK    : for multi-part Word questions — at least one of the expected chunk
           IDs appears in the answer, confirming page metadata was preserved
           through the full pipeline (retrieve → format → LLM cite)
NOINVENT : for negative tests — none of the must_not_include phrases appear;
           guards against the model sourcing real data for fictional queries
REQKW    : for reasoning/comparison tests — ALL of the required_keywords must
           appear in the answer (stricter than KEYWORD which is OR-logic);
           used when multiple specific data points must be cited together
           (e.g. both episode ratings in a comparison question)
LISTSIZE : for ranking/completeness tests — the answer must contain at least
           min_list_items distinct list items (seasons, episodes, or numbered
           entries); catches "winner only" answers that skip the full ordered list

Live subset
-----------
Only cases with live=True run when --live is passed.
Route checks always run for ALL cases regardless of the live flag.
"""

from __future__ import annotations

import os
import sys
import logging

# Ensure project root is on sys.path so 'app' is importable regardless of
# how this file is invoked (python tests/test_agent.py or python -m tests.test_agent)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unicodedata
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Test case definition
# ---------------------------------------------------------------------------

@dataclass
class Case:
    id: str
    query: str
    expected_route: str
    keywords: list[str] = field(default_factory=list)
    """Anchor words — at least one must appear in the LLM answer (topic signal)."""

    source_markers: list[str] = field(default_factory=list)
    """File/source citation cues expected in the answer, or not-found signals."""

    required_chunk_ids: list[str] = field(default_factory=list)
    """Chunk position strings (e.g. '0_122') that must appear in the answer.
    Verifies that page-level metadata survived the retrieve → format → LLM cite
    pipeline end-to-end. Only checked in live mode."""

    must_not_include: list[str] = field(default_factory=list)
    """Phrases that must NOT appear in the answer.
    Used in negative tests to detect hallucinated content from other real shows."""

    required_keywords: list[str] = field(default_factory=list)
    """ALL of these keywords must appear in the answer (AND-logic).
    Used in reasoning/comparison tests where multiple data points must be
    cited together — e.g. both episode ratings in a cross-season comparison.
    Checked as REQKW in live mode; complements the OR-logic `keywords` field."""

    min_list_items: int = 0
    """Minimum number of distinct list items the answer must contain.
    0 means unchecked.  Checked as LISTSIZE in live mode.

    Counting rules (in priority order):
      1. Distinct 'עונה N' season labels  — used for full-season rankings
      2. Numbered list lines ('1. …')     — used for any ordered list
      3. Bullet / dash lines ('- …')      — used for unordered lists

    Catches "winner only" answers to ranking questions that should return
    the full ordered list (e.g. min_list_items=4 for a 7-season ranking)."""

    expect_caution: bool = False
    """If True, answer must contain hedging / grounding language."""

    live: bool = True
    """If False, this case is skipped in live (LLM) checks but still runs in
    the fast offline route-only suite."""

    description: str = ""


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

CASES: list[Case] = [

    # =========================================================================
    # EXCEL_NUMERIC — single-value and ranking lookups
    # =========================================================================

    Case(
        id="E1",
        query="מה היה ריטינג ההשקה של נוטוק",
        expected_route="excel_numeric",
        keywords=["נוטוק"],
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description="Single numeric lookup — answer must mention show name and cite source",
    ),
    Case(
        id="E2",
        query="מה היה ריטינג ההשקה של הראש",
        expected_route="excel_numeric",
        keywords=["16"],
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description="Single numeric lookup — known rating is ~16.2%, must cite file",
    ),
    Case(
        id="E3",
        query="איזו עונה של התכנית חתונה ממבט ראשון השיקה הכי גבוה? סדר לי את הריטינג של ההשקות",
        expected_route="excel_numeric",
        keywords=["21", "עונה"],
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description="Ranking question — season 5 leads with 21.7%, must cite file",
    ),

    # =========================================================================
    # WORD_QUOTE — single-chunk quote/strategy lookups
    # =========================================================================

    Case(
        id="W1",
        query="מה היו הסלוגנים של קמפיין ההשקה, קמפיין האמצע וקמפיין הגמר של נינג'ה ישראל בעונה האחרונה",
        expected_route="word_quote",
        keywords=["קמפיין"],   # model answers campaign content without always repeating show name
        source_markers=["docx", "מסמך", "מסמכי", "נשלף", "לא נמצא"],
        description="Slogan retrieval — must cite doc or explicitly say not found",
    ),
    Case(
        id="W2",
        query="צטט ספציפית ממסמך תובנות ריאליטי את התובנות המרכזיות של הכוכב הבא גמר עונה 12",
        expected_route="word_quote",
        keywords=["כוכב"],
        source_markers=["docx", "מסמך", "מסמכי", "נשלף"],
        description="Explicit quote request — must name the source document",
    ),
    Case(
        id="W3",
        query="מהם החוקים של עשה ואל תעשה בטונייטים של חתונה ממבט ראשון",
        expected_route="word_quote",
        keywords=["תעשה"],
        source_markers=["docx", "מסמך", "מסמכי", "נשלף"],
        description="Guidelines retrieval — must cite source document",
    ),

    # =========================================================================
    # HYBRID — requires both Excel and Word evidence
    # =========================================================================

    Case(
        id="H1",
        query="תנתח לי איך כוונות הצפיה לדרמות האלו נכונות ביחס לנקודת הפתיחה בפועל של השקת הדרמות ומה אפשר ללמוד מזה להבא",
        expected_route="hybrid",
        keywords=[],
        source_markers=["xlsx", "מעקבי", "docx", "מסמך", "מסמכי", "נשלף"],
        description="Analysis across both sources — must cite at least one source",
    ),
    Case(
        id="H2",
        query="איזה טונייטים ספציפיים בעונות 6 ו 7 (חתונמי) הביאו את המספרים הכי גבוהים לנקודת הפתיחה ולמה",
        expected_route="hybrid",
        keywords=["25", "24"],
        source_markers=["xlsx", "מעקבי", "docx", "מסמך", "מסמכי", "נשלף"],
        description="Numeric ranking + reason — must cite at least one source",
    ),

    # =========================================================================
    # UNKNOWN — open-ended opinion / insufficient grounding
    # =========================================================================

    Case(
        id="U1",
        query="מה היית מבטיח השנה בהשקת המירוץ למליון וממה היית נמנע?",
        expected_route="unknown",
        keywords=[],
        expect_caution=True,
        description="Open-ended opinion — must hedge or ground in retrieved data",
    ),
    Case(
        id="U2",
        query="מה המסקנה שלך לגבי קידום טונייטי בסדרה של חנוך דאום - מה הכי נכון להבטיח?",
        expected_route="unknown",
        keywords=[],
        expect_caution=True,
        description="Strategic open-ended — must not assert conclusions without grounding",
    ),

    # =========================================================================
    # MW — Multi-part Word: questions that require 2–3 separate chunks
    # =========================================================================

    Case(
        id="MW1",
        query="מה היו הסלוגנים של קמפיין ההשקה, קמפיין האמצע וקמפיין הסיום של חתונה ממבט ראשון עונה 7?",
        expected_route="word_quote",
        keywords=["חתונמי", "צונאמי"],
        source_markers=["docx", "מסמך"],
        required_chunk_ids=["0_122", "0_128"],
        # chunk 0_122 = launch slogan ("חתונמי 2025 \ הגיע הזמן לאהבה")
        # chunk 0_128 = finale slogans ("הסיום צונאמי בחתונמי" / "הסוף בענק ממש")
        description=(
            "Multi-part: 3 campaign slogans spanning ≥2 chunks — "
            "model must scan all chunks and cite both chunk positions"
        ),
        live=True,
    ),
    Case(
        id="MW2",
        query="מה הייתה האסטרטגיה של קמפיין ההשקה של חתונה ממבט ראשון עונה 7 ואיך השתנה לקראת ההשקה?",
        expected_route="word_quote",
        keywords=["בולטות", "מוזיקה"],
        # chunk 0_123 describes the brief change: received bad prominence indicators,
        # the campaign pivot was driven by new music ("I'm so excited", "מאמאמיה")
        source_markers=["docx", "מסמך"],
        # required_chunk_ids intentionally omitted: the brief-change narrative may reach
        # the model via captions or adjacent chunks; chunk citation is too brittle here.
        description=(
            "Multi-chunk strategy narrative — brief change content lives in chunk 0_123; "
            "tests that caption highlights the pivot, not only the first chunk body"
        ),
        live=True,
    ),

    # =========================================================================
    # C — Caption-sensitive: answer lives in Azure extractive highlight
    # =========================================================================

    Case(
        id="C1",
        query="מה הסלוגן של השקת חתונה ממבט ראשון עונה 7?",
        expected_route="word_quote",
        keywords=["הגיע הזמן לאהבה"],
        # Azure caption for chunk 0_122 explicitly surfaces "חתונמי 2025 \ הגיע הזמן לאהבה"
        # before the full chunk (which opens with a scheduling table).
        source_markers=["docx", "מסמך"],
        required_chunk_ids=["0_122"],
        description=(
            "Caption-sensitive: slogan lives in Azure highlight of chunk 0_122; "
            "without the caption the model might miss it under the scheduling table text"
        ),
        live=True,
    ),

    # =========================================================================
    # HB — Hybrid with both sources explicitly named in the question
    # =========================================================================

    Case(
        id="HB1",
        query="מה היה הרייטינג של השקת חתונה ממבט ראשון עונה 7 ומה הייתה האסטרטגיה של הקמפיין?",
        expected_route="hybrid",
        keywords=["רייטינג"],
        source_markers=["xlsx", "מעקבי", "docx", "מסמך"],
        description=(
            "Explicit dual-source question — answer must cite Excel rating "
            "AND Word strategy doc; tests that both sections appear"
        ),
        live=True,
    ),

    # =========================================================================
    # WA — Word-Answers regression: @search.answers promotion
    #
    # Azure AI Search returns semantic answers in @search.answers separately
    # from the standard @value ranked list. If the best answer chunk ranks
    # outside the top-N by reranker score but is surfaced by @search.answers,
    # the bot must still use it — otherwise it returns a false "no data found".
    #
    # Concrete case (May 12, 2026 investigation):
    #   Query: "מה היו התובנות של העונה האחרונה של רוקדים?"
    #   @search.answers[0] → chunk_332  score=0.965  contains:
    #     "רוקדים עם כוכבים בעונה הראשונה בקשת- 44% כוונות בשלב הראשון של הקמפיין"
    #   Bot's top-5 by reranker: chunk_622/247/354/1_21/697_1 — all about MasterChef
    #   Bot conclusion: "לא נמצאו נתונים עבור התוכנית רוקדים עם כוכבים"  ← FALSE NEGATIVE
    # =========================================================================

    Case(
        id="WA1",
        query="מה היו התובנות של העונה האחרונה של רוקדים עם כוכבים?",
        expected_route="word_quote",
        keywords=["44", "כוונות", "רוקדים"],
        source_markers=["docx", "מסמך", "מסמכי", "נשלף"],
        must_not_include=["לא נמצאו נתונים עבור התוכנית"],
        description=(
            "@search.answers regression: chunk_332 contains 'רוקדים עם כוכבים — 44% כוונות' "
            "but ranks outside the top-5 by reranker score. Without @search.answers promotion "
            "the bot returns a false 'no data found'. After fix, chunk_332 must surface and "
            "the answer must cite the 44% viewing-intention figure."
        ),
        live=True,
    ),

    # =========================================================================
    # N — Negative: fictional show / data not in index
    # =========================================================================

    Case(
        id="N1",
        query="מה היה הרייטינג של השקת הדרקון הירוק עונה 1?",
        expected_route="excel_numeric",
        keywords=[],
        source_markers=["לא נמצא", "אין מידע", "לא נמצאו", "לא קיים", "לא נשלף"],
        expect_caution=True,
        must_not_include=[
            "הזמר במסכה",  # real show whose chunks surface for 'dragon' queries
        ],
        # KNOWN LIMITATION — live=False until retriever-level show-name filtering is added.
        # Root cause: Azure Search returns "הזמר במסכה" (The Masked Singer) chunks when
        # queried for "דרקון ירוק" because the Masked Singer has a Green Dragon character.
        # The model then uses that data and ignores the show-name mismatch.
        # Prompt-level "check the show name" instructions are insufficient — the fix
        # requires post-retrieval filtering (reject docs where show_name ≠ queried show).
        # The route check (excel_numeric for any rating question) still runs offline.
        live=False,
        description=(
            "Fictional show — Excel index has no record; model must explicitly "
            "say not found rather than hallucinate a rating. "
            "KNOWN ISSUE: model confuses 'הדרקון הירוק' with 'הזמר במסכה' (Masked Singer dragon character). "
            "Needs retriever-level show-name filtering before this live test can pass."
        ),
    ),
    Case(
        id="N2",
        query="מה הסלוגן של קמפיין ההשקה של הדרקון הירוק עונה 1?",
        expected_route="word_quote",
        keywords=[],
        source_markers=["לא נמצא", "אין מידע", "לא נמצאו"],
        expect_caution=True,
        must_not_include=[
            "הגיע הזמן לאהבה",     # חתונמי launch slogan
            "הסיום צונאמי בחתונמי", # חתונמי finale slogan
            "הסוף (בענק ממש)",      # חתונמי finale slogan part 2
        ],
        description=(
            "Fictional show slogan — Word index has no record; model must not "
            "hallucinate or confuse with slogans from other real shows"
        ),
        live=True,
    ),

    # =========================================================================
    # SB — Semantic bridge: "השקה" user vocabulary ≠ source-document labels
    #
    # The user says "השקה" (launch) but the Excel rows are identified by date,
    # by "פרק 1" / "פרק ראשון" column labels, or by "ראשון" ordinal — NOT by the
    # word "השקה" itself.  These tests verify that the agent bridges the gap
    # and retrieves the correct row rather than:
    #   (a) skipping the season entirely
    #   (b) returning the second episode instead of the first
    #
    # Season data confirmed from source images:
    #   Season 3  E1  22.2.2020  opening-point 21   rating 17.8
    #   Season 3  E2  23.2.2020  opening-point 26   rating 23.7   ← NOT the launch
    #   Season 7  E1  26.1.2025  opening-point 23.5 rating 20.7
    #   Season 7  E2  27.1.2025  opening-point 20   rating 16.4   ← NOT the launch
    #   Season 5  E1  09.5.2022  rating 21.7                      ← all-time highest
    # =========================================================================

    Case(
        id="SB1",
        query="מה היה רייטינג פרק הפתיחה של חתונה ממבט ראשון עונה 7?",
        expected_route="excel_numeric",
        keywords=["20.7"],
        # S7E1 (26.1.2025) is the launch: rating 20.7, opening-point 23.5.
        # S7E2 (27.1.2025) rating is 16.4 — if the agent returns that, the keyword fails.
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description=(
            "Semantic bridge: user says 'פרק הפתיחה'; source labels the row by date or "
            "'פרק 1'. Must retrieve S7E1 (26.1.2025, rating 20.7), NOT S7E2 (16.4)."
        ),
        live=True,
    ),
    Case(
        id="SB2",
        query="מה היה רייטינג ההשקה של חתונה ממבט ראשון עונה 3?",
        expected_route="excel_numeric",
        keywords=["17.8"],
        # S3E1 (22.2.2020) is the launch: rating 17.8, opening-point 21.
        # S3E2 (23.2.2020) has a higher rating (23.7) but it is NOT the launch.
        # A semantic retrieval that returns only E2 would fail this keyword check.
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description=(
            "Structural bridge: Season 3 launched with two consecutive episodes on "
            "back-to-back nights (22.2 & 23.2.2020). The first (22.2, 17.8) is the "
            "launch; the second (23.2, 23.7) is not, even though its rating is higher. "
            "Tests that the agent picks the opening episode rather than the peak."
        ),
        live=True,
    ),
    Case(
        id="SB3",
        query="סדר לי את רייטינג ההשקות של כל העונות של חתונה ממבט ראשון",
        expected_route="excel_numeric",
        keywords=["עונה 3"],
        # Season 3 has a structurally different layout (two-night launch) and
        # Season 7 uses "פרק ראשון" labels — both are at risk of being skipped.
        # Season 5 (21.7) should appear as the highest-rated launch.
        # The keyword "עונה 3" verifies that the structurally non-standard season
        # was NOT dropped from the ranked list.
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description=(
            "Ranking completeness: all seasons must appear in the ordered list. "
            "Season 3 (two-night launch, 17.8) and Season 7 ('פרק ראשון' label, 20.7) "
            "are structurally different from the other seasons and must not be skipped. "
            "Season 5 (21.7) should rank first."
        ),
        live=True,
    ),
    Case(
        id="SB4",
        query="מה הייתה נקודת הפתיחה של פרק ראשון של חתונה ממבט ראשון עונה 7?",
        expected_route="excel_numeric",
        keywords=["23.5"],
        # S7E1 opening-point = 23.5 (26.1.2025).
        # S7E2 opening-point = 20 (27.1.2025).
        # Uses "פרק ראשון" vocabulary — source may label this as a date or ordinal.
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description=(
            "Vocabulary bridge: 'פרק ראשון' ≡ 'השקה' for opening-point questions. "
            "S7E1 opening-point = 23.5. Must not return S7E2 opening-point (20)."
        ),
        live=True,
    ),

    # =========================================================================
    # RC — Reasoning and Comparison
    #
    # These tests require the agent to do more than retrieve-and-report.
    # They exercise four distinct reasoning capabilities:
    #
    #   1. Semantic bridging   — user term ("פרק הפתיחה") ≠ source label (date row)
    #   2. Exclusion logic     — "launch" means FIRST episode, not HIGHEST episode
    #   3. Cross-season comparison — compare two seasons using their CORRECT rows
    #   4. Episode labeling    — both episodes in a two-night premiere must be
    #                            retrieved AND attributed to the correct ordinal
    #
    # Failure signatures the tests are designed to catch:
    #   - Agent returns S3E2 (23.7) instead of S3E1 (17.8) as S3's launch
    #     because S3E2 is semantically more salient (higher rating)
    #   - Agent skips S3 or S7 from a full ranking (structural outlier)
    #   - Agent swaps ordinal labels (calls the higher-rated row "פרק 1")
    #   - Agent draws wrong comparison conclusion from misidentified launch row
    #
    # The REQKW check (AND-logic) is used where multiple specific data points
    # must ALL be present to confirm correct multi-row reasoning.
    # =========================================================================

    Case(
        id="RC1",
        query=(
            "מה היה ריטינג פרק הפתיחה של חתונה ממבט ראשון עונה 3 - "
            "לא הפרק הגבוה ביותר, אלא הפרק הראשון שיצא?"
        ),
        expected_route="excel_numeric",
        keywords=["17.8"],
        # Semantic bridge: "פרק הפתיחה" / "פרק הראשון שיצא" → row 1 by date (22.2.2020).
        # Exclusion logic: query explicitly says "not the highest" — model must not pick
        # S3E2 (23.2.2020, 23.7) even though it has a higher rating.
        # Expected answer shape: cites 17.8 (E1); may also mention 23.7 for context.
        # Failure: returns 23.7 as the launch → keyword check fails.
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description=(
            "Exclusion reasoning: query explicitly says 'not the highest, the first'. "
            "S3E1 (22.2.2020) = 17.8 is the launch; S3E2 (23.2.2020) = 23.7 is not, "
            "even though it is higher. Failure: returns 23.7 as the launch rating."
        ),
        live=True,
    ),
    Case(
        id="RC2",
        query=(
            "עונה 3 ועונה 7 של חתונה ממבט ראשון - "
            "איזו מהן השיגה ריטינג השקה גבוה יותר? הצג את הנתונים ואת המסקנה."
        ),
        expected_route="excel_numeric",
        required_keywords=["17.8", "20.7"],
        # Both correct launch ratings must appear in the answer:
        #   S3E1 = 17.8  (22.2.2020)
        #   S7E1 = 20.7  (26.1.2025)
        # If the agent uses S3E2 (23.7) instead of S3E1, it will:
        #   (a) cite 23.7 instead of 17.8 → "17.8" missing from answer → REQKW fails
        #   (b) conclude "Season 3 opened higher" → incorrect comparison
        # Expected answer shape: table or two lines with both values, naming S7 as winner.
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description=(
            "Cross-season comparison: correct launch ratings are S3=17.8, S7=20.7. "
            "S7 opened higher (20.7 > 17.8). "
            "REQKW requires both values — if S3E2 (23.7) is used instead, "
            "'17.8' is absent and the check fails. Failure also produces wrong conclusion "
            "(S3 named as winner instead of S7)."
        ),
        live=True,
    ),
    Case(
        id="RC3",
        query=(
            "דרג את כל עונות חתונה ממבט ראשון לפי ריטינג ההשקה מהגבוה לנמוך. "
            "איזו עונה מדורגת ראשונה ומה הריטינג שלה?"
        ),
        expected_route="excel_numeric",
        keywords=["21.7"],
        # Season 5 (21.7) is the highest launch — must appear at #1.
        # Season 3 (17.8, two-night premiere) and Season 7 (20.7, 'פרק ראשון' label)
        # have non-standard structures; if either is skipped the ranking is incomplete.
        # If S3E2 (23.7) is used as S3's launch, Season 3 would incorrectly rank above
        # Season 5 (21.7), displacing the correct #1.
        # Expected answer shape: ordered list, S5 first, then S7, then remaining seasons.
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description=(
            "Ranking completeness + structural outlier: S5 (21.7) must rank first. "
            "S3 (17.8, two-night) and S7 (20.7, 'פרק ראשון') must appear in correct order. "
            "Failure: using S3E2 (23.7) pushes S3 above S5 → wrong #1."
        ),
        live=True,
    ),
    Case(
        id="RC4",
        query="בחתונה ממבט ראשון עונה 3, מה היה ריטינג פרק 1 לעומת פרק 2 של העונה?",
        expected_route="excel_numeric",
        required_keywords=["17.8", "23.7"],
        # Both S3E1 (22.2.2020, 17.8) and S3E2 (23.2.2020, 23.7) must be cited.
        # REQKW enforces AND-logic: both values must appear.
        # This tests episode labeling — the agent must:
        #   (a) retrieve two distinct rows from S3
        #   (b) assign 17.8 to "פרק 1" and 23.7 to "פרק 2" (by chronological order)
        # Expected answer shape: clear per-episode attribution (פרק 1: 17.8, פרק 2: 23.7).
        # Failure mode A: only one value → only one episode was retrieved.
        # Failure mode B: values swapped → ordinal attribution is wrong.
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description=(
            "Episode labeling: both S3E1 (22.2.2020, 17.8) and S3E2 (23.2.2020, 23.7) "
            "must be retrieved and correctly attributed. REQKW enforces both values appear. "
            "Failure A: one value missing → only one episode retrieved. "
            "Failure B: values present but swapped → ordinal attribution wrong."
        ),
        live=True,
    ),

    # =========================================================================
    # RS — Ranking Shape: answer must be a complete ordered list, not a winner summary
    # CS — Completeness: all required items must appear (multi-row data)
    # NR — Negative Reasoning: agent must cite structural data limitations, not guess
    #
    # These tests go beyond verifying the right data is retrieved.
    # They verify the SHAPE of the answer and the agent's ability to
    # recognize when the data structure cannot support the question.
    #
    # RS tests catch "winner only" answers to questions that require a full list.
    # CS tests catch "first match only" answers to questions that require all items.
    # NR tests catch invented data when the data schema has no matching dimension.
    # =========================================================================

    Case(
        id="RS1",
        query=(
            "תן לי רשימה מסודרת של כל העונות של חתונה ממבט ראשון לפי ריטינג ההשקה, "
            "מהגבוה לנמוך"
        ),
        expected_route="excel_numeric",
        required_keywords=["21.7", "עונה 5"],
        # AND: both the exact top rating AND the season label must appear together.
        # This catches the case where the model says "Season 5 won" without citing
        # its actual rating, or cites 21.7 but doesn't attribute it to Season 5.
        keywords=["17.8"],
        # OR: soft check that Season 3 (structural outlier) appears in the list.
        # Season 3's two-night premiere makes it the most likely season to be dropped.
        min_list_items=4,
        # LISTSIZE: the answer must contain ≥4 distinct 'עונה N' labels.
        # With top-5 retrieval there are at least 5 seasons available; 4 is a
        # conservative floor that still catches "winner only" answers.
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description=(
            "Ranking shape: full ordered list required, not just the winner. "
            "REQKW: '21.7' AND 'עונה 5' must co-appear (top slot correct). "
            "KEYWORD: '17.8' (S3) is a soft check that structural outlier is present. "
            "LISTSIZE ≥4: catches 'Season 5 won' answers with no list. "
            "Failure: model returns only winner, or list has <4 seasons."
        ),
        live=True,
    ),
    Case(
        id="CS1",
        query=(
            "ספר לי על שני פרקי הפתיחה של עונה 3 של חתונה ממבט ראשון - "
            "מה היו הריטינגים של שני הלילות?"
        ),
        expected_route="excel_numeric",
        required_keywords=["17.8", "23.7"],
        # AND: both premiere nights must be cited.
        #   S3E1  22.2.2020  rating 17.8
        #   S3E2  23.2.2020  rating 23.7
        # A "first-match only" retrieval would return only E1 (17.8) and miss E2 (23.7).
        min_list_items=2,
        # LISTSIZE ≥2: answer must list at least 2 distinct items (the two nights).
        # Catches single-episode answers to an explicit "both nights" question.
        source_markers=["xlsx", "מעקבי", "קובץ", "נשלף"],
        description=(
            "Completeness: query asks explicitly for both premiere nights. "
            "REQKW: '17.8' (E1, 22.2) AND '23.7' (E2, 23.2) must both appear. "
            "LISTSIZE ≥2: answer must enumerate at least 2 separate items. "
            "Failure A: only 17.8 returned → first-match retrieval, E2 skipped. "
            "Failure B: only 23.7 returned → model retrieved only the higher-rated night."
        ),
        live=True,
    ),
    Case(
        id="NR1",
        query=(
            "מה היה ריטינג ההשקה של חתונה ממבט ראשון עונה 3 לפי חלוקת גיל הצופים?"
        ),
        expected_route="excel_numeric",
        keywords=[],
        source_markers=["לא נמצא", "אין מידע", "לא קיים", "לא נשלף", "אינם כוללים", "אין נתוני"],
        expect_caution=True,
        # The Excel data schema contains: date, opening-point %, episode rating,
        # competition. It does NOT contain any demographic (age/gender) breakdown.
        # The agent must recognize the mismatch between the question's dimension
        # (age group) and the available data schema, and say so explicitly.
        # It must NOT invent age-group percentages ("צעירים X%, מבוגרים Y%").
        must_not_include=["18-24", "25-34", "35-49", "גיל 18", "גיל 25", "גיל 35"],
        description=(
            "Negative reasoning: demographic breakdown by viewer age group is not in "
            "the data schema. Agent must explicitly say the data structure does not "
            "contain this dimension, rather than invent percentages. "
            "SOURCE/CAUTION: must contain an 'insufficient / not found' signal. "
            "NOINVENT: must not contain invented age-bracket values."
        ),
        live=True,
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_hebrew(text: str, min_chars: int = 10) -> bool:
    """Return True if text contains at least min_chars Hebrew Unicode characters."""
    count = sum(1 for c in text if "\u05d0" <= c <= "\u05ea")
    return count >= min_chars


def _contains_keyword(text: str, keywords: list[str]) -> tuple[bool, str]:
    """Return (True, keyword) for the first keyword found, else (False, '')."""
    for kw in keywords:
        if kw in text:
            return True, kw
    return False, ""


def _check_all_keywords(
    text: str, keywords: list[str]
) -> tuple[bool, list[str], list[str]]:
    """Return (all_found, found_kws, missing_kws) — every keyword must appear.

    Used for REQKW checks in reasoning/comparison tests where multiple
    specific data points (e.g. both episode ratings) must all be cited.
    """
    found = [kw for kw in keywords if kw in text]
    missing = [kw for kw in keywords if kw not in text]
    return len(missing) == 0, found, missing


def _count_list_items(text: str) -> int:
    """Count distinct list items in a structured answer.

    Counting priority:
      1. Distinct 'עונה N' labels — most reliable for season-ranking answers.
      2. Numbered list lines ('1. ' / '1) ') — any ordered list.
      3. Bullet / dash lines ('- ' / '* ') — unordered lists.

    Returns the first non-zero count found.
    """
    import re

    seasons = set(re.findall(r"עונה\s+\d+", text))
    if seasons:
        return len(seasons)

    numbered = re.findall(r"(?m)^\s*\d+[.)]\s", text)
    if numbered:
        return len(numbered)

    bullets = re.findall(r"(?m)^\s*[-*•]\s", text)
    return len(bullets)


def _has_source_evidence(text: str, markers: list[str]) -> tuple[bool, str]:
    """Return (True, marker) if any source citation marker appears in the answer.

    A 'not-found' signal ("לא נמצא") is also accepted as a grounded response.

    Built-in source signals checked before the per-case markers:
    - "לא נמצא" / "לא נמצאו" / "אין מידע" / "לא קיים" / "לא נשלף" — not-found grounding
    - "קטע"   — the model cited a chunk position (e.g. "קטע 0_122"), which is a direct
                 retrieval citation regardless of whether it also named the file
    - "[מקור" — the model echoed a [מקור: …] label from the formatted context
    """
    not_found_signals = ["לא נמצא", "לא נמצאו", "אין מידע", "לא קיים", "לא נשלף"]
    for sig in not_found_signals:
        if sig in text:
            return True, f"not-found signal: {sig!r}"
    # Chunk-position citation — universal source evidence
    if "קטע" in text:
        return True, "chunk citation: 'קטע'"
    # Echoed context label
    if "[מקור" in text:
        return True, "context label: '[מקור'"
    for m in markers:
        if m in text:
            return True, m
    return False, ""


def _has_caution(text: str) -> tuple[bool, str]:
    """Return (True, marker) if the answer contains hedging or grounding language.

    Checks that the model either:
    - grounds the answer in retrieved data ("על פי המידע שנשלף", "בהתבסס על", ...)
    - admits insufficient evidence ("לא נמצא", "לא ניתן לאשר", ...)
    - asks for clarification ("הבהרה", "האם אתה שואל", ...)
    - qualifies with uncertainty ("ייתכן", "לא בטוח", "חלקי", ...)
    """
    cautious_markers = [
        "על פי המידע",
        "על פי הנתונ",  # matches "על פי הנתונים שנשלפו" (common model phrasing)
        "בהתבסס על",
        "שנשלף",        # final-pe form
        "שנשלפ",        # regular-pe form — matches "שנשלפו", "שנשלפים" etc.
        "ממסמך",
        "לא נמצא",
        "לא נמצאו",
        "אין מידע",
        "לא ניתן לאשר",
        "לא ניתן",
        "הבהרה",
        "האם אתה שואל",
        "ייתכן",
        "לא בטוח",
        "חלקי",
        "מוגבל",
        "בהתאם למידע",
        "לפי המידע",
        "לא נשלף",
        "לא קיים",
    ]
    for m in cautious_markers:
        if m in text:
            return True, m
    return False, ""


def _check_chunk_ids(text: str, chunk_ids: list[str]) -> tuple[bool, list[str], list[str]]:
    """Return (all_found, found_ids, missing_ids) for required chunk IDs.

    The answer format includes 'קטע 0_122' style citations when the model
    follows the Word output discipline addendum.
    """
    found = [cid for cid in chunk_ids if cid in text]
    missing = [cid for cid in chunk_ids if cid not in text]
    return len(missing) == 0, found, missing


def _check_no_invention(text: str, forbidden: list[str]) -> tuple[bool, str]:
    """Return (clean, phrase) — clean=True means none of the forbidden phrases appear."""
    for phrase in forbidden:
        if phrase in text:
            return False, phrase
    return True, ""


# ---------------------------------------------------------------------------
# Test runners
# ---------------------------------------------------------------------------

def run_route_checks() -> tuple[int, int]:
    """Check that classify() returns the expected route for every case.

    Always runs offline — no network calls.
    Covers all cases regardless of their live flag.
    """
    from app.query_router import classify

    passed = failed = 0
    logger.info("ROUTE CHECKS (no network, all cases)\n" + "-" * 50)
    for case in CASES:
        result = classify(case.query)
        ok = result.route == case.expected_route
        mark = "PASS" if ok else "FAIL"
        passed += ok
        failed += not ok
        live_tag = "" if case.live else " [live=off]"
        status = (
            f"[{mark}] {case.id:<4} {result.route:<14} "
            f"(expected {case.expected_route:<14}) "
            f"{case.query[:50]}{live_tag}"
        )
        logger.info(status)
        if not ok:
            logger.info(f"       hits: {result.summary}")
    logger.info("")
    return passed, failed


def run_live_checks() -> tuple[int, int]:
    """Run full end-to-end checks including LLM responses.

    Only runs cases with live=True.
    """
    from app.agent import answer_question

    live_cases = [c for c in CASES if c.live]

    passed = failed = 0
    logger.info(
        f"LIVE CHECKS (router + retrieval + LLM) — {len(live_cases)}/{len(CASES)} cases\n"
        + "-" * 60
    )

    for case in live_cases:
        logger.info(f"\n[{case.id}] {case.description}")
        logger.info(f"  Query:  {case.query[:90]}")
        try:
            answer = answer_question(case.query)
        except Exception as exc:
            logger.error(f"  ERROR:  {exc}")
            failed += 1
            continue

        checks: list[tuple[str, bool, str]] = []

        # SHAPE
        checks.append(("SHAPE", bool(answer and answer.strip()), "answer is non-empty string"))

        # HEBREW
        checks.append(("HEBREW", _is_hebrew(answer), "answer contains ≥10 Hebrew chars"))

        # KEYWORD (only if keywords defined)
        if case.keywords:
            found, kw = _contains_keyword(answer, case.keywords)
            checks.append((
                "KEYWORD", found,
                f"one of {case.keywords} appears in answer (found: {kw!r})"
            ))

        # SOURCE — file/sheet/source citation or not-found signal
        if case.source_markers:
            ok, hit = _has_source_evidence(answer, case.source_markers)
            checks.append((
                "SOURCE", ok,
                f"source citation or not-found signal (found: {hit!r})"
            ))

        # CAUTION — hedging/grounding language
        if case.expect_caution:
            ok, hit = _has_caution(answer)
            checks.append((
                "CAUTION", ok,
                f"cautious/grounding language (found: {hit!r})"
            ))

        # CHUNK — expected chunk IDs appear in the answer (page metadata check)
        if case.required_chunk_ids:
            all_found, found_ids, missing_ids = _check_chunk_ids(answer, case.required_chunk_ids)
            checks.append((
                "CHUNK", all_found,
                (
                    f"chunk IDs in answer — "
                    f"required: {case.required_chunk_ids}, "
                    f"found: {found_ids}, "
                    f"missing: {missing_ids}"
                ),
            ))

        # NOINVENT — none of the forbidden phrases appear
        if case.must_not_include:
            clean, leaked = _check_no_invention(answer, case.must_not_include)
            checks.append((
                "NOINVENT", clean,
                (
                    f"forbidden phrases absent — "
                    f"checking: {case.must_not_include!r}, "
                    f"leaked: {leaked!r}"
                ),
            ))

        # REQKW — ALL required_keywords must appear (AND-logic; stricter than KEYWORD)
        if case.required_keywords:
            all_found, found_kws, missing_kws = _check_all_keywords(answer, case.required_keywords)
            checks.append((
                "REQKW", all_found,
                (
                    f"all required keywords — "
                    f"required: {case.required_keywords}, "
                    f"found: {found_kws}, "
                    f"missing: {missing_kws}"
                ),
            ))

        # LISTSIZE — answer must contain at least min_list_items distinct items
        if case.min_list_items:
            count = _count_list_items(answer)
            ok = count >= case.min_list_items
            checks.append((
                "LISTSIZE", ok,
                f"≥{case.min_list_items} distinct list items (found {count})"
            ))

        case_ok = all(ok for _, ok, _ in checks)
        passed += case_ok
        failed += not case_ok

        for check_name, ok, detail in checks:
            mark = "PASS" if ok else "FAIL"
            logger.info(f"  [{mark}] {check_name:<8} {detail}")

        preview = answer[:300]
        logger.info(f"  Answer: {preview}{'…' if len(answer) > 300 else ''}")

    logger.info("")
    return passed, failed


# ---------------------------------------------------------------------------
# Conversation history (multi-turn) tests — offline, no network
# ---------------------------------------------------------------------------

def run_history_checks() -> tuple[int, int]:
    """Verify that conversation history is threaded through the prompt layer.

    These are fast offline tests — they call build_messages() directly and
    inspect the resulting messages list structure.
    """
    from app.prompts import build_messages

    passed = failed = 0
    logger.info("HISTORY CHECKS (offline — build_messages structure)\n" + "-" * 50)

    # H1: empty history produces exactly 2 messages (system + user)
    msgs = build_messages("excel_numeric", "test context", "test question", history=None)
    ok = len(msgs) == 2 and msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"
    mark = "PASS" if ok else "FAIL"
    passed += ok; failed += not ok
    logger.info(f"  [{mark}] H1  No history → 2 messages (system + user): got {len(msgs)}")

    # H2: history with 2 turns produces 4 messages (system + 2 history + user)
    history = [
        {"role": "user",      "content": "מה היה הרייטינג של נינגה?"},
        {"role": "assistant", "content": "הרייטינג היה 15.3%."},
    ]
    msgs = build_messages("hybrid", "ctx", "ומה לגבי עונה 4?", history=history)
    ok = (
        len(msgs) == 4
        and msgs[0]["role"] == "system"
        and msgs[1]["role"] == "user"
        and msgs[2]["role"] == "assistant"
        and msgs[3]["role"] == "user"
    )
    mark = "PASS" if ok else "FAIL"
    passed += ok; failed += not ok
    logger.info(f"  [{mark}] H2  2-turn history → 4 messages: got {len(msgs)}")

    # H3: history content is preserved verbatim
    ok = (
        "נינגה" in msgs[1]["content"]
        and "15.3%" in msgs[2]["content"]
        and "עונה 4" in msgs[3]["content"]
    )
    mark = "PASS" if ok else "FAIL"
    passed += ok; failed += not ok
    logger.info(f"  [{mark}] H3  History content preserved in messages")

    # H4: current user message has the retrieval context block
    ok = "ctx" in msgs[3]["content"] and "עונה 4" in msgs[3]["content"]
    mark = "PASS" if ok else "FAIL"
    passed += ok; failed += not ok
    logger.info(f"  [{mark}] H4  Current user message includes context + question")

    # H5: QueryRequest model caps history at MAX_HISTORY_TURNS
    from app.models import QueryRequest, MAX_HISTORY_TURNS
    long_history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
    req = QueryRequest(question="test", history=long_history)
    ok = len(req.history) <= MAX_HISTORY_TURNS
    mark = "PASS" if ok else "FAIL"
    passed += ok; failed += not ok
    logger.info(f"  [{mark}] H5  History capped at {MAX_HISTORY_TURNS}: got {len(req.history)}")

    logger.info("")
    return passed, failed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    live = "--live" in sys.argv
    total_passed = total_failed = 0

    rp, rf = run_route_checks()
    total_passed += rp
    total_failed += rf

    hp, hf = run_history_checks()
    total_passed += hp
    total_failed += hf

    if live:
        lp, lf = run_live_checks()
        total_passed += lp
        total_failed += lf
    else:
        live_count = sum(1 for c in CASES if c.live)
        logger.info(
            f"Skipping live checks ({live_count} curated cases). "
            "Run with --live to include LLM responses.\n"
        )

    total = total_passed + total_failed
    logger.info("=" * 50)
    sys.stdout.write(f"RESULT: {total_passed}/{total} passed")
    if total_failed:
        logger.info(f"  ({total_failed} FAILED)")
    else:
        logger.info("  — all clear")

    sys.exit(0 if total_failed == 0 else 1)
