"""Yahoo Finance snapshots accessed through the yfinance client."""

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import yfinance as yf

from scripts.company_universe import Company
from scripts.source_models import ListingSnapshot, MarketSnapshot

MARKET_FIELDS: dict[str, tuple[str, str]] = {
    "marketCap": ("market_cap", "USD"),
    "enterpriseValue": ("enterprise_value", "USD"),
    "trailingPE": ("trailing_pe", "ratio"),
    "priceToSalesTrailing12Months": ("price_to_sales_ttm", "ratio"),
    "enterpriseToEbitda": ("enterprise_to_ebitda", "ratio"),
    "operatingMargins": ("operating_margin_ttm", "ratio"),
    "profitMargins": ("net_margin_ttm", "ratio"),
    "revenueGrowth": ("revenue_growth_yoy", "ratio"),
    "freeCashflow": ("free_cash_flow_ttm", "USD"),
    "totalDebt": ("total_debt", "USD"),
    "totalCash": ("cash", "USD"),
}
US_EXCHANGES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX"}


class YahooClient:
    def __init__(self, cache_dir: Path | None = None, offline: bool = False) -> None:
        self._cache_dir = cache_dir
        self._offline = offline

    def snapshots(self, company: Company) -> tuple[ListingSnapshot, list[MarketSnapshot]]:
        info, observed_on = self._load(company)
        exchange = str(info.get("exchange", ""))
        if str(info.get("symbol", "")).upper() != company.ticker or info.get("quoteType") != "EQUITY":
            raise ValueError(f"Yahoo identity mismatch for {company.ticker}")
        if exchange not in US_EXCHANGES or info.get("currency") != "USD":
            raise ValueError(f"{company.ticker} is not verified as an active US-listed equity")
        employees = info.get("fullTimeEmployees")
        if (
            isinstance(employees, bool)
            or not isinstance(employees, (int, float))
            or employees <= 0
            or not math.isfinite(float(employees))
            or not float(employees).is_integer()
        ):
            raise ValueError(f"{company.ticker} has no non-null Yahoo headcount signal")
        profile_url = f"https://finance.yahoo.com/quote/{company.ticker}/profile/"
        listing = ListingSnapshot(company.ticker, exchange, int(employees), observed_on, profile_url)
        statistics_url = f"https://finance.yahoo.com/quote/{company.ticker}/key-statistics/"
        snapshots: list[MarketSnapshot] = []
        for source_field, (metric, unit) in MARKET_FIELDS.items():
            value = info.get(source_field)
            if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value)):
                snapshots.append(MarketSnapshot(company.ticker, metric, float(value), unit, observed_on, statistics_url))
        if not snapshots:
            raise ValueError(f"Yahoo returned no usable market statistics for {company.ticker}")
        return listing, snapshots

    def _load(self, company: Company) -> tuple[dict[str, Any], date]:
        path = self._cache_dir / f"yahoo_{company.ticker}.json" if self._cache_dir else None
        if self._offline:
            if path is None or not path.exists():
                raise FileNotFoundError(f"missing cached Yahoo response for {company.ticker}")
            cached = json.loads(path.read_text(encoding="utf-8"))
            return cached["payload"], date.fromisoformat(cached["observed_on"])
        info: dict[str, Any] = yf.Ticker(company.ticker).get_info()
        if not info:
            raise ValueError(f"Yahoo returned an empty response for {company.ticker}")
        observed_on = date.today()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            cached = {"observed_on": observed_on.isoformat(), "payload": info}
            path.write_text(json.dumps(cached, default=str, separators=(",", ":")), encoding="utf-8")
        return info, observed_on
