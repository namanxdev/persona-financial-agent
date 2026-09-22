"""The opening stance must not pretend to read a signal it cannot read.

The old keyless rule averaged every retrieved value -- FCF dollars, P/E
multiples, margins, headcounts -- so the stance was just the sign of the largest
number and every keyless answer opened "constructive momentum", even for a
question about margin worries.
"""

import asyncio

import pytest

from agent.core import answer_query
from agent.llm import choose_framing
from agent.models import QueryRequest
from agent.personas import get_persona
from agent.synthesis import build_prompt


@pytest.mark.parametrize("signals", [[], ["ORCL free_cash_flow_ttm=-24540000000.0"]])
def test_keyless_framing_is_neutral(monkeypatch, signals: list[str]) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    choice = choose_framing("pe_analyst", "tech", "How do these look?", signals)
    assert choice.stance == "neutral"
    assert choice.mode == "deterministic_fallback"


def test_keyless_answer_does_not_claim_a_stance(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = asyncio.run(answer_query(QueryRequest(
        query="I am worried about margins in this sector. Who is most exposed?",
        persona="equity_analyst", sector="retail",
    )))
    assert "here is what the retrieved data shows" in response.answer
    assert "constructive" not in response.answer


def test_neutral_stance_leaves_the_judgement_to_the_model() -> None:
    prompt = build_prompt("equity_analyst", "tech", "q", get_persona("equity_analyst"), [], "neutral")
    assert "Decide the overall stance yourself from the evidence." in prompt
    assert "Overall stance to take" not in prompt


def test_model_calls_run_off_the_event_loop(monkeypatch) -> None:
    """The provider clients are synchronous; called on the loop, one slow model
    reply would stall every other in-flight API request."""
    import threading

    from agent import core

    seen: dict[str, object] = {}
    real = core.choose_framing

    def spy(*args, **kwargs):
        seen["thread"] = threading.current_thread()
        return real(*args, **kwargs)

    monkeypatch.setattr(core, "choose_framing", spy)

    async def run():
        seen["loop_thread"] = threading.current_thread()
        return await answer_query(QueryRequest(
            query="Which companies here look attractive?", persona="equity_analyst", sector="tech",
        ))

    asyncio.run(run())
    assert seen["thread"] is not seen["loop_thread"]
