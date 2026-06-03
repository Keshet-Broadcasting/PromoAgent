# Session Findings — Word-docs Index Extraction Gap (the real root cause)

**Author:** Claude (pairing session with Amit)
**Scope:** Tracing why PromoBot couldn't quote אף אחד לא עוזב את פאלו אלטו's strategy in a
"quote all dramas" question led, layer by layer, to a **document-extraction bug** in the
word-docs ingestion pipeline. Confirmed against the live SharePoint source via the M365 MCP.

---

## 0. TL;DR

The bot omitted פאלו אלטו from a "quote the sales strategies of all dramas" answer. We peeled
back **four layers**, each a real fix:

1. **Genre contamination** — `BROAD_RETRIEVAL_ENABLED` was off → fixed (prior session).
2. **Retrieval breadth** — single top-N gave ~3 shows → per-show fetch gives 16/17. Fixed.
3. **LLM enumeration** — model listed a subset → Coverage Mode prompt. Fixed.
4. **Min-size guardrail dropped it (ROOT — now pinned down exactly)** — פאלו אלטו's strategy
   section IS in the source, IS extracted into the chunk stream, and IS emitted as a chunk
   (`show=פאלו אלטו`, `question_type=אסטרטגיה`, 114 chars). But `_apply_semantic_guardrails`
   **discards any chunk < `SEMANTIC_CHUNK_MIN_CHARS` (150)** as "trivia" — so the 114-char
   strategy answer was silently dropped. **~369 short but real labeled Q&A sections** (strategy/
   slogan/short answers) were lost the same way across the 4 GPT docs. **Fixed in code**
   (commit `f68b9c5`); requires re-ingestion to land in the index.

> The earlier hypothesis in §2 below (a >4 MB extraction/structure gap) was **disproven**: the
> text is a normal `<w:p>` at body index 13, present in `_to_para_stream_docx`'s output. The
> loss is the size guardrail, not extraction. §2/§3 are corrected accordingly.

## 1. The decisive evidence

| Probe | Result |
|---|---|
| Langfuse trace `f303cc26` | "quote all dramas" returned **6 word chunks**, ~3 shows; פאלו אלטו absent |
| Per-show retrieval (after fix) | **16/17 dramas** in context incl. פאלו אלטו ✅ |
| Index search for "מקרה רצח שעלול להבעיר" / slogan / "מה האסטרטגיה...פאלו אלטו" | **0 chunks contain it**; פאלו אלטו has no `question_type='אסטרטגיה'` chunk (גוף שלישי/השוטרים do) |
| `preprocess_word_docs.py --preview-doc "מסמך דרמות GPT.docx"` (dry run, the actual pipeline) | 178 chunks, 6 "מה האסטרטגיה" sections, 36 פאלו אלטו mentions — but **0** occurrences of פאלו אלטו's strategy phrases |
| **M365 MCP** read of SharePoint `DocLib4/עבודה ChatGPT/מסמך דרמות GPT.docx` (mod 2026-02-25) | **Contains all three strategy phrases** ✅ |

**Conclusion (refined in §2):** the source HAS the text AND the repo *does* extract it into a
chunk — but the min-size guardrail discarded that 114-char chunk, so it never reached the index.
(The probes above pre-date that finding; they observe the *symptom* — absent from the index — not
the cause.) Now fixed + re-ingested.

## 2. Root cause (definitive)

