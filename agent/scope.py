"""Extract company-shaped mentions; confirm unknowns through the MCP registry."""

import re
from dataclasses import dataclass, field
from typing import Literal

from agent.models import CompanyRow, ListedCompany

_ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("apple",), "MSFT": ("microsoft",), "GOOGL": ("alphabet", "google"),
    "META": ("meta", "facebook"), "ORCL": ("oracle",), "CSCO": ("cisco",),
    "IBM": ("ibm",), "ADBE": ("adobe",),
    "WMT": ("walmart", "wal-mart"), "COST": ("costco",), "TGT": ("target",),
    "HD": ("home depot",), "LOW": ("lowe's", "lowes"), "BBY": ("best buy",),
    "KR": ("kroger",), "DG": ("dollar general",),
    "UPS": ("united parcel",), "FDX": ("fedex", "federal express"),
    "XPO": ("xpo",), "GXO": ("gxo",), "CHRW": ("c.h. robinson", "ch robinson"),
    "JBHT": ("j.b. hunt", "jb hunt"), "EXPD": ("expeditors",), "HUBG": ("hub group",),
}
_CASE_SENSITIVE_ALIASES = frozenset({"target", "meta", "low", "cost", "best buy", "apple", "ups"})
_PROPER_NOUN_RE = re.compile(r"[A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+){0,2}")
_TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")
_TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 .,&'\-]*$")
_PRECEDING = re.compile(r"(?:about|vs|versus|than|between|like)\W+$", re.IGNORECASE)
_OPENING = re.compile(r"^(?:(?:what|how|who|which|tell|me|do|you|think|is|are|about|the|a|an)\W+)*$", re.IGNORECASE)


@dataclass(frozen=True)
class Candidate:
    text: str
    kind: Literal["ticker", "name"]
    company_context: bool
    direct_context: bool = False
    joined_catalog: bool = False
    joined_with: tuple[str, ...] = ()


@dataclass
class ScopeResult:
    matched: dict[str, CompanyRow] = field(default_factory=dict)
    candidates: list[Candidate] = field(default_factory=list)


def _strip_possessive(phrase: str) -> str:
    """"Snowflake's" and "Snowflake" are one mention, not two."""
    return phrase[:-2] if phrase.endswith("'s") else phrase


def _alias_index(catalog: list[CompanyRow]) -> dict[str, str]:
    index: dict[str, str] = {}
    for company in catalog:
        index[company.ticker.lower()] = company.ticker
        for alias in _ALIASES.get(company.ticker, ()):
            index[alias] = company.ticker
    return index


def _alias_spans(alias: str, query: str) -> list[tuple[int, int]]:
    """Find whole aliases, requiring case for aliases shared with ordinary words."""
    if alias in _CASE_SENSITIVE_ALIASES:
        variants = [re.compile(rf"(?<!\w){re.escape(v)}(?!\w)") for v in (alias.title(), alias.upper())]
    else:
        variants = [re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE)]
    return [match.span() for pattern in variants for match in pattern.finditer(query)]


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    """Keep offsets while hiding resolved fragments from later scans."""
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _company_context(
    query: str, start: int, end: int, catalog_spans: list[tuple[int, int]],
    candidates: list[tuple[str, str, int, int]],
) -> tuple[bool, bool, tuple[str, ...]]:
    before, after = query[:start], query[end:]
    direct = bool(after.startswith("'s") or _PRECEDING.search(before))
    direct |= bool(_OPENING.fullmatch(before) and not after.strip(" ?.!,"))
    joined_catalog = False
    joined: list[str] = []
    others = [(s, e, None) for s, e in catalog_spans]
    others.extend((s, e, text) for text, _, s, e in candidates)
    for other_start, other_end, other_text in others:
        if (other_start, other_end) == (start, end):
            continue
        between = query[end:other_start] if end <= other_start else query[other_end:start] if other_end <= start else ""
        if re.fullmatch(r"\s*(?:and|or|,)\s*", between, re.IGNORECASE):
            if other_text is None:
                joined_catalog = True
            else:
                joined.append(other_text)
    return direct, joined_catalog, tuple(joined)


def resolve_mentions(query: str, catalog: list[CompanyRow]) -> ScopeResult:
    by_ticker = {company.ticker: company for company in catalog}
    aliases = _alias_index(catalog)
    result = ScopeResult()
    resolved: list[tuple[int, int]] = []
    for alias, ticker in aliases.items():
        spans = _alias_spans(alias, query) if len(alias) >= 2 else []
        if spans:
            result.matched[ticker] = by_ticker[ticker]
            resolved.extend(spans)
    masked = _mask(query, resolved)
    pending: list[tuple[str, Literal["ticker", "name"], int, int]] = []
    ticker_spans: list[tuple[int, int]] = []
    for match in _TICKER_RE.finditer(masked):
        token = match.group()
        if token in by_ticker:
            result.matched[token] = by_ticker[token]
            resolved.append(match.span())
        else:
            pending.append((token, "ticker", *match.span()))
        ticker_spans.append(match.span())
    masked = _mask(masked, ticker_spans)
    for match in _PROPER_NOUN_RE.finditer(masked):
        phrase = _strip_possessive(match.group())
        start = match.start()
        if start == 0 and phrase.lower() not in aliases and phrase not in by_ticker:
            opener, separator, tail = phrase.partition(" ")
            if not separator:
                continue
            start += len(opener) + len(separator)
            phrase = _strip_possessive(tail)
        if phrase and phrase.lower() not in aliases and phrase not in by_ticker:
            end = start + len(phrase)
            pending.append((" ".join(phrase.split()), "name", start, end))
    seen: set[tuple[str, str]] = set()
    for phrase, kind, start, end in pending:
        key = (phrase, kind)
        if key not in seen:
            direct, joined_catalog, joined = _company_context(query, start, end, resolved, pending)
            result.candidates.append(Candidate(
                phrase, kind, direct or joined_catalog or bool(joined), direct, joined_catalog, joined,
            ))
            seen.add(key)
    return result


def valid_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Drop extractor shapes the bounded MCP tool cannot accept."""
    return [item for item in candidates if item.kind == "ticker" or (
        len(item.text) <= 60 and _TOOL_NAME_RE.fullmatch(item.text)
    )]


def outside_catalog(candidates: list[Candidate], hits: list[ListedCompany]) -> list[str]:
    confirmed_texts = {hit.query for hit in hits}
    outside: list[str] = []
    for candidate in candidates:
        matches = [hit for hit in hits if hit.query == candidate.text and hit.match_kind == candidate.kind]
        if not matches:
            continue
        short_context = candidate.direct_context or candidate.joined_catalog or bool(
            confirmed_texts.intersection(candidate.joined_with)
        )
        named = candidate.kind == "name" and (
            any(hit.name_match == "exact" for hit in matches)
            or (candidate.company_context and len({hit.ticker for hit in matches}) == 1)
        )
        if named or (candidate.kind == "ticker" and (len(candidate.text) >= 4 or short_context)):
            if candidate.text not in outside:
                outside.append(candidate.text)
    return outside
