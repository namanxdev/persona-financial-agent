"""What the model may see, and what it is allowed to say back.

Both halves are here on purpose. `evidence_payload` renders the retrieved rows
into the display strings the model is shown, and `allowed_numbers` derives the
numeric allowlist from those same strings -- so "quote the evidence" and "pass
validation" are the same act, and the two can never drift apart.

`validate` is the whole trust boundary for agent/synthesis.py: a candidate that
fails it is discarded and the deterministic composer writes the answer instead.
"""

import re

from agent.format import format_value, metric_label
from agent.models import CompanyRow, EvidenceItem, Synthesis
from agent.scope import ACRONYM_STOPWORDS, resolve_mentions

_MAX_CHARS = 400
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Letters only: punctuated acronyms like EV/EBITDA and P/E decompose into their
# letter runs, so the allowlist below never has to enumerate punctuation variants.
_UPPERCASE = re.compile(r"\b[A-Z]{2,5}\b")



def evidence_payload(evidence: list[EvidenceItem]) -> list[dict[str, str]]:
    """Identifiers and display strings only -- raw floats are deliberately withheld.

    The only numbers put in front of the model are the exact strings the
    validator will accept back, which is what makes "copy it verbatim" an
    instruction the model can actually satisfy.
    """
    return [
        {
            "evidence_id": item.evidence_id,
            "ticker": item.ticker,
            "metric": metric_label(item.field),
            "display": format_value(item.value, item.unit, item.field),
            "as_of_date": item.as_of_date.isoformat(),
        }
        for item in evidence
    ]


def allowed_numbers(payload: list[dict[str, str]]) -> set[str]:
    allowed: set[str] = set()
    for row in payload:
        for text in (row["display"], row["as_of_date"]):
            allowed.update(match.group().replace(",", "") for match in _NUMBER.finditer(text))
    return allowed


def _chunks(candidate: Synthesis) -> list[str]:
    """Each written unit separately: a bullet is its own claim, not part of its neighbour."""
    return [candidate.thesis, *candidate.supporting_points, *candidate.risks, *candidate.limitations]


def _sentences(chunk: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", chunk) if part.strip()]


def _numbers_by_ticker(evidence: list[EvidenceItem]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for item, row in zip(evidence, evidence_payload(evidence)):
        grouped.setdefault(item.ticker, set()).update(allowed_numbers([row]))
    return grouped


def _ungrounded(candidate: Synthesis, evidence: list[EvidenceItem], tickers: set[str]) -> set[str]:
    """Numbers the evidence does not support, checked per sentence.

    A sentence naming exactly one company is held to *that company's* figures, so
    the model cannot attach MSFT's margin to AAPL -- both numbers are real, but
    the pairing would not be. Sentences naming none or several fall back to the
    full set, which is the most that can be checked without parsing attribution.
    """
    by_ticker = _numbers_by_ticker(evidence)
    everything: set[str] = set().union(*by_ticker.values()) if by_ticker else set()
    found: set[str] = set()
    for chunk in _chunks(candidate):
        for sentence in _sentences(chunk):
            named = {token for token in _UPPERCASE.findall(sentence) if token in tickers}
            allowed = by_ticker[next(iter(named))] if len(named) == 1 else everything
            found.update(
                match.group()
                for match in _NUMBER.finditer(sentence)
                if match.group().replace(",", "") not in allowed
            )
    return found


def out_of_scope_mentions(candidate: Synthesis, catalog: list[CompanyRow]) -> list[str]:
    """Company names in the draft that this sector's catalog does not contain.

    Checking uppercase tickers against the evidence is not enough: a model handed
    the user's question will happily write about "Snowflake" in proper-noun form,
    which is not ticker-shaped and so passes every numeric check while the answer
    is *about* a company holding no data. This runs the same resolver a query
    goes through, so a name the agent would refuse to answer about cannot appear
    in an answer either.

    Sentence by sentence, because that resolver ignores a sentence-initial capital
    -- otherwise every bullet starting "Market volatility..." would read as a
    company. That leaves one gap by design: a draft whose *only* mention of an
    uncovered company opens a sentence is not caught. Closing it needs a
    dictionary of ordinary words, and the version that tried refused a real
    question about "the margin and valuation picture" because the answer happened
    to open a bullet with "Valuation". A missed mention costs a plainer answer; a
    false one costs a refusal of a question the data can actually answer.
    """
    found: list[str] = []
    for chunk in _chunks(candidate):
        for sentence in _sentences(chunk):
            for name in resolve_mentions(sentence, catalog).unmatched:
                if name not in found:
                    found.append(name)
    return found


def validate(
    candidate: Synthesis,
    evidence: list[EvidenceItem],
    catalog: list[CompanyRow] | None = None,
) -> str | None:
    """Return a rejection reason, or None if the candidate may be shown."""
    if not candidate.thesis.strip() or not candidate.supporting_points:
        return "empty thesis or no supporting points"

    known_ids = {item.evidence_id for item in evidence}
    unknown_ids = [ref for ref in candidate.evidence_ids if ref not in known_ids]
    if unknown_ids:
        return f"cites evidence not retrieved this turn: {unknown_ids}"
    if not candidate.evidence_ids:
        return "cites no evidence"

    prose = " ".join(_chunks(candidate))
    if len(prose) > _MAX_CHARS * (2 + len(candidate.supporting_points)):
        return "output far longer than the evidence supports"

    # Membership is tested against everything retrieved this turn, not just the rows
    # the model chose to cite: discussing a retrieved company without formally citing
    # it is untidy, whereas naming one that was never retrieved is fabrication.
    tickers = {item.ticker for item in evidence}
    invented = {
        token
        for token in _UPPERCASE.findall(prose)
        if token not in ACRONYM_STOPWORDS and token not in tickers
    }
    if invented:
        return f"names companies outside the retrieved evidence: {sorted(invented)}"

    if catalog is not None:
        outside = out_of_scope_mentions(candidate, catalog)
        if outside:
            return f"names companies outside the sector catalog: {outside}"

    ungrounded = _ungrounded(candidate, evidence, tickers)
    if ungrounded:
        return f"states figures absent from the evidence: {sorted(ungrounded)}"
    return None
