"""What the model may see, and what it is allowed to say back.

Both halves are here on purpose. `evidence_payload` renders the retrieved rows
into the display strings the model is shown, and the allowlist is read out of
those same strings with the same `_QUANTITY` pattern later run over the prose --
so "quote the evidence" and "pass validation" are the same act, and the two can
never drift apart.

A figure is compared as a typed quantity -- (sign, currency, digits, suffix) --
not as a bare digit run, so "-$24.5B" restated as "$24.5B" (sign), "$24.5M"
(magnitude) or "45.1%" as "45.1x" (unit) is rejected even though the digits
match. Dates are matched first, as whole YYYY-MM-DD tokens, and must equal a
retrieved as_of_date.

Not checked: pronoun hand-offs ("Its margin is...") and numbers written as words
("roughly double"); see README "What this does not check".

`validate` is the whole trust boundary for agent/synthesis.py: a candidate that
fails it is discarded and the deterministic composer writes the answer instead.
"""

import re

from agent.company_guard import Lookup, company_violations
from agent.format import format_value, metric_label
from agent.models import CompanyRow, EvidenceItem, Synthesis
from agent.scope import resolve_mentions

_MAX_CHARS = 400
_DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
# The sign may sit either side of "$" ("-$24.5B", "$-24.5B"), but a hyphen inside a
# word ("COVID-19", "2024-2025") is not a sign. `(?!\d)` rather than `(?!\w)` after
# the digits, so "5.7billion" still yields a figure (with no suffix) to check.
_QUANTITY = re.compile(
    r"(?<!\d)(?P<lead>(?<!\w)-)?(?:(?P<currency>\$)(?P<trail>-)?)?"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)(?!\d)(?P<suffix>[BMK%x](?![A-Za-z]))?"
)
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


Quantity = tuple[str, str, str, str]  # (sign, currency, digits without commas, suffix)


def _quantities(text: str) -> list[tuple[Quantity, str]]:
    """Every figure in `text` as (typed quantity, text as written), dates excluded."""
    text = _DATE.sub(lambda match: " " * len(match.group()), text.replace("\u2212", "-"))  # unicode minus
    return [
        (
            ("-" if match["lead"] or match["trail"] else "", match["currency"] or "",
             match["number"].replace(",", ""), match["suffix"] or ""),
            match.group().strip().rstrip(","),
        )
        for match in _QUANTITY.finditer(text)
    ]


def allowed_figures(payload: list[dict[str, str]]) -> tuple[set[Quantity], set[str]]:
    """The quantities and dates a draft may quote, read from what the model was shown."""
    quantities = {quantity for row in payload for quantity, _ in _quantities(row["display"])}
    return quantities, {row["as_of_date"] for row in payload}


def _chunks(candidate: Synthesis) -> list[str]:
    """Each written unit separately: a bullet is its own claim, not part of its neighbour."""
    return [candidate.thesis, *candidate.supporting_points, *candidate.risks, *candidate.limitations]


def _sentences(chunk: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", chunk) if part.strip()]


def _figures_by_ticker(evidence: list[EvidenceItem]) -> dict[str, tuple[set[Quantity], set[str]]]:
    rows: dict[str, list[dict[str, str]]] = {}
    for item, row in zip(evidence, evidence_payload(evidence)):
        rows.setdefault(item.ticker, []).append(row)
    return {ticker: allowed_figures(group) for ticker, group in rows.items()}


def _named(sentence: str, tickers: set[str], catalog: list[CompanyRow] | None) -> set[str]:
    """Companies a sentence names: retrieved tickers, plus names the catalog resolves."""
    named = {token for token in _UPPERCASE.findall(sentence) if token in tickers}
    if catalog is not None:
        named |= set(resolve_mentions(sentence, catalog).matched)
    return named


def _ungrounded(
    candidate: Synthesis, evidence: list[EvidenceItem], tickers: set[str], catalog: list[CompanyRow] | None
) -> set[str]:
    """Figures the evidence does not support, checked per sentence.

    A sentence naming exactly one company -- by ticker or by name -- is held to
    *that company's* figures, so the model cannot attach MSFT's margin to AAPL or
    to "Apple": both numbers are real, but the pairing would not be. Sentences
    naming none or several fall back to the full set, which is the most that can
    be checked without parsing attribution.
    """
    by_ticker = _figures_by_ticker(evidence)
    everything = allowed_figures(evidence_payload(evidence))
    found: set[str] = set()
    for chunk in _chunks(candidate):
        for sentence in _sentences(chunk):
            named = _named(sentence, tickers, catalog)
            owner = by_ticker.get(next(iter(named)), (set(), set())) if len(named) == 1 else everything
            quantities, dates = owner
            found.update(date for date in _DATE.findall(sentence) if date not in dates)
            found.update(text for quantity, text in _quantities(sentence) if quantity not in quantities)
    return found


def out_of_scope_mentions(
    candidate: Synthesis, catalog: list[CompanyRow], lookup: Lookup | None = None,
) -> list[str]:
    if lookup is None:
        return []
    return company_violations(candidate, [], catalog, lookup)[1]


def validate(
    candidate: Synthesis,
    evidence: list[EvidenceItem],
    catalog: list[CompanyRow] | None = None,
    lookup: Lookup | None = None,
    question: str = "",
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
    if catalog is not None and lookup is not None:
        try:
            unretrieved, outside = company_violations(candidate, evidence, catalog, lookup, question)
        except Exception as exc:
            return f"company lookup failed: {exc}"
        if outside:
            return f"names companies outside the sector catalog: {outside}"
        if unretrieved:
            return f"names companies outside the retrieved evidence: {unretrieved}"

    ungrounded = _ungrounded(candidate, evidence, tickers, catalog)
    if ungrounded:
        return f"states figures absent from the evidence: {sorted(ungrounded)}"
    return None
