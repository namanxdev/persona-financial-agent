"""Internal records shared by source adapters and the database writer."""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Fact:
    ticker: str
    metric: str
    value: float
    unit: str
    period_kind: str
    period_start: date | None
    period_end: date | None
    reported_at: date | None
    source_url: str
    as_of_date: date
    accession: str | None = None
    source_tag: str | None = None
    scale: float = 1.0
    lineage: tuple["Fact", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ListingSnapshot:
    ticker: str
    exchange: str
    employee_count: int
    observed_on: date
    source_url: str


@dataclass(frozen=True)
class MarketSnapshot:
    ticker: str
    metric: str
    value: float
    unit: str
    observed_on: date
    source_url: str
