"""Deterministic claim rendering -- CONTRACTS.md 'Shared agent and API'.

Every sentence in an answer comes from a template filled in from an
EvidenceItem already produced by a tool call this turn (financial rows, screen
rows, or hiring rows). The LLM/deterministic framing choice from agent/llm.py
only selects a non-factual opening qualifier; it cannot alter or introduce a
number. Empty evidence always produces the fixed no-data response, never a
best-effort guess.
"""

from agent.format import format_value, metric_label
from agent.llm import FramingChoice
from agent.models import EvidenceItem, FinancialRow, HiringSignalRow, PersonaName, ScreenResult, SourceRef
from agent.personas import PersonaPolicy

NO_DATA_ANSWER = "No data available for this request: the underlying tool calls returned nothing usable."

_PERSONA_INTRO: dict[PersonaName, str] = {
    "mutual_fund_analyst": "a long-only, benchmark-relative view of {sector}",
    "equity_analyst": "a fundamentals and valuation view of {sector}",
    "pe_analyst": "a deal/ops view of {sector}",
}
_STANCE_QUALIFIER: dict[str, str] = {
    "constructive": "the retrieved data points to constructive momentum",
    "cautious": "the retrieved data argues for caution",
    "mixed": "the retrieved data is mixed",
}


def out_of_scope_answer(sector: str, names: list[str]) -> str:
    quoted = ", ".join(f"'{name}'" for name in names)
    pronoun = "it" if len(names) == 1 else "them"
    return (
        f"I don't have {quoted} in the {sector} sector dataset, so I can't answer about {pronoun} -- "
        f"I won't guess from general knowledge. Ask about one of the covered {sector} companies instead."
    )


def _financial_evidence(rows: list[FinancialRow]) -> list[EvidenceItem]:
    return [
        EvidenceItem(
            evidence_id=f"{row.ticker}:{row.metric}",
            ticker=row.ticker, field=row.metric, value=row.value, unit=row.unit,
            as_of_date=row.as_of_date, source_url=row.source_url, source_lineage=row.source_lineage,
        )
        for row in rows
    ]


def _hiring_evidence(rows: list[HiringSignalRow]) -> list[EvidenceItem]:
    return [
        EvidenceItem(
            evidence_id=f"{row.ticker}:{row.signal_kind}:{row.date.isoformat()}",
            ticker=row.ticker, field=row.signal_kind, value=row.value, unit=row.unit,
            as_of_date=row.as_of_date, source_url=row.source_url,
            source_lineage=[SourceRef(
                source_url=row.source_url, as_of_date=row.as_of_date, field=row.signal_kind,
                value=row.value, unit=row.unit, period_kind="observation", period_end=row.period_end,
            )],
        )
        for row in rows
    ]


def _screen_claims(screen: ScreenResult, metric: str, verb: str) -> list[str]:
    label = metric_label(metric)
    claims = [
        f"{verb} by {label}, #{row.rank}: {row.ticker} at {format_value(row.value, row.unit, row.metric)} (as of {row.as_of_date})."
        for row in screen.rows
    ]
    if screen.excluded:
        names = "; ".join(f"{item.ticker} ({item.reason})" for item in screen.excluded)
        claims.append(f"Excluded from the {label} screen -- {names}.")
    return claims


def _financial_claims(financials: dict[str, list[FinancialRow]]) -> list[str]:
    return [
        f"{row.ticker}'s {metric_label(row.metric)} is {format_value(row.value, row.unit, row.metric)} as of {row.as_of_date}."
        for rows in financials.values()
        for row in rows
    ]


def _hiring_claims(hiring: dict[str, list[HiringSignalRow]]) -> list[str]:
    return [
        f"{row.ticker}'s latest hiring/headcount signal: {format_value(row.value, row.unit, row.signal_kind)} "
        f"as of {row.date} ({row.source_url})."
        for rows in hiring.values()
        for row in rows
    ]


def compose_answer(
    persona: PersonaName,
    sector: str,
    policy: PersonaPolicy,
    framing: FramingChoice,
    primary_screen: ScreenResult | None,
    secondary_screen: ScreenResult | None,
    financials: dict[str, list[FinancialRow]],
    hiring: dict[str, list[HiringSignalRow]],
) -> tuple[str, list[EvidenceItem]]:
    evidence: list[EvidenceItem] = []
    claims: list[str] = []
    seen_fields: set[tuple[str, str]] = set()

    if primary_screen is not None:
        evidence.extend(_financial_evidence(primary_screen.rows))
        seen_fields.update((row.ticker, row.metric) for row in primary_screen.rows)
        claims.extend(_screen_claims(primary_screen, policy.screen_metric, "Ranked"))
    if secondary_screen is not None and policy.secondary_screen_metric:
        evidence.extend(_financial_evidence(secondary_screen.rows))
        seen_fields.update((row.ticker, row.metric) for row in secondary_screen.rows)
        claims.extend(_screen_claims(secondary_screen, policy.secondary_screen_metric, "Re-screened"))

    deduped_financials = {
        ticker: [row for row in rows if (row.ticker, row.metric) not in seen_fields]
        for ticker, rows in financials.items()
    }
    for ticker, rows in deduped_financials.items():
        evidence.extend(_financial_evidence(rows))
    claims.extend(_financial_claims(deduped_financials))

    for rows in hiring.values():
        evidence.extend(_hiring_evidence(rows))
    claims.extend(_hiring_claims(hiring))

    if not evidence:
        return NO_DATA_ANSWER, []

    lead = f"From {_PERSONA_INTRO[persona].format(sector=sector)}: {_STANCE_QUALIFIER[framing.stance]}."
    # ranking_rationale describes the sector-screen methodology; only include it
    # when a screen actually ran this turn, so a single-company answer doesn't
    # describe a screening step that never happened.
    parts = [lead] + ([policy.ranking_rationale] if primary_screen is not None else []) + claims
    return " ".join(parts), evidence
