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
        "Azure AI Search, Azure OpenAI, Azure Container Apps."
    )

    user = f"""Review this pull request. Focus on:

### Python / FastAPI (app/)
- **Security**: JWT/Entra ID auth logic, rate limiting bypasses, prompt injection
- **Secrets**: API keys or tokens hardcoded anywhere (even in comments)
- **Error handling**: Unhandled exceptions, Azure SDK errors leaking to users
- **Hebrew text**: Encoding issues, RTL edge cases in string operations
- **Async**: Missing `await`, sync calls that should be async, N+1 against Azure AI Search
- **Types**: Missing type hints, incorrect return types

### Next.js / TypeScript (promobot-ui/)
- **Type safety**: `any` types, missing null checks
- **Security**: XSS risks, auth tokens in localStorage vs httpOnly cookies
- **Hebrew/RTL**: Missing `dir="rtl"`, hardcoded LTR styles
- **Error states**: Missing loading/error handling around API calls

### Tests (tests/)
- Missing coverage for new code paths
- Empty assertions (`assert True`)
- Changes that could corrupt the 54 gold-standard eval cases

### Infrastructure (Dockerfile, azure-pipelines.yml)
- Secrets in env var definitions
- Missing health checks or resource limits

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
3. **Issues found** — for each issue: severity (🔴 Critical / 🟠 Important / 🟡 Suggestion), file+line reference, problem, and fix
4. **What looks good** section
5. Footer: *— PromoAgent CR Agent (gpt-4o)*

Skip pure formatting/whitespace issues. Only review changed lines."""

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
