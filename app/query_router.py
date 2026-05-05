"""
query_router.py

Rule-based query router for the Promo department agent.

Classifies Hebrew queries into one of:
    - excel_numeric   → tv-promos index (ratings, rankings, comparisons)
    - word_quote      → word-docs index (quotes, strategies, slogans)
    - hybrid          → both indexes
    - unknown         → no clear signal

Usage (CLI):
    python query_router.py "מה היה רייטינג ההשקה של נוטוק"
    python query_router.py                                   # runs built-in examples
"""

from __future__ import annotations

import re
import sys
import logging
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

EXCEL_NUMERIC_PATTERNS: list[re.Pattern] = [
    re.compile(p)
    for p in [
        r"רייטינג",
        r"ריטינג",
        r"\brating\b",
        r"נקודת פתיחה",
        r"נקודות פתיחה",
        r"נקודות הפתיחה",
        r"נקודת הפתיחה",
        r"ממוצע",
        r"אחוז",
        r"%",
        r"\bshare\b",
        r"נתח צפי",
        r"הכי גבוה",
        r"הכי נמוך",
        r"הכי הרבה",
        r"הכי טוב",
        r"השיק.? הכי",
        r"\bטופ\b",
        r"\btop\b",
        r"סדר לי",
        r"סדר.? את",
        r"\bדרג\b",
        r"השווה",
        r"השוואה",
        r"ביחס ל",
        r"לעומת",
        r"כמה צפו",
        r"כמה השלימו",
        r"ביצועים",
    ]
]

# "כוונות צפייה" (viewing intentions) data lives in Word docs (research),
# not in Excel promo tracking — force hybrid when these appear.
HYBRID_FORCE_PATTERNS: list[re.Pattern] = [
    re.compile(p)
    for p in [
        r"כוונות צפי",
        r"כוונות הצפי",
        r"מחקר כוונות",
        r"בדיקת פרומו",
        r"בדיקת שטח",
    ]
]

WORD_QUOTE_PATTERNS: list[re.Pattern] = [
    re.compile(p)
    for p in [
        r"צטט",
        r"ציטוט",
        r"במדויק",
        r"במדוייק",
        r"אסטרטגי",
        r"סלוג[נן]",       # סלוגן (final nun) / סלוגנים (regular nun)
        r"עשה ואל תעשה",
        r"חוקים של",
        r"כללים של",
        r"מסמך",
        r"תובנות",
        r"המלצ",
        r"ניסוח",
        r"נוסח",
        r"טקסט",
        r"מסרים",
        r"\bמסר\b",
        r"אימאג'",
    ]
]

# Analysis / explanation keywords — trigger hybrid when combined with
# either numeric or quote signals.
ANALYSIS_PATTERNS: list[re.Pattern] = [
    re.compile(p)
    for p in [
        r"תנתח",
        r"\bנתח\b",
        r"ולמה",
        r"מה אפשר ללמוד",
    ]
]

ROUTE_EXCEL = "excel_numeric"
ROUTE_WORD = "word_quote"
ROUTE_HYBRID = "hybrid"
ROUTE_UNKNOWN = "unknown"


@dataclass
class RouteResult:
    route: str
    numeric_hits: list[str]
    quote_hits: list[str]
    analysis_hits: list[str]

    @property
    def summary(self) -> str:
        parts = [self.route]
        if self.numeric_hits:
            parts.append(f"numeric={self.numeric_hits}")
        if self.quote_hits:
            parts.append(f"quote={self.quote_hits}")
        if self.analysis_hits:
            parts.append(f"analysis={self.analysis_hits}")
        return "  |  ".join(parts)


def classify(query: str) -> RouteResult:
    """Classify a Hebrew query into a routing category."""
    q = query.strip()

    numeric_hits = [p.pattern for p in EXCEL_NUMERIC_PATTERNS if p.search(q)]
    quote_hits = [p.pattern for p in WORD_QUOTE_PATTERNS if p.search(q)]
    analysis_hits = [p.pattern for p in ANALYSIS_PATTERNS if p.search(q)]
    hybrid_force = any(p.search(q) for p in HYBRID_FORCE_PATTERNS)

    has_numeric = bool(numeric_hits)
    has_quote = bool(quote_hits)
    has_analysis = bool(analysis_hits)

    if hybrid_force:
        route = ROUTE_HYBRID
    elif has_numeric and has_quote:
        route = ROUTE_HYBRID
    elif (has_numeric or has_quote) and has_analysis:
        route = ROUTE_HYBRID
    elif has_numeric:
        route = ROUTE_EXCEL
    elif has_quote:
        route = ROUTE_WORD
    else:
        route = ROUTE_UNKNOWN

    return RouteResult(
        route=route,
        numeric_hits=numeric_hits,
        quote_hits=quote_hits,
        analysis_hits=analysis_hits,
    )


# ---------------------------------------------------------------------------
# Built-in examples for quick validation
# ---------------------------------------------------------------------------

EXAMPLES: list[tuple[str, str]] = [
    ("צטט במדוייק את האסטרטגיות מכירה של כל הדרמות בשנה האחרונה", ROUTE_WORD),
    ("מה היה ריטינג ההשקה של נוטוק", ROUTE_EXCEL),
    ("מה היו כוונות הצפיה לפני השקת הדרמה אור ראשון", ROUTE_HYBRID),
    ("מה היו הסלוגנים של קמפיין ההשקה של נינג'ה ישראל", ROUTE_WORD),
    ("איזו עונה השיקה הכי גבוה? סדר לי את הריטינג של ההשקות", ROUTE_EXCEL),
    ("צטט ספציפית ממסמך תובנות ריאליטי את התובנות המרכזיות", ROUTE_WORD),
    ("איזה טונייטים הביאו את המספרים הכי גבוהים לנקודת הפתיחה ולמה", ROUTE_HYBRID),
    ("מהם החוקים של עשה ואל תעשה בטונייטים של חתונה ממבט ראשון", ROUTE_WORD),
    ("תנתח לי איך כוונות הצפיה נכונות ביחס לנקודת הפתיחה בפועל", ROUTE_HYBRID),
    ("תנתח את קמפיין השמר וצטט תובנות משם", ROUTE_HYBRID),
]


def run_examples() -> None:
    """Run built-in examples and print pass/fail for each."""
    passed = 0
    for query, expected in EXAMPLES:
        result = classify(query)
        ok = result.route == expected
        passed += ok
        mark = "PASS" if ok else "FAIL"
        logger.info(f"  [{mark}]  {result.route:<14}  (expect {expected:<14})  {query[:60]}")
        if not ok:
            logger.info(f"         hits: {result.summary}")
    logger.info(f"\n  {passed}/{len(EXAMPLES)} passed")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) > 1:
        q = sys.argv[1]
        r = classify(q)
        logger.info(f"Query:  {q}")
        logger.info(f"Route:  {r.route}")
        logger.info(f"Detail: {r.summary}")
    else:
        logger.info("Query Router — built-in examples\n")
        run_examples()
