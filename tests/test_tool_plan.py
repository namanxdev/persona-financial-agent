"""Each persona's declared tool_plan must be the plan that actually runs.

agent/retrieval.py reads tool_plan only to branch (tool_plan[1], and whether it
lists get_hiring_signals), so the declared order could drift from the executed
one without any other test noticing -- while the declared plan is what the docs
present as each persona's fingerprint.
"""

import asyncio
from itertools import groupby

import pytest

from agent.core import answer_query
from agent.models import PersonaName, QueryRequest, Sector
from agent.personas import get_persona, list_personas

DIVERGENCE_QUESTIONS: list[tuple[str, Sector]] = [
    ("Is this sector a good place to be putting money to work right now?", "tech"),
    ("Which companies here look attractive right now?", "retail"),
    ("What is the outlook for this sector?", "logistics"),
]


@pytest.mark.parametrize("persona", list_personas())
@pytest.mark.parametrize(("query", "sector"), DIVERGENCE_QUESTIONS)
def test_executed_tool_calls_follow_the_declared_plan(persona: PersonaName, query: str, sector: Sector) -> None:
    response = asyncio.run(answer_query(QueryRequest(query=query, persona=persona, sector=sector)))
    executed = [name for name, _ in groupby(response.tools_called)]  # consecutive repeats collapsed
    assert executed == get_persona(persona).tool_plan
