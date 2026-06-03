"""
preprocess_word_docs.py

Downloads every .docx blob from "promo-docs-poc", extracts semantic chunks, and
saves a JSON file per document to the "promo-docs-json" container.

Two extraction paths are used depending on file size:
  <= 4 MB  →  Azure AI Document Intelligence (prebuilt-layout)
             Paragraphs are chunked on role="sectionHeading"/"title".
             Tables are interleaved in reading order via span offsets.
   > 4 MB  →  python-docx fallback
             Paragraphs are chunked on Word heading styles (Heading 1-9, Title).
             Tables are iterated in document-body order.

Output JSON format (one array per source document):
    [
      {
        "chunk_id":    "<12-char doc hash>_chunk_<n>",
        "header":      "<heading text, or empty string>",
        "chunk":       "<full section text>",
        "title":       "<source blob filename>",
        "source_file": "<full blob HTTPS URL>",
        "parent_id":   "<32-char SHA-256 of title>"
      },
      ...
    ]

Required .env variables:
    AZURE_STORAGE_CONNECTION_STRING
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
    AZURE_DOCUMENT_INTELLIGENCE_KEY

Usage:
    python preprocess_word_docs.py
    python preprocess_word_docs.py --overwrite
"""

import argparse
import base64
import hashlib
import io
import json
import logging
import os
import re
import sys
from pathlib import Path

# Make app/ importable so we can pull the show catalog as the single source of
# truth for show_name extraction. Without this, running the script directly
# (python scripts/preprocess_word_docs.py) fails to find app.domain_catalog.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import xml.etree.ElementTree as ET            # stdlib XML parser for .docx fallback
import zipfile                                 # stdlib ZIP reader for .docx files
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient, ContainerClient
from dotenv import load_dotenv

from app.domain_catalog import SHOWS as _CATALOG_SHOWS

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_DI_ENDPOINT = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
AZURE_DI_KEY = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")

SOURCE_CONTAINER = "promo-docs-poc"
DEST_CONTAINER = "promo-docs-json"
MODEL_ID = "prebuilt-layout"

# Files larger than this are processed with the python-docx fallback instead of
# sending bytes inline to Document Intelligence (4 MB service limit).
DI_SIZE_LIMIT_BYTES = 4 * 1024 * 1024

# Target size for semantic chunks. If a section is larger than this, it will
# be hard-split at paragraph boundaries.
CHUNK_MAX_CHARS = 3000

# Document Intelligence paragraph roles
HEADING_ROLES = {"sectionHeading", "title"}
SKIP_ROLES    = {"pageHeader", "pageFooter", "pageNumber", "footnote"}

# Word style IDs that represent headings (locale-independent English IDs).
# "HeadingBold" is a synthetic ID returned by _xml_para_style_id() for paragraphs
# that use bold formatting instead of a formal heading style (common in Hebrew docs).
HEADING_STYLE_IDS = {f"Heading{i}" for i in range(1, 10)} | {"Title", "HeadingBold"}

# Word Open XML namespaces used in document.xml
_W  = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_wn = lambda tag: f"{{{_W}}}{tag}"   # shorthand: _wn('p') → '{...}p'

# ---------------------------------------------------------------------------
# Semantic chunking constants (GPT-template documents only)
# ---------------------------------------------------------------------------

# How many chars of the document to scan when probing for the GPT template
GPT_TEMPLATE_PROBE_CHARS = 5000
# Max/min char limits for semantic chunks (~800 / ~3 short Hebrew sentences)
SEMANTIC_CHUNK_MAX_CHARS = 3200
SEMANTIC_CHUNK_MIN_CHARS = 150

# Paragraphs that open a new show/season block (ריאליטי and דרמות docs)
_PRIMARY_TEXT_SIGNALS = (
    "המסמכים הבאים יעסקו בתוכנית",
    "המסמכים הבאים יעסקו בסדרה",
)

# Bold+underline paragraph anchors that open a Q&A section (all 3 docs)
_SECONDARY_ANCHORS = (
    "מה האסטרטגיה",
    "מה הסלוגן",
    "מה השיקול שעמד מאחורי",
    "התלבטויות מיוחדות",
    "האימאג'",
    "חידושים והמצאות",
    "תוצאות המחקר",
    "מה חשבנו על הרייטינג",
    "תובנות מהקמפיין",
    "נקודות של עשה ואל תעשה",
    "מעקב פרומו",
    "התייחסות לפרקי",
    "בדיקת כוונות",
    "תכנית מדיה",
)

# Sections whose table content must NOT be split across sub-chunks
_ATOMIC_SECTION_KEYS = ("תכנית מדיה", "מעקב פרומו")

_DATE_LINE_RE  = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b")
_SEASON_RE     = re.compile(r"עונה\s+(\d+)")
# Catalog-based show_name lookup. Built once at module load from the domain
# catalog (app.domain_catalog.SHOWS). Each entry is (search_term, official_name)
# where search_term may be an alias. Longest-first so greedy substring matching
# prefers the most specific show (e.g. "הכוכב הבא לאירוויזיון" over "הכוכב הבא",
# and "חתונה ממבט ראשון" over "חתונמי").
def _build_catalog_lookup() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for show in _CATALOG_SHOWS:
        for term in (show.official,) + tuple(show.aliases):
            if term and term not in seen:
                seen.add(term)
                pairs.append((term, show.official))
    return sorted(pairs, key=lambda x: len(x[0]), reverse=True)


_CATALOG_LOOKUP: list[tuple[str, str]] = _build_catalog_lookup()


