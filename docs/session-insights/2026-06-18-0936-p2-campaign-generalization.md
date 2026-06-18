# Task / Problem Summary

Started P2 after P0/P1 were merged to `main`: generalize campaign-retrospective behavior beyond the two MasterChef VIP cases.

# Root Cause

The P0/P1 work fixed specific MasterChef naming and promo-usage phrasing, but broader campaign-role questions still routed to `unknown`. Examples:
- "מה היה התפקיד של הזוגות בקמפיין ההשקה של המירוץ למיליון?"
- "איזה תפקיד שיחק יובל שמלא בקמפיין של נינג'ה ישראל?"
- "האם להראות את הזוגות ולדבר עליהם בקמפיין המירוץ למיליון? האם זה עבד?"

After routing was fixed, case `25` showed a second quality issue: hybrid answers could still over-index on Excel evidence and miss the strategic verdict. The answer needed to distinguish initial curiosity / opening signal from deeper campaign impact.

# What Went Well

The existing P0/P1 architecture made the P2 change small: add broader campaign-role/effectiveness route patterns, then add prompt guards for Word and hybrid answers.

# What Went Poorly

The first live eval for case `25` routed correctly but scored only judge 3/5 because the generated answer reported performance evidence without capturing the gold nuance: exposure of couples worked for initial curiosity, but not as a complete depth/retention strategy.

Documentation lagged behind the final PR-review hardening commits. The session insight was created for the main P2 behavior change, but it did not immediately capture the later review follow-ups around prompt-history sanitization and extra regression coverage.

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

# Tradeoffs Or Alternatives Considered

Could have added only dataset cases and waited for more failures, but the routing probe already showed real unknown-route misses on existing campaign language. The chosen change is still narrow: it targets campaign role/effectiveness phrasing without changing numeric lookup behavior.

# Tests Added Or Updated

- `tests/test_retrieval_planning.py::test_campaign_role_phrasing_routes_to_campaign_analysis`
- `tests/test_retrieval_planning.py::test_word_prompt_guards_campaign_role_overstatement`
- `tests/test_retrieval_planning.py::test_hybrid_prompt_shapes_campaign_effectiveness_answers`
- `tests/test_retrieval_planning.py::test_campaign_prompt_preserves_hebrew_utf8_roundtrip`
- `tests/test_retrieval_planning.py::test_build_messages_bounds_and_sanitizes_history`

# Verification

- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 27 passed
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 28 passed after PR-review routing/prompt coverage
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 29 passed after prompt-history sanitization
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 29 passed after non-string history and bidi-control coverage
- `python -m pytest tests/test_retrieval_planning.py tests/test_eval_dataset_reporting.py -q` -> 29 passed after role-type, truncation, and mixed-language routing coverage
- `ReadLints` on edited files -> no linter errors
- `python tests/eval_dataset.py --judge --only 25` -> judge 5/5, overall 85.4%, groundedness 100%
- `python tests/eval_dataset.py --judge --only 56` -> judge 4/5, groundedness 100%

Note: live eval emitted Langfuse trace-export SSL errors. These affected observability export only; the retrieval, generation, judge scoring, and eval summary completed. Treat as a separate observability/certificate follow-up if clean tracing is required, not as a blocker for this P2 behavior change.

# Lessons Learned

For campaign analysis, retrieval routing and answer shape must move together. A query can retrieve the right Word and Excel context but still answer poorly if the prompt does not force the business distinction between first-signal success and deeper strategic success.

For this repo, docs are part of the change, not an afterthought. When review follow-ups add behavior or hardening tests, the session insight should be updated before the commit/push that contains those changes.

# Follow-Up Actions

- Run a broader eval slice after the P2 branch is stable, especially campaign/strategy cases `11`, `12`, `25`, `28`, `41`, `56`, `63`, and `64`.
- If more Word-only campaign-role cases appear, consider moving the role/effectiveness guard into a shared campaign-analysis addendum instead of duplicating route-specific instructions.
