"""
formatters.py

Context formatters and Azure content-filter sanitizer for the Promo agent.

Responsibilities
----------------
- _sanitize_for_content_filter : neutralise violence phrases that trigger Azure
  OpenAI content filter (violence: medium) in drama/thriller promo texts.
- _fmt_excel / _fmt_word / _fmt_sharepoint : convert raw Azure Search result
  dicts into structured Markdown strings consumed by the prompt layer.
- _chunk_pos : helper that extracts the sequential position from a chunk_id.

All functions are pure (no I/O, no Azure calls) and can be unit-tested cheaply.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Azure OpenAI content-filter sanitizer
# ---------------------------------------------------------------------------
# The Azure content filter (violence: medium) blocks prompts that contain
# explicit violence phrases common in drama/thriller promo texts (e.g. הראש).
# Each tuple is (compiled_pattern, neutral_replacement).
# Replacements preserve meaning so the LLM can still answer correctly,
# but use brackets so it's clear they are sanitised — not original wording.
# ---------------------------------------------------------------------------

_CF_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"אקדח\s+לראש"),        "[נשק מכוון]"),
    (re.compile(r"אקדח"),               "[נשק]"),
    # Bare "ירי" is word-bounded to avoid corrupting benign words that contain
    # the same letters (e.g. "איריס", "מכירים").
    (re.compile(r"ירייה|יריות|(?<![א-ת])ירי(?![א-ת])"), "[תקיפה]"),
    (re.compile(r"יורה"),               "[תוקף]"),
    (re.compile(r"נורה(?=[\s,.\-\u05d0-\u05ea])"), "[נפגע]"),
    (re.compile(r"נורים|נורות"),        "[נפגעים]"),
    (re.compile(r"נהרג(?:ו|ת|ים|ות)?"), "[נחסל]"),
    (re.compile(r"הורג(?:ת|ים|ות)?"),   "[מחסל]"),
    (re.compile(r"להרוג"),              "[לחסל]"),
    (re.compile(r"הרוג(?:ים|ות)?"),     "[נחסל]"),
    (re.compile(r"נדקר"),               "[נתקף]"),
    (re.compile(r"דוקר"),               "[תוקף בנשק]"),
    (re.compile(r"גופ[הות]"),           "[קורבן]"),
]


def _sanitize_for_content_filter(text: str) -> str:
    """Replace phrases that trigger Azure OpenAI violence content filter.

    Applied to promo_text and Word/SharePoint chunks before prompt assembly.
    Prevents Error 400 on queries about shows with violent promo content
    (e.g. הראש) while preserving enough meaning for the LLM to answer.
    """
    for pattern, replacement in _CF_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Context formatters
# ---------------------------------------------------------------------------

def _chunk_pos(chunk_id: str) -> str:
    """Extract the sequential position from a chunk_id like '…_chunk_0_111'."""
    if "_chunk_" in chunk_id:
        return chunk_id.split("_chunk_", 1)[1]
    return chunk_id


def _fmt_excel(docs: list[dict]) -> str:
    if not docs:
        return "לא נמצאו תוצאות רלוונטיות ב-Excel."

    header    = "| # | תוכנית | עונה | פרק | תאריך | נקודת פתיחה (%) | רייטינג ממוצע (%) | מקור |"
    separator = "|---|---|---|---|---|---|---|---|"
    rows: list[str] = []
    promo_texts: list[str] = []

    for i, d in enumerate(docs, 1):
        show    = d.get("show_name") or "—"
        season  = d.get("season") or "—"
        episode = d.get("episode_number") or "—"
        date    = d.get("date") or "—"
        opening = f"{d['opening_point']}" if d.get("opening_point") else "—"
        rating  = f"{d['rating']}" if d.get("rating") else "—"
        source  = d.get("tab_name") or d.get("source_file") or "—"
        rows.append(
            f"| {i} | {show} | {season} | {episode} | {date} | {opening} | {rating} | {source} |"
        )

        text = _sanitize_for_content_filter((d.get("promo_text") or "").strip()[:500])
        if text:
            promo_texts.append(f"**[{i}]** {text}")

    table = "\n".join([header, separator] + rows)
    if promo_texts:
        table += "\n\n### טקסטי פרומו\n\n" + "\n\n".join(promo_texts)
    return table


def _fmt_word(docs: list[dict]) -> str:
    if not docs:
        return "לא נמצאו תוצאות רלוונטיות במסמכי Word."
    lines: list[str] = []
    for i, d in enumerate(docs, 1):
        source    = d.get("title") or ""
        header    = d.get("header") or ""
        caption   = _sanitize_for_content_filter((d.get("caption") or "").strip())
        chunk     = _sanitize_for_content_filter((d.get("chunk") or "").strip()[:900])
        score     = d.get("score") or 0
        chunk_id  = d.get("chunk_id") or ""
        show_name = d.get("show_name") or ""
        season    = d.get("season") or ""
        qtype     = d.get("question_type") or ""
        pos       = _chunk_pos(chunk_id) if chunk_id else "—"

        meta = f"[{i}] [מקור: {source}] | קטע מס': {pos}"
        if header:
            meta += f" | פרק: {header}"
        if show_name:
            meta += f" | תוכנית: {show_name}"
        if season:
            meta += f" | עונה: {season}"
        if qtype:
            meta += f" | סוג שאלה: {qtype}"
        meta += f" | רלוונטיות: {score:.2f}"

        parts = [meta]
        if caption:
            parts.append(f"ציטוט מודגש (Azure): {caption}")
        parts.append(f"תוכן מלא: {chunk}")
        lines.append("\n".join(parts))
    return "\n\n---\n\n".join(lines)


def _fmt_sharepoint(docs: list[dict]) -> str:
    if not docs:
        return "לא נמצאו תוצאות ב-SharePoint."
    lines: list[str] = []
    for i, d in enumerate(docs, 1):
        title = d.get("title") or "(ללא שם)"
        url   = d.get("url") or ""
        text  = _sanitize_for_content_filter((d.get("text") or "").strip()[:600])
        meta  = f"[{i}] {title}"
        if url:
            meta += f"  |  {url}"
        parts = [meta]
        if text:
            parts.append(text)
        lines.append("\n".join(parts))
    return "\n\n---\n\n".join(lines)
