"""Read-only SEC company registry indexed for bounded, exact candidate lookups."""

import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Literal

from mcp_server.models import ListedCompanyRow

_SUFFIXES = set("inc incorporated corp corporation co company ltd limited plc llc lp sa nv ag se com".split())
_NAME_INPUT = re.compile(r"^[A-Za-z][A-Za-z0-9 .,&'\-]*$")
_TICKER_INPUT = re.compile(r"^[A-Z]{1,5}$")
_JURISDICTION = re.compile(r"\s*[/\\]\s*[A-Za-z]{2,3}\s*[/\\]?\s*$")


def normalize_name(text: str) -> str:
    value = _JURISDICTION.sub("", text.strip()).lower().replace("&", " and ")
    value = value.replace(".com", " com")
    value = re.sub(r"[.,']", "", value)
    words = value.split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    if words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


class ListedRegistry:
    def __init__(self, rows: list[list[Any]], source_url: str, as_of_date: date) -> None:
        self.source_url = source_url
        self.as_of_date = as_of_date
        self.by_ticker: dict[str, list[Any]] = {}
        self.by_name: dict[str, list[list[Any]]] = defaultdict(list)
        first_rows: dict[str, list[list[Any]]] = defaultdict(list)
        nonfirst: Counter[str] = Counter()
        for row in rows:
            self.by_ticker.setdefault(str(row[2]).upper(), row)
            normalized = normalize_name(str(row[1]))
            if not normalized:
                continue
            self.by_name[normalized].append(row)
            words = normalized.split()
            first_rows[words[0]].append(row)
            nonfirst.update(set(words[1:]))
        self.by_first_word = {
            word: matches[0] for word, matches in first_rows.items()
            if len(word) >= 4 and len(matches) == 1 and nonfirst[word] == 0
        }
        self.by_prefix = first_rows

    @classmethod
    def load(cls, path: Path) -> "ListedRegistry":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("fields") != ["cik", "name", "ticker", "exchange"]:
            raise ValueError("invalid listed-company registry fields")
        if not isinstance(payload.get("data"), list):
            raise ValueError("invalid listed-company registry data")
        return cls(payload["data"], payload["source_url"], date.fromisoformat(payload["as_of_date"]))

    @property
    def tickers(self) -> set[str]:
        return set(self.by_ticker)

    def _result(self, query: str, kind: Literal["ticker", "name"], row: list[Any]) -> ListedCompanyRow:
        return ListedCompanyRow(
            query=query, match_kind=kind, cik=row[0], name=row[1], ticker=row[2], exchange=row[3],
            source_url=self.source_url, as_of_date=self.as_of_date,
        )

    def lookup(self, names: list[str], tickers: list[str]) -> list[ListedCompanyRow]:
        if len(names) > 20 or len(tickers) > 20:
            raise ValueError("at most 20 names and 20 tickers are allowed")
        if any(len(name) > 60 or not _NAME_INPUT.fullmatch(name) for name in names):
            raise ValueError("invalid company name candidate")
        if any(not _TICKER_INPUT.fullmatch(ticker) for ticker in tickers):
            raise ValueError("invalid ticker candidate")
        results: list[ListedCompanyRow] = []
        for ticker in tickers:
            row = self.by_ticker.get(ticker)
            if row is not None:
                results.append(self._result(ticker, "ticker", row))
        for name in names:
            normalized = normalize_name(name)
            matches = self.by_name.get(normalized, [])
            if not matches:
                words = normalized.split()
                if len(words) == 1:
                    row = self.by_first_word.get(normalized)
                    matches = [row] if row else []
                elif words:
                    matches = [row for row in self.by_prefix.get(words[0], [])
                               if normalize_name(str(row[1])).startswith(normalized + " ")]
            results.extend(self._result(name, "name", row) for row in matches)
        return results
