"""Confirm company names in a draft against retrieved evidence and the registry."""

import re
from typing import Callable

from agent.models import CompanyRow, EvidenceItem, ListedCompany, Synthesis
from agent.scope import Candidate, outside_catalog, resolve_mentions

Lookup = Callable[[list[str], list[str]], list[ListedCompany]]


def company_violations(
    candidate: Synthesis, evidence: list[EvidenceItem], catalog: list[CompanyRow], lookup: Lookup,
) -> tuple[list[str], list[str]]:
    retrieved = {item.ticker for item in evidence}
    unretrieved: list[str] = []
    outside: list[str] = []
    for chunk in [candidate.thesis, *candidate.supporting_points, *candidate.risks, *candidate.limitations]:
        for sentence in re.split(r"(?<=[.!?])\s+", chunk):
            if not sentence.strip():
                continue
            resolved = resolve_mentions(sentence, catalog)
            for ticker in resolved.matched:
                if ticker not in retrieved and ticker not in unretrieved:
                    unretrieved.append(ticker)
            candidates: list[Candidate] = resolved.candidates
            for offset in range(0, len(candidates), 20):
                batch = candidates[offset:offset + 20]
                names = [item.text for item in batch if item.kind == "name"]
                tickers = [item.text for item in batch if item.kind == "ticker"]
                hits = lookup(names, tickers)
                for name in outside_catalog(batch, hits):
                    if name not in outside:
                        outside.append(name)
    return unretrieved, outside
