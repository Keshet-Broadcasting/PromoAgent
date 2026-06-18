"""
prompts.py

Prompt layer for the Promo department agent.

Responsibilities
----------------
1. Load the base system prompt from system_prompt.txt once at import time.
2. Provide route-specific addenda that sharpen task instructions for each
   query category without duplicating the base policy.
3. Expose build_messages() — the single public function that agent.py will call
   to assemble a ready-to-send messages list for the OpenAI SDK.

Usage (from agent.py)
---------------------
    from prompts import build_messages
    messages = build_messages(route, context_str, user_query)
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=messages,
        ...
    )
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base system prompt — loaded once from file
# ---------------------------------------------------------------------------

_PROMPT_FILE = Path(__file__).with_name("system_prompt.txt")

if not _PROMPT_FILE.exists():
    raise FileNotFoundError(
        f"system_prompt.txt not found at {_PROMPT_FILE}. "
        "It must exist alongside prompts.py."
    )

SYSTEM_PROMPT: str = _PROMPT_FILE.read_text(encoding="utf-8").strip()

# Strip non-printing control characters and Unicode bidi-override characters
# (\u202a–\u202e) from chat history before it is sent back to the model as
# prior conversation context. Bidi overrides can silently reverse rendered text
# and are sometimes used in prompt-injection payloads.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e]")
_MAX_HISTORY_CHARS = 600
_ALLOWED_HISTORY_ROLES = {"user", "assistant"}


# ---------------------------------------------------------------------------
# Route-specific addenda
# Each string adds focused task instructions on top of the base policy.
# Keep them short — the base policy already covers the broad rules.
# ---------------------------------------------------------------------------

_ROUTE_ADDENDUM: dict[str, str] = {

    "excel_numeric": """
## הוראות לשאלה כמותית (מקור: Excel)

ענה לפי הסדר הבא:
1. הצג תחילה את כל הערכים הרלוונטיים שנמצאו בנתונים (אחוזים, ציונים, תאריכים).
2. ציין במפורש את שם הקובץ ואת שם הגיליון/טאב כאשר הם זמינים בנתוני המקור.
3. ציין בפירוש שהנתונים נשלפו ישירות מהקובץ.
4. רק לאחר מכן הסק מסקנה — ורק אם היא נתמכת במלואה על ידי הנתונים.
5. אם שאלת השוואה ("הכי גבוה", "הכי נמוך", "בין עונות") — ודא שבדקת את כל הערכים הרלוונטיים לפני שנותן תשובה סופית.
6. אל תמציא מספרים. אם הנתון חסר — אמור זאת מפורשות.
""".strip(),

    "word_quote": """
## הוראות לשאלת ציטוט / אסטרטגיה / ניסוח (מקור: מסמכי Word)

**חובה**: עברו על **כל** קטעי הטקסט שנשלפו (כל [1], [2], [3]... עד הסוף) לפני שמנסחים תשובה.

1. אם השאלה כוללת מספר חלקים (לדוגמה: קמפיין השקה + קמפיין אמצע + קמפיין סיום), טפל בכל חלק בנפרד וחפש עדות לכל חלק בכל אחד מקטעי הטקסט.
2. אל תסתפק בקטע הטקסט הראשון שמוצא משהו רלוונטי — המשיכו לסרוק את כל הקטעים האחרים לפני מתן תשובה סופית.
3. אם המשתמש ביקש ציטוט — החזר את הציטוט המלא כפי שמופיע במקור, ללא שינוי בניסוח.
4. ציין את שם המסמך / שם הקובץ / כותרת הפרק ממנו נלקח הציטוט.
5. אם יש מספר ניסוחים רלוונטיים לאותו נושא — הצג את כולם.
6. אל תפרפרז ציטוט כאשר המשתמש ביקש את הטקסט המדויק.
7. הבחנה קריטית בין שלושה מצבים — אל תערבב ביניהם:
   - **נמצא עם תיאור**: המונח מופיע בקטע וגם יש לו תיאור/ניתוח ייעודי — ספק את התיאור.
   - **נמצא ללא תיאור**: המונח מוזכר בקטע (בכותרת, ברשימה, בהקשר) אך אין לו תיאור עצמאי — אמור "מוזכר בנתונים אך ללא תיאור ייעודי בקטעים שנשלפו" ואל תכתוב "לא נמצאו נתונים".
   - **לא נמצא כלל**: המונח אינו מופיע בשום מקום בנתונים שנשלפו — רק אז כתוב "לא נמצאו נתונים".
