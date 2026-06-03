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

**Conclusion:** the source HAS the text (Graph extracts it; the docs-Claude quoted it
verbatim), but the repo's preprocessing does NOT extract it → it never reaches the index.

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

**Scale of the loss (measured per doc, pre-fix):**

| Doc | chunks kept (≥150) | dropped <150 | of dropped: **real headed sections** |
|---|---|---|---|
| דרמות | 174 | 103 | **88** |
| בידור | 127 | 85 | **70** |
| תוכניות נוספות | 67 | 41 | **32** |
| ריאליטי | 423 | ~? | **179** |

→ **~369 real labeled Q&A sections** silently dropped across the four docs (the index had only
~6 `אסטרטגיה` chunks across 17 dramas for exactly this reason). The >4 MB python-docx fallback
and the historical 16 MB Basic-tier metadata-only episode are real context but are **not** the
cause here — the content was extracted fine; the size guardrail discarded it.

## 3. Fix (shipped) + re-ingest

**Code fix — commit `f68b9c5` (`scripts/preprocess_word_docs.py`):** keep a below-min-size
chunk when it is a real labeled Q&A section (`_is_meaningful_short_section`: header matches a
recognized `_SECONDARY_ANCHORS` / `_PRIMARY_TEXT_SIGNALS`); still discard genuinely headerless
fragments. **Verified additive** — every chunk already ≥150 chars is byte-for-byte unchanged
(174/127/67/423 preserved exactly); only the ~369 headed short sections are recovered, and
פאלו אלטו's strategy is now present. Word pipeline only — Excel (`tv-promos`) untouched.
Regression tests in `tests/test_preprocess_chunking.py`.

**Required next: re-ingest** the 4 GPT docs (delete-first per doc, data-invariant) so the index
picks up the recovered chunks. Verify after: index search for "מקרה רצח שעלול להבעיר" returns a
chunk and פאלו אלטו has a `question_type='אסטרטגיה'` chunk.

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
