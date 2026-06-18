#!/usr/bin/env python3
"""
PromoAgent Code Review — uses Azure OpenAI (gpt-4o) to review PRs
and posts a single review comment via the GitHub CLI.
"""

import os
import subprocess
import sys


def run(cmd: list[str], check: bool = True) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def get_diff() -> tuple[str, str]:
    base = os.environ.get("BASE_REF", "main")
    files = run(["git", "diff", "--name-only", f"origin/{base}...HEAD"])
    diff = run(["git", "diff", f"origin/{base}...HEAD"])
    # Truncate to ~60k chars to stay within context limits
    if len(diff) > 60_000:
        diff = diff[:60_000] + "\n\n[... diff truncated — showing first 60k chars only ...]"
    return files, diff


def call_azure_openai(files: str, diff: str) -> str:
    from openai import OpenAI

    client = OpenAI(
        base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_KEY"],
    )

    system = (
        "You are a senior code reviewer for the PromoAgent project — "
        "a Hebrew-language RAG system for Keshet's Promo department. "
        "The stack: Python/FastAPI backend, Next.js/TypeScript frontend, "
        "Azure AI Search, Azure OpenAI, Azure Container Apps.\n\n"
        "## Architecture facts — read before reviewing\n\n"
        "1. **Auth is handled exclusively by FastAPI middleware in `app/api.py`** (Entra ID / JWT). "
        "Individual service functions like `classify()`, `build_messages()`, or `_retrieve()` are "
        "internal helpers called only AFTER middleware has already validated the request. "
        "Do NOT flag these functions for missing JWT checks.\n\n"
        "2. **`app/query_router.py` does NOT call Azure AI Search or OpenAI.** "
        "It is a pure in-process regex classifier. Do NOT flag it for missing Azure SDK error handling.\n\n"
        "3. **Hebrew has no upper/lowercase.** `re.IGNORECASE` has no effect on Hebrew-only patterns. "
        "Do NOT suggest adding this flag to patterns that contain only Hebrew characters.\n\n"
        "4. **Routing is NOT a prompt injection surface.** `classify()` matches user input against "
        "regex patterns to decide which search index to query. The user's raw text is never "
        "concatenated into the regex patterns. Only flag actual prompt injection where user input "
        "is embedded into an LLM prompt string without sanitization.\n\n"
        "5. **`azure-pipelines.yml` secrets are correctly managed.** "
        "All secret values use `$(VAR-NAME)` syntax, which is resolved at runtime from Azure Key Vault "
        "via linked variable groups (`kst-ai-shared`, `kst-ai-stage`, `kst-ai-prod`). "
        "This is the correct Azure DevOps pattern. Do NOT flag these as hardcoded secrets.\n\n"
        "6. **`.env` is gitignored.** `.env.example` contains only placeholder values "
        "(`<your-key>`, `sk-lf-...`). Neither file exposes real secrets.\n\n"
        "Only raise an issue if it represents a REAL risk given these facts."
    )

    user = f"""Review this pull request. Focus on actual issues, not checklist pattern-matching.

### Python / FastAPI (app/)
- **Secrets**: Real API keys or tokens hardcoded in source (not `$(VAR)` references or `<placeholder>` values)
- **Prompt injection**: User input embedded in LLM prompts without sanitization (NOT regex classification)
- **Error handling**: Unhandled exceptions where errors would leak internal details to end users
- **Hebrew text**: Actual encoding bugs, incorrect byte-level operations on Hebrew strings
- **Async correctness**: Missing `await` on async functions, sync blocking calls in async context
- **Type safety**: Missing type hints on public functions, provably incorrect return types

### Next.js / TypeScript (promobot-ui/)
- **Type safety**: `any` types, missing null checks on API responses
- **Security**: User-controlled input rendered without sanitization (XSS), auth tokens in localStorage
- **Hebrew/RTL**: Missing `dir="rtl"` on text containers, hardcoded LTR styles breaking Hebrew UI
- **Error states**: No loading/error handling on fetch calls

### Tests (tests/)
- New code paths with zero test coverage
- Assertions that can never fail (`assert True`, tautologies)
- Changes that could overwrite or corrupt the gold-standard eval dataset

### Infrastructure (Dockerfile, azure-pipelines.yml)
- Real secrets hardcoded (not `$(VAR)` Key Vault references)
- Missing HEALTHCHECK when the service exposes a /health endpoint

## Changed files
{files}

## Diff
```
{diff}
```

## Output format
Write a structured review with:
1. **Overall verdict**: ✅ Approved / 🟠 Needs minor changes / 🔴 Needs major changes
2. **Summary** (2–3 sentences)
3. **Issues found** — for each issue: severity (🔴 Critical / 🟠 Important / 🟡 Suggestion), file+line, problem, and concrete fix
4. **What looks good** section
5. Footer: *— PromoAgent CR Agent (gpt-4o)*

Skip pure formatting/whitespace issues. Only review changed lines. If there are no real issues, output ✅ Approved."""

    response = client.chat.completions.create(
        model=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-1"),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=4096,
        temperature=0.2,
    )
    return response.choices[0].message.content


def post_review(body: str) -> None:
    pr_number = os.environ.get("PR_NUMBER", "")
    if not pr_number:
        print("No PR_NUMBER — cannot post review", file=sys.stderr)
        sys.exit(1)
    run(["gh", "pr", "review", pr_number, "--comment", "--body", body])
    print(f"✅ Review posted on PR #{pr_number}")


def main() -> None:
    files, diff = get_diff()
    if not diff:
        print("No diff detected — skipping review.")
        return

    print(f"Reviewing {len(diff)} chars of diff across:\n{files}\n")
    review = call_azure_openai(files, diff)
    print("Review generated. Posting to PR...")
    post_review(review)


if __name__ == "__main__":
    main()