8. בשאלות רטרוספקטיבה על קמפיין יחיד ("למה קראנו לזה", "למה לא", "מה קרה לשם/מיתוג") — אל תפתח ברשימת מקורות.
   פתח ב-**מסקנה אסטרטגית** במשפט אחד, המשך ב-**קשת הקמפיין** לפי שלבים (השקה / אמצע / גמר או שינוי מיתוג), ורק אז שלב **ציטוטים** או מקורות תומכים inline.
   אם המקורות מצביעים על שינוי לאורך זמן, המסקנה חייבת לשקף את השינוי ולא רק את הרציונאל הראשוני.
9. בשאלות על תפקיד של אלמנט בקמפיין — הבחנה קריטית: עצם אזכור של X אינו מוכיח ש-X היה **עוגן מרכזי**.
   הפרד בין **קמפיין ההשקה / מיתוג ראשי** לבין שימוש שוטף, הוכחת רמה, דמות עוגן, או חיזוק נקודתי.
""".strip(),

    "hybrid": """
## הוראות לשאלה משולבת (מקורות: Excel + מסמכי Word)

בנה את התשובה במבנה הבא:
1. **נתוני Excel** — הצג תחילה את הערכים הכמותיים (רייטינג, נקודת פתיחה, כוונות צפייה וכו').
   ציין שם קובץ וגיליון כאשר זמינים.
2. **הקשר מהמסמכים** — לאחר מכן הוסף את האסטרטגיה, הציטוט, או הניסוח הרלוונטי ממסמכי ה-Word.
   ציין את שם המסמך.
3. **מסקנה** — סכם רק אם שני המקורות יחד תומכים בה.
4. אם אחד המקורות לא הניב תוצאות רלוונטיות — ציין זאת וענה על בסיס מה שנמצא.
5. בשאלות על תפקיד של אלמנט בקמפיין ("היו בפרומואים X", "מה היה התפקיד של X בקמפיין") — הבחנה קריטית:
   עצם זה ש-X הופיע בפרומואים או בשורות Excel אינו מוכיח שהוא היה **עוגן מרכזי** או מסר ההשקה.
   לפני מסקנה, הפרד בין **קמפיין ההשקה / מיתוג ראשי** לבין **שוטף / טונייטים / גמר / הוכחת רמה**.
   מותר לכתוב "X היה עוגן מרכזי", "עוגן מיתוגי" או "עוגן תוכני" רק אם מסמכי Word אומרים במפורש שזה היה בפרונט, המסר המרכזי, הרציונאל, או עוגן הקמפיין.
   לגבי מנות/אוכל: ברירת המחדל היא לנסח "היו מנות, אבל לא כעוגן המיתוג הראשי; הן שימשו כהוכחת רמה/חומר שוטף/טונייטים/גמר" אלא אם המקורות אומרים במפורש אחרת.
   אם Excel מראה ש-X הופיע אבל מסמכי Word מצביעים על רציונאל אחר — כתוב: "כן, X הופיע בפרומואים, אבל לא כעוגן המרכזי; הוא שימש כהוכחה/חומר שוטף/חיזוק בהמשך."
6. בשאלות אפקטיביות ("האם זה עבד", "הוכיח את עצמו") — פתח בפסק דין: **עבד / עבד חלקית / לא עבד**.
   לאחר מכן הפרד בין **סקרנות ראשונית** (פתיחה, חשיפה, באזז) לבין **עומק / שימור / תפקיד אסטרטגי לאורך הקמפיין**.
   אל תסיק "עבד" רק מנתון פתיחה טוב אם המסמכים מצביעים על מגבלה אסטרטגית.
""".strip(),

    "unknown": """
## הוראות לשאלה לא מוכרת

1. אל תנחש ואל תמציא תשובה.
2. אם ניתן לזהות בשאלה כוונה ברורה — ענה על בסיס המידע שנשלף.
3. אם השאלה עמומה מדי — בקש הבהרה: "האם אתה שואל על נתוני רייטינג, על ניסוח קמפיין, או על משהו אחר?"
4. אם נשלף מידע רלוונטי — השתמש בו ותאר ממה הוא נלקח.
5. אם לא נשלף מידע רלוונטי כלל — אמור: "לא נמצא מידע רלוונטי בנתונים הזמינים."
""".strip(),

}

# SharePoint-specific instruction appended to the route addendum whenever the
# context contains a SharePoint section.  Keeps the LLM grounded on those docs.
_SHAREPOINT_ADDENDUM = """

## שימוש במסמכי SharePoint (DocLib4)

הקטע "=== מסמכי SharePoint (DocLib4) ===" מכיל תוצאות ממאגר המסמכים של ספריית הפרומו ב-SharePoint.
השתמש בתוצאות אלה **רק כמקור משלים** — כאשר אין נתוני Excel או מסמכי Word זמינים.
ציין בתשובה שהמידע נלקח מ-SharePoint / DocLib4.
אל תמציא תוכן שאינו מופיע בקטעים שנשלפו.
""".strip()

_BROAD_RETRIEVAL_ADDENDUM = """

## שימוש בשליפה רחבה

כאשר מופיע בקונטקסט "כיסוי שליפה רחבה", התשובה חייבת:
1. לפתוח במסקנה או במספר המרכזי, ואז להציג את הטבלה/ההשוואה.
2. לציין אילו תוכניות/ז'אנרים כוסו וכמה שורות נכנסו לקונטקסט.
3. אם יש פחות כיסוי ממה שהמשתמש ביקש, לכתוב במפורש: "הממצא חלקי".
4. בשאלות השוואה/דפוסים, להציג לפחות 3 דוגמאות תומכות אם הן קיימות בקונטקסט.
5. לסיים בשורת מקור קצרה: "מקור: ..." עם קובץ/מסמך/סוג השליפה.
""".strip()


# ---------------------------------------------------------------------------
# Context block formatter
# ---------------------------------------------------------------------------

def _format_context(context: str) -> str:
    """Wrap retrieved context in a clearly labelled block for the prompt."""
    if not context or not context.strip():
        return "לא נמצאו תוצאות שליפה רלוונטיות."
    return f"## נתוני מקור שנשלפו\n\n{context.strip()}"


def _safe_history_turn(turn: object) -> dict[str, str] | None:
    """Return a bounded chat-history turn, or None when malformed."""
    if not isinstance(turn, dict):
        log.debug("Skipping non-dict history turn: %r", type(turn))
        return None
    role = turn.get("role")
    if not isinstance(role, str) or role not in _ALLOWED_HISTORY_ROLES:
        log.debug("Skipping history turn with invalid role: %r", role)
        return None
    content = turn.get("content")
    if not isinstance(content, str):
        log.debug("Skipping history turn with non-string content: %r", type(content))
        return None
    text = _CONTROL_CHARS_RE.sub(" ", content)
    if len(text) > _MAX_HISTORY_CHARS:
        text = text[:_MAX_HISTORY_CHARS] + "…"
    return {"role": role, "content": text}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_messages(
    route: str,
    context: str,
    user_query: str,
    history: list[dict] | None = None,
) -> list[dict]:
    """Build a messages list ready for the OpenAI chat completions API.

    Parameters
    ----------
    route       : one of "excel_numeric", "word_quote", "hybrid", "unknown"
    context     : pre-formatted retrieval results string (built by agent.py)
    user_query  : the original user question
    history     : previous conversation turns as [{"role": ..., "content": ...}]

    Returns
    -------
    [
        {"role": "system",    "content": <base_policy + route_addendum>},
        {"role": "user",      "content": <prior turn 1>},        # ← history
        {"role": "assistant", "content": <prior turn 2>},        # ← history
        ...
        {"role": "user",      "content": <context_block + user_query>},
    ]
    """
    addendum = _ROUTE_ADDENDUM.get(route, _ROUTE_ADDENDUM["unknown"])
    # If the context contains a SharePoint section, append the SharePoint instruction
    if "=== מסמכי SharePoint" in context:
        addendum = f"{addendum}\n\n{_SHAREPOINT_ADDENDUM}"
    if "כיסוי שליפה רחבה" in context:
        addendum = f"{addendum}\n\n{_BROAD_RETRIEVAL_ADDENDUM}"
    system_content = f"{SYSTEM_PROMPT}\n\n{addendum}"

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]

    for turn in (history or []):
        safe_turn = _safe_history_turn(turn)
        if safe_turn:
            messages.append(safe_turn)

    user_content = f"{_format_context(context)}\n\n## שאלת המשתמש\n\n{user_query}"
    messages.append({"role": "user", "content": user_content})

    return messages
