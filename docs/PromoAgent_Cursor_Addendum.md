# Cursor Addendum — Critical Findings from Promo Team Feedback
**נספח ל-PromoAgent_Cursor_Handoff.md**  
**תאריך:** 20.05.2026

---

## What Changed: Add This to Your Context Before Starting

After reviewing an actual bot failure on a real promo team query, two critical corrections to the Cursor Handoff are required. Read this before implementing anything.

---

## Finding 1 — SCORE SCALE IS 0–4, NOT 0–1 (fixes threshold)

**From the actual API response (feedback from promo team.md):**
```json
"sources": [
  { "title": "מסמך דרמות GPT.docx",   "score": 2.3168 },
  { "title": "מסמך דרמות GPT.docx",   "score": 2.2453 },
  { "title": "מסמך ריאליטי GPT.docx", "score": 2.2201 },
  { "title": "מסמך ריאליטי GPT.docx", "score": 2.1805 },
  { "title": "מסמך ריאליטי GPT.docx", "score": 2.1362 }
]
```

Azure AI Search semantic reranker scores are on a **0–4 scale**, not 0–1.

**Correction to Cursor Handoff threshold:**

| Handoff said | Correct value |
|-------------|---------------|
| `SP_SCORE_THRESHOLD=0.70` | `SP_SCORE_THRESHOLD=2.5` |
| `top_score < _SP_SCORE_THRESHOLD` triggers SP | Same logic, different value |

**Before writing `_needs_sharepoint_enrichment()`**, verify the exact score scale by reading `app/search_word_docs.py` and checking what field the score comes from. If the score in `word_docs` dicts is `@search.rerankerScore` (0–4), use 2.5 as threshold. If it's a normalized score (0–1), use 0.70.

**Also fix `_confidence()` in service.py:**  
The current function checks `score >= 0.85` → "high", which incorrectly returns "high" for almost all semantic scores (since 2.3 > 0.85). This is a latent bug — but DO NOT fix it in this PR. Note it as a separate issue.

---

## Finding 2 — THE RIGHT SOURCES ARE IN AZURE — THE PROBLEM IS CHUNKING

The failed query was a strategy/synthesis question about a pregnancy storyline in חתונמי. The bot:
- Found the **correct source documents** (`מסמך דרמות GPT.docx`, `מסמך ריאליטי GPT.docx`) ✅
- Gave a **wrong answer** — it recommended using the pregnancy as a promotional element immediately, which is the OPPOSITE of what the documents say ❌

**Root cause:** Fixed-size chunking splits the strategic reasoning across multiple chunks. The model sees:
- Chunk A: tactical points (how to show couples)
- Chunk B: first part of strategy  
- Chunk C: second part of strategy

...but never sees the full connected argument. So it picks up surface-level tactics while missing the core insight ("don't make it a scoop — build 'what happened after'").

**Implication for SP enrichment implementation:**  
SharePoint enrichment will retrieve the *same documents* that are already in Azure word-docs. Adding SP for these queries will NOT fix the answer quality problem. The fix is **Phase 6 — Semantic Chunking**.

**What SP enrichment DOES help with:**
- Queries about shows/seasons NOT YET ingested into Azure (freshness gap)
- Queries where Azure returns zero results (existing fallback, rare)
- Queries about very recent תובנות files that haven't been re-ingested

**What SP enrichment does NOT help with:**
- Quality of answers when source docs are already in Azure but chunked badly
- The pregnancy question above — same content, same chunking problem

**Implication for eval:** Run `python scripts/diagnose_word_docs.py` before enabling SP enrichment. If `מסמך דרמות GPT.docx` and `מסמך ריאליטי GPT.docx` are in the word-docs index with good chunk quality, SP enrichment won't improve quote/strategy eval scores. Phase 6 will.

---

## Finding 3 — BOT GAVE WRONG ANSWER DIRECTION (prompt + chunking problem)

The custom GPT's reference answer says: **do NOT use pregnancy as a promo element — build "what happened after" instead**.

The bot's answer says: **use the pregnancy in promos, in spoiler promos, as a unifying/dividing element** — the literal opposite.

This is not a retrieval failure. It's a context synthesis failure caused by chunking. The model received 5 chunks from 2 documents but couldn't reconstruct the full argument.

**Do NOT attempt to fix this in the SP enrichment PR.** Document it as a known issue for Phase 6.

---

## Updated Implementation Checklist for Cursor

Replace the threshold line in the Cursor Handoff with this:

```python
# IMPORTANT: Azure semantic reranker scores are on 0–4 scale (verified from prod API response)
# 2.5 ≈ "reasonably confident" | 3.0+ = "high confidence"
# Default 2.5 means: trigger SP if top score < 2.5 (i.e., below ~62% of max)
_SP_SCORE_THRESHOLD = float(os.getenv("SP_SCORE_THRESHOLD", "2.5"))
```

And update `.env.example`:
```env
SP_SCORE_THRESHOLD=2.5   # Azure reranker score 0–4; trigger SP enrichment below this value
```

Everything else in the Cursor Handoff remains valid.

---

## What Cursor Should NOT Do in This PR

- Do NOT fix `_confidence()` score calibration — separate issue
- Do NOT attempt to fix the pregnancy question answer quality — that's Phase 6 (chunking)
- Do NOT re-ingest or modify Azure indexes
- Do NOT modify `system_prompt.txt`