def _extract_show_from_text(text: str) -> str:
    """Return the longest catalog show (or alias) found in text; otherwise "".

    This is the generic replacement for the regex-based show_name extraction
    that previously misfired and captured doc_type words ('השקה', 'גמר', ...)
    on ~60% of chunks. The catalog is the single source of truth -- any value
    returned is guaranteed to be a real official show_name. If extraction
    cannot find a known show, returns "" (chunk left untagged) rather than
    guessing.
    """
    if not text:
        return ""
    for term, official in _CATALOG_LOOKUP:
        if term in text:
            return official
    return ""

_DOCTYPE_KEYS  = {"השקה": "השקה", "גמר": "גמר", "מחקר": "מחקר", "אסטרטגיה": "אסטרטגיה"}
_QTYPE_MAP     = {
    "מה האסטרטגיה":              "אסטרטגיה",
    "מה הסלוגן":                 "סלוגן",
    "מה השיקול":                  "שיקול",
    "התלבטויות":                  "התלבטויות",
    "האימאג'":                    "אימאג",
    "חידושים":                    "חידושים",
    "תוצאות המחקר":               "מחקר",
    "מה חשבנו על הרייטינג":      "רייטינג",
    "תובנות מהקמפיין":            "תובנות",
    "נקודות של עשה":              "עשה_ואל_תעשה",
    "מעקב פרומו":                 "מעקב",
    "התייחסות לפרקי":             "פרקים",
    "בדיקת כוונות":               "כוונות",
    "תכנית מדיה":                 "תכנית_מדיה",
}


# ---------------------------------------------------------------------------
# Shared ID helpers
# ---------------------------------------------------------------------------


def _doc_hash(title: str) -> str:
    """32-char hex hash of the document title — used as parent_id."""
    return hashlib.sha256(title.encode("utf-8")).hexdigest()[:32]


def _chunk_id(doc_hash: str, n: int) -> str:
    """URL-safe chunk key: first 12 chars of parent hash + chunk index."""
    return f"{doc_hash[:12]}_chunk_{n}"


def _make_chunk(doc_hash: str, n: int, header: str, lines: list[str],
                title: str, source_url: str) -> dict | None:
    """Build a chunk dict from accumulated lines; returns None if text is empty."""
    text = "\n".join(lines).strip()
    if not text:
        return None
    return {
        "chunk_id":    _chunk_id(doc_hash, n),
        "header":      header,
        "chunk":       text,
        "title":       title,
        "source_file": source_url,
        "parent_id":   doc_hash,
    }


# ---------------------------------------------------------------------------
# Path A — Document Intelligence (files <= 4 MB)
# ---------------------------------------------------------------------------


def _di_format_table(table) -> list[str]:
    """Render a DI DocumentTable as 'cell1 | cell2 | ...' row strings."""
    rows: dict[int, dict[int, str]] = {}
    for cell in table.cells:
        rows.setdefault(cell.row_index, {})[cell.column_index] = (cell.content or "").strip()
    lines: list[str] = []
    for row_idx in sorted(rows):
        row = rows[row_idx]
        line = " | ".join(row[c] for c in sorted(row))
        if line.strip():
            lines.append(line)
    return lines


def _di_build_event_stream(result: AnalyzeResult) -> list[tuple]:
    """
    Return a reading-order list of events from a DI AnalyzeResult.

    Events:
        ("heading", text)     — sectionHeading / title paragraph
        ("text",    text)     — body paragraph
        ("table",   [lines])  — formatted table rows

    Paragraphs whose span falls inside a table's span are suppressed so that
    table cell text is not duplicated.
    """
    table_map: list[tuple[int, int, object]] = []
    for tbl in result.tables or []:
        if tbl.spans:
            start = tbl.spans[0].offset
            table_map.append((start, start + tbl.spans[0].length, tbl))
    table_map.sort(key=lambda x: x[0])

    paragraphs = sorted(
        (p for p in (result.paragraphs or []) if p.spans),
        key=lambda p: p.spans[0].offset,
    )

    events: list[tuple] = []
    emitted: set[int] = set()

    for para in paragraphs:
        offset = para.spans[0].offset
        role   = getattr(para, "role", None)

        if role in SKIP_ROLES:
            continue

        in_table = False
        for ti, (t_start, t_end, tbl) in enumerate(table_map):
            if t_start <= offset < t_end:
                in_table = True
                if ti not in emitted:
                    events.append(("table", _di_format_table(tbl)))
                    emitted.add(ti)
                break

        if in_table:
            continue

        text = (para.content or "").strip()
        if not text:
            continue

        if role in HEADING_ROLES:
            events.append(("heading", text))
        else:
            events.append(("text", text))

    # Tables that had no overlapping paragraphs (edge case)
    for ti, (_, _, tbl) in enumerate(table_map):
        if ti not in emitted:
            events.append(("table", _di_format_table(tbl)))

    return events


def extract_chunks_di(result: AnalyzeResult, title: str, source_url: str) -> list[dict]:
    """Convert a DI AnalyzeResult into semantic chunks.

    If the document matches the GPT question template, the semantic chunking
    path is used (split_semantic).  Otherwise falls back to the existing
    heading-based fixed-size chunking.
    """
    doc_hash = _doc_hash(title)
    events   = _di_build_event_stream(result)

    # Probe for GPT template using joined non-table text
    probe_text = " ".join(
        payload[0] for kind, *payload in events
        if kind in ("heading", "text")
    )
    if detect_gpt_template(probe_text):
        logger.info("    GPT template detected — using semantic chunking.")
        return split_semantic(_to_para_stream_di(events), title, source_url)

    # --- Legacy fixed-size chunking (unchanged) ---
    chunks: list[dict] = []
    current_header = ""
    current_lines:  list[str] = []

    def _flush() -> None:
        chunk = _make_chunk(doc_hash, len(chunks), current_header, current_lines,
                            title, source_url)
        if chunk:
            chunks.append(chunk)

    for kind, *payload in events:
        if kind == "heading":
            _flush()
            current_header = payload[0]
            current_lines  = []
        elif kind == "text":
            current_lines.append(payload[0])
        elif kind == "table":
            current_lines.extend(payload[0])

    _flush()
    return _split_large_chunks(chunks)


