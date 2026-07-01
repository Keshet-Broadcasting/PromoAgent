# Prompt Cache Misses And Partial-Coverage Wording

## Task / Problem Summary

Investigate repeated Langfuse traces where the same long PromoBot question reported `input_cached_tokens=0`, then fix prompt-cache routing. Also explain why an answer said "המידע שנשלף חלקי" for a broad drama-ranking query.

## Root Cause

Prompt caching was supported by the provider, but current production relied on opportunistic routing only. A historical trace showed `input_cached_tokens=9472`; repeated current traces with the newer prompt hash showed `0`. The provider calls did not send `prompt_cache_key` or retention hints.

The "חלקי" wording came from prompt/context pressure: the base prompt had a fixed partial-coverage phrase, and broad retrieval context said to mark the answer partial if a requested show/season was missing. The model applied that too broadly whenever it saw a broad retrieval pack.

## What Went Well

- Langfuse observation-level usage made the cache miss measurable.
- Comparing system prompt hashes separated provider capability from current prompt/version behavior.
- The fix stayed small and local to provider kwargs plus prompt wording.

## What Went Poorly

- The first Langfuse URL pointed to the agent span, not the generation child, which initially hid the real token details.
- The old wording conflated broad retrieval with partial retrieval.

## How It Was Solved

- Added explicit `prompt_cache_key` and `prompt_cache_retention` payloads to Azure/OpenAI-compatible chat completion calls.
- Made cache behavior configurable through `PROMPT_CACHE_ENABLED`, `PROMPT_CACHE_KEY`, and `PROMPT_CACHE_RETENTION`.
- Reworded partial-coverage instructions so the model states a limit only when missing requested coverage is explicit.

## Tradeoffs Or Alternatives Considered

- Route-specific prompt splitting would reduce total prompt size, but it is a larger behavior change and should be measured separately.
- Leaving caching automatic was rejected because repeated current traces showed no cache hits.

## Tests Added Or Updated

- `tests/test_chat_provider_params.py`: prompt-cache kwargs default, disable, and override behavior.
- `tests/test_retrieval_planning.py`: broad retrieval context no longer forces a partial disclaimer.

## Lessons Learned

- Langfuse `usage.input` can include cached tokens; `usageDetails.input_cached_tokens` is the cache-hit signal.
- Prompt-cache hit rate is operational, not guaranteed by prompt length alone.
- Broad evidence-pack metadata should report coverage facts without telling the model the conclusion.

## Follow-Up Actions

- After deployment, repeat the current production question and verify `input_cached_tokens > 0`.
- Consider route-specific prompt assembly if input cost remains high after cache routing is stable.
