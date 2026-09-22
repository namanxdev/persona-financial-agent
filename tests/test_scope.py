"""Scope resolution against the real sector catalog.

The catalog is read straight from the committed database (read-only, the same
deliberately separate path evals/cases.py uses) so an alias table that drifts
from the tickers actually on file shows up here, not in a live demo.
"""

import sqlite3
from pathlib import Path

import pytest

from agent.models import CompanyRow, Sector
from agent.scope import resolve_mentions

DATABASE = Path(__file__).resolve().parents[1] / "data" / "agent_techhome.db"


def _catalog(sector: Sector) -> list[CompanyRow]:
    connection = sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT ticker, name, sector, as_of_date, source_url FROM companies WHERE sector = ?", (sector,)
        ).fetchall()
    finally:
        connection.close()
    return [
        CompanyRow(ticker=t, name=n, sector=s, as_of_date=d, source_url=u) for t, n, s, d, u in rows
    ]


@pytest.mark.parametrize(
    ("sector", "query", "matched", "unmatched"),
    [
        # An alias match used to leave its own fragment ("Lowe", "Hunt", "JB")
        # behind for the proper-noun scan, which then refused the whole turn.
        ("retail", "Is Lowe's a better LBO candidate than Home Depot?", {"LOW", "HD"}, []),
        ("retail", "Is Home Depot or Lowe's the better LBO candidate?", {"LOW", "HD"}, []),
        ("logistics", "How is J.B. Hunt doing?", {"JBHT"}, []),
        ("logistics", "What's J.B. Hunt's revenue?", {"JBHT"}, []),
        ("logistics", "What's JB Hunt's revenue?", {"JBHT"}, []),
        ("logistics", "What about Hub Group and C.H. Robinson?", {"HUBG", "CHRW"}, []),
        # "ups" in lowercase is an ordinary word, not United Parcel Service.
        ("logistics", "What are the ups and downs of this sector?", set(), []),
        ("logistics", "UPS or FedEx on margins?", {"UPS", "FDX"}, []),
        # Genuine out-of-scope names must still be refused.
        ("tech", "What do you think about Snowflake?", set(), ["Snowflake"]),
        ("logistics", "What do you think about RIVN?", set(), ["RIVN"]),
        ("logistics", "How are UPS and FedEx positioned vs Amazon Air?", {"UPS", "FDX"}, ["Amazon Air"]),
    ],
)
def test_resolve_mentions_against_the_real_catalog(
    sector: Sector, query: str, matched: set[str], unmatched: list[str]
) -> None:
    result = resolve_mentions(query, _catalog(sector))
    assert set(result.matched) == matched
    assert result.unmatched == unmatched
