"""Resolve company mentions in a query against the sector catalog.

CONTRACTS.md: "Before generic screening, load the sector catalog and resolve
mentions against normalized tickers, full names, and aliases... Any unmatched
mentioned company gets an explicit no-data response before sector retrieval;
uppercase-ticker-only detection is insufficient."

This is a deliberately simple heuristic, not an NER model: it looks for
ALL-CAPS ticker-shaped tokens and Title-Case proper-noun phrases, matches them
against a small alias table for the 24-company universe, and treats anything
proper-noun-shaped that doesn't match as an explicit out-of-scope mention. It
is scoped to the *requested sector's* 8 companies, matching how the catalog is
loaded (list_companies(sector) is always the first tool call).
"""

import re
from dataclasses import dataclass, field

from agent.models import CompanyRow

# Aliases beyond the literal ticker/legal name, keyed by ticker. Kept short and
# distinctive to avoid false-positive substring matches on ordinary words.
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

_QUESTION_STOPWORDS = {
    "what", "which", "who", "where", "why", "how", "is", "are", "do", "does",
    "can", "could", "should", "would", "will", "walk", "if", "the", "this",
    "that", "these", "those", "my", "your", "our", "i", "tell", "let's",
}
_DOMAIN_STOPWORDS = {
    "tech", "retail", "logistics", "mutual", "fund", "analyst", "equity", "pe",
    "sector", "companies", "company",
}
_ACRONYM_STOPWORDS = {
    "EBITDA", "ROI", "YOY", "TTM", "CEO", "CFO", "GDP", "SEC", "IPO", "ESG",
    "EPS", "FCF", "USD", "GAAP", "LBO", "KPI", "MF", "PE",
}
# Aliases that are also ordinary finance vocabulary. A mention of one of these
# only counts as a company reference when it is capitalised as a proper noun.
_CASE_SENSITIVE_ALIASES = frozenset({"target", "meta", "low", "cost", "best buy", "apple"})

_PROPER_NOUN_RE = re.compile(r"[A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+){0,2}")
_TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")


@dataclass
class ScopeResult:
    matched: dict[str, CompanyRow] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)


def _alias_index(catalog: list[CompanyRow]) -> dict[str, str]:
    """Lowercase alias/name/ticker -> ticker, scoped to this sector's catalog."""
    index: dict[str, str] = {}
    for company in catalog:
        index[company.ticker.lower()] = company.ticker
        for alias in _ALIASES.get(company.ticker, ()):
            index[alias] = company.ticker
    return index


def _alias_mentioned(alias: str, query: str, query_lower: str) -> bool:
    """Whether `alias` appears in `query` as an actual company mention.

    Two distinct false-positive classes have to be excluded, and they need
    different treatment:

    1. Substring collisions -- "expose the cost" contains "xpo", "metadata"
       contains "meta". Lookarounds for a non-word neighbour kill these.
    2. Whole-word collisions -- "the target market", "the low cost operator".
       Here the alias really is a standalone word, so boundaries do not help.
       Company names are proper nouns, so for the aliases that double as
       ordinary finance vocabulary we additionally require the writer to have
       capitalised it. "What about Target?" resolves; "the target market" does
       not. Unambiguous aliases ("costco", "walmart") stay case-insensitive so
       a lowercase query still works.
    """
    if alias in _CASE_SENSITIVE_ALIASES:
        # Look for the proper-noun spelling in the untouched query: "Target",
        # "Best Buy", "META". The lowercase form is ordinary vocabulary.
        return any(
            re.search(rf"(?<!\w){re.escape(variant)}(?!\w)", query)
            for variant in (alias.title(), alias.upper())
        )
    return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", query_lower) is not None


def resolve_mentions(query: str, catalog: list[CompanyRow]) -> ScopeResult:
    by_ticker = {company.ticker: company for company in catalog}
    alias_index = _alias_index(catalog)
    query_lower = query.lower()
    result = ScopeResult()

    for alias, ticker in alias_index.items():
        if len(alias) >= 2 and _alias_mentioned(alias, query, query_lower):
            result.matched[ticker] = by_ticker[ticker]

    words = query.split()
    for ticker_match in _TICKER_RE.finditer(query):
        token = ticker_match.group()
        if token in _ACRONYM_STOPWORDS:
            continue
        if token in by_ticker:
            result.matched[token] = by_ticker[token]
        elif token not in result.matched:
            result.unmatched.append(token)

    for phrase_match in _PROPER_NOUN_RE.finditer(query):
        phrase = phrase_match.group()
        if phrase_match.start() == 0 and phrase == words[0].strip(",.?!"):
            continue  # sentence-initial capitalization is not proof of a proper noun
        if phrase.lower() in _QUESTION_STOPWORDS or phrase.lower() in _DOMAIN_STOPWORDS:
            continue
        if any(word.lower() in _QUESTION_STOPWORDS for word in phrase.split()):
            continue
        if phrase.lower() in alias_index or phrase in by_ticker:
            continue  # already captured above
        if phrase not in result.unmatched:
            result.unmatched.append(phrase)

    return result