Traced on the **exact ingested file** (`C:\Users\amit.rosen\Downloads\docx\מסמך דרמות GPT.docx`,
26,719,791 bytes — byte-size matches Amit's Drive note for the indexed file):

- The strategy text is present in the docx as **normal body text** (a `<w:p>` at body child
  index 13; body has only `p`/`tbl`/`sectPr` — no text boxes/content controls). `iter(w:t)`
  finds it; **`_to_para_stream_docx` includes it** in the stream the chunker sees.
- `split_semantic` emits it as a real chunk: `header="מה האסטרטגיה של הסדרה אף אחד..."`,
  `show_name=אף אחד לא עוזב את פאלו אלטו`, `question_type=אסטרטגיה`, **body = 114 chars**.
- **`_apply_semantic_guardrails` then discards it** because `114 < SEMANTIC_CHUNK_MIN_CHARS`
  (150). The min-size filter was meant to drop "trivial 1-liners" but also kills short *labeled*
  answers (a one-line strategy, a slogan).

**Which docs are affected — two code paths.** `preprocess_word_docs.py` routes **>4 MB docs to
the python-docx fallback** (`extract_chunks_docx` → `split_semantic`) and **≤4 MB docs to
Document Intelligence** (`extract_chunks_di`). The min-size drop bites the **fallback path**
(large docs); the DI path produces coarser chunks and is unaffected.

| Doc | path | old index | new (re-ingested) | recovered |
|---|---|---|---|---|
| מסמך דרמות GPT (25.5 MB) | fallback | 174 | **262** | **+88** |
| מסמך ריאליטי GPT (34.6 MB) | fallback | 423 | **602** | **+179** |
| GPT מסמך בידור (0.7 MB) | DI | 45 | 45 | 0 (unaffected) |
| GPT מסמך תוכניות נוספות (0.6 MB) | DI | 25 | 25 | 0 (unaffected) |

→ **~267 real labeled Q&A sections recovered** on the two large docs (which is where the
strategy sections live; the index previously had only ~6 `אסטרטגיה` chunks across 17 dramas).
The small docs were already correct (DI path). The historical 16 MB Basic-tier metadata-only
episode is real context but not the cause — the content was extracted fine; the size guardrail
discarded it.

> Caveat for future readers: an earlier draft of this doc cited +70/+32 for the two small docs.
> That was measured by running the *fallback* extractor on local copies — NOT the DI path prod
> uses for ≤4 MB docs. In production those two are unchanged at 45/25.

## 3. Fix (shipped) + re-ingest

**Code fix — commit `f68b9c5` (`scripts/preprocess_word_docs.py`):** keep a below-min-size
chunk when it is a real labeled Q&A section (`_is_meaningful_short_section`: header matches a
recognized `_SECONDARY_ANCHORS` / `_PRIMARY_TEXT_SIGNALS`); still discard genuinely headerless
fragments. **Verified additive** — every chunk already ≥150 chars is byte-for-byte unchanged.
Word pipeline only — Excel (`tv-promos`) untouched. Tests in `tests/test_preprocess_chunking.py`.

**Re-ingest — DONE (2026-06-03).** Re-chunked + re-ingested the two large docs (delete-first):
דרמות 174→**262**, ריאליטי 423→**602** (index 667→**934**). Small docs skipped (unchanged).
Two follow-on fixes surfaced during ingest (commit `bbf83c3`):
- **Ingest robustness** — embedding aborted the whole doc on one transient proxy stall (60s,
  no retry), briefly leaving דרמות with 0 chunks. Now 180s timeout + 4-attempt backoff retry.
- **Coverage precision** — even once indexed, פאלו אלטו's short strategy chunk ranked too low to
  be the per-show top-1. Added `fetch_word_docs_per_show(prefer_question_types=...)` to pull each
  show's אסטרטגיה/סלוגן section first for strategy-intent coverage queries.

**Verified end-to-end:** "צטט את האסטרטגיות מכירה של כל הדרמות" now quotes פאלו אלטו's strategy
(strategy phrase present) and covers 12 dramas (was 7). Index search for "מקרה רצח שעלול להבעיר"
returns a chunk; פאלו אלטו has a `question_type='אסטרטגיה'` chunk. ✅

## 4. Action items

### P0
- **Re-ingest the 4 GPT docs** with the fixed chunker (preprocess → ingest, delete-first).
  Expected index growth: דרמות 174→262, בידור 127→197, תוכניות 67→99, ריאליטי 423→602.

### P1
- **M365-MCP catalog-sync** (SharePoint `DocLib4` → `word-docs`) — a *separate* improvement for
  freshness/new docs (the query-time fallback stays score-gated SP enrichment; index = primary).
  Not the fix for this bug, but prevents source/index drift going forward.
- Add an ingestion **completeness check**: after ingest, assert each GPT doc's expected
  question-type sections (אסטרטגיה/שיקול/תובנות) exist per show; fail loudly on gaps.

### Already shipped (branch `fix/genre-contamination-truncation`)
- Genre filter activation, truncation fix, per-show coverage, Coverage Mode prompt, regression
  tests, startup warning. These make the bot as good as the *current index* allows; the
  re-ingest unlocks the rest.

## 5. Note on the M365 MCP
The Microsoft 365 MCP (`sharepoint_search` / `read_resource`) is connected and working — it
read the live drama doc and confirmed the source content. It is the most direct tool for both
the re-ingest fix and the ongoing catalog-sync. (A separate Google Drive MCP is also connected
but is unrelated — it holds Amit's working notes, not the promo source docs.)
