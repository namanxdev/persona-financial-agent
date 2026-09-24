"""Shared evidence, catalog and draft for the validator and synthesis tests.

Values mirror real rows: a percent (MSFT margin), a multiple (AAPL P/E) and a
negative dollar figure (ORCL free cash flow), so sign, unit and magnitude can
each be tested against the display string the model is actually shown.
"""

from datetime import date

from agent.models import CompanyRow, EvidenceItem, ListedCompany, Synthesis

AS_OF = date(2026, 9, 7)


def evidence() -> list[EvidenceItem]:
    rows = (
        ("MSFT", "operating_margin_ttm", 0.45111),  # 45.1%
        ("AAPL", "trailing_pe", 36.60984),  # 36.61x
        ("ORCL", "free_cash_flow_ttm", -24.54e9),  # -$24.5B
    )
    return [
        EvidenceItem(
            evidence_id=f"{ticker}:{field}", ticker=ticker, field=field, value=value,
            unit="USD" if field == "free_cash_flow_ttm" else "ratio", as_of_date=AS_OF,
            source_url=f"https://data.sec.gov/{ticker.lower()}.json", source_lineage=[],
        )
        for ticker, field, value in rows
    ]


def catalog() -> list[CompanyRow]:
    names = {"MSFT": "Microsoft Corporation", "AAPL": "Apple Inc.", "ORCL": "Oracle Corporation"}
    return [
        CompanyRow(ticker=ticker, name=name, sector="tech", as_of_date=AS_OF, source_url="https://example.com")
        for ticker, name in names.items()
    ]


def candidate(**overrides) -> Synthesis:
    fields = {
        "thesis": "MSFT screens best on operating quality in this cohort.",
        "supporting_points": ["MSFT's operating margin (TTM) is 45.1% as of 2026-09-07."],
        "risks": ["AAPL trades at 36.61x trailing earnings, leaving little room for error."],
        "limitations": ["Only a few metrics were retrieved this turn."],
        "evidence_ids": ["MSFT:operating_margin_ttm", "AAPL:trailing_pe"],
    }
    fields.update(overrides)
    return Synthesis(**fields)


def listed_lookup(names: list[str], tickers: list[str]) -> list[ListedCompany]:
    """Fixed registry replies for guard tests; no server or vocabulary dependency."""
    known_names = {"snowflake": "SNOW", "old dominion": "ODFL", "nvidia": "NVDA"}
    known_tickers = {"ODFL", "NVDA", "RIVN", "AI", "GM", "IT"}
    matches = [(name, "name", known_names[name.lower()]) for name in names if name.lower() in known_names]
    matches += [(ticker, "ticker", ticker) for ticker in tickers if ticker in known_tickers]
    return [ListedCompany(
        query=text, match_kind=kind, ticker=ticker, name=f"{ticker} Inc.", exchange="NYSE", cik=1,
        source_url="https://www.sec.gov/files/company_tickers_exchange.json", as_of_date=AS_OF,
    ) for text, kind, ticker in matches]
