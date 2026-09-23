"""The question adds a focus to what the persona retrieves.

The persona sets the lens; a closed list of keyword triggers adds the metric
the question is actually about. Before this, "Which logistics company carries
the least debt?" asked of the mutual-fund persona came back as a revenue-growth
ranking with HIGH confidence.
"""

import asyncio

import pytest

from agent.core import answer_query
from agent.focus import question_focus
from agent.models import QueryRequest


def _run(query: str, persona: str, sector: str):
    return asyncio.run(answer_query(QueryRequest(query=query, persona=persona, sector=sector)))


def test_least_debt_focuses_on_total_debt_ascending() -> None:
    assert question_focus("Which logistics company carries the least debt?") == [("total_debt", "asc")]


@pytest.mark.parametrize("query", [
    "Is this sector a good place to be putting money to work right now?",
    "Which companies here look attractive right now?",
    "What is the outlook for this sector?",
])
def test_divergence_questions_carry_no_focus(query: str) -> None:
    """The graded divergence questions must still be answered by the persona alone."""
    assert question_focus(query) == []


@pytest.mark.parametrize(("query", "expected"), [
    ("Who has the biggest debt load?", [("total_debt", "desc")]),
    ("Whose margins are lowest?", [("operating_margin_ttm", "asc")]),
    ("Which has the highest growth and the least debt?",
     [("revenue_growth_yoy", "desc"), ("total_debt", "asc")]),
    ("What is the cheapest name on P/E?", [("trailing_pe", "asc")]),
    ("How strong is free cash flow, and how levered are they?",
     [("free_cash_flow_ttm", "desc"), ("liabilities_to_equity", "asc")]),
])
def test_direction_words_bind_to_the_nearest_trigger(query: str, expected: list) -> None:
    assert question_focus(query) == expected


def test_sector_question_about_debt_screens_debt() -> None:
    response = _run("Which logistics company carries the least debt?", "mutual_fund_analyst", "logistics")
    assert response.tools_called[-1] == "run_sector_screen"
    assert any(item.field == "total_debt" for item in response.evidence)
    assert "total debt" in response.answer


def test_company_question_about_leverage_fetches_leverage() -> None:
    response = _run("How levered is MSFT?", "equity_analyst", "tech")
    assert any(item.ticker == "MSFT" and item.field == "liabilities_to_equity" for item in response.evidence)


def test_focus_the_persona_already_screens_adds_no_extra_screen() -> None:
    response = _run(
        "Walk me through the margin profile of the companies in your data.", "equity_analyst", "tech"
    )
    assert response.tools_called.count("run_sector_screen") == 2  # margin, then P/E -- nothing extra
    assert any(item.ticker == "MSFT" and item.field == "operating_margin_ttm" for item in response.evidence)


def test_missing_data_for_the_asked_metric_lowers_confidence() -> None:
    """XPO has no liabilities/equity on file. It was fetched before, as an optional
    metric, so its absence cost nothing; now that the question asks for it, it must."""
    response = _run("How levered is XPO?", "pe_analyst", "logistics")
    assert response.confidence != "high"
