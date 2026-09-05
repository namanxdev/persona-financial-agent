"""Fail-closed validation run before an atomic database replacement."""

import math
import sqlite3
from datetime import date
from pathlib import Path

EXPECTED_LINEAGE = {
    "operating_margin": 2,
    "net_margin": 2,
    "free_cash_flow": 2,
    "fcf_margin": 3,
    "revenue_growth": 2,
    "liabilities_to_equity": 2,
}


def validate_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        _assert_clean(connection)
        _assert_universe(connection)
        _assert_provenance(connection)
        _assert_periods(connection)
        _assert_lineage(connection)
    finally:
        connection.close()


def _assert_clean(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
        raise ValueError("SQLite quick_check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("SQLite foreign-key validation failed")


def _assert_universe(connection: sqlite3.Connection) -> None:
    counts = dict(connection.execute("SELECT sector, COUNT(*) FROM companies GROUP BY sector"))
    if counts != {"tech": 8, "retail": 8, "logistics": 8}:
        raise ValueError(f"expected company counts 8/8/8, got {counts}")
    covered = connection.execute(
        "SELECT COUNT(DISTINCT ticker) FROM hiring_signals WHERE value IS NOT NULL AND value > 0"
    ).fetchone()[0]
    if covered != 24:
        raise ValueError(f"expected a non-null hiring/headcount signal for all 24 companies, got {covered}")
    revenue = connection.execute(
        "SELECT COUNT(DISTINCT ticker) FROM financial_observations WHERE metric='revenue' AND value IS NOT NULL"
    ).fetchone()[0]
    if revenue != 24:
        raise ValueError(f"expected SEC revenue coverage for all 24 companies, got {revenue}")


def _assert_provenance(connection: sqlite3.Connection) -> None:
    for table in ("companies", "financial_observations", "financial_lineage", "hiring_signals"):
        missing = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE source_url IS NULL OR source_url NOT LIKE 'https://%' OR as_of_date IS NULL"
        ).fetchone()[0]
        if missing:
            raise ValueError(f"{table} contains {missing} rows without valid provenance")
        future = connection.execute(f"SELECT COUNT(*) FROM {table} WHERE as_of_date > ?", (date.today().isoformat(),)).fetchone()[0]
        if future:
            raise ValueError(f"{table} contains {future} future semantic dates")


def _assert_periods(connection: sqlite3.Connection) -> None:
    invalid = connection.execute(
        """SELECT COUNT(*) FROM financial_observations WHERE
        (period_kind='fiscal_year' AND (period_start IS NULL OR period_end IS NULL OR as_of_date != period_end)) OR
        (period_kind='instant' AND (period_start IS NOT NULL OR period_end IS NULL OR as_of_date != period_end)) OR
        (period_kind='observation' AND (period_start IS NOT NULL OR period_end IS NOT NULL))"""
    ).fetchone()[0]
    if invalid:
        raise ValueError(f"found {invalid} observations with invalid period semantics")
    for value, unit in connection.execute("SELECT value, unit FROM financial_observations WHERE value IS NOT NULL"):
        if isinstance(value, bool) or not math.isfinite(value) or not unit:
            raise ValueError("financial observations require finite values and explicit units")


def _assert_lineage(connection: sqlite3.Connection) -> None:
    missing = connection.execute(
        """SELECT COUNT(*) FROM financial_observations o
        LEFT JOIN financial_lineage l ON l.observation_id=o.id WHERE l.id IS NULL"""
    ).fetchone()[0]
    if missing:
        raise ValueError(f"found {missing} financial observations without lineage")
    for metric, expected in EXPECTED_LINEAGE.items():
        rows = connection.execute(
            """SELECT o.id, COUNT(l.id) FROM financial_observations o
            JOIN financial_lineage l ON l.observation_id=o.id WHERE o.metric=? GROUP BY o.id""",
            (metric,),
        ).fetchall()
        if any(count != expected for _, count in rows):
            raise ValueError(f"{metric} does not retain all {expected} constituent rows")
