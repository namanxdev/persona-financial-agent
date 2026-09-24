"""The synthesis path: model output is injected rather than fetched, so these run offline.

The validator itself is tested in tests/test_evidence_guard.py. These cover
what synthesize() does with its verdict -- ship the draft, fall back to the
deterministic composer, never call the provider when switched off -- and how an
out-of-scope name in a discarded draft becomes a refusal.
"""

import json

import pytest

from agent.core import _query_named_out_of_scope
from agent.personas import get_persona
from agent.synthesis import render, synthesize
from tests.guard_fixtures import candidate, catalog, evidence, listed_lookup


def test_synthesize_returns_the_candidate_when_the_model_behaves(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "on")
    outcome = synthesize(
        "equity_analyst", "tech", "How do these look?", get_persona("equity_analyst"),
        evidence(), "mixed", complete=lambda _: candidate().model_dump_json(),
    )
    assert outcome.synthesis is not None
    answer = render(outcome.synthesis)
    assert "45.1%" in answer and "Risks:" in answer and "Limitations:" in answer


def test_synthesize_falls_back_when_the_model_fabricates(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "on")
    fabricated = candidate(supporting_points=["MSFT's operating margin (TTM) is 99.9%."])
    outcome = synthesize(
        "equity_analyst", "tech", "How do these look?", get_persona("equity_analyst"),
        evidence(), "mixed", complete=lambda _: fabricated.model_dump_json(),
    )
    assert outcome.synthesis is None


def test_synthesize_falls_back_when_the_model_returns_unusable_output(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "on")
    for payload in ("not json at all", json.dumps({"thesis": "no other fields"})):
        outcome = synthesize(
            "pe_analyst", "tech", "How do these look?", get_persona("pe_analyst"),
            evidence(), "cautious", complete=lambda _, p=payload: p,
        )
        assert outcome.synthesis is None


def test_synthesis_switch_forces_the_deterministic_path(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "off")
    called = False

    def _complete(_: str) -> str:
        nonlocal called
        called = True
        return candidate().model_dump_json()

    assert synthesize(
        "pe_analyst", "tech", "How do these look?", get_persona("pe_analyst"),
        evidence(), "mixed", complete=_complete,
    ).synthesis is None
    assert not called, "the switch must be checked before any provider call"


@pytest.mark.parametrize("rows", [[]])
def test_no_evidence_never_reaches_the_model(rows) -> None:
    assert synthesize(
        "pe_analyst", "tech", "How do these look?", get_persona("pe_analyst"),
        rows, "mixed", complete=lambda _: candidate().model_dump_json(),
    ).synthesis is None


def test_out_of_scope_names_are_reported_so_the_caller_can_refuse(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "on")
    draft = candidate(thesis="MSFT screens well, but Snowflake looks stronger here.")
    outcome = synthesize(
        "mutual_fund_analyst", "tech", "what do you think about snowflake?",
        get_persona("mutual_fund_analyst"), evidence(), "mixed",
        catalog=catalog(), complete=lambda _: draft.model_dump_json(), lookup=listed_lookup,
    )
    assert outcome.synthesis is None
    assert "Snowflake" in outcome.out_of_scope


def test_a_lowercase_question_about_an_uncovered_company_becomes_a_refusal() -> None:
    """The draft is discarded either way; the name decides refusal vs sector answer."""
    assert _query_named_out_of_scope(("Snowflake",), "what do you think about snowflake?") == ["Snowflake"]
    assert _query_named_out_of_scope(("Snowflake's",), "any view on snowflake?") == ["Snowflake"]


def test_a_name_the_model_raised_by_itself_does_not_trigger_a_refusal() -> None:
    """Only what the *question* asked about can turn a sector answer into a refusal.

    Otherwise the model name-dropping a peer ("unlike Nvidia...") would refuse a
    perfectly good sector question.
    """
    assert _query_named_out_of_scope(("Nvidia",), "how does this sector look?") == []


def test_render_separates_list_items_and_closes_each_section() -> None:
    """Items used to be joined with bare spaces: "Supporting evidence: Free cash flow
    (TTM) of $5.7B Headcount of 300,000 employees EV/EBITDA of 8.92x..."."""
    draft = candidate(
        thesis="FDX generates cash",
        supporting_points=["Free cash flow (TTM) of $5.7B", "Headcount of 300,000 employees."],
        risks=["Leverage could rise"],
        limitations=[],
    )
    assert render(draft) == (
        "FDX generates cash. Supporting evidence: Free cash flow (TTM) of $5.7B; "
        "Headcount of 300,000 employees. Risks: Leverage could rise."
    )
