import json
import sqlite3
from datetime import date
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.build_db import rebuild_database
from scripts.company_universe import COMPANIES
from scripts.derive_metrics import derive_metrics
from scripts.sec_source import SecClient
from scripts.yfinance_source import YahooClient
from tests.stage1_fakes import OBSERVED, FakeSec, FakeYahoo


def _content(path: Path) -> tuple[list[tuple], ...]:
    connection = sqlite3.connect(path)
    try:
        return (
            connection.execute("SELECT ticker,name,sector,exchange,cik,source_url,as_of_date FROM companies ORDER BY ticker").fetchall(),
            connection.execute(
                """SELECT ticker,metric,value,unit,period_kind,period_start,period_end,reported_at,accession,source_tag,
                scale,source_url,as_of_date FROM financial_observations ORDER BY id"""
            ).fetchall(),
            connection.execute(
                "SELECT observation_id,input_observation_id,role,source_url,as_of_date FROM financial_lineage ORDER BY id"
            ).fetchall(),
            connection.execute(
                """SELECT ticker,signal,signal_kind,value,unit,observed_on,period_end,source_url,as_of_date
                FROM hiring_signals ORDER BY id"""
            ).fetchall(),
        )
    finally:
        connection.close()


def test_rebuild_is_valid_and_replay_equivalent(tmp_path: Path) -> None:
    database = tmp_path / "database.db"
    rebuild_database(database, FakeSec(), FakeYahoo())
    first = _content(database)
    rebuild_database(database, FakeSec(), FakeYahoo())
    assert _content(database) == first
    connection = sqlite3.connect(database)
    try:
        assert dict(connection.execute("SELECT sector,COUNT(*) FROM companies GROUP BY sector")) == {
            "tech": 8,
            "retail": 8,
            "logistics": 8,
        }
        assert connection.execute("SELECT COUNT(DISTINCT ticker) FROM hiring_signals WHERE value > 0").fetchone()[0] == 24
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            """SELECT COUNT(*) FROM financial_observations o LEFT JOIN financial_lineage l
            ON o.id=l.observation_id WHERE l.id IS NULL"""
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_failed_refresh_preserves_previous_database(tmp_path: Path) -> None:
    database = tmp_path / "database.db"
    rebuild_database(database, FakeSec(), FakeYahoo())
    previous = database.read_bytes()
    with pytest.raises(RuntimeError, match="deliberate source failure"):
        rebuild_database(database, FakeSec(fail_ticker="META"), FakeYahoo())
    assert database.read_bytes() == previous


def test_validation_failure_preserves_previous_database(tmp_path: Path) -> None:
    class MissingRevenueSec(FakeSec):
        def company_facts(self, company):
            facts, url, observed = super().company_facts(company)
            if company.ticker == "META":
                facts = [fact for fact in facts if fact.metric != "revenue"]
            return facts, url, observed

    database = tmp_path / "database.db"
    rebuild_database(database, FakeSec(), FakeYahoo())
    previous = database.read_bytes()
    with pytest.raises(ValueError, match="revenue coverage"):
        rebuild_database(database, MissingRevenueSec(), FakeYahoo())
    assert database.read_bytes() == previous


def test_derived_ratios_reject_period_mismatch_and_zero_denominator() -> None:
    facts, _, _ = FakeSec().company_facts(COMPANIES[0])
    mismatched = [
        replace(fact, period_start=date(2024, 1, 2)) if fact.metric == "operating_income" else fact
        for fact in facts
    ]
    assert "operating_margin" not in {fact.metric for fact in derive_metrics(mismatched)}
    zero_revenue = [replace(fact, value=0) if fact.metric == "revenue" else fact for fact in facts]
    derived = {fact.metric for fact in derive_metrics(zero_revenue)}
    assert not {"operating_margin", "net_margin", "fcf_margin", "revenue_growth"}.intersection(derived)


def test_sec_alias_selection_prefers_newest_context_and_amendment() -> None:
    def item(start: str, end: str, filed: str, value: int, form: str = "10-K") -> dict:
        return {"start": start, "end": end, "filed": filed, "val": value, "form": form, "fp": "FY", "accn": filed}

    payload = {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            item("2023-01-01", "2023-12-31", "2024-02-01", 90),
        ]}},
        "Revenues": {"units": {"USD": [
            item("2024-01-01", "2024-12-31", "2025-02-01", 100),
            item("2024-01-01", "2024-12-31", "2025-03-01", 101, "10-K/A"),
        ]}},
    }}}
    facts = SecClient._select(payload, "TEST", "revenue", (
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"
    ), True, "https://data.sec.gov/test")
    assert [(fact.as_of_date, fact.value) for fact in facts] == [(date(2024, 12, 31), 101), (date(2023, 12, 31), 90)]


def test_yahoo_offline_uses_original_observation_date(tmp_path: Path) -> None:
    company = COMPANIES[0]
    payload = {
        "symbol": company.ticker, "quoteType": "EQUITY", "exchange": "NMS", "currency": "USD",
        "fullTimeEmployees": 100, "marketCap": 123,
    }
    (tmp_path / f"yahoo_{company.ticker}.json").write_text(
        json.dumps({"observed_on": OBSERVED.isoformat(), "payload": payload}), encoding="utf-8"
    )
    listing, market = YahooClient(tmp_path, offline=True).snapshots(company)
    assert listing.observed_on == OBSERVED
    assert market[0].observed_on == OBSERVED


@pytest.mark.parametrize("employees", [True, 10.5, 0])
def test_yahoo_rejects_invalid_headcount(tmp_path: Path, employees: object) -> None:
    company = COMPANIES[0]
    payload = {
        "symbol": company.ticker, "quoteType": "EQUITY", "exchange": "NMS", "currency": "USD",
        "fullTimeEmployees": employees, "marketCap": 123,
    }
    (tmp_path / f"yahoo_{company.ticker}.json").write_text(
        json.dumps({"observed_on": OBSERVED.isoformat(), "payload": payload}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="headcount"):
        YahooClient(tmp_path, offline=True).snapshots(company)
