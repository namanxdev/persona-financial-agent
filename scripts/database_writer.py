"""SQLite persistence isolated from both source retrieval and the future agent package."""

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from scripts.company_universe import Company
from scripts.source_models import Fact, ListingSnapshot, MarketSnapshot


def create_database(
    path: Path,
    schema_path: Path,
    companies: tuple[Company, ...],
    listings: dict[str, ListingSnapshot],
    sec_urls: dict[str, str],
    facts: list[Fact],
    market: list[MarketSnapshot],
    company_observed: dict[str, date],
) -> None:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(schema_path.read_text(encoding="utf-8"))
        _insert_companies(connection, companies, listings, sec_urls, company_observed, retrieved_at)
        all_facts = facts + [_market_fact(item) for item in market]
        _insert_facts(connection, all_facts, retrieved_at)
        _insert_hiring(connection, listings, retrieved_at)
        connection.commit()
    finally:
        connection.close()


def _insert_companies(
    connection: sqlite3.Connection,
    companies: tuple[Company, ...],
    listings: dict[str, ListingSnapshot],
    sec_urls: dict[str, str],
    company_observed: dict[str, date],
    retrieved_at: str,
) -> None:
    rows = [
        (
            c.ticker, c.name, c.sector, listings[c.ticker].exchange, c.cik, sec_urls[c.ticker],
            company_observed[c.ticker].isoformat(), retrieved_at,
        )
        for c in companies
    ]
    connection.executemany("INSERT INTO companies VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)


def _insert_facts(connection: sqlite3.Connection, facts: list[Fact], retrieved_at: str) -> None:
    identifiers: dict[int, int] = {}
    for fact in facts:
        cursor = connection.execute(
            """INSERT INTO financial_observations
            (ticker,metric,value,unit,period_kind,period_start,period_end,reported_at,accession,source_tag,scale,
             source_url,as_of_date,retrieved_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                fact.ticker,
                fact.metric,
                fact.value,
                fact.unit,
                fact.period_kind,
                _iso(fact.period_start),
                _iso(fact.period_end),
                _iso(fact.reported_at),
                fact.accession,
                fact.source_tag,
                fact.scale,
                fact.source_url,
                fact.as_of_date.isoformat(),
                retrieved_at,
            ),
        )
        identifiers[id(fact)] = int(cursor.lastrowid)
    for fact in facts:
        output_id = identifiers[id(fact)]
        inputs = fact.lineage or (fact,)
        for item in inputs:
            input_id = identifiers.get(id(item))
            if input_id is None:
                raise ValueError(f"lineage input was not persisted: {fact.ticker}/{fact.metric}")
            connection.execute(
                "INSERT INTO financial_lineage (observation_id,input_observation_id,role,source_url,as_of_date) VALUES (?,?,?,?,?)",
                (output_id, input_id, item.metric, item.source_url, item.as_of_date.isoformat()),
            )


def _insert_hiring(connection: sqlite3.Connection, listings: dict[str, ListingSnapshot], retrieved_at: str) -> None:
    rows = [
        (
            item.ticker,
            f"Yahoo Finance reported {item.employee_count:,} full-time employees",
            "headcount",
            item.employee_count,
            "employees",
            item.observed_on.isoformat(),
            None,
            item.source_url,
            item.observed_on.isoformat(),
            retrieved_at,
        )
        for item in listings.values()
    ]
    connection.executemany(
        """INSERT INTO hiring_signals
        (ticker,signal,signal_kind,value,unit,observed_on,period_end,source_url,as_of_date,retrieved_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )


def _market_fact(snapshot: MarketSnapshot) -> Fact:
    return Fact(
        ticker=snapshot.ticker,
        metric=snapshot.metric,
        value=snapshot.value,
        unit=snapshot.unit,
        period_kind="observation",
        period_start=None,
        period_end=None,
        reported_at=None,
        source_url=snapshot.source_url,
        as_of_date=snapshot.observed_on,
    )


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None
