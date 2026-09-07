"""Pydantic models for data crossing the MCP tool boundary.

These are the only shapes the agent package is allowed to see from the database:
every field here traces back to a real row plus its source_url/as_of_date. Shared
Literal aliases (Sector, Direction, PeriodKind) live here too so agent/models.py can
reuse them without redefining the domain vocabulary.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, HttpUrl

Sector = Literal["tech", "retail", "logistics"]
Direction = Literal["asc", "desc"]
PeriodKind = Literal["instant", "quarter", "fiscal_year", "ttm", "observation"]


class SourceRef(BaseModel):
    source_url: HttpUrl
    as_of_date: date
    field: str
    value: float | int | str | None
    unit: str | None = None
    period_kind: PeriodKind
    period_start: date | None = None
    period_end: date | None = None


class CompanyRow(BaseModel):
    ticker: str
    name: str
    sector: Sector
    as_of_date: date
    source_url: HttpUrl


class FinancialRow(BaseModel):
    ticker: str
    metric: str
    value: float | None
    unit: str | None
    period_kind: PeriodKind
    period_start: date | None
    period_end: date | None
    as_of_date: date
    source_url: HttpUrl
    source_lineage: list[SourceRef]


class HiringSignalRow(BaseModel):
    ticker: str
    signal: str | None
    signal_kind: Literal["headcount", "hiring_signal"]
    value: float | int | None
    unit: str | None
    date: date
    period_end: date | None
    as_of_date: date
    source_url: HttpUrl


class ScreenRow(FinancialRow):
    rank: int


class ScreenExclusion(BaseModel):
    ticker: str
    reason: str
    as_of_date: date
    source_url: HttpUrl


class ScreenResult(BaseModel):
    rows: list[ScreenRow]
    excluded: list[ScreenExclusion]