# ---------------------------------------------------------------------------
# Path B — stdlib fallback (files > 4 MB, no third-party deps)
# ---------------------------------------------------------------------------


def _xml_cell_text(tc_elem: ET.Element) -> str:
    """Concatenate all w:t text nodes inside a table-cell element."""
    return "".join(
        (node.text or "") for node in tc_elem.iter(_wn("t"))
    ).strip()


def _xml_format_table(tbl_elem: ET.Element) -> list[str]:
    """
    Render a w:tbl element as 'cell1 | cell2 | ...' row strings.
    Only direct w:tr children are processed (avoids descending into nested tables).
    Duplicate rows from merged cells are deduplicated.
    """
    lines: list[str] = []
    seen_rows: set[tuple] = set()

    for tr in tbl_elem:
        if tr.tag != _wn("tr"):
            continue
        cells = tuple(
            _xml_cell_text(tc)
            for tc in tr
            if tc.tag == _wn("tc")
        )
        if cells in seen_rows:
            continue
        seen_rows.add(cells)
        line = " | ".join(c for c in cells if c)
        if line.strip():
            lines.append(line)

    return lines


def _xml_para_style_id(p_elem: ET.Element) -> str:
    """
    Extract the w:styleId from a paragraph's w:pPr/w:pStyle element, or ''.
    Also returns a synthetic 'HeadingN' if w:outlineLvl is set (locale-independent),
    or if the paragraph is entirely/mostly bold.
    """
    pPr = p_elem.find(_wn("pPr"))
    p_text = "".join((node.text or "") for node in p_elem.iter(_wn("t"))).strip()
    
    if pPr is None:
        return ""

    # Check w:pStyle first (works for English-named styles)
    pStyle = pPr.find(_wn("pStyle"))
    if pStyle is not None:
        sid = pStyle.get(_wn("val"), "")
        if sid in HEADING_STYLE_IDS:
            return sid
            
    # Fallback 1: w:outlineLvl present → it's a heading regardless of style name
    outlineLvl = pPr.find(_wn("outlineLvl"))
    if outlineLvl is not None:
        lvl_str = outlineLvl.get(_wn("val"), "")
        try:
            lvl = int(lvl_str)
            if 0 <= lvl <= 8:          # outline levels 0-8 = Heading 1-9
                return f"Heading{lvl + 1}"
        except ValueError:
            pass

    # Fallback 2: Check for bold formatted text at the start of the paragraph.
    # Often used as a heading when formal styles are not applied.
    # Only applies if text is relatively short (typical heading length).
    if 5 < len(p_text) < 150:
        r = p_elem.find(_wn("r"))
        if r is not None:
            rPr = r.find(_wn("rPr"))
            if rPr is not None and rPr.find(_wn("b")) is not None:
                return "HeadingBold"

    return ""


def _xml_para_bold(p_elem: ET.Element) -> bool:
    """Return True if the first run of the paragraph has w:b set."""
    for r in p_elem.iter(_wn("r")):
        rPr = r.find(_wn("rPr"))
        if rPr is not None and rPr.find(_wn("b")) is not None:
            return True
        break
    return False


def _xml_para_underline(p_elem: ET.Element) -> bool:
    """Return True if the first run of the paragraph has w:u (non-none value)."""
    for r in p_elem.iter(_wn("r")):
        rPr = r.find(_wn("rPr"))
        if rPr is not None:
            u = rPr.find(_wn("u"))
            if u is not None:
                val = u.get(_wn("val"), "")
                if val and val.lower() not in ("none", ""):
                    return True
        break
    return False


def _xml_para_font_size(p_elem: ET.Element) -> int:
    """Return the font size in points for the first run (w:sz is in half-points)."""
    for r in p_elem.iter(_wn("r")):
        rPr = r.find(_wn("rPr"))
        if rPr is not None:
            sz = rPr.find(_wn("sz"))
            if sz is not None:
                try:
                    return int(sz.get(_wn("val"), "0")) // 2
                except (ValueError, TypeError):
                    pass
        break
    return 0


# ---------------------------------------------------------------------------
# Paragraph stream abstraction (used by semantic chunking path only)
# ---------------------------------------------------------------------------


def _to_para_stream_di(events: list[tuple]) -> list[dict]:
    """
    Convert a DI event list into a normalised paragraph stream.
    Font size and underline are unavailable from DI — left at defaults.

    Each item: {text, is_heading, is_bold, is_uline, font_size, is_table, table_lines}
    """
    stream: list[dict] = []
    for kind, *payload in events:
        if kind == "heading":
            stream.append({
                "text": payload[0], "is_heading": True,
                "is_bold": False, "is_uline": False, "font_size": 0,
                "is_table": False, "table_lines": None,
            })
        elif kind == "text":
            stream.append({
                "text": payload[0], "is_heading": False,
                "is_bold": False, "is_uline": False, "font_size": 0,
                "is_table": False, "table_lines": None,
            })
        elif kind == "table":
            stream.append({
                "text": "", "is_heading": False,
                "is_bold": False, "is_uline": False, "font_size": 0,
                "is_table": True, "table_lines": payload[0],
            })
    return stream


