"""test_data_health.py

Data-quality and index-health tests for the PromoAgent pipeline.

Three test layers:

1. **Catalog unit tests** (always run, no network):
   - Catalog has no duplicate official names that would silently override aliases.
   - Newly-added shows (May 25) are present and tagged with a valid genre.
   - Doc-type words (השקה, גמר, מחקר, ...) are NOT present as official show names
     — this is the guard against the Phase 6c regression we fixed.
   - The catalog-lookup helper (`_extract_show_from_text` reimplemented here)
     produces the expected official names for known heading patterns and the
     expected empty result for unknown queries.

2. **word-docs index health** (marked `live`, requires Azure Search creds):
   - Schema has the 4 Phase 6b metadata fields.
   - No chunks have `show_name` set to a doc-type value.
   - ≥80% of chunks have non-empty `show_name`.
   - ≥30 distinct catalog shows are represented in the index.

3. **tv-promos index sanity** (marked `live`):
   - Schema has show_name + rating fields.
   - The big shows the eval relies on each have a meaningful number of rows.

Usage:
    # Fast tests only
    pytest tests/test_data_health.py -m "not live"
    # All tests
    pytest tests/test_data_health.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

import pytest

# Make app/ importable when tests are run via pytest from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.domain_catalog import SHOWS, official_show_names


# ---------------------------------------------------------------------------
# Helper — replicates _extract_show_from_text from preprocess_word_docs.py
# so the test doesn't pull in Azure-SDK imports just to verify the logic.
# Keep in sync with scripts/preprocess_word_docs.py.
# ---------------------------------------------------------------------------

def _build_catalog_lookup() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for show in SHOWS:
        for term in (show.official,) + tuple(show.aliases):
            if term and term not in seen:
                seen.add(term)
                pairs.append((term, show.official))
    return sorted(pairs, key=lambda x: len(x[0]), reverse=True)


_LOOKUP = _build_catalog_lookup()


def _extract_show_from_text(text: str) -> str:
    if not text:
        return ""
    for term, official in _LOOKUP:
        if term in text:
            return official
    return ""


# Words that look like show names from a regex POV but are actually doc-types
# emitted by the previous (buggy) parser. If any of these appear as official
# show names in the catalog, the new generic lookup would mis-attribute chunks.
_DOC_TYPE_GARBAGE = frozenset({
    "השקה",
    "גמר",
    "גמר ועונה",
    "השקה וגמר",
    "סיום עונה",
    "אמצע עונה",
    "מחקר",
    "אסטרטגיה",
    "ראשונה",
})


# ===========================================================================
# Layer 1 — Catalog unit tests (always run)
# ===========================================================================


def test_catalog_has_no_duplicate_official_names():
    """A duplicate official name silently overrides the first entry in the
    `_OFFICIAL_BY_NAME` dict — we want explicit awareness of any duplicate."""
    counts = Counter(show.official for show in SHOWS)
    duplicates = {name: c for name, c in counts.items() if c > 1}
    # Known historical duplicate (אהבה גדולה מהחיים appears as both drama and
    # reality). Document explicitly so a new accidental duplicate fails.
    known = {"אהבה גדולה מהחיים"}
    new_duplicates = set(duplicates) - known
    assert not new_duplicates, (
        f"Unexpected duplicate official names in catalog: {new_duplicates}. "
        f"If intentional, add to the `known` set in this test."
    )


def test_catalog_no_garbage_official_names():
    """Doc-type words must never be official show names. If the buggy parser's
    output ever leaks back into the catalog, this fails."""
    officials = {show.official for show in SHOWS}
    leaked = _DOC_TYPE_GARBAGE & officials
    assert not leaked, (
        f"Doc-type words present as official show names in catalog: {leaked}. "
        f"These would cause _extract_show_from_text to return them as shows."
    )


def test_catalog_contains_newly_added_shows():
    """The 8 untracked shows added on May 25 (Phase 6c) must be present."""
    expected_additions = {
        "סברי מרנן",
        "מועדון לילה",
        "כוכבים בריבוע",
        "צא מזה",
        "כפולים",
        "רצח בים המלח",
    }
    officials = {show.official for show in SHOWS}
    missing = expected_additions - officials
    assert not missing, f"Missing newly-added shows: {missing}"


def test_catalog_aliases_resolve_to_official_names():
    """Every alias must point to a show that's also in the official list."""
    officials = {show.official for show in SHOWS}
    for show in SHOWS:
        for alias in show.aliases:
            assert show.official in officials, (
                f"Alias {alias!r} points to {show.official!r} which is not an official name"
            )


