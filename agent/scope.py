"""Resolve company mentions in a query against the sector catalog.

The rule: before any generic screening, load the sector catalog and resolve
mentions against normalized tickers, full names, and aliases. Any mentioned
company that does not match gets an explicit no-data response before sector
retrieval runs -- detecting uppercase tickers alone is not sufficient.

This is a deliberately simple heuristic, not an NER model: it looks for
ALL-CAPS ticker-shaped tokens and Title-Case proper-noun phrases, matches them
against a small alias table for the 24-company universe, and treats anything
proper-noun-shaped that doesn't match as an explicit out-of-scope mention. It
is scoped to the *requested sector's* 8 companies, matching how the catalog is
loaded (list_companies(sector) is always the first tool call).

Known gap: a question written Entirely In Title Case still misfires, because
any capitalised phrase outside the vocabulary list reads as a name. The real fix
is to refuse only names that are real companies outside coverage (a server-side
list such as SEC's company_tickers.json), not to grow the vocabulary list.
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
# Uppercase tokens that are financial vocabulary rather than a ticker. Shared with
# agent/evidence_guard.py, which asks the same question of generated prose: two
# copies of this list drifted apart once already and let "EV/EBITDA" read as a
# company on one side of the boundary but not the other.
ACRONYM_STOPWORDS = frozenset({
    "EBITDA", "EBIT", "EBITA", "ROI", "ROIC", "ROE", "ROA", "YOY", "QOQ", "YTD",
    "TTM", "FY", "CEO", "CFO", "COO", "GDP", "CPI", "SEC", "IPO", "ESG", "EPS",
    "EV", "FCF", "PS", "USD", "USA", "US", "GAAP", "LBO", "IRR", "NAV", "KPI", "LTM", "NTM", "CAGR",
    "MF", "PE", "WACC", "DCF", "TAM", "CAPEX", "OPEX", "COGS", "SGA", "AI",
    "OK", "AND", "THE", "BUT", "NOT", "ALL", "NEW", "FOR", "PER", "VS", "IN",
    "ON", "AT", "TO", "OF", "IS",
    *"EBITDAR EBT NOPAT PEG PB NPV MOIC CAPM TSR ROCE ROTE NIM FCFF FCFE OCF DPS BVPS SOTP".split(),
    *"NWC CCC DSO DIO DPO PPE SBC NOL RSU AR AP SG IFRS FASB SOX QTD MTD CY LTV".split(),
    *"IG HY CDS DSCR FFO AFFO SOFR YTM ABS MBS PPI PCE PMI FOMC FED ECB IMF OPEC WTI VIX".split(),
    *"ETF REIT ADR SPAC NYSE FX EUR UK EU EM AUM ARR MRR NRR RPO CAC ARPU DAU MAU SAAS API".split(),
    *"GPU CPU ML LLM IOT IT SMB OEM SSS AOV GMV SKU POS DTC BOPIS BNPL CPG NPS CTO CIO".split(),
    *"LTL FTL TL TMS WMS TEU OTIF OR CDL USPS FOB DC JIT BUY SELL HOLD".split(),
})
# Ordinary finance words people capitalise mid-sentence ("the Fed", "Q2 Results",
# "AI Capex"). A proper-noun phrase made only of these is not a company name.
_FINANCE_VOCABULARY = frozenset({
    "results", "earnings", "fed", "capex", "opex", "economy", "fund", "funds", "mutual",
    "wall", "street", "market", "markets", "guidance", "outlook", "revenue", "margins",
    "margin", "growth", "inflation", "tariff", "tariffs", "recession", "rates", "sector",
    "industry", "quarter", "valuation", "dividend", "dividends", "debt", "cash", "strong", "weak",
    *"operating gross net free flow income profit return assets capital working yield ratio interest".split(),
    *"leverage value price pricing sales share shares buyback cost costs expense liquidity multiple".split(),
    *"multiples risk exposure headcount hiring freight volume volumes shipping capacity backlog".split(),
    *"inventory demand supply chain same store comparable cloud software consensus peers china mexico".split(),
})
# Aliases that are also ordinary finance vocabulary. A mention of one of these
# only counts as a company reference when it is capitalised as a proper noun.
_CASE_SENSITIVE_ALIASES = frozenset({"target", "meta", "low", "cost", "best buy", "apple", "ups"})

_PROPER_NOUN_RE = re.compile(r"[A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+){0,2}")
_TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")


@dataclass
class ScopeResult:
    matched: dict[str, CompanyRow] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)


def _strip_possessive(phrase: str) -> str:
    """"Snowflake's" and "Snowflake" are one mention, not two."""
    return phrase[:-2] if phrase.endswith("'s") else phrase


def _is_vocabulary(word: str) -> bool:
    bare = _strip_possessive(word).lower()
    return (
        bare in _FINANCE_VOCABULARY or bare in _QUESTION_STOPWORDS
        or bare in _DOMAIN_STOPWORDS or bare.upper() in ACRONYM_STOPWORDS
    )


def _alias_index(catalog: list[CompanyRow]) -> dict[str, str]:
    """Lowercase alias/name/ticker -> ticker, scoped to this sector's catalog."""
    index: dict[str, str] = {}
    for company in catalog:
        index[company.ticker.lower()] = company.ticker
        for alias in _ALIASES.get(company.ticker, ()):
            index[alias] = company.ticker
    return index


