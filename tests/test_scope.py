"""Catalog matches and registry candidates against the real sector catalog."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from agent.models import CompanyRow, ListedCompany, Sector
from agent.scope import Candidate, outside_catalog, resolve_mentions

DATABASE = Path(__file__).resolve().parents[1] / "data" / "agent_techhome.db"


def _catalog(sector: Sector) -> list[CompanyRow]:
    connection = sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT ticker, name, sector, as_of_date, source_url FROM companies WHERE sector = ?", (sector,)
        ).fetchall()
    finally:
        connection.close()
    return [CompanyRow(ticker=t, name=n, sector=s, as_of_date=d, source_url=u) for t, n, s, d, u in rows]


@pytest.mark.parametrize(("sector", "query", "matched", "candidates"), [
    ("retail", "Is Lowe's a better LBO candidate than Home Depot?", {"LOW", "HD"}, ["LBO"]),
    ("logistics", "How is J.B. Hunt doing?", {"JBHT"}, []),
    ("logistics", "What's JB Hunt's revenue?", {"JBHT"}, []),
    ("logistics", "What about Hub Group and C.H. Robinson?", {"HUBG", "CHRW"}, []),
    ("logistics", "What are the ups and downs of this sector?", set(), []),
    ("logistics", "UPS or FedEx on margins?", {"UPS", "FDX"}, []),
    ("tech", "What do you think about Snowflake?", set(), ["Snowflake"]),
    ("logistics", "What do you think about RIVN?", set(), ["RIVN"]),
    ("logistics", "How are the OTR carriers doing on margins?", set(), ["OTR"]),
    ("tech", "Is this sector a good place to be putting money to work right now?", set(), []),
])
def test_resolve_mentions_against_catalog(
    sector: Sector, query: str, matched: set[str], candidates: list[str],
) -> None:
    result = resolve_mentions(query, _catalog(sector))
    assert set(result.matched) == matched
    assert [item.text for item in result.candidates] == candidates


@pytest.mark.parametrize(("query", "expected"), [
    ("What about RIVN?", [("RIVN", "ticker", True)]),
    ("GM's margins", [("GM", "ticker", True)]),
    ("UPS and ODFL", [("ODFL", "ticker", True)]),
    ("AI capex", [("AI", "ticker", False)]),
    ("IT spending", [("IT", "ticker", False)]),
    ("What about Old Dominion?", [("Old Dominion", "name", True)]),
])
def test_candidates_record_company_usage(query: str, expected: list[tuple[str, str, bool]]) -> None:
    result = resolve_mentions(query, _catalog("logistics"))
    assert [(item.text, item.kind, item.company_context) for item in result.candidates] == expected


def _hit(text: str, kind: str, ticker: str) -> ListedCompany:
    return ListedCompany(
        query=text, match_kind=kind, ticker=ticker, name=f"{ticker} Corporation", exchange="NYSE",
        cik=1, source_url="https://www.sec.gov/files/company_tickers_exchange.json", as_of_date=date.today(),
    )


def test_outside_catalog_uses_length_context_and_match_kind() -> None:
    candidates = [
        Candidate("AI", "ticker", False), Candidate("GM", "ticker", True, direct_context=True),
        Candidate("RIVN", "ticker", False), Candidate("Snowflake", "name", False),
        Candidate("OTR", "ticker", True),
    ]
    hits = [_hit("AI", "ticker", "AI"), _hit("GM", "ticker", "GM"),
            _hit("RIVN", "ticker", "RIVN"), _hit("Snowflake", "name", "SNOW")]
    assert outside_catalog(candidates, hits) == ["GM", "RIVN", "Snowflake"]
