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
4. **Extraction gap (ROOT)** — פאלו אלטו's strategy section **exists in the source doc but is
   missing from the Azure word-docs index**, because the >4 MB ingestion fallback drops it.
   **Not fixable in retrieval/prompt code — requires re-ingestion.**

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

## 2. Root cause

- `preprocess_word_docs.py` routes files **>4 MB to a python-docx/XML fallback**
  (`extract_chunks_docx` → `split_semantic` over `_to_para_stream_docx`). `מסמך דרמות GPT.docx`
  is **~25.5 MB**; `מסמך ריאליטי GPT.docx` is **~36.3 MB** — both take this path.
- That fallback extracts MOST content (178 chunks) but **drops this section's content**. The
  exact XML structure it misses (text box / shape / a specific table layout) is not yet
  pinned down, but Microsoft Graph extracts the same section correctly — so it IS extractable.
- Corroboration (Amit's Drive note "index with claude"): these two large docs previously hit
  the **16 MB Basic-tier limit** and were indexed **metadata-only** at one point. Large-doc
  handling for these two files has been fragile throughout.

**Impact:** likely affects **multiple shows' strategy sections** across both large docs
(the index had only ~6 `אסטרטגיה` chunks across 17 dramas) — silently capping answer quality
on exactly the strategic/quote questions the promo team cares about most.

## 3. Fix options (data layer)

1. **Re-ingest via the M365 MCP / Graph extraction** (recommended). Graph already extracts the
   content the repo fallback misses. Pull the doc text via the MCP, chunk, and upload to the
   `word-docs` index. This also directly serves the goal of **surfacing documents not yet in
   the index** (new/updated docs) — i.e. a SharePoint→index catalog-sync built on the MCP.
2. **Fix `extract_chunks_docx`** to capture the missing structure (e.g. `w:txbxContent` text
   boxes / shapes), then re-ingest `מסמך דרמות GPT.docx` and `מסמך ריאליטי GPT.docx`.
3. Either way: **re-ingest must be delete-first** for the affected doc (data-invariant), and
   verify the פאלו אלטו `question_type='אסטרטגיה'` chunk lands afterward.

## 4. Action items

### P0
- Re-ingest the two large GPT docs so their full content (incl. all strategy sections) is in
  the index. Verify with: index search for "מקרה רצח שעלול להבעיר" returns a chunk; פאלו אלטו
  has a `question_type='אסטרטגיה'` chunk.

### P1
- Stand up the **M365-MCP catalog-sync** (SharePoint `DocLib4` → `word-docs`) so new/updated
  docs are picked up automatically — closes the "documents not in the index" gap and prevents
  the source/index drift that produced this bug.
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
