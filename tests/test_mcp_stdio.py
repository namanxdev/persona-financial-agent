"""Exercises the four MCP tools through a real stdio subprocess and ClientSession.

Per AGENTS.md/REVIEW_CHECKLIST.md, direct handler calls do not satisfy the Stage 2
gate -- every assertion here goes through a spawned `python -m mcp_server.server`
process talking JSON-RPC over stdio, exactly as the agent does in agent/mcp_client.py.
"""

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "agent_techhome.db"


async def _call(name: str, arguments: dict) -> object:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server", "--database", str(DATABASE)],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(name, arguments)


def _run(name: str, arguments: dict) -> object:
    return asyncio.run(_call(name, arguments))


def test_list_companies_returns_sourced_rows_for_sector() -> None:
    result = _run("list_companies", {"sector": "logistics"})
    assert not result.isError
    rows = result.structuredContent["result"]
    assert {row["ticker"] for row in rows} == {"UPS", "FDX", "XPO", "GXO", "CHRW", "JBHT", "EXPD", "HUBG"}
    for row in rows:
        assert row["source_url"].startswith("https://")
        assert row["as_of_date"]


def test_list_companies_rejects_unknown_sector() -> None:
    result = _run("list_companies", {"sector": "manufacturing"})
    assert result.isError


def test_get_financials_returns_newest_row_with_lineage() -> None:
    connection = sqlite3.connect(DATABASE)
    expected = connection.execute(
        "SELECT value FROM financial_observations WHERE ticker='XPO' AND metric='revenue' ORDER BY as_of_date DESC LIMIT 1"
    ).fetchone()[0]
    connection.close()

    result = _run("get_financials", {"ticker": "XPO", "metrics": ["revenue", "free_cash_flow_ttm"]})
    assert not result.isError
    rows = {row["metric"]: row for row in result.structuredContent["result"]}
    assert rows["revenue"]["value"] == pytest.approx(expected)
    assert rows["revenue"]["source_lineage"][0]["field"] == "revenue"
    assert rows["revenue"]["source_url"].startswith("https://")


def test_get_financials_rejects_unknown_ticker_and_metric() -> None:
    unknown_ticker = _run("get_financials", {"ticker": "NOPE", "metrics": ["revenue"]})
    assert unknown_ticker.isError
    assert "unknown ticker" in unknown_ticker.content[0].text

    unknown_metric = _run("get_financials", {"ticker": "XPO", "metrics": ["not_a_real_metric"]})
    assert unknown_metric.isError
    assert "unknown metric" in unknown_metric.content[0].text


def test_get_financials_omits_metrics_with_no_row_instead_of_fabricating() -> None:
    # EXPD has no liabilities_to_equity coverage; the tool must silently omit it
    # rather than inventing a null placeholder row.
    result = _run("get_financials", {"ticker": "EXPD", "metrics": ["revenue", "liabilities_to_equity"]})
    assert not result.isError
    metrics = {row["metric"] for row in result.structuredContent["result"]}
    assert metrics == {"revenue"}


def test_get_hiring_signals_returns_nonnull_headcount() -> None:
    result = _run("get_hiring_signals", {"ticker": "UPS", "limit": 1})
    assert not result.isError
    rows = result.structuredContent["result"]
    assert len(rows) == 1
    assert rows[0]["value"] is not None
    assert rows[0]["value"] > 0
    assert rows[0]["source_url"].startswith("https://")


def test_get_hiring_signals_rejects_invalid_limit() -> None:
    result = _run("get_hiring_signals", {"ticker": "UPS", "limit": 0})
    assert result.isError


def test_run_sector_screen_ranks_and_reports_exclusions() -> None:
    result = _run("run_sector_screen", {"sector": "logistics", "metric": "liabilities_to_equity", "direction": "desc", "limit": 8})
    assert not result.isError
    payload = result.structuredContent
    values = [row["value"] for row in payload["rows"]]
    assert values == sorted(values, reverse=True)
    ranks = [row["rank"] for row in payload["rows"]]
    assert ranks == list(range(1, len(ranks) + 1))
    included = {row["ticker"] for row in payload["rows"]}
    excluded = {row["ticker"] for row in payload["excluded"]}
    assert included.isdisjoint(excluded)
    all_logistics = {"UPS", "FDX", "XPO", "GXO", "CHRW", "JBHT", "EXPD", "HUBG"}
    assert included | excluded == all_logistics
    for exclusion in payload["excluded"]:
        assert exclusion["source_url"].startswith("https://")
        assert exclusion["as_of_date"]


def test_run_sector_screen_rejects_bad_direction() -> None:
    result = _run("run_sector_screen", {"sector": "logistics", "metric": "revenue", "direction": "sideways", "limit": 5})
    assert result.isError
