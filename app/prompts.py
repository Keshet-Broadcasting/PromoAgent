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

from pathlib import Path

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


# ---------------------------------------------------------------------------
# Context block formatter
# ---------------------------------------------------------------------------

def _format_context(context: str) -> str:
    """Wrap retrieved context in a clearly labelled block for the prompt."""
    if not context or not context.strip():
        return "לא נמצאו תוצאות שליפה רלוונטיות."
    return f"## נתוני מקור שנשלפו\n\n{context.strip()}"


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
    system_content = f"{SYSTEM_PROMPT}\n\n{addendum}"

    messages: list[dict] = [{"role": "system", "content": system_content}]

    _MAX_HISTORY_CHARS = 600
    for turn in (history or []):
        content = turn["content"]
        if len(content) > _MAX_HISTORY_CHARS:
            content = content[:_MAX_HISTORY_CHARS] + "…"
        messages.append({"role": turn["role"], "content": content})

    user_content = f"{_format_context(context)}\n\n## שאלת המשתמש\n\n{user_query}"
    messages.append({"role": "user", "content": user_content})

    return messages