def _alias_spans(alias: str, query: str) -> list[tuple[int, int]]:
    """Where `alias` appears in `query` as an actual company mention.

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

    Spans are offsets into `query` itself (case-insensitive matching runs on the
    original string, not a lowercased copy), so the caller can blank them out.
    """
    if alias in _CASE_SENSITIVE_ALIASES:
        # Look for the proper-noun spelling in the untouched query: "Target",
        # "Best Buy", "META". The lowercase form is ordinary vocabulary.
        variants = [re.compile(rf"(?<!\w){re.escape(v)}(?!\w)") for v in (alias.title(), alias.upper())]
    else:
        variants = [re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE)]
    return [match.span() for pattern in variants for match in pattern.finditer(query)]


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    """Blank out resolved mentions, keeping every other offset where it was.

    Without this, a later scan re-reads the leftovers of a name it already
    resolved -- "Lowe's" matched LOW, then "Lowe" came back as an unknown
    company and the whole turn was refused.
    """
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def resolve_mentions(query: str, catalog: list[CompanyRow]) -> ScopeResult:
    by_ticker = {company.ticker: company for company in catalog}
    alias_index = _alias_index(catalog)
    result = ScopeResult()

    resolved: list[tuple[int, int]] = []
    for alias, ticker in alias_index.items():
        spans = _alias_spans(alias, query) if len(alias) >= 2 else []
        if spans:
            result.matched[ticker] = by_ticker[ticker]
            resolved.extend(spans)
    query = _mask(query, resolved)

    for ticker_match in _TICKER_RE.finditer(query):
        token = ticker_match.group()
        if token in by_ticker:
            result.matched[token] = by_ticker[token]
            resolved.append(ticker_match.span())
        elif token in ACRONYM_STOPWORDS:
            continue  # vocabulary, not a company -- checked after the catalog, not before
        elif token not in result.matched:
            result.unmatched.append(token)
    query = _mask(query, resolved)

    for phrase_match in _PROPER_NOUN_RE.finditer(query):
        phrase = _strip_possessive(phrase_match.group())
        if phrase_match.start() == 0 and phrase.lower() not in alias_index and phrase not in by_ticker:
            # Sentence-initial capitalisation is not proof of a proper noun -- but it
            # only explains the *first* word. "While Snowflake operates..." still names
            # a company, so drop the opener and judge what follows on its own.
            _, _, tail = phrase.partition(" ")
            phrase = _strip_possessive(tail)
            if not phrase:
                continue
        if all(_is_vocabulary(word) for word in phrase.split()):
            continue  # "the TTM margin", "the Fed", "AI Capex" are vocabulary, not companies
        if any(word.lower() in _QUESTION_STOPWORDS for word in phrase.split()):
            continue
        if phrase.lower() in alias_index or phrase in by_ticker:
            continue  # already captured above
        if phrase not in result.unmatched:
            result.unmatched.append(phrase)

    return result
