"""Deterministic source doubles; production builds never import this module."""

from datetime import date

from scripts.company_universe import Company
from scripts.source_models import Fact, ListingSnapshot, MarketSnapshot

OBSERVED = date(2026, 9, 5)


class FakeSec:
    def __init__(self, fail_ticker: str | None = None) -> None:
        self.fail_ticker = fail_ticker

    def company_facts(self, company: Company) -> tuple[list[Fact], str, date]:
        if company.ticker == self.fail_ticker:
            raise RuntimeError("deliberate source failure")
        offset = company.cik % 1000
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company.cik:010d}.json"
        current_start, current_end = date(2024, 1, 1), date(2024, 12, 31)
        prior_start, prior_end = date(2023, 1, 1), date(2023, 12, 31)
        current = 1_000_000 + offset
        prior = 900_000 + offset
        values = (
            ("revenue", current, current_start, current_end),
            ("revenue", prior, prior_start, prior_end),
            ("operating_income", current * 0.2, current_start, current_end),
            ("net_income", current * 0.15, current_start, current_end),
            ("operating_cash_flow", current * 0.18, current_start, current_end),
            ("capital_expenditures", current * 0.04, current_start, current_end),
        )
        facts = [self._fact(company.ticker, url, *row) for row in values]
        facts.extend(
            (
                self._instant(company.ticker, url, "liabilities", 500_000 + offset, current_end),
                self._instant(company.ticker, url, "stockholders_equity", 400_000 + offset, current_end),
            )
        )
        return facts, url, OBSERVED

    @staticmethod
    def _fact(ticker: str, url: str, metric: str, value: float, start: date, end: date) -> Fact:
        return Fact(
            ticker, metric, value, "USD", "fiscal_year", start, end, date(2025, 2, 1), url, end,
            accession="000-test", source_tag="TestTag",
        )

    @staticmethod
    def _instant(ticker: str, url: str, metric: str, value: float, end: date) -> Fact:
        return Fact(
            ticker, metric, value, "USD", "instant", None, end, date(2025, 2, 1), url, end,
            accession="000-test", source_tag="TestTag",
        )


class FakeYahoo:
    def snapshots(self, company: Company) -> tuple[ListingSnapshot, list[MarketSnapshot]]:
        profile = f"https://finance.yahoo.com/quote/{company.ticker}/profile/"
        stats = f"https://finance.yahoo.com/quote/{company.ticker}/key-statistics/"
        listing = ListingSnapshot(company.ticker, "NMS", 10_000 + company.cik % 1000, OBSERVED, profile)
        market = [
            MarketSnapshot(company.ticker, "market_cap", 2_000_000 + company.cik, "USD", OBSERVED, stats),
            MarketSnapshot(company.ticker, "trailing_pe", 20 + company.cik % 5, "ratio", OBSERVED, stats),
        ]
        return listing, market