def _to_para_stream_docx(body: ET.Element) -> list[dict]:
    """
    Walk an XML body element and convert paragraphs/tables to the normalised stream.
    Extracts bold, underline, and font_size from XML run properties.
    """
    stream: list[dict] = []
    for child in body:
        tag = child.tag
        if tag == _wn("p"):
            text = "".join(
                (node.text or "") for node in child.iter(_wn("t"))
            ).strip()
            if not text:
                continue
            style_id = _xml_para_style_id(child)
            stream.append({
                "text":       text,
                "is_heading": style_id in HEADING_STYLE_IDS,
                "is_bold":    _xml_para_bold(child),
                "is_uline":   _xml_para_underline(child),
                "font_size":  _xml_para_font_size(child),
                "is_table":   False,
                "table_lines": None,
            })
        elif tag == _wn("tbl"):
            stream.append({
                "text": "", "is_heading": False,
                "is_bold": False, "is_uline": False, "font_size": 0,
                "is_table": True, "table_lines": _xml_format_table(child),
            })
    return stream


# ---------------------------------------------------------------------------
# Semantic chunking — detection and metadata helpers
# ---------------------------------------------------------------------------


def detect_gpt_template(text: str) -> bool:
    """Return True when the document uses the standard GPT question template.

    Probes the first GPT_TEMPLATE_PROBE_CHARS characters for the canonical
    opening anchor 'מה האסטרטגיה'.  All three GPT knowledge docs contain this
    anchor in their first section.
    """
    return "מה האסטרטגיה" in text[:GPT_TEMPLATE_PROBE_CHARS]


def _parse_block_title(title_text: str) -> dict:
    """Extract show_name, season, and doc_type from a show-block heading.

    Examples handled:
      Pattern 1 — dash-separated strategy/insights titles:
        'תובנות השקה – ארץ נהדרת עונה 23 22/10/2025'
        'אסטרטגיה - חתונה ממבט ראשון – עונה 5 – גמר'
      Pattern 2 — bridge sentence (primary signal text):
        'המסמכים הבאים יעסקו בתוכנית "הזמר במסכה" עונה 1'
        "המסמכים הבאים יעסקו בסדרה 'פאלו אלטו'"
    """
    # season
    season_match = _SEASON_RE.search(title_text)
    season = int(season_match.group(1)) if season_match else None

    # Bridge-sentence fast path: when the heading is the explicit bridge
    # ('המסמכים הבאים יעסקו ב<תוכנית|סדרה> "X"') we trust the quoted name
    # directly. This handles the drama/reality docs cleanly.
    bridge_match = re.search(
        r'יעסקו\s+ב(?:תוכנית|סדרה)\s*[\u0022\u201c\u2018\u2019\u0027\u201d]'
        r'(.+?)'
        r'[\u0022\u201c\u2018\u2019\u0027\u201d]',
        title_text,
    )
    if bridge_match:
        bridge_name = bridge_match.group(1).strip()
        # Validate against catalog so we don't propagate garbage; if the
        # quoted text contains a catalog name, return that; else accept the
        # bridge text as-is (rare new shows).
        official = _extract_show_from_text(bridge_name)
        return {
            "show_name": official or bridge_name,
            "season":    season,
            "doc_type":  "כללי",  # bridge sentences don't carry doc_type
        }

    # doc_type -- keyword search (unchanged from previous version)
    doc_type = "כללי"
    for kw, label in _DOCTYPE_KEYS.items():
        if kw in title_text:
            doc_type = label
            break

    # show_name -- catalog-based lookup. Replaces the old _SHOW_RE-based
    # extraction that captured doc_type words on ~60% of chunks. If nothing in
    # the catalog matches, show_name is left empty (honest 'unknown') rather
    # than guessing from the heading text.
    show_name = _extract_show_from_text(title_text)

    return {"show_name": show_name, "season": season, "doc_type": doc_type}


def _normalize_question_type(header: str) -> str:
    """Map a Q&A heading to a canonical question_type label."""
    for key, qtype in _QTYPE_MAP.items():
        if key in header:
            return qtype
    return "כללי"


def _is_primary_split(para: dict, next_para: dict | None) -> bool:
    """True when this paragraph opens a new show/season block.

    Criteria (any one sufficient):
    1. Text starts with one of the Hebrew primary signals.
    2. Paragraph is a heading with font_size >= 20 (בידור doc, docx path only)
       AND the next paragraph looks like a date.
    3. Paragraph is a heading AND the next paragraph looks like a date
       (DI path: font_size unavailable; rely on heading role + date verification).
    """
    text = para["text"]

    # Signal 1 — explicit text marker
    for signal in _PRIMARY_TEXT_SIGNALS:
        if signal in text:
            return True

    # Signal 2 / 3 — heading followed by a date line
    if para["is_heading"] and next_para is not None:
        next_text = next_para.get("text") or ""
        if _DATE_LINE_RE.search(next_text):
            # For docx path, require large font OR the text itself signals a show
            if para["font_size"] >= 20:
                return True
            # For DI path (font_size == 0): accept any heading + date combination
            # when it looks like a show/season title (contains 'עונה' or typical doc words)
            if para["font_size"] == 0 and re.search(r"עונה|תובנות|אסטרטגיה|השקה|גמר", text):
                return True

    return False


