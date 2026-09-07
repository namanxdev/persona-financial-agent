"""Deterministic confidence scoring -- CONTRACTS.md 'Deterministic confidence'.

The model never picks this. One slot is created per (company, required metric)
in the plan that was actually executed, plus one slot per explicitly requested
hiring signal. Coverage and freshness are both computed over that fixed slot
set, so one fresh row can never conceal several stale or missing ones.
"""

from dataclasses import dataclass
from datetime import date

from agent.models import Confidence

_FRESH_DAYS = 180
_STALE_DAYS = 450
_OLD_DAYS = 730


@dataclass(frozen=True)
class Slot:
    company: str
    field: str
    value: object
    as_of_date: date | None  # None means the slot was requested but no row came back


@dataclass(frozen=True)
class ConfidenceResult:
    tier: Confidence
    coverage: float
    freshness: float
    score: float
    slot_count: int
    newest_evidence_age_days: int | None
    worst_required_age_days: int | None


def _slot_freshness(as_of: date | None, today: date) -> float:
    if as_of is None:
        return 0.0
    age = (today - as_of).days
    if age < 0:
        return 0.0  # future semantic dates are invalid, not fresh
    if age <= _FRESH_DAYS:
        return 1.0
    if age <= _STALE_DAYS:
        return 0.6
    if age <= _OLD_DAYS:
        return 0.25
    return 0.0


def compute_confidence(slots: list[Slot], today: date | None = None) -> ConfidenceResult:
    today = today or date.today()
    n = max(len(slots), 1)
    non_null = sum(1 for slot in slots if slot.value is not None)
    coverage = non_null / n
    freshness_scores = [_slot_freshness(slot.as_of_date, today) for slot in slots]
    freshness = sum(freshness_scores) / n
    score = 0.65 * coverage + 0.35 * freshness

    ages = [(today - slot.as_of_date).days for slot in slots if slot.as_of_date is not None]
    newest_age = min(ages) if ages else None
    worst_age = max(ages) if ages else None
    all_fresh = bool(slots) and all(f == 1.0 for f in freshness_scores)

    if score >= 0.80 and all_fresh:
        tier: Confidence = "high"
    elif score >= 0.50:
        tier = "medium"
    else:
        tier = "low"

    return ConfidenceResult(
        tier=tier,
        coverage=coverage,
        freshness=freshness,
        score=score,
        slot_count=len(slots),
        newest_evidence_age_days=newest_age,
        worst_required_age_days=worst_age,
    )
