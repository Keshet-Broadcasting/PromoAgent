"""
convert_excel_to_json.py

Parses a TV-promo ratings Excel workbook (Hebrew sheet names) and converts
all broadcast rows across all sheets into a single flat JSON array.

Usage:
    python scripts/convert_excel_to_json.py [input.xlsx] [output.json]

Defaults:
    input.xlsx  -> "מעקבי פרומו.xlsx"
    output.json -> "processed_promos.json"

Dependencies:
    pip install pandas openpyxl
"""

import json
import math
import re
import sys
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Configuration: canonical column names we expect after normalization
# ---------------------------------------------------------------------------

# Hebrew header tokens we know about, mapped to our canonical English keys.
HEADER_MAP = {
    "תאריך": "date",
    "בפרומו": "promo_text",
    "נקודת פתיחה": "opening_rating",
    "רייטינג פרק": "average_rating",
    "תחרות": "competition",
    "רשת": "competition",          # used in one sheet instead of תחרות
    "חדשות": "competition_extra",  # secondary competition column
    "ליד": "lead_in",
    "מספר פרק": "episode",
    "מס' פרק": "episode",
    "יום בשבוע": "weekday",
    "יום": "weekday",
    "יום שידור": "weekday",
    "ברייקים": "breaks",
    "חשיפה": "reveal",
    "מי היה במסכה": "reveal",
    "אולפ\"ש": "olfash",
    "שימור": "retention",
    "אודישנים": "section",
    "שלב הבתים": "section",
    "עונה 8- בפרומו": "promo_text",
    "עונה 9- בפרומו": "promo_text",
    "אודישנים ": "section",
}

# Sheets that have NO header row — data starts at row 1 (0-indexed) or row 2.
# Order assumed: [date, promo_text, opening_rating, average_rating, competition]
# Some have an episode number + weekday prefix (פרק/יום) — we detect dynamically.
NO_HEADER_SHEETS = {
    "היורשת",
    "נוטוק",
    "מאסטר שף עונה 11 VIP",
}