def _is_secondary_split(para: dict, inside_block: bool) -> bool:
    """True when this paragraph opens a Q&A section within a show block.

    Requires:
    - We are inside a show block (inside_block=True)
    - The paragraph is formatted as bold+underline OR is a DI heading
    - The text starts with one of the canonical secondary anchors
    """
    if not inside_block:
        return False
    if not (para["is_heading"] or (para["is_bold"] and para["is_uline"])):
        return False
    text = para["text"]
    return any(text.startswith(anchor) for anchor in _SECONDARY_ANCHORS)


# ---------------------------------------------------------------------------
# Semantic chunking — main splitter
# ---------------------------------------------------------------------------


def _is_meaningful_short_section(chunk: dict) -> bool:
    """A below-min-size chunk is still worth keeping when it is a real, labeled
    Q&A section — its header is a recognized secondary anchor (e.g. 'מה האסטרטגיה',
    'מה הסלוגן') or primary show signal. Such sections carry concise but real
    answers (a one-line strategy or slogan) and must not be discarded as trivia.

    Regression this guards: פאלו אלטו's 'מה האסטרטגיה' answer is 114 chars (< the
    150 min) and was silently dropped, so the bot could never quote it. ~190 such
    labeled sections across the GPT docs were being lost the same way. Genuinely
    headerless fragments (no recognized header) are still discarded.
    """
    header = (chunk.get("header") or "").strip()
    if not header:
        return False
    if any(header.startswith(anchor) for anchor in _SECONDARY_ANCHORS):
        return True
    if any(signal in header for signal in _PRIMARY_TEXT_SIGNALS):
        return True
    return False


def _apply_semantic_guardrails(
    chunks: list[dict],
) -> list[dict]:
    """Apply min-size filter and max-size splitting with 1-line overlap.

    - Chunks below SEMANTIC_CHUNK_MIN_CHARS are discarded (trivial 1-liners).
    - Chunks above SEMANTIC_CHUNK_MAX_CHARS are split at paragraph boundaries;
      the last line of sub-chunk N is prepended to sub-chunk N+1 (overlap).
    - Sections flagged atomic=True (תכנית מדיה / מעקב פרומו) bypass the max
      limit so tables are never split mid-row.
    """
    result: list[dict] = []
    for chunk in chunks:
        text = chunk["chunk"].strip()

        # Min-size filter — discard trivial fragments, but KEEP short chunks that
        # are real labeled Q&A sections (concise strategy/slogan answers).
        if len(text) < SEMANTIC_CHUNK_MIN_CHARS and not _is_meaningful_short_section(chunk):
            continue

        # Atomic sections (tables) — keep as-is regardless of size
        if chunk.get("_atomic"):
            c = chunk.copy()
            c.pop("_atomic", None)
            result.append(c)
            continue

        # Max-size split
        if len(text) <= SEMANTIC_CHUNK_MAX_CHARS:
            result.append(chunk)
            continue

        lines = [ln for ln in text.split("\n") if ln.strip()]
        sub_idx = 0
        current: list[str] = []
        current_len = 0
        overlap_line: str | None = None

        def _flush_sub(buf: list[str]) -> None:
            nonlocal sub_idx
            sub_text = "\n".join(buf).strip()
            if len(sub_text) >= SEMANTIC_CHUNK_MIN_CHARS:
                sub = chunk.copy()
                sub["chunk_id"] = f"{chunk['chunk_id']}s{sub_idx}"
                sub["chunk"]    = sub_text
                result.append(sub)
                sub_idx += 1

        for line in lines:
            line_len = len(line)
            if overlap_line and not current:
                current.append(overlap_line)
                current_len = len(overlap_line)
                overlap_line = None
            if current_len + line_len + 1 > SEMANTIC_CHUNK_MAX_CHARS:
                overlap_line = current[-1] if current else None
                _flush_sub(current)
                current = [line]
                current_len = line_len
            else:
                current.append(line)
                current_len += line_len + 1
        if current:
            _flush_sub(current)

    return result


def split_semantic(
    para_stream: list[dict],
    title: str,
    source_url: str,
) -> list[dict]:
    """Split a GPT-template document into Q&A-scoped semantic chunks.

    Two-level split:
      Level 1 (primary): show/season blocks detected by _is_primary_split.
      Level 2 (secondary): Q&A sections detected by _is_secondary_split.

    Each flush produces one chunk carrying show_name, season, doc_type, and
    question_type metadata.  Tables under atomic section keys are kept whole.
    """
    doc_hash = _doc_hash(title)
    chunks_raw: list[dict] = []

    # Current show-block metadata
    block_meta: dict = {"show_name": "", "season": None, "doc_type": "כללי"}
    inside_block: bool = False

    # Current Q&A section state
    section_header: str = ""
    section_lines:  list[str] = []
    is_atomic: bool = False   # True for תכנית מדיה / מעקב פרומו sections

    def _flush_section() -> None:
        text = "\n".join(section_lines).strip()
        if not text:
            return
        chunks_raw.append({
            "chunk_id":      _chunk_id(doc_hash, len(chunks_raw)),
            "header":        section_header,
            "chunk":         text,
            "title":         title,
            "source_file":   source_url,
            "parent_id":     doc_hash,
            "show_name":     block_meta["show_name"],
            "season":        block_meta["season"],
            "doc_type":      block_meta["doc_type"],
            "question_type": _normalize_question_type(section_header),
            "_atomic":       is_atomic,
        })

    for idx, para in enumerate(para_stream):
        next_para = para_stream[idx + 1] if idx + 1 < len(para_stream) else None

        # --- Level-1: primary split → new show block ---
        if _is_primary_split(para, next_para):
            _flush_section()
            section_header = ""
            section_lines  = []
            is_atomic      = False
            inside_block   = True
            block_meta     = _parse_block_title(para["text"])
            # The primary heading itself becomes the section header for the
            # introductory content that follows (before the first Q&A anchor)
            section_header = para["text"]
            continue

        # --- Level-2: secondary split → new Q&A section ---
        if _is_secondary_split(para, inside_block):
            _flush_section()
            section_header = para["text"]
            section_lines  = []
            is_atomic      = any(key in para["text"] for key in _ATOMIC_SECTION_KEYS)
            continue

        # --- Accumulate content ---
        if para["is_table"]:
            section_lines.extend(para["table_lines"] or [])
        elif para["text"]:
            section_lines.append(para["text"])

    _flush_section()

    return _apply_semantic_guardrails(chunks_raw)


