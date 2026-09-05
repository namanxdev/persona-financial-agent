"""SEC Company Facts retrieval and conservative fiscal-period selection."""

import json
import math
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

from scripts.company_universe import Company
from scripts.source_models import Fact

ANNUAL_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditures": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "diluted_eps": ("EarningsPerShareDiluted",),
}
INSTANT_TAGS: dict[str, tuple[str, ...]] = {
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "cash_and_equivalents": ("CashAndCashEquivalentsAtCarryingValue",),
    "stockholders_equity": (
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "StockholdersEquity",
    ),
}
SEC_ROOT = "https://data.sec.gov/api/xbrl/companyfacts"


class SecClient:
    def __init__(self, user_agent: str, cache_dir: Path | None = None, offline: bool = False) -> None:
        if not offline and ("@" not in user_agent or "example.com" in user_agent.lower()):
            raise ValueError("SEC_USER_AGENT must contain a real contact email")
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self._cache_dir = cache_dir
        self._offline = offline

    def company_facts(self, company: Company) -> tuple[list[Fact], str, date]:
        url = f"{SEC_ROOT}/CIK{company.cik:010d}.json"
        payload, observed_on = self._load(company, url)
        if int(payload.get("cik", -1)) != company.cik:
            raise ValueError(f"SEC CIK mismatch for {company.ticker}")
        expected = set(re.findall(r"[a-z0-9]+", company.name.lower())) - {"inc", "corporation", "the", "co"}
        actual = set(re.findall(r"[a-z0-9]+", str(payload.get("entityName", "")).lower()))
        if expected and not expected.intersection(actual):
            raise ValueError(f"SEC entity name mismatch for {company.ticker}")
        facts: list[Fact] = []
        for metric, tags in ANNUAL_TAGS.items():
            facts.extend(self._select(payload, company.ticker, metric, tags, annual=True, source_url=url))
        for metric, tags in INSTANT_TAGS.items():
            facts.extend(self._select(payload, company.ticker, metric, tags, annual=False, source_url=url))
        if not any(f.metric == "revenue" for f in facts):
            raise ValueError(f"SEC returned no comparable annual revenue for {company.ticker}")
        return facts, url, observed_on

    def _load(self, company: Company, url: str) -> tuple[dict[str, Any], date]:
        path = self._cache_dir / f"sec_{company.ticker}.json" if self._cache_dir else None
        if self._offline:
            if path is None or not path.exists():
                raise FileNotFoundError(f"missing cached SEC response for {company.ticker}")
            cached = json.loads(path.read_text(encoding="utf-8"))
            return cached["payload"], date.fromisoformat(cached["observed_on"])
        response = self._session.get(url, timeout=45)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        observed_on = date.today()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            cached = {"observed_on": observed_on.isoformat(), "payload": payload}
            path.write_text(json.dumps(cached, separators=(",", ":")), encoding="utf-8")
        time.sleep(0.12)
        return payload, observed_on

    @staticmethod
    def _select(
        payload: dict[str, Any], ticker: str, metric: str, tags: tuple[str, ...], annual: bool, source_url: str
    ) -> list[Fact]:
        us_gaap = payload.get("facts", {}).get("us-gaap", {})
        expected_unit = "USD/shares" if metric == "diluted_eps" else "USD"
        candidates: list[dict[str, Any]] = []
        for priority, tag in enumerate(tags):
            units = us_gaap.get(tag, {}).get("units", {})
            for item in SecClient._valid_units(units.get(expected_unit, []), annual):
                candidates.append({**item, "_tag": tag, "_priority": priority})
        selected = SecClient._latest_by_period(candidates)[:2]
        return [SecClient._to_fact(ticker, metric, expected_unit, item, annual, source_url) for item in selected]

    @staticmethod
    def _valid_units(items: list[dict[str, Any]], annual: bool) -> list[dict[str, Any]]:
        valid: list[dict[str, Any]] = []
        for item in items:
            if item.get("form") not in {"10-K", "10-K/A"} or item.get("fp") != "FY" or not item.get("end"):
                continue
            value = item.get("val")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                continue
            end = date.fromisoformat(item["end"])
            filed = date.fromisoformat(item["filed"]) if item.get("filed") else end
            if end > date.today() or filed > date.today():
                continue
            if annual:
                if not item.get("start"):
                    continue
                days = (date.fromisoformat(item["end"]) - date.fromisoformat(item["start"])).days
                if not 350 <= days <= 380:
                    continue
            valid.append(item)
        return valid

    @staticmethod
    def _latest_by_period(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_context: dict[tuple[str | None, str], dict[str, Any]] = {}
        for item in items:
            key = (item.get("start"), item["end"])
            current = by_context.get(key)
            if current is None or (item.get("filed", ""), -item.get("_priority", 999), item.get("accn", "")) > (
                current.get("filed", ""), -current.get("_priority", 999), current.get("accn", "")
            ):
                by_context[key] = item
        return sorted(by_context.values(), key=lambda row: (row["end"], row.get("filed", "")), reverse=True)

    @staticmethod
    def _to_fact(
        ticker: str, metric: str, unit: str, item: dict[str, Any], annual: bool, source_url: str
    ) -> Fact:
        end = date.fromisoformat(item["end"])
        return Fact(
            ticker=ticker,
            metric=metric,
            value=float(item["val"]),
            unit=unit,
            period_kind="fiscal_year" if annual else "instant",
            period_start=date.fromisoformat(item["start"]) if item.get("start") else None,
            period_end=end,
            reported_at=date.fromisoformat(item["filed"]) if item.get("filed") else None,
            source_url=source_url,
            as_of_date=end,
            accession=item.get("accn"),
            source_tag=item.get("_tag"),
        )
