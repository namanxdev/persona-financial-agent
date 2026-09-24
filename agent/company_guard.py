"""Confirm company names in a draft against retrieved evidence and the registry."""

import re
from typing import Callable

from agent.models import CompanyRow, EvidenceItem, ListedCompany, Synthesis
from agent.scope import Candidate, outside_catalog, resolve_mentions, valid_candidates

Lookup = Callable[[list[str], list[str]], list[ListedCompany]]


def company_violations(
    candidate: Synthesis, evidence: list[EvidenceItem], catalog: list[CompanyRow], lookup: Lookup,
    question: str = "",
) -> tuple[list[str], list[str]]:
    retrieved = {item.ticker for item in evidence}
    unretrieved: list[str] = []
    outside: list[str] = []
    # Each candidate carries whether its sentence holds a figure but names no retrieved company:
    # that is where a real ticker could take credit for a number it does not own.
    entries: list[tuple[Candidate, bool]] = []
    for chunk in [candidate.thesis, *candidate.supporting_points, *candidate.risks, *candidate.limitations]:
        for sentence in re.split(r"(?<=[.!?])\s+", chunk):
            if not sentence.strip():
                continue
            resolved = resolve_mentions(sentence, catalog)
            for ticker in resolved.matched:
                if ticker not in retrieved and ticker not in unretrieved:
                    unretrieved.append(ticker)
            orphan_figure = bool(re.search(r"\d", sentence)) and not retrieved.intersection(resolved.matched)
            entries.extend((item, orphan_figure) for item in valid_candidates(resolved.candidates))
    candidates = [item for item, _ in entries]
    names = list(dict.fromkeys(item.text for item in candidates if item.kind == "name"))
    tickers = list(dict.fromkeys(item.text for item in candidates if item.kind == "ticker"))
    hits = lookup(names, tickers) if names or tickers else []
    outside.extend(outside_catalog([item for item in candidates if item.kind == "name"], hits))
    # About a fifth of common finance acronyms are also listed tickers (FCF, AI, IT, LTM), so a
    # short ticker counts as a company only by context (4-5 letters always do) or an orphan figure.
    by_context = set(outside_catalog([item for item in candidates if item.kind == "ticker"], hits))
    confirmed = {hit.query for hit in hits if hit.match_kind == "ticker" and hit.ticker not in retrieved}
    for item, orphan_figure in entries:
        if item.kind != "ticker" or item.text not in confirmed or item.text in outside:
            continue
        if re.search(rf"(?<!\w){re.escape(item.text)}(?!\w)", question):
            continue
        if item.text in by_context or orphan_figure:
            outside.append(item.text)
    return unretrieved, outside