def _split_large_chunks(chunks: list[dict]) -> list[dict]:
    """
    Split any chunk exceeding CHUNK_MAX_CHARS into smaller sub-chunks.
    Preserves existing metadata and appends a suffix to chunk_id.
    """
    final_chunks = []
    for chunk in chunks:
        text = chunk["chunk"]
        if len(text) <= CHUNK_MAX_CHARS:
            final_chunks.append(chunk)
            continue
            
        # Split by paragraph boundaries
        paragraphs = text.split("\n")
        current_text = []
        current_len = 0
        sub_idx = 0
        
        for p in paragraphs:
            p_clean = p.strip()
            if not p_clean: continue
            
            p_len = len(p_clean)
            # If a single paragraph is larger than the limit, we just have to take it or split it further.
            # For simplicity, we split at word boundaries if a single paragraph is too large.
            if p_len > CHUNK_MAX_CHARS:
                # Flush current if exists
                if current_text:
                    new_chunk = chunk.copy()
                    new_chunk["chunk_id"] = f"{chunk['chunk_id']}_{sub_idx}"
                    new_chunk["chunk"] = "\n".join(current_text)
                    final_chunks.append(new_chunk)
                    sub_idx += 1
                    current_text = []
                    current_len = 0
                
                # Split large paragraph
                words = p_clean.split(" ")
                p_current = []
                p_curr_len = 0
                for w in words:
                    if p_curr_len + len(w) + 1 > CHUNK_MAX_CHARS:
                        new_chunk = chunk.copy()
                        new_chunk["chunk_id"] = f"{chunk['chunk_id']}_{sub_idx}"
                        new_chunk["chunk"] = " ".join(p_current)
                        final_chunks.append(new_chunk)
                        sub_idx += 1
                        p_current = [w]
                        p_curr_len = len(w)
                    else:
                        p_current.append(w)
                        p_curr_len += len(w) + 1
                if p_current:
                    current_text = [" ".join(p_current)]
                    current_len = p_curr_len
            elif current_len + p_len + 1 > CHUNK_MAX_CHARS:
                new_chunk = chunk.copy()
                new_chunk["chunk_id"] = f"{chunk['chunk_id']}_{sub_idx}"
                new_chunk["chunk"] = "\n".join(current_text)
                final_chunks.append(new_chunk)
                sub_idx += 1
                current_text = [p_clean]
                current_len = p_len
            else:
                current_text.append(p_clean)
                current_len += p_len + 1
                
        if current_text:
            new_chunk = chunk.copy()
            new_chunk["chunk_id"] = f"{chunk['chunk_id']}_{sub_idx}"
            new_chunk["chunk"] = "\n".join(current_text)
            final_chunks.append(new_chunk)
            
    return final_chunks


def extract_chunks_docx(docx_bytes: bytes, title: str, source_url: str) -> list[dict]:
    """
    Fallback extractor using stdlib zipfile + xml.etree for large files.

    If the document matches the GPT question template, the semantic chunking
    path is used (split_semantic).  Otherwise falls back to the existing
    heading-based fixed-size chunking.
    """
    doc_hash = _doc_hash(title)

    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        xml_bytes = zf.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    body = root.find(_wn("body"))
    if body is None:
        return []

    # Probe for GPT template using joined paragraph text
    probe_text = " ".join(
        "".join((n.text or "") for n in p.iter(_wn("t"))).strip()
        for p in body
        if p.tag == _wn("p")
    )[:GPT_TEMPLATE_PROBE_CHARS]
    if detect_gpt_template(probe_text):
        logger.info("    GPT template detected — using semantic chunking.")
        return split_semantic(_to_para_stream_docx(body), title, source_url)

    # --- Legacy fixed-size chunking (unchanged) ---
    chunks: list[dict] = []
    current_header = ""
    current_lines:  list[str] = []

    def _flush() -> None:
        chunk = _make_chunk(doc_hash, len(chunks), current_header, current_lines,
                            title, source_url)
        if chunk:
            chunks.append(chunk)

    for child in body:
        tag = child.tag

        if tag == _wn("p"):
            text = "".join(
                (node.text or "") for node in child.iter(_wn("t"))
            ).strip()
            if not text:
                continue

            style_id   = _xml_para_style_id(child)
            is_heading = style_id in HEADING_STYLE_IDS

            if is_heading:
                _flush()
                current_header = text
                current_lines  = []
            else:
                current_lines.append(text)

        elif tag == _wn("tbl"):
            current_lines.extend(_xml_format_table(child))

    _flush()
    return _split_large_chunks(chunks)


# ---------------------------------------------------------------------------
# Blob helpers
# ---------------------------------------------------------------------------


