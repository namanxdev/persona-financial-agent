"""Shared evidence, catalog and draft for the validator and synthesis tests.

Values mirror real rows: a percent (MSFT margin), a multiple (AAPL P/E) and a
negative dollar figure (ORCL free cash flow), so sign, unit and magnitude can
each be tested against the display string the model is actually shown.
"""

from datetime import date

from agent.models import CompanyRow, EvidenceItem, Synthesis

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
