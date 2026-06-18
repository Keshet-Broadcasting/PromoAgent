# Task / Problem Summary

Started P2 after P0/P1 were merged to `main`: generalize campaign-retrospective behavior beyond the two MasterChef VIP cases.

# Root Cause

The P0/P1 work fixed specific MasterChef naming and promo-usage phrasing, but broader campaign-role questions still routed to `unknown`. Examples:
- "מה היה התפקיד של הזוגות בקמפיין ההשקה של המירוץ למיליון?"
- "איזה תפקיד שיחק יובל שמלא בקמפיין של נינג'ה ישראל?"
- "האם להראות את הזוגות ולדבר עליהם בקמפיין המירוץ למיליון? האם זה עבד?"

After routing was fixed, case `25` showed a second quality issue: hybrid answers could still over-index on Excel evidence and miss the strategic verdict. The answer needed to distinguish initial curiosity / opening signal from deeper campaign impact.

A later Langfuse check on the original MasterChef VIP pair showed that the naming answer improved, but the dishes/promos follow-up could still overstate "מנות" as a campaign anchor and could retrieve generic MasterChef rows when the query relied on "העונה הזו" or VIP context.

# What Went Well

The existing P0/P1 architecture made the P2 change small: add broader campaign-role/effectiveness route patterns, then add prompt guards for Word and hybrid answers.

# What Went Poorly

The first live eval for case `25` routed correctly but scored only judge 3/5 because the generated answer reported performance evidence without capturing the gold nuance: exposure of couples worked for initial curiosity, but not as a complete depth/retention strategy.

Documentation lagged behind the final PR-review hardening commits. The session insight was created for the main P2 behavior change, but it did not immediately capture the later review follow-ups around prompt-history sanitization and extra regression coverage.

The Excel diagnosis was initially confusing because one shell check passed Hebrew through PowerShell incorrectly. A UTF-safe rerun showed the current index does contain `מאסטר שף` rows with `season="11 VIP"`, while the older JSON conversion path could collapse VIP suffixes to plain numeric seasons.

# How It Was Solved

- Added broader route patterns for campaign-role phrasing such as `תפקיד...בקמפיין`, `בקמפיין...תפקיד`, `תפקיד שיחק`, and `קמפיין ההשקה`.
- Added hybrid force patterns for campaign-effectiveness phrasing such as `האם זה עבד` and `הוכיח את עצמו`.
- Extended the Word-route prompt guard so role questions distinguish "mentioned/used" from "central campaign anchor".
- Extended the hybrid prompt so effectiveness questions open with a verdict: worked / partially worked / did not work, then separate initial curiosity from depth / retention / strategic role.
- Added PR-review hardening coverage for ambiguous campaign queries, unrelated queries, Hebrew UTF-8 prompt roundtrip, and ordered effectiveness-prompt structure.
- Hardened `build_messages()` history handling: malformed turns are skipped, only `user` / `assistant` roles are preserved, control characters are stripped, and prior-turn content remains capped.
- Tightened prompt-history hardening after a follow-up review: non-string history content is skipped instead of stringified, and the Hebrew prompt test now checks that bidi override controls are not introduced.
- Added final PR-review edge coverage: non-string history roles are skipped, truncated history must end with an ellipsis, and mixed Hebrew/English campaign-role phrasing still routes to campaign analysis.
- Added `logging.debug` statements to `_safe_history_turn` for each skip path, and tightened return type to `dict[str, str] | None`.
- Tightened the hybrid campaign-role prompt so dishes/food should not be described as `עוגן מרכזי`, `עוגן מיתוגי`, or `עוגן תוכני` unless the Word documents explicitly support that. The default phrasing is now "היו מנות, אבל לא כעוגן המיתוג הראשי; הן שימשו כהוכחת רמה/חומר שוטף/טונייטים/גמר".
- Updated hybrid retrieval for explicit/contextualized VIP campaign promo questions: instead of semantic Excel top-N, the service now performs an exact show fetch for `מאסטר שף`, then narrows to populated VIP-season rows. A narrow fallback maps `נבחרת החלומות` to season `11` for legacy indexes that lost the `VIP` suffix.
- Fixed the Excel-to-JSON conversion helper so future ingestion preserves `מאסטר שף עונה 11 VIP` as `season="11 VIP"` instead of collapsing it to `11`.
- Fixed the Azure pipeline failure by adding `pandas` to `requirements.txt`; `scripts/convert_excel_to_json.py` imports pandas and tests import that script, so the dependency must be installed in CI.