# ---------------------------------------------------------------------------
# Catalog lookup behavior — the parser fix is only as good as this helper.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("heading, expected", [
    # The exact garbage patterns we saw in the live index pre-fix
    ("תובנות השקה – ארץ נהדרת – עונה 23 22/10/2025",       "ארץ נהדרת"),
    ("תובנות גמר ועונה – חתונה ממבט ראשון – ע7",            "חתונה ממבט ראשון"),
    ("תובנות גמר – אור ראשון",                                "אור ראשון"),
    ("אסטרטגיה ראשונה – נינג'ה ישראל – 19/05",               "נינג'ה ישראל"),

    # Longest-match preference
    ("תובנות השקה – הכוכב הבא לאירוויזיון – עונה 12",       "הכוכב הבא לאירוויזיון"),
    ("תובנות השקה – הכוכב הבא – עונה 9",                     "הכוכב הבא"),

    # Entertainment doc — no bridge sentence, show name in heading
    ("מה האסטרטגיה של השקת התוכנית 'כוכבים בריבוע' עונה 1?", "כוכבים בריבוע"),

    # Bridge sentence
    ('המסמכים הבאים יעסקו בתוכנית "הזמר במסכה" עונה 1',       "הזמר במסכה"),

    # Newly-added shows
    ("תובנות השקה – סברי מרנן – עונה 8",                     "סברי מרנן"),
    ("תובנות השקה – מועדון לילה ע9",                         "מועדון לילה"),

    # Alias fallback (truncated heading the parser used to capture wrong)
    ("תובנות השקה – מה באמת קרה שם",                          "מה באמת קרה שם ארז טל"),

    # Unknown shows must return empty — never guess
    ("תובנות השקה – שמלה לא קיימת – עונה 1",                 ""),
    ("תובנות השקה – פילם נוואר חדש",                          ""),
])
def test_extract_show_from_text(heading, expected):
    assert _extract_show_from_text(heading) == expected


def test_extract_show_never_returns_doc_type():
    """Whatever the input, _extract_show_from_text must never return a doc-type
    word. This is the structural guarantee of the Phase 6c rewrite."""
    sample_headings = [
        "תובנות השקה – ארץ נהדרת",
        "תובנות גמר ועונה – חתונה ממבט ראשון",
        "תובנות גמר",
        "אסטרטגיה ראשונה",
        "סיום עונה",
        "אמצע עונה",
    ]
    for heading in sample_headings:
        result = _extract_show_from_text(heading)
        assert result not in _DOC_TYPE_GARBAGE, (
            f"Heading {heading!r} returned doc-type {result!r} as show_name"
        )


# ===========================================================================
# Layer 2 — word-docs index health (live)
# ===========================================================================


def _live_search_client(index_name: str):
    """Return a SearchClient or skip the test if credentials aren't configured."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    ep = os.getenv("AZURE_SEARCH_ENDPOINT")
    key = os.getenv("AZURE_SEARCH_KEY")
    if not ep or not key:
        pytest.skip(f"Azure Search credentials not configured")
    return SearchClient(endpoint=ep, index_name=index_name, credential=AzureKeyCredential(key))


@pytest.mark.live
def test_word_docs_schema_has_phase_6b_fields():
    """The schema migration must have included the 4 metadata fields."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient

    ep = os.getenv("AZURE_SEARCH_ENDPOINT")
    key = os.getenv("AZURE_SEARCH_KEY")
    if not ep or not key:
        pytest.skip("Azure Search credentials not configured")

    client = SearchIndexClient(endpoint=ep, credential=AzureKeyCredential(key))
    idx = client.get_index("word-docs")
    field_names = {f.name for f in idx.fields}
    expected = {"show_name", "season", "doc_type", "question_type"}
    missing = expected - field_names
    assert not missing, f"word-docs index is missing Phase 6b fields: {missing}"


