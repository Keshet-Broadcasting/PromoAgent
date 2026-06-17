# Task / Problem Summary

Compared two MasterChef VIP / "נבחרת החלומות" answers from PromoAgent and a Custom GPT, using Gemini's critique, to identify where the quality gap comes from.

# Root Cause

The gap is not only tone. The two sample questions route as `unknown`, so the service uses shallow top-3 retrieval from Excel and Word instead of the richer `word_quote` / `hybrid` / Strategic Synthesis paths. This makes the answer depend on whichever chunks surface first.

Additional contributors:
- The user wrote "אולסטרס" while relevant source wording may appear as "אולסטארס", creating a spelling/normalization retrieval miss.
- The first PromoAgent answer retrieved one strong chunk but missed later campaign-evolution evidence: "נבחרת החלומות לא תפס" and the shift back to "מאסטר שף".
- The second question uses anaphora ("העונה הזו"), so the answer quality depends on preserving the prior subject. PromoAgent answered as a broad MasterChef season lookup, while the Custom GPT kept the specific "נבחרת החלומות" campaign frame.
- Prompt and tests strongly reward source citation, chunk IDs, and groundedness. That protects trust but biases the visible answer toward evidence reporting unless strategic mode is explicitly triggered.

# What Went Well

PromoAgent gave precise citations, file names, chunk references, dates, and explicit caveats. It avoided inventing a difference from "אולסטרס" when that term was not in its retrieved context.

# What Went Poorly

The agent did not reconstruct the full campaign arc from naming, research wording, mid-season retreat, and final branding. It also treated the dishes question as "were there any dishes anywhere" instead of "what role did dishes play in this specific campaign over time".

# How It Was Solved

Implemented a narrow P0/P1 fix on branch `fix/campaign-retrospective-routing`.

P0 — route real campaign phrasing correctly:
- Added route patterns so campaign naming questions route to `word_quote`.
- Added promo-usage patterns such as "היו בפרומואים" / "פרומואים...מנות" so they route to `hybrid`.
- Added query-term normalization for "אולסטרס" -> "אולסטארס" and "מאסטרשף" -> "מאסטר שף".

P1 — preserve follow-up context for retrieval:
- Added retrieval-only contextualization for follow-up phrasing like "העונה הזו", appending recent show/campaign context from conversation history while leaving the user-facing question unchanged.

Eval/data follow-up:
- Added dataset cases `63` and `64` to `dataset.jsonl` for the two MasterChef VIP questions.
- Fixed eval reporting so non-applicable numeric metrics print `n/a` instead of `-100%`.

Quality follow-up for case `64`:
- Added a narrow hybrid-prompt guard for campaign-role questions.
- The prompt now forces the answer to distinguish between an element merely appearing in promos and being the main launch-branding anchor.
- It also requires comparing launch branding against ongoing / tonight / finale / proof-of-level usage before concluding.

# Tradeoffs Or Alternatives Considered

Keeping strict grounding is valuable and should not be removed. The better fix is to route these campaign-why / campaign-usage questions into a richer Word or hybrid analysis path, while preserving inline citations.

# Tests Added Or Updated

Added offline regression tests in `tests/test_retrieval_planning.py`:
- `test_campaign_retrospective_phrasing_routes_out_of_unknown`
- `test_campaign_term_normalization_covers_allstars_variant`
- `test_followup_retrieval_query_uses_recent_campaign_context`

Added eval-reporting regression test:
- `tests/test_eval_dataset_reporting.py::test_summary_renders_non_applicable_numeric_as_na`

Added prompt-quality regression test:
- `tests/test_retrieval_planning.py::test_hybrid_prompt_guards_against_campaign_role_overstatement`

Added dataset cases:
- `63` — MasterChef VIP naming / "נבחרת החלומות" vs "אולסטארס"
- `64` — dishes in MasterChef VIP / "נבחרת החלומות" promos

Verified:
- `python -m pytest tests/test_retrieval_planning.py -q` -> 18 passed
- `python tests/test_agent.py` -> 33/33 passed
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 19 passed
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 20 passed
- `python tests/eval_dataset.py --rejudge --only 63,64` -> overall 64.4%, groundedness 100%, numeric n/a
- `python tests/eval_dataset.py --judge --only 64` -> judge 5/5, overall 88.1%, groundedness 100%, numeric n/a
- `ReadLints` on edited files -> no linter errors

Targeted eval result:
- Case `63`: judge 4/5. The answer captured the naming logic and de-emphasis of "נבחרת החלומות" in favor of the main "מאסטר שף" brand.
- Case `64`: judge 2/5. Retrieval/routing worked, but generation over-interpreted the evidence and said dishes were the central campaign anchor. Gold says the opposite nuance: dishes existed, but mainly as secondary proof / ongoing promo material rather than the launch-branding anchor.
- After the prompt follow-up, case `64` improved to judge 5/5. The answer now says dishes appeared, but frames their role as proof of culinary level / competition and separates that from the campaign's main launch branding.

# Lessons Learned

For this product, "why did we call it X", "why not Y", "did we use Z in promos", and Hebrew anaphora like "העונה הזו" are not generic unknown questions. They are campaign-analysis questions and need deeper Word retrieval plus synthesis.

# Follow-Up Actions

- P0/P1 are complete mechanically, and the immediate case `64` quality follow-up is fixed in the prompt layer.
- Consider a strategic answer shape for single-campaign retrospectives: thesis first, campaign arc second, citations inline.
- Consider extending this pattern beyond hybrid questions if future Word-only campaign-role questions show the same overstatement behavior.