# Tradeoffs Or Alternatives Considered

Could have added only dataset cases and waited for more failures, but the routing probe already showed real unknown-route misses on existing campaign language. The chosen change is still narrow: it targets campaign role/effectiveness phrasing without changing numeric lookup behavior.

# Tests Added Or Updated

- `tests/test_retrieval_planning.py::test_campaign_role_phrasing_routes_to_campaign_analysis`
- `tests/test_retrieval_planning.py::test_word_prompt_guards_campaign_role_overstatement`
- `tests/test_retrieval_planning.py::test_hybrid_prompt_shapes_campaign_effectiveness_answers`
- `tests/test_retrieval_planning.py::test_campaign_prompt_preserves_hebrew_utf8_roundtrip`
- `tests/test_retrieval_planning.py::test_build_messages_bounds_and_sanitizes_history`
- `tests/test_retrieval_planning.py::test_hybrid_vip_campaign_query_fetches_vip_excel_rows`
- `tests/test_retrieval_planning.py::test_hybrid_vip_campaign_query_handles_legacy_non_vip_season_metadata`
- `tests/test_retrieval_planning.py::test_excel_json_conversion_preserves_masterchef_vip_season_suffix`
- `tests/test_retrieval_planning.py::test_excel_json_conversion_dependencies_are_declared`

# Verification

- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 27 passed
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 28 passed after PR-review routing/prompt coverage
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 29 passed after prompt-history sanitization
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 29 passed after non-string history and bidi-control coverage
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 29 passed after role-type, truncation, and mixed-language routing coverage
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -v` -> 32 passed after MasterChef VIP prompt/retrieval/ingestion regressions
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -v` -> 33 passed after declaring `pandas`
- Live UTF-safe retrieval check for `היו בפרומואים של מאסטר שף VIP / נבחרת החלומות מנות?` -> exact show fetch, `ranking_show=מאסטר שף`, 11 Excel rows from `season="11 VIP"`
- `ReadLints` on edited files -> no linter errors
- `python tests/eval_dataset.py --judge --only 25` -> judge 5/5, overall 85.4%, groundedness 100%
- `python tests/eval_dataset.py --judge --only 56` -> judge 4/5, groundedness 100%

Note: live eval emitted Langfuse trace-export SSL errors. These affected observability export only; the retrieval, generation, judge scoring, and eval summary completed. Treat as a separate observability/certificate follow-up if clean tracing is required, not as a blocker for this P2 behavior change.

# Lessons Learned

For campaign analysis, retrieval routing and answer shape must move together. A query can retrieve the right Word and Excel context but still answer poorly if the prompt does not force the business distinction between first-signal success and deeper strategic success.

For this repo, docs are part of the change, not an afterthought. When review follow-ups add behavior or hardening tests, the session insight should be updated before the commit/push that contains those changes.

For Excel debugging with Hebrew text on Windows, do not trust inline Hebrew passed through PowerShell unless `PYTHONIOENCODING` and the source string path are UTF-safe. Use Unicode escapes or file-based inputs for live checks.

# Follow-Up Actions

- Run a broader eval slice after the P2 branch is stable, especially campaign/strategy cases `11`, `12`, `25`, `28`, `41`, `56`, `63`, and `64`.
- If more Word-only campaign-role cases appear, consider moving the role/effectiveness guard into a shared campaign-analysis addendum instead of duplicating route-specific instructions.
- Re-run the original two MasterChef VIP questions through the deployed API with real chat history enabled, then inspect Langfuse to verify the second answer says dishes were not the main branding anchor.
