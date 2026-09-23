"""Question focus: which metric a question is actually about, from a closed list.

The persona sets the lens (agent/personas.py fixes what each one retrieves);
the question adds a focus. Without this, retrieval was persona x sector only, so
"Which logistics company carries the least debt?" asked of the mutual-fund
persona came back as a revenue-growth ranking.

No model chooses metrics. Each trigger is a fixed lowercase keyword mapped to a
real database column and a default ranking direction, so every retrieval shape
the focus can add is still enumerable. A direction word ("least", "highest")
overrides the default when it sits within a few words of the trigger; the
nearest one wins, so "the highest growth and the least debt" ranks growth
descending and debt ascending.
"""

import re

from agent.models import Direction

_TRIGGERS: tuple[tuple[re.Pattern[str], str, Direction], ...] = (
    (re.compile(r"\b(?:debts?|borrow\w*)\b"), "total_debt", "asc"),
    (re.compile(r"\b(?:leverag\w*|levered|balance[- ]sheets?)\b"), "liabilities_to_equity", "asc"),
    (re.compile(r"\b(?:growth|growing)\b"), "revenue_growth_yoy", "desc"),
    (re.compile(r"\b(?:margins?|profitab\w*)\b"), "operating_margin_ttm", "desc"),
    (re.compile(r"\b(?:valuations?|cheap\w*|expensive|multiples?|p/e)\b"), "trailing_pe", "asc"),
    (re.compile(r"\b(?:cash[- ]flows?|fcf|cash generation)\b"), "free_cash_flow_ttm", "desc"),
)
_DIRECTION_WORDS: dict[str, Direction] = {
    "most": "desc", "highest": "desc", "largest": "desc", "biggest": "desc",
    "least": "asc", "lowest": "asc", "smallest": "asc", "cheapest": "asc",
}
_WINDOW = 3  # words either side of a trigger that may set its direction
_WORD = re.compile(r"[a-z/']+")


def _direction(before: list[str], after: list[str], default: Direction) -> Direction:
    """Nearest direction word wins; at equal distance the one before the trigger does."""
    before = before[-_WINDOW:][::-1]
    after = after[:_WINDOW]
    for distance in range(_WINDOW):
        for words in (before, after):
            if distance < len(words) and words[distance] in _DIRECTION_WORDS:
                return _DIRECTION_WORDS[words[distance]]
    return default


def question_focus(query: str) -> list[tuple[str, Direction]]:
    """(metric, direction) pairs the question asks about, in order of mention, de-duplicated."""
    text = query.lower()
    hits = sorted(
        (match.start(), match.end(), metric, default)
        for pattern, metric, default in _TRIGGERS
        for match in pattern.finditer(text)
    )
    focus: list[tuple[str, Direction]] = []
    for index, (start, end, metric, default) in enumerate(hits):
        if any(metric == seen for seen, _ in focus):
            continue
        # A direction word between two triggers can only belong to one of them, so
        # each trigger looks no further than its neighbours.
        lower = hits[index - 1][1] if index else 0
        upper = hits[index + 1][0] if index + 1 < len(hits) else len(text)
        before = _WORD.findall(text[lower:start])
        after = _WORD.findall(text[end:upper])
        focus.append((metric, _direction(before, after, default)))
    return focus
