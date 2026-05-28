"""
Domain catalog for PromoAgent.

This module is the single source of truth for show names, aliases, and broad
genre groupings used by retrieval planning. Keep the names aligned with the
exact `show_name` values stored in the Azure Search indexes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ShowRecord:
    official: str
    genre: str
    aliases: tuple[str, ...] = ()
    indexed: bool = True


SHOWS: tuple[ShowRecord, ...] = (
    # Drama / scripted
    ShowRecord("אהבה גדולה מהחיים", "drama"),
    ShowRecord("אור ראשון", "drama"),
    ShowRecord("אף אחד לא עוזב את פאלו אלטו", "drama", aliases=("פאלו אלטו",)),
    ShowRecord("ביום שהאדמה רעדה", "drama"),
    ShowRecord("בקרוב אצלי", "drama"),
    ShowRecord("גוף שלישי", "drama"),
    ShowRecord("הבוגדים", "drama"),
    ShowRecord("החיים הם תקופה קשה", "drama", aliases=("חנוך דאום",)),
    ShowRecord("היורשת", "drama"),
    ShowRecord("הנחלה", "drama"),
    ShowRecord("הראש", "drama"),
    ShowRecord("השוטרים", "drama"),
    ShowRecord("חולי אהבה", "drama"),
    ShowRecord("להיות איתה", "drama"),
    ShowRecord("צומת מילר", "drama"),
    ShowRecord("כפולים", "drama"),
    ShowRecord("רצח בים המלח", "drama"),

    # Reality / competition
    ShowRecord("חתונה ממבט ראשון", "reality", aliases=("חתונמי",)),
    ShowRecord("חתונה ממבט שני", "reality", aliases=("חתונמי 2",)),
    ShowRecord("המירוץ למיליון", "reality", aliases=("המירוץ למליון", "מירוץ")),
    ShowRecord("רוקדים עם כוכבים", "reality", aliases=("רוקדים",)),
    ShowRecord("הזמר במסכה", "reality", aliases=("זמר",)),
    ShowRecord("נינג'ה ישראל", "reality", aliases=("נינג'ה", "נינג׳ה")),
    ShowRecord("הכוכב הבא לאירוויזיון", "reality"),
    ShowRecord("הכוכב הבא", "reality", aliases=("כוכב",)),
    ShowRecord("מאסטר שף", "reality"),
    ShowRecord("המטבח המנצח", "reality"),
    ShowRecord("המטבח המנצח VIP - עונות 2 ו-3", "reality"),
    ShowRecord("הקינוח המושלם", "reality"),
    ShowRecord("הכרישים", "reality"),
    ShowRecord("יצאת צדיק", "reality"),
    ShowRecord("ישמח חתני", "reality"),
    ShowRecord("מבחן ההורים הגדול", "reality"),
    ShowRecord("אהבה גדולה מהחיים", "reality"),
    ShowRecord("בייבי בום", "reality"),

    # Entertainment / factual / comedy
    ShowRecord("ארץ נהדרת", "entertainment", aliases=("ארץ",)),
    ShowRecord("זה לא אולפן שישי", "entertainment"),
    ShowRecord("בית הספר למוזיקה", "entertainment"),
    ShowRecord("מה באמת קרה שם ארז טל", "entertainment", aliases=("מה באמת קרה שם",)),
    ShowRecord("מה שבע", "entertainment"),
    ShowRecord("נוטוק", "entertainment", aliases=("נו טוק", "No Talk")),
    ShowRecord("שיטת אשכנזי", "entertainment"),
    ShowRecord("סברי מרנן", "entertainment"),
    ShowRecord("מועדון לילה", "entertainment"),
    ShowRecord("כוכבים בריבוע", "entertainment"),
    ShowRecord("צא מזה", "entertainment"),
    ShowRecord("המתמחים", "factual"),
)


GENRE_LABELS: dict[str, str] = {
    "drama": "דרמות",
    "reality": "ריאליטי",
    "entertainment": "בידור",
    "factual": "דוקו/פאקטואליה",
}


GENRE_PATTERNS: dict[str, tuple[str, ...]] = {
    "drama": ("דרמה", "דרמות", "סדרה", "סדרות"),
    "reality": ("ריאליטי", "תוכניות ריאליטי", "תכנית ריאליטי"),
    "entertainment": ("בידור", "תוכניות בידור", "תכנית בידור"),
    "factual": ("דוקו", "פאקטואליה", "תיעודי"),
}

# Content-type adjective phrases that use "דרמה" to describe content or emotion
# (NOT a genre label). These must be stripped BEFORE genre detection to avoid
# false-positives on queries like "טונייט שמציג דרמה אישית" routing to drama genre.
_DRAMA_CONTENT_TYPE_RE = re.compile(
    r"דרמה\s+(?:אישית|רגשית|פנימית|זוגית|משפחתית|אנושית|של\b)"
)


_OFFICIAL_BY_NAME = {show.official: show for show in SHOWS}

# כוכב + season number: seasons ≥10 use "הכוכב הבא לאירוויזיון"; seasons <10 use "הכוכב הבא"
# Handles: "כוכב עונה 11", "כוכב בעונה 11", "כוכב 11"
_KOCHAV_SEASON_RE = re.compile(r"\bכוכב\s+(?:ב?עונה\s+)?(\d+)\b")


def _expand_kochav_season(m: re.Match) -> str:
    season = int(m.group(1))
    show = "הכוכב הבא לאירוויזיון" if season >= 10 else "הכוכב הבא"
    return f"{show} עונה {m.group(1)}"


def official_show_names(indexed_only: bool = True) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for show in SHOWS:
        if indexed_only and not show.indexed:
            continue
        if show.official not in seen:
            seen.add(show.official)
            names.append(show.official)
    return names


def aliases() -> list[tuple[str, str]]:
    """Return alias -> official mappings, longest aliases first."""
    pairs: list[tuple[str, str]] = []
    for show in SHOWS:
        for alias in show.aliases:
            pairs.append((alias, show.official))
    return sorted(pairs, key=lambda item: len(item[0]), reverse=True)


def expand_aliases(query: str) -> str:
    expanded = query
    # Context-aware כוכב: "כוכב עונה N" → correct show name based on season number
    expanded = _KOCHAV_SEASON_RE.sub(_expand_kochav_season, expanded)
    for alias, official in aliases():
        # Skip if the official name is already in the query — avoids doubling
        # like "נינג'ה ישראל" → "נינג'ה ישראל ישראל" when the alias "נינג'ה"
        # matches as a substring of an already-official mention.
        if official in expanded:
            continue
        expanded = re.sub(re.escape(alias), official, expanded)
    return expanded


def extract_show_names(query: str) -> list[str]:
    """Return all official show names present in the query, longest first."""
    expanded = expand_aliases(query)
    matches: list[str] = []
    for name in sorted(official_show_names(), key=len, reverse=True):
        if name in expanded and name not in matches:
            matches.append(name)
    return matches


def genres_for_query(query: str) -> list[str]:
    # Strip content-type drama phrases (e.g. "דרמה אישית") before checking genre
    # patterns — they describe content/emotion, not the drama show genre.
    clean = _DRAMA_CONTENT_TYPE_RE.sub("", query)
    matches: list[str] = []
    for genre, patterns in GENRE_PATTERNS.items():
        if any(pattern in clean for pattern in patterns):
            matches.append(genre)
    return matches


def shows_for_genres(genres: list[str]) -> list[str]:
    wanted = set(genres)
    names: list[str] = []
    for show in SHOWS:
        if show.genre in wanted and show.indexed and show.official not in names:
            names.append(show.official)
    return names


def genre_label(genre: str) -> str:
    return GENRE_LABELS.get(genre, genre)
