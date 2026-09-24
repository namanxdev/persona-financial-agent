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
    candidates: list[Candidate] = []
    for chunk in [candidate.thesis, *candidate.supporting_points, *candidate.risks, *candidate.limitations]:
        for sentence in re.split(r"(?<=[.!?])\s+", chunk):
            if not sentence.strip():
                continue
            resolved = resolve_mentions(sentence, catalog)
            for ticker in resolved.matched:
                if ticker not in retrieved and ticker not in unretrieved:
                    unretrieved.append(ticker)
            candidates.extend(valid_candidates(resolved.candidates))
    names = list(dict.fromkeys(item.text for item in candidates if item.kind == "name"))
    tickers = list(dict.fromkeys(item.text for item in candidates if item.kind == "ticker"))
    hits = lookup(names, tickers) if names or tickers else []
    outside.extend(outside_catalog([item for item in candidates if item.kind == "name"], hits))
    for item in candidates:
        if item.kind != "ticker" or item.text in outside:
            continue
        if re.search(rf"(?<!\w){re.escape(item.text)}(?!\w)", question):
            continue
        if any(hit.query == item.text and hit.match_kind == "ticker" and hit.ticker not in retrieved for hit in hits):
            outside.append(item.text)
    return unretrieved, outside