def _ensure_container(blob_service: BlobServiceClient, name: str) -> ContainerClient:
    cc = blob_service.get_container_client(name)
    try:
        cc.get_container_properties()
    except Exception:
        logger.info(f"  Container '{name}' not found — creating it ...")
        cc.create_container()
        logger.info(f"  Container '{name}' created.")
    return cc


def _json_blob_name(docx_blob_name: str) -> str:
    if docx_blob_name.lower().endswith(".docx"):
        return docx_blob_name[:-5] + ".json"
    return docx_blob_name + ".json"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(overwrite: bool = False, doc_filter: str | None = None) -> None:
    """Process all (or one) .docx blobs and save JSON chunks to promo-docs-json.

    doc_filter: if set, only the blob whose filename matches (case-insensitive)
                will be processed; all others are silently skipped.
    """
    missing = []
    if not AZURE_STORAGE_CONNECTION_STRING:
        missing.append("AZURE_STORAGE_CONNECTION_STRING")
    if not AZURE_DI_ENDPOINT:
        missing.append("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    if not AZURE_DI_KEY:
        missing.append("AZURE_DOCUMENT_INTELLIGENCE_KEY")
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Check your .env file."
        )

    di_client = DocumentIntelligenceClient(
        endpoint=AZURE_DI_ENDPOINT,
        credential=AzureKeyCredential(AZURE_DI_KEY),
    )
    blob_service    = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    dest_container  = _ensure_container(blob_service, DEST_CONTAINER)

    existing_json: set[str] = set()
    if not overwrite:
        existing_json = {b.name for b in dest_container.list_blobs()}

    source_container = blob_service.get_container_client(SOURCE_CONTAINER)
    blobs      = list(source_container.list_blobs())
    docx_blobs = [b for b in blobs if b.name.lower().endswith(".docx")]
    skipped_ext = len(blobs) - len(docx_blobs)

    if doc_filter:
        docx_blobs = [
            b for b in docx_blobs
            if os.path.basename(b.name).lower() == doc_filter.lower()
        ]
        if not docx_blobs:
            logger.error(f"--doc filter '{doc_filter}' matched no blobs.")
            return
        logger.info(f"--doc filter active: processing only '{doc_filter}'")

    logger.info(f"Found {len(blobs)} blob(s) in '{SOURCE_CONTAINER}'.")
    logger.info(f"  {len(docx_blobs)} .docx file(s) to process.")
    if skipped_ext:
        logger.info(f"  {skipped_ext} non-.docx file(s) skipped.")
    logger.info("")

    processed       = 0
    skipped_existing = 0
    total_chunks    = 0
    errors          = 0

    for blob_props in docx_blobs:
        blob_name = blob_props.name
        json_name = _json_blob_name(blob_name)
        size_bytes = blob_props.size or 0
        size_mb    = size_bytes / 1_048_576

        if json_name in existing_json and not overwrite:
            logger.info(f"  SKIP  {blob_name!r} (already processed)")
            skipped_existing += 1
            continue

        logger.info(f"  Processing  {blob_name!r}  ({size_mb:.1f} MB) ...")

        try:
            blob_client = source_container.get_blob_client(blob_name)
            docx_bytes  = blob_client.download_blob().readall()
            source_url  = blob_client.url
            title       = os.path.basename(blob_name)

            if size_bytes > DI_SIZE_LIMIT_BYTES:
                # ----- python-docx fallback for large files -----
                logger.info(f"    File exceeds {DI_SIZE_LIMIT_BYTES // (1024*1024)} MB limit "
                            f"— using python-docx fallback ...")
                chunks = extract_chunks_docx(docx_bytes, title, source_url)
            else:
                # ----- Document Intelligence path -----
                logger.info(f"    Analyzing with Document Intelligence ({MODEL_ID}) ...")
                poller = di_client.begin_analyze_document(
                    "prebuilt-layout",
                    {"base64Source": base64.b64encode(docx_bytes).decode()},
                )
                result = poller.result()
                chunks = extract_chunks_di(result, title, source_url)

            logger.info(f"    Produced {len(chunks)} chunk(s).")

            if chunks:
                json_bytes = json.dumps(chunks, ensure_ascii=False, indent=2).encode("utf-8")
                dest_container.upload_blob(name=json_name, data=json_bytes, overwrite=True)
                logger.info(f"    Saved -> '{json_name}'")
            else:
                logger.warning("    WARNING: No text content extracted — skipping upload.")

            processed    += 1
            total_chunks += len(chunks)

        except Exception as exc:
            logger.error(f"    ERROR processing '{blob_name}': {exc}")
            errors += 1

    logger.info("")
    logger.info("=" * 52)
    logger.info(f"  .docx blobs found     : {len(docx_blobs)}")
    logger.info(f"  Documents processed   : {processed}")
    logger.info(f"  Skipped (exist)       : {skipped_existing}")
    logger.info(f"  Total chunks produced : {total_chunks}")
    logger.info(f"  Errors                : {errors}")
    logger.info(f"  Output container      : {DEST_CONTAINER}")
    logger.info("=" * 52)


