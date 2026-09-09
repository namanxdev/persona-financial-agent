"""Pydantic models owned entirely by the agent package.

MCP is a protocol boundary: the agent receives JSON-RPC over stdio and parses
it into types it owns here, rather than importing the server package's model
classes. That keeps the "agent never touches a DB driver" guarantee robust to
future changes on the server side (this package never imports the server
package at all), and matches what MCP actually is -- the server could be a
different language entirely. agent/mcp_client.py validates each tool
response's JSON directly into these classes.

The Sector/Direction/PeriodKind/SourceRef/*Row shapes intentionally mirror the
wire shapes the MCP server returns -- this package's own copy of that contract,
not a re-export of the server's classes.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, HttpUrl

Sector = Literal["tech", "retail", "logistics"]
Direction = Literal["asc", "desc"]
PeriodKind = Literal["instant", "quarter", "fiscal_year", "ttm", "observation"]
PersonaName = Literal["mutual_fund_analyst", "equity_analyst", "pe_analyst"]
Confidence = Literal["low", "medium", "high"]


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


class QueryRequest(BaseModel):
    query: str
    persona: PersonaName
    sector: Sector


class EvidenceItem(BaseModel):
    evidence_id: str
    ticker: str
    field: str
    value: float | int | str | None
    unit: str | None
    as_of_date: date
    source_url: HttpUrl
    source_lineage: list[SourceRef]


class Synthesis(BaseModel):
    """A model-written thesis that passed every check in agent/synthesis.py.

    Present only when the LLM path ran *and* validated; `None` means the
    deterministic composer wrote the answer.
    """

    thesis: str
    supporting_points: list[str]
    risks: list[str]
    limitations: list[str]
    evidence_ids: list[str]


class QueryResponse(BaseModel):
    answer: str
    persona: PersonaName
    sector: Sector
    companies_referenced: list[str]
    evidence: list[EvidenceItem]
    confidence: Confidence
    tools_called: list[str]
    synthesis: Synthesis | None = None
