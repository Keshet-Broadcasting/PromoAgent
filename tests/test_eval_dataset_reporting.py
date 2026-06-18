from __future__ import annotations

import logging

from tests.eval_dataset import CaseResult, _fmt_pct, print_summary


def test_summary_renders_non_applicable_numeric_as_na(caplog):
    """No numeric cases in a slice should print n/a, not -100%."""
    caplog.set_level(logging.INFO)

    results = [
        CaseResult(
            id="63",
            category="strategy",
            query="q1",
            keyword_score=0.59,
            grounded_score=1.0,
            overall=0.773,
        ),
        CaseResult(
            id="64",
            category="factual",
            query="q2",
            keyword_score=0.59,
            grounded_score=1.0,
            overall=0.773,
        ),
    ]

    print_summary(results, use_judge=False)

    output = caplog.text
    assert "Numeric accuracy: n/a" in output
    assert "-100" not in output


def test_fmt_pct_renders_edges():
    assert _fmt_pct(-1) == "n/a"
    assert _fmt_pct(0) == "0.0%"
    assert _fmt_pct(1) == "100.0%"
    assert _fmt_pct(0.125, decimals=0) == "12%"