def preview_doc(doc_name: str) -> None:  # noqa: C901
    import sys as _sys
    # Force UTF-8 output so Hebrew and special chars render correctly in all terminals.
    if hasattr(_sys.stdout, "reconfigure"):
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    """Download one .docx blob, run chunking, and print every chunk to stdout.

    Nothing is written to Azure Storage or any other destination.
    Use this to verify semantic chunking output before running a full ingest.

    Usage:
        python scripts/preprocess_word_docs.py --preview-doc "מסמך ריאליטי GPT.docx"
    """
    required = {
        "AZURE_STORAGE_CONNECTION_STRING": AZURE_STORAGE_CONNECTION_STRING,
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": AZURE_DI_ENDPOINT,
        "AZURE_DOCUMENT_INTELLIGENCE_KEY": AZURE_DI_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    blob_service     = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    source_container = blob_service.get_container_client(SOURCE_CONTAINER)

    # Find the matching blob (case-insensitive filename comparison)
    blobs = list(source_container.list_blobs())
    target = next(
        (b for b in blobs if os.path.basename(b.name).lower() == doc_name.lower()),
        None,
    )
    if target is None:
        available = [os.path.basename(b.name) for b in blobs if b.name.lower().endswith(".docx")]
        logger.error(f"Document '{doc_name}' not found in '{SOURCE_CONTAINER}'.")
        logger.error("Available .docx files:")
        for name in available:
            logger.error(f"  {name}")
        return

    blob_name  = target.name
    size_bytes = target.size or 0
    size_mb    = size_bytes / 1_048_576
    logger.info(f"\nDownloading '{blob_name}' ({size_mb:.1f} MB) ...")

    blob_client = source_container.get_blob_client(blob_name)
    docx_bytes  = blob_client.download_blob().readall()
    source_url  = blob_client.url
    title       = os.path.basename(blob_name)

    if size_bytes > DI_SIZE_LIMIT_BYTES:
        logger.info("    Exceeds 4 MB — using python-docx fallback ...")
        chunks = extract_chunks_docx(docx_bytes, title, source_url)
    else:
        di_client = DocumentIntelligenceClient(
            endpoint=AZURE_DI_ENDPOINT,
            credential=AzureKeyCredential(AZURE_DI_KEY),
        )
        logger.info(f"    Analyzing with Document Intelligence ({MODEL_ID}) ...")
        poller = di_client.begin_analyze_document(
            "prebuilt-layout",
            {"base64Source": base64.b64encode(docx_bytes).decode()},
        )
        result = poller.result()
        chunks = extract_chunks_di(result, title, source_url)

    # ------------------------------------------------------------------
    # Print every chunk — no upload
    # ------------------------------------------------------------------
    sep  = "=" * 72
    dash = "-" * 72
    print(f"\n{sep}")
    print(f"  DOCUMENT : {title}")
    print(f"  CHUNKS   : {len(chunks)}")
    print(sep)

    for i, c in enumerate(chunks, 1):
        chunk_text = c.get("chunk", "").strip()
        header     = c.get("header", "") or "(no header)"
        show_name  = c.get("show_name", "") or ""
        season     = c.get("season")
        doc_type   = c.get("doc_type", "") or ""
        qtype      = c.get("question_type", "") or ""
        chunk_len  = len(chunk_text)

        print(f"\n[{i:03d}]  {dash[:len(dash)-6]}")
        print(f"  chunk_id    : {c.get('chunk_id', '')}")
        print(f"  header      : {header}")
        if show_name:
            print(f"  show_name   : {show_name}")
        if season is not None:
            print(f"  season      : {season}")
        if doc_type:
            print(f"  doc_type    : {doc_type}")
        if qtype:
            print(f"  quest_type  : {qtype}")
        print(f"  length      : {chunk_len} chars")
        print()
        # Print the first 600 chars of the chunk body; show ellipsis if truncated
        preview = chunk_text[:600]
        if len(chunk_text) > 600:
            preview += "\n  [... truncated ...]"
        for line in preview.splitlines():
            print(f"    {line}")

    print(f"\n{sep}")
    print(f"  TOTAL CHUNKS : {len(chunks)}")

    # Quality summary
    short  = sum(1 for c in chunks if len(c.get("chunk", "").strip()) < SEMANTIC_CHUNK_MIN_CHARS)
    long_  = sum(1 for c in chunks if len(c.get("chunk", "").strip()) > SEMANTIC_CHUNK_MAX_CHARS)
    no_hdr = sum(1 for c in chunks if not c.get("header", "").strip())
    no_show = sum(1 for c in chunks if not c.get("show_name", ""))
    print(f"  Too short (<{SEMANTIC_CHUNK_MIN_CHARS} chars) : {short}")
    print(f"  Too long  (>{SEMANTIC_CHUNK_MAX_CHARS} chars) : {long_}")
    print(f"  No header                   : {no_hdr}")
    print(f"  No show_name                : {no_show}")
    print(sep)
    print("\nNOTE: Nothing was written to Azure Storage.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Chunk .docx blobs via Document Intelligence (or python-docx fallback) "
                    "and save JSON to promo-docs-json"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-process documents that already have a JSON file in the destination",
    )
    parser.add_argument(
        "--doc",
        metavar="FILENAME",
        default=None,
        help=(
            "Process only the named document (case-insensitive filename match). "
            "Implies --overwrite for that single file. "
            "Example: --doc \"מסמך ריאליטי GPT.docx\""
        ),
    )
    parser.add_argument(
        "--preview-doc",
        metavar="FILENAME",
        default=None,
        help=(
            "Dry-run mode: download and chunk ONE named document, print every chunk "
            "to stdout, and exit WITHOUT writing anything to Azure Storage. "
            "Example: --preview-doc \"מסמך ריאליטי GPT.docx\""
        ),
    )
    args = parser.parse_args()
    if args.preview_doc:
        preview_doc(args.preview_doc)
    elif args.doc:
        main(overwrite=True, doc_filter=args.doc)
    else:
        main(overwrite=args.overwrite)
