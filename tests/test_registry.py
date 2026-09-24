"""Registry fixtures cover company matching without a server subprocess."""

import json
import sqlite3
from pathlib import Path

import pytest

from mcp_server.registry import ListedRegistry, normalize_name
from scripts.build_registry import validate_snapshot

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "listed_companies.json"
DATABASE = ROOT / "data" / "agent_techhome.db"


@pytest.fixture(scope="module")
def registry() -> ListedRegistry:
    return ListedRegistry.load(REGISTRY)


@pytest.mark.parametrize(("raw", "expected"), [
    ("Old Dominion Freight Line, Inc.", "old dominion freight line"),
    ("Amazon.com, Inc.", "amazon"),
    ("Snowflake Inc.", "snowflake"),
    ("Rivian Automotive, Inc. / DE", "rivian automotive"),
    ("Match Group, Inc.", "match group"),
])
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


@pytest.mark.parametrize("ticker", ["ODFL", "RIVN", "NVDA"])
def test_ticker_hits(registry: ListedRegistry, ticker: str) -> None:
    hits = registry.lookup([], [ticker])
    assert hits and hits[0].ticker == ticker
    assert hits[0].match_kind == "ticker"
    assert hits[0].source_url and hits[0].as_of_date


@pytest.mark.parametrize("name", ["Old Dominion", "Snowflake", "Nvidia", "Amazon", "Rivian"])
def test_name_hits(registry: ListedRegistry, name: str) -> None:
    hits = registry.lookup([name], [])
    assert hits and hits[0].match_kind == "name"


def test_name_hit_reports_exact_vs_partial(registry: ListedRegistry) -> None:
    assert registry.lookup(["Old Dominion Freight Line"], [])[0].name_match == "exact"
    assert registry.lookup(["Old Dominion"], [])[0].name_match == "prefix"
    assert registry.lookup(["Carrier"], [])[0].name_match == "first_word"
    assert len({hit.ticker for hit in registry.lookup(["United States"], [])}) > 1


@pytest.mark.parametrize("name", ["Free Cash Flow", "Operating Margin", "Net Debt"])
def test_finance_phrases_miss(registry: ListedRegistry, name: str) -> None:
    assert registry.lookup([name], []) == []


@pytest.mark.parametrize("ticker", ["OTR", "DAT", "ZQX"])
def test_non_company_tickers_miss(registry: ListedRegistry, ticker: str) -> None:
    assert registry.lookup([], [ticker]) == []


def test_common_word_fixture_does_not_match_single_word_names(registry: ListedRegistry) -> None:
    """Test-only words guard the data-derived first-word rule; runtime has no vocabulary list."""
    words = "Net Free Gross Operating Capital Global First American Margin Growth Revenue Income Cash Debt Market Fund Sector Retail Tech Logistics Price Value Profit Return Assets Risk Ratio Volume Supply Demand Cost Sales Share Shares Earnings Quarter Annual Current Future New Best Better Strong Weak Long Short Main Core Total Average High Low Close Rate Rates Tax Stock Bond Index Equity Credit Buy Sell Hold Large Small Top Bottom North South East West United General National International Public Private Financial Finance Business Company Corporation Group Holdings Trust Service Services Systems Technology Software Hardware Cloud Data Digital Energy Power Water Oil Gas Food Health Medical Bank Banking Insurance Property Real Estate Consumer Industrial Transport Freight Shipping Delivery Distribution Network Online Direct Store Stores Supply Chain Inventory Headcount Hiring Employment Workforce Employee Employees Management Analyst Research Investment Investor Portfolio Valuation Multiple Margin Margins Cashflow Flow Freecash Operating Margin Growth Profitability Leverage Liquidity Capitalization Capitalised Ratio Ratios Earnings Yield Dividend Dividends Revenue Netincome Grossprofit".split()
    assert len(words) >= 100
    assert registry.lookup(words[:20], []) == []
    for offset in range(20, len(words), 20):
        assert registry.lookup(words[offset:offset + 20], []) == []


def test_catalog_covered(registry: ListedRegistry) -> None:
    connection = sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True)
    try:
        tickers = {row[0] for row in connection.execute("SELECT ticker FROM companies")}
    finally:
        connection.close()
    assert len(tickers) == 24
    assert tickers <= registry.tickers


@pytest.mark.parametrize(("names", "tickers"), [
    (["Name"] * 21, []), (["A" * 61], []), (["a; DROP"], []), ([], ["rivn"]),
])
def test_rejects_invalid_inputs(registry: ListedRegistry, names: list[str], tickers: list[str]) -> None:
    with pytest.raises(ValueError):
        registry.lookup(names, tickers)


def test_validate_snapshot_checks_catalog(tmp_path: Path) -> None:
    payload = {"fields": ["cik", "name", "ticker", "exchange"], "data": [[1, "Example Inc.", "EXM", "NYSE"]]}
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="5,000"):
        validate_snapshot(payload, DATABASE)
