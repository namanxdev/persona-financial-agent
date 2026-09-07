"""Eval case definitions.

Every expected value is read fresh from the committed database at run time --
never a hardcoded constant -- so the eval keeps working after a DB rebuild
changes a yfinance-sourced snapshot. Every case calls answer_query, which
opens a real stdio MCP session against mcp_server; nothing here monkeypatches
a tool handler or reads the database as a substitute for agent retrieval.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from agent.core import answer_query
from agent.models import PersonaName, QueryRequest, Sector

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "agent_techhome.db"


@dataclass
class EvalResult:
    name: str
    passed: bool
    detail: str


def _latest_financial(ticker: str, metric: str) -> float | None:
    connection = sqlite3.connect(DATABASE)
    try:
        row = connection.execute(
            "SELECT value FROM financial_observations WHERE ticker=? AND metric=? ORDER BY as_of_date DESC, id DESC LIMIT 1",
            (ticker, metric),
        ).fetchone()
        return row[0] if row else None
    finally:
        connection.close()


def _latest_hiring(ticker: str) -> float | None:
    connection = sqlite3.connect(DATABASE)
    try:
        row = connection.execute(
            "SELECT value FROM hiring_signals WHERE ticker=? ORDER BY observed_on DESC, id DESC LIMIT 1", (ticker,)
        ).fetchone()
        return row[0] if row else None
    finally:
        connection.close()


async def _divergence_case(name: str, query: str, sector: Sector) -> EvalResult:
    personas: tuple[PersonaName, ...] = ("mutual_fund_analyst", "equity_analyst", "pe_analyst")
    responses = {p: await answer_query(QueryRequest(query=query, persona=p, sector=sector)) for p in personas}
    sequences = {p: r.tools_called for p, r in responses.items()}
    company_sets = {p: set(r.companies_referenced) for p, r in responses.items()}
    pairs = [(personas[i], personas[j]) for i in range(3) for j in range(i + 1, 3)]
    seq_diffs = all(sequences[a] != sequences[b] for a, b in pairs)
    set_diffs = all(company_sets[a] != company_sets[b] for a, b in pairs)
    have_evidence = all(r.evidence for r in responses.values())
    passed = seq_diffs and set_diffs and have_evidence
    detail = (
        f"sequences_differ={seq_diffs} sets_differ={set_diffs} all_have_evidence={have_evidence} | "
        + " | ".join(f"{p}: tools={sequences[p]} companies={sorted(company_sets[p])}" for p in personas)
    )
    return EvalResult(name, passed, detail)


async def _grounding_value_case(
    name: str, query: str, persona: PersonaName, sector: Sector, ticker: str, field: str, expected: float | None
) -> EvalResult:
    if expected is None:
        return EvalResult(name, False, f"no ground-truth {field} for {ticker} in the DB -- fix the case, not the assertion")
    response = await answer_query(QueryRequest(query=query, persona=persona, sector=sector))
    matches = [item for item in response.evidence if item.ticker == ticker and item.field == field]
    if not matches:
        return EvalResult(name, False, f"no evidence item for {ticker}/{field}; evidence={[e.evidence_id for e in response.evidence]}")
    passed = matches[0].value == expected
    return EvalResult(name, passed, f"expected {ticker}.{field}={expected}, got {matches[0].value}")


async def _refusal_case(name: str, query: str, persona: PersonaName, sector: Sector, must_mention: str) -> EvalResult:
    response = await answer_query(QueryRequest(query=query, persona=persona, sector=sector))
    passed = response.confidence == "low" and not response.evidence and must_mention in response.answer
    detail = f"confidence={response.confidence} evidence={response.evidence} answer={response.answer!r}"
    return EvalResult(name, passed, detail)


def build_cases() -> list[tuple[str, Callable[[], Awaitable[EvalResult]]]]:
    return [
        ("divergence_tech_investment_case", lambda: _divergence_case(
            "divergence_tech_investment_case",
            "Is this sector a good place to be putting money to work right now?", "tech",
        )),
        ("divergence_retail_attractive_case", lambda: _divergence_case(
            "divergence_retail_attractive_case", "Which companies here look attractive right now?", "retail",
        )),
        ("divergence_logistics_outlook_case", lambda: _divergence_case(
            "divergence_logistics_outlook_case", "What is the outlook for this sector?", "logistics",
        )),
        ("grounding_ups_headcount", lambda: _grounding_value_case(
            "grounding_ups_headcount",
            "What's the most recent headcount or hiring signal you have for UPS?",
            "pe_analyst", "logistics", "UPS", "headcount", _latest_hiring("UPS"),
        )),
        ("grounding_msft_operating_margin", lambda: _grounding_value_case(
            "grounding_msft_operating_margin",
            "Walk me through the margin profile of the companies in your data.",
            "equity_analyst", "tech", "MSFT", "operating_margin_ttm", _latest_financial("MSFT", "operating_margin_ttm"),
        )),
        ("grounding_cost_revenue_growth", lambda: _grounding_value_case(
            "grounding_cost_revenue_growth",
            "Which of these companies would fit a long-term core holding versus a name I should avoid?",
            "mutual_fund_analyst", "retail", "COST", "revenue_growth_yoy", _latest_financial("COST", "revenue_growth_yoy"),
        )),
        ("refusal_unknown_ticker_style", lambda: _refusal_case(
            "refusal_unknown_ticker_style", "What do you think about RIVN?", "pe_analyst", "logistics", "RIVN",
        )),
        ("refusal_unknown_mixed_case_name", lambda: _refusal_case(
            "refusal_unknown_mixed_case_name", "What do you think about Snowflake?", "equity_analyst", "tech", "Snowflake",
        )),
    ]