# Sheets that contain only a single merged note (no real data rows).
EMPTY_NOTE_SHEETS = {
    "אור ראשון",
    "מאסטר שף עונה 9 VIP",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_cell(value):
    """Convert NaN / empty strings to None, otherwise strip whitespace."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        v = value.strip()
        return v if v else None
    return value


def to_float(value):
    """
    Convert a cell to float. Strips '%' signs and commas.
    If the cell contains non-numeric text (e.g. "השקה"), returns
    (None, original_text) so the caller can move that text into promo_text.
    Returns (float_or_None, leftover_text_or_None).
    """
    v = clean_cell(value)
    if v is None:
        return None, None
    if isinstance(v, (int, float)):
        return float(v), None
    # string case
    s = str(v).replace("%", "").replace(",", "").strip()
    try:
        return float(s), None
    except ValueError:
        return None, str(v).strip()


def parse_season(sheet_name: str):
    """Extract Hebrew season label, preserving VIP suffix when present."""
    m = re.search(r"עונה\s*(\d+)(?:\s*(VIP))?", sheet_name, flags=re.IGNORECASE)
    if m:
        season = m.group(1)
        return f"{season} VIP" if m.group(2) else int(season)
    m = re.search(r"(\d+)\s*$", sheet_name.strip())
    if m:
        return int(m.group(1))
    return None


def parse_show_name(sheet_name: str):
    """Strip the 'עונה N' suffix (and trailing standalone numbers / 'VIP')
    to get the base show name."""
    name = sheet_name.strip()
    name = re.sub(r"\s*עונה\s*\d+.*$", "", name)
    name = re.sub(r"\s+\d+\s*$", "", name)
    name = re.sub(r"\s*VIP\s*$", "", name, flags=re.IGNORECASE)
    return name.strip()


def extract_episode_from_text(text):
    """Try to infer an episode number from promo / section text."""
    if not text:
        return None
    s = str(text)
    m = re.search(r"פרק\s*(\d+)", s)
    if m:
        return int(m.group(1))
    if re.search(r"\bהשקה\b", s):
        return 1
    return None


def normalize_headers(raw_headers):
    """Map raw Hebrew headers to canonical English keys."""
    mapped = []
    for h in raw_headers:
        h_clean = clean_cell(h)
        if h_clean is None:
            mapped.append(None)
        else:
            mapped.append(HEADER_MAP.get(str(h_clean).strip(), str(h_clean).strip()))
    return mapped


def is_section_header_row(row_values):
    """A 'section' row has exactly one non-empty cell with known section text."""
    non_empty = [clean_cell(v) for v in row_values if clean_cell(v) is not None]
    if len(non_empty) == 1:
        text = str(non_empty[0]).strip()
        if len(text) < 30 and not re.match(r"^\d", text):
            return text
    return None


# ---------------------------------------------------------------------------
# Core per-sheet processing
# ---------------------------------------------------------------------------

def process_sheet(sheet_name: str, df_raw: pd.DataFrame):
    """
    df_raw is the sheet loaded with header=None so we see every row as-is.
    Returns a list of record dicts.
    """
    records = []
    show_name = parse_show_name(sheet_name)
    season = parse_season(sheet_name)

    # ---------- 1. Empty/note-only sheets ----------
    if sheet_name in EMPTY_NOTE_SHEETS:
        note_text = None
        for _, row in df_raw.iterrows():
            for cell in row:
                c = clean_cell(cell)
                if c is not None:
                    note_text = str(c)
                    break
            if note_text:
                break
        records.append({
            "show_name": show_name,
            "season": season,
            "episode": None,
            "date": None,
            "opening_rating": None,
            "average_rating": None,
            "promo_text": note_text,
            "competition": None,
        })
        return records

    # ---------- 2. No-header sheets ----------
    if sheet_name in NO_HEADER_SHEETS:
        for _, row in df_raw.iterrows():
            vals = [clean_cell(v) for v in row.tolist()]
            if all(v is None for v in vals):
                continue

            if len(vals) >= 7 and isinstance(vals[0], (int, float)) and not isinstance(vals[0], bool):
                ep = int(vals[0])
                date = vals[2]
                promo = vals[3]
                opening_raw = vals[4]
                avg_raw = vals[5]
                comp = vals[6] if len(vals) > 6 else None
            else:
                ep = None
                date = vals[0] if len(vals) > 0 else None
                promo = vals[1] if len(vals) > 1 else None
                opening_raw = vals[2] if len(vals) > 2 else None
                avg_raw = vals[3] if len(vals) > 3 else None
                comp = vals[4] if len(vals) > 4 else None

            opening, opening_overflow = to_float(opening_raw)
            avg, avg_overflow = to_float(avg_raw)

            promo_parts = [p for p in (promo, opening_overflow, avg_overflow) if p]
            promo_text = " | ".join(str(p) for p in promo_parts) if promo_parts else None

            if ep is None:
                ep = extract_episode_from_text(promo_text)

            records.append({
                "show_name": show_name,
                "season": season,
                "episode": ep,
                "date": str(date) if date is not None else None,
                "opening_rating": opening,
                "average_rating": avg,
                "promo_text": promo_text,
                "competition": str(comp) if comp is not None else None,
            })
        return records

    # ---------- 3. Standard sheets ----------
    if len(df_raw) < 3:
        return records

    header_row = df_raw.iloc[1].tolist()
    headers = normalize_headers(header_row)

    non_empty_headers = [h for h in headers if h]
    section_only_header = (
        len(non_empty_headers) == 1
        and non_empty_headers[0] == "section"
    )

    current_section = None

    if section_only_header:
        current_section = clean_cell(header_row[0])

    data_start = 2
    for i in range(data_start, len(df_raw)):
        row = df_raw.iloc[i].tolist()

        if all(clean_cell(v) is None for v in row):
            continue

        section_label = is_section_header_row(row)
        if section_label and not section_only_header:
            current_section = section_label
            continue

        row_dict = {}
        for h, v in zip(headers, row):
            if h is None:
                continue
            row_dict.setdefault(h, clean_cell(v))

        if section_only_header:
            vals = [clean_cell(v) for v in row]
            if all(v is None for v in vals):
                continue
            if len(vals) >= 7 and isinstance(vals[0], (int, float)):
                row_dict = {
                    "episode": int(vals[0]),
                    "weekday": vals[1],
                    "date": vals[2],
                    "promo_text": vals[3],
                    "opening_rating": vals[4],
                    "average_rating": vals[5],
                    "competition": vals[6],
                }
            else:
                row_dict = {
                    "date": vals[0] if len(vals) > 0 else None,
                    "promo_text": vals[1] if len(vals) > 1 else None,
                    "opening_rating": vals[2] if len(vals) > 2 else None,
                    "average_rating": vals[3] if len(vals) > 3 else None,
                    "competition": vals[4] if len(vals) > 4 else None,
                }

        opening, opening_overflow = to_float(row_dict.get("opening_rating"))
        avg, avg_overflow = to_float(row_dict.get("average_rating"))

        promo = row_dict.get("promo_text")
        extras = [x for x in (opening_overflow, avg_overflow) if x]
        if extras:
            promo = " | ".join([str(promo)] + extras) if promo else " | ".join(extras)

        if current_section:
            promo = f"[{current_section}] " + (str(promo) if promo else "")

        ep = row_dict.get("episode")
        if isinstance(ep, float) and not math.isnan(ep):
            ep = int(ep)
        elif isinstance(ep, str):
            m = re.search(r"\d+", ep)
            ep = int(m.group()) if m else None
        elif ep is None or (isinstance(ep, float) and math.isnan(ep)):
            ep = None

        if ep is None:
            ep = extract_episode_from_text(promo)

        date_val = row_dict.get("date")
        if isinstance(date_val, pd.Timestamp):
            date_str = date_val.strftime("%d.%m.%Y").lstrip("0").replace(".0", ".")
        else:
            date_str = str(date_val) if date_val is not None else None

        records.append({
            "show_name": show_name,
            "season": season,
            "episode": ep,
            "date": date_str,
            "opening_rating": opening,
            "average_rating": avg,
            "promo_text": str(promo) if promo else None,
            "competition": str(row_dict["competition"]) if row_dict.get("competition") is not None else None,
        })

    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("מעקבי פרומו.xlsx")
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("processed_promos.json")

    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {input_path} ...")
    all_sheets = pd.read_excel(input_path, sheet_name=None, header=None, engine="openpyxl")
    print(f"Found {len(all_sheets)} sheets.")

    all_records = []
    for sheet_name, df_raw in all_sheets.items():
        try:
            sheet_records = process_sheet(sheet_name, df_raw)
            print(f"  [{sheet_name}] -> {len(sheet_records)} record(s)")
            all_records.extend(sheet_records)
        except Exception as exc:
            print(f"  [{sheet_name}] !! ERROR: {exc}", file=sys.stderr)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Wrote {len(all_records)} records to {output_path}")


if __name__ == "__main__":
    main()
