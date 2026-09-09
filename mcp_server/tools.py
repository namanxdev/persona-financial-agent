"""Tool handlers: validate inputs, query the database, and attach provenance.

Each function implements one of the four MCP tools. They are plain
async functions taking a connection so mcp_server/server.py (the stdio wiring)
can register them as tools with minimal glue, and tests can exercise them
directly against a real sqlite3.Connection without spawning a subprocess.
"""

import sqlite3

from mcp_server import database as db
from mcp_server.models import (
    CompanyRow,
    Direction,
    FinancialRow,
    HiringSignalRow,
    ScreenExclusion,
    ScreenResult,
    ScreenRow,
    Sector,
    SourceRef,
)


def _lineage(connection: sqlite3.Connection, observation_id: int) -> list[SourceRef]:
    return [
        SourceRef(
            source_url=row["source_url"],
            as_of_date=row["as_of_date"],
            field=row["metric"],
            value=row["value"],
            unit=row["unit"],
            period_kind=row["period_kind"],
            period_start=row["period_start"],
            period_end=row["period_end"],
        )
        for row in db.source_lineage(connection, observation_id)
    ]


def _financial_kwargs(connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
    return {
        "ticker": row["ticker"],
        "metric": row["metric"],
        "value": row["value"],
        "unit": row["unit"],
        "period_kind": row["period_kind"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "as_of_date": row["as_of_date"],
        "source_url": row["source_url"],
        "source_lineage": _lineage(connection, row["id"]),
    }


def _validate_limit(limit: int) -> None:
    if not (1 <= limit <= 24):
        raise ValueError(f"limit must be between 1 and 24, got {limit}")


async def list_companies(connection: sqlite3.Connection, sector: Sector) -> list[CompanyRow]:
    rows = db.list_companies(connection, sector)
    return [
        CompanyRow(ticker=r["ticker"], name=r["name"], sector=r["sector"], as_of_date=r["as_of_date"], source_url=r["source_url"])
        for r in rows
    ]


async def get_financials(connection: sqlite3.Connection, ticker: str, metrics: list[str]) -> list[FinancialRow]:
    if not db.ticker_exists(connection, ticker):
        raise ValueError(f"unknown ticker: {ticker}")
    known = db.known_metrics(connection)
    unknown = sorted(set(metrics) - known)
    if unknown:
        raise ValueError(f"unknown metric(s): {', '.join(unknown)}")
    rows: list[FinancialRow] = []
    for metric in metrics:
        row = db.latest_observation(connection, ticker, metric)
        if row is not None:
            rows.append(FinancialRow(**_financial_kwargs(connection, row)))
    return rows


async def get_hiring_signals(connection: sqlite3.Connection, ticker: str, limit: int) -> list[HiringSignalRow]:
    _validate_limit(limit)
    if not db.ticker_exists(connection, ticker):
        raise ValueError(f"unknown ticker: {ticker}")
    rows = db.hiring_signals(connection, ticker, limit)
    return [
        HiringSignalRow(
            ticker=r["ticker"],
            signal=r["signal"],
            signal_kind=r["signal_kind"],
            value=r["value"],
            unit=r["unit"],
            date=r["observed_on"],
            period_end=r["period_end"],
            as_of_date=r["as_of_date"],
            source_url=r["source_url"],
        )
        for r in rows
    ]


async def run_sector_screen(
    connection: sqlite3.Connection, sector: Sector, metric: str, direction: Direction, limit: int
) -> ScreenResult:
    _validate_limit(limit)
    if metric not in db.known_metrics(connection):
        raise ValueError(f"unknown metric: {metric}")
    companies = db.list_companies(connection, sector)
    if not companies:
        raise ValueError(f"unknown sector: {sector}")
    candidates = {c["ticker"]: db.latest_observation(connection, c["ticker"], metric) for c in companies}
    fallback_provenance = {c["ticker"]: (c["source_url"], c["as_of_date"]) for c in companies}

    cohort_counts: dict[tuple[str, str | None], int] = {}
    for row in candidates.values():
        if row is not None and row["value"] is not None:
            key = (row["period_kind"], row["unit"])
            cohort_counts[key] = cohort_counts.get(key, 0) + 1
    canonical = max(cohort_counts, key=cohort_counts.get) if cohort_counts else None

    included: list[tuple[str, sqlite3.Row]] = []
    excluded: list[ScreenExclusion] = []
    for ticker, row in candidates.items():
        fallback_url, fallback_date = fallback_provenance[ticker]
        if row is None:
            excluded.append(ScreenExclusion(ticker=ticker, reason=f"no {metric} observation on file", as_of_date=fallback_date, source_url=fallback_url))
        elif row["value"] is None:
            excluded.append(ScreenExclusion(ticker=ticker, reason=f"latest {metric} observation is null", as_of_date=row["as_of_date"], source_url=row["source_url"]))
        elif (row["period_kind"], row["unit"]) != canonical:
            excluded.append(ScreenExclusion(ticker=ticker, reason=f"incomparable period/unit for {metric}", as_of_date=row["as_of_date"], source_url=row["source_url"]))
        else:
            included.append((ticker, row))

    included.sort(key=lambda item: item[0])  # ticker ascending, stable tiebreak
    included.sort(key=lambda item: item[1]["value"], reverse=(direction == "desc"))
    ranked = [
        ScreenRow(**_financial_kwargs(connection, row), rank=index + 1)
        for index, (_, row) in enumerate(included[:limit])
    ]
    return ScreenResult(rows=ranked, excluded=excluded)
