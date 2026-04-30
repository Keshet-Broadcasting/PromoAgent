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

import xml.etree.ElementTree as ET            # stdlib XML parser for .docx fallback
import zipfile                                 # stdlib ZIP reader for .docx files
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient, ContainerClient
from dotenv import load_dotenv

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

# Word style IDs that represent headings (locale-independent English IDs)
HEADING_STYLE_IDS = {f"Heading{i}" for i in range(1, 10)} | {"Title"}

# Word Open XML namespaces used in document.xml
_W  = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_wn = lambda tag: f"{{{_W}}}{tag}"   # shorthand: _wn('p') → '{...}p'


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
    """Convert a DI AnalyzeResult into semantic chunks."""
    doc_hash = _doc_hash(title)
    events   = _di_build_event_stream(result)

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

    Opens the .docx ZIP archive, parses word/document.xml, and walks the
    document body in document order (preserving table/paragraph interleaving).
    Heading paragraphs (Heading 1-9, Title styles) start new chunks.
    """
    doc_hash = _doc_hash(title)

    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        xml_bytes = zf.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    body = root.find(_wn("body"))
    if body is None:
        return []

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


def main(overwrite: bool = False) -> None:
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
    args = parser.parse_args()
    main(overwrite=args.overwrite)
