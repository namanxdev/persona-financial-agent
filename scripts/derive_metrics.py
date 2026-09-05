"""Derived metrics with strict period/unit compatibility and explicit lineage."""

from collections import defaultdict
from datetime import date

from scripts.source_models import Fact


def derive_metrics(raw_facts: list[Fact]) -> list[Fact]:
    by_ticker: dict[str, list[Fact]] = defaultdict(list)
    for fact in raw_facts:
        by_ticker[fact.ticker].append(fact)
    derived: list[Fact] = []
    for ticker_facts in by_ticker.values():
        derived.extend(_annual_metrics(ticker_facts))
        derived.extend(_instant_metrics(ticker_facts))
    return derived


def _annual_metrics(facts: list[Fact]) -> list[Fact]:
    groups: dict[tuple[date | None, date | None, str], dict[str, Fact]] = defaultdict(dict)
    for fact in facts:
        if fact.period_kind == "fiscal_year":
            groups[(fact.period_start, fact.period_end, fact.unit)][fact.metric] = fact
    result: list[Fact] = []
    revenues: list[Fact] = []
    for (_, _, unit), group in groups.items():
        revenue = group.get("revenue")
        if unit == "USD" and revenue and revenue.value > 0:
            revenues.append(revenue)
            result.extend(_ratio(group.get(metric), revenue, output) for metric, output in (
                ("operating_income", "operating_margin"),
                ("net_income", "net_margin"),
            ) if group.get(metric))
            cashflow = group.get("operating_cash_flow")
            capex = group.get("capital_expenditures")
            if cashflow and capex and capex.value >= 0:
                fcf = _derived("free_cash_flow", cashflow.value - capex.value, "USD", (cashflow, capex))
                result.extend((fcf, _derived("fcf_margin", fcf.value / revenue.value, "ratio", (cashflow, capex, revenue))))
    revenues.sort(key=lambda fact: fact.period_end or date.min, reverse=True)
    if len(revenues) >= 2:
        current, previous = revenues[:2]
        if _consecutive_comparable(current, previous) and previous.value > 0:
            growth = current.value / previous.value - 1
            result.append(_derived("revenue_growth", growth, "ratio", (current, previous)))
    return result


def _instant_metrics(facts: list[Fact]) -> list[Fact]:
    by_end: dict[date | None, dict[str, Fact]] = defaultdict(dict)
    for fact in facts:
        if fact.period_kind == "instant" and fact.unit == "USD":
            by_end[fact.period_end][fact.metric] = fact
    result: list[Fact] = []
    for group in by_end.values():
        liabilities, equity = group.get("liabilities"), group.get("stockholders_equity")
        if liabilities and equity and equity.value > 0:
            result.append(_derived("liabilities_to_equity", liabilities.value / equity.value, "ratio", (liabilities, equity)))
    return result


def _ratio(numerator: Fact, denominator: Fact, metric: str) -> Fact:
    return _derived(metric, numerator.value / denominator.value, "ratio", (numerator, denominator))


def _derived(metric: str, value: float, unit: str, lineage: tuple[Fact, ...]) -> Fact:
    primary = lineage[0]
    return Fact(
        ticker=primary.ticker,
        metric=metric,
        value=value,
        unit=unit,
        period_kind=primary.period_kind,
        period_start=primary.period_start,
        period_end=primary.period_end,
        reported_at=max((item.reported_at for item in lineage if item.reported_at), default=None),
        source_url=primary.source_url,
        as_of_date=primary.as_of_date,
        lineage=lineage,
    )


def _consecutive_comparable(current: Fact, previous: Fact) -> bool:
    if not all((current.period_start, current.period_end, previous.period_start, previous.period_end)):
        return False
    current_days = (current.period_end - current.period_start).days
    previous_days = (previous.period_end - previous.period_start).days
    gap = (current.period_start - previous.period_end).days
    return current.unit == previous.unit == "USD" and abs(current_days - previous_days) <= 14 and 0 <= gap <= 14