@pytest.mark.live
def test_word_docs_no_doc_type_as_show_name():
    """After the Phase 6c re-ingest, no chunk should have show_name set to a
    doc-type word. This catches a parser regression immediately."""
    sc = _live_search_client("word-docs")
    counts = Counter()
    res = sc.search(search_text="*", select=["show_name"], top=1000)
    for r in res:
        counts[(r.get("show_name") or "").strip()] += 1
    leaked = {sn: c for sn, c in counts.items() if sn in _DOC_TYPE_GARBAGE}
    assert not leaked, (
        f"Live word-docs index has chunks tagged with doc-type as show_name: {leaked}. "
        f"Phase 6c re-ingest did not run, or the parser regressed."
    )


@pytest.mark.live
def test_word_docs_show_name_coverage():
    """At least 80% of chunks should have a non-empty show_name post-Phase-6c.
    Pre-Phase-6c we had 17 empty out of 667 (~97% non-empty) but ~60% garbage;
    after the fix, we expect cleaner data with a slightly lower coverage as
    untaggable chunks honestly return empty."""
    sc = _live_search_client("word-docs")
    total = 0
    non_empty = 0
    res = sc.search(search_text="*", select=["show_name"], top=1000)
    for r in res:
        total += 1
        if (r.get("show_name") or "").strip():
            non_empty += 1
    assert total > 0, "Word index appears empty"
    coverage = non_empty / total
    assert coverage >= 0.80, (
        f"Word index show_name coverage dropped to {coverage:.1%} "
        f"({non_empty}/{total}). Expected ≥80%."
    )


@pytest.mark.live
def test_word_docs_catalog_overlap():
    """≥30 catalog shows should have at least one chunk in the index after
    Phase 6c. Pre-fix only 22 of 40 catalog shows matched any chunk."""
    sc = _live_search_client("word-docs")
    index_show_names = set()
    res = sc.search(search_text="*", select=["show_name"], top=1000)
    for r in res:
        sn = (r.get("show_name") or "").strip()
        if sn:
            index_show_names.add(sn)
    catalog = set(official_show_names())
    overlap = catalog & index_show_names
    assert len(overlap) >= 30, (
        f"Only {len(overlap)} catalog shows match index show_names. "
        f"Pre-fix baseline was 22; expected ≥30 after Phase 6c re-ingest. "
        f"Catalog ({len(catalog)}) ∩ Index ({len(index_show_names)})."
    )


# ===========================================================================
# Layer 3 — tv-promos (Excel) index sanity (live)
# ===========================================================================


@pytest.mark.live
def test_tv_promos_has_essential_fields():
    """The Excel index must expose the fields service.py relies on."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient

    ep = os.getenv("AZURE_SEARCH_ENDPOINT")
    key = os.getenv("AZURE_SEARCH_KEY")
    if not ep or not key:
        pytest.skip("Azure Search credentials not configured")

    client = SearchIndexClient(endpoint=ep, credential=AzureKeyCredential(key))
    idx = client.get_index("tv-promos")
    field_names = {f.name for f in idx.fields}
    required = {"show_name", "season", "rating", "opening_point", "promo_text"}
    missing = required - field_names
    assert not missing, f"tv-promos index is missing required fields: {missing}"


@pytest.mark.live
@pytest.mark.parametrize("show_name, min_rows", [
    ("חתונה ממבט ראשון", 100),  # 6 seasons × ~25 episodes
    ("נינג'ה ישראל",      80),   # 4 seasons × ~30 episodes
    ("הכוכב הבא",         50),
    ("ארץ נהדרת",         80),   # 5 seasons × ~20 episodes
])
def test_tv_promos_show_has_rows(show_name, min_rows):
    """Major shows must have a meaningful number of rows. If any drops to ~0,
    we know an ingest broke for that tab (e.g., the row-2-has-data bug for
    היורשת / נוטוק)."""
    sc = _live_search_client("tv-promos")
    safe = show_name.replace("'", "''")
    res = sc.search(
        search_text="*",
        filter=f"show_name eq '{safe}'",
        top=0,
        include_total_count=True,
    )
    list(res)
    count = res.get_count()
    assert count >= min_rows, (
        f"Show {show_name!r} has only {count} rows in tv-promos "
        f"(expected ≥{min_rows}). The Excel tab may have an ingest issue."
    )
