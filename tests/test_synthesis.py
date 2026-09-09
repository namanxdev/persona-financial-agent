"""The synthesis path is only as safe as its validator, so the validator is the test.

Model output is injected rather than fetched, so these run offline and assert on
exactly the failure modes the guard exists to catch: cited evidence that was
never retrieved, companies that were never in the data, and figures the model
computed or invented instead of quoting.
"""

import json
from datetime import date

import pytest

from agent.core import _query_named_out_of_scope
from agent.evidence_guard import evidence_payload, out_of_scope_mentions, validate
from agent.models import CompanyRow, EvidenceItem, Synthesis
from agent.personas import get_persona
from agent.synthesis import render, synthesize


def _evidence() -> list[EvidenceItem]:
    return [
        EvidenceItem(
            evidence_id="MSFT:operating_margin_ttm", ticker="MSFT",
            field="operating_margin_ttm", value=0.45111, unit="ratio",
            as_of_date=date(2025, 6, 30), source_url="https://data.sec.gov/msft.json",
            source_lineage=[],
        ),
        EvidenceItem(
            evidence_id="AAPL:trailing_pe", ticker="AAPL", field="trailing_pe",
            value=32.5, unit="ratio", as_of_date=date(2025, 6, 30),
            source_url="https://data.sec.gov/aapl.json", source_lineage=[],
        ),
    ]


def _catalog() -> list[CompanyRow]:
    names = {"MSFT": "Microsoft Corporation", "AAPL": "Apple Inc."}
    return [
        CompanyRow(ticker=ticker, name=name, sector="tech",
                   as_of_date=date(2025, 6, 30), source_url="https://example.com")
        for ticker, name in names.items()
    ]


def _candidate(**overrides) -> Synthesis:
    fields = {
        "thesis": "MSFT screens best on operating quality in this cohort.",
        "supporting_points": ["MSFT's operating margin (TTM) is 45.1% as of 2025-06-30."],
        "risks": ["AAPL trades at 32.50x trailing earnings, leaving little room for error."],
        "limitations": ["Only two metrics were retrieved this turn."],
        "evidence_ids": ["MSFT:operating_margin_ttm", "AAPL:trailing_pe"],
    }
    fields.update(overrides)
    return Synthesis(**fields)


def test_payload_shows_the_model_display_strings_not_raw_floats() -> None:
    payload = evidence_payload(_evidence())
    assert payload[0]["display"] == "45.1%"
    assert payload[1]["display"] == "32.50x"
    assert all("value" not in row for row in payload)


def test_candidate_quoting_the_evidence_verbatim_is_accepted() -> None:
    assert validate(_candidate(), _evidence()) is None


def test_rejects_evidence_ids_that_were_never_retrieved() -> None:
    reason = validate(_candidate(evidence_ids=["MSFT:operating_margin_ttm", "NVDA:trailing_pe"]), _evidence())
    assert reason is not None and "not retrieved this turn" in reason


def test_rejects_a_fabricated_figure() -> None:
    reason = validate(
        _candidate(supporting_points=["MSFT's operating margin (TTM) is 61.4% as of 2025-06-30."]),
        _evidence(),
    )
    assert reason is not None and "absent from the evidence" in reason


def test_rejects_a_figure_the_model_computed_from_the_evidence() -> None:
    """Even arithmetic over real values is a number no tool returned."""
    reason = validate(
        _candidate(risks=["The two names average 38.8% on the metrics retrieved."]),
        _evidence(),
    )
    assert reason is not None and "absent from the evidence" in reason


def test_rejects_a_company_that_was_never_retrieved() -> None:
    reason = validate(_candidate(thesis="NVDA is the stronger operator here."), _evidence())
    assert reason is not None and "outside the retrieved evidence" in reason


def test_rejects_a_real_figure_attached_to_the_wrong_company() -> None:
    """Both numbers are genuine; the pairing is not. Membership alone would miss this."""
    reason = validate(
        _candidate(supporting_points=["AAPL's operating margin (TTM) is 45.1%."]),
        _evidence(),
    )
    assert reason is not None and "absent from the evidence" in reason


def test_allows_discussing_a_retrieved_company_it_did_not_formally_cite() -> None:
    """A live run rejected a good answer for naming AAPL without citing its row."""
    candidate = _candidate(
        risks=["AAPL is the weaker operator of the two."],
        evidence_ids=["MSFT:operating_margin_ttm"],
    )
    assert validate(candidate, _evidence()) is None


def test_financial_acronyms_are_not_mistaken_for_companies() -> None:
    """A live run rejected a good answer over "EV/EBITDA"; punctuated acronyms must pass."""
    candidate = _candidate(
        risks=["On an EV/EBITDA and P/E basis the US names look full, and FCF may lag."],
    )
    assert validate(candidate, _evidence()) is None


def test_rejects_an_empty_thesis() -> None:
    assert validate(_candidate(thesis="   "), _evidence()) is not None


def test_synthesize_returns_the_candidate_when_the_model_behaves(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "on")
    outcome = synthesize(
        "equity_analyst", "tech", "How do these look?", get_persona("equity_analyst"),
        _evidence(), "mixed", complete=lambda _: _candidate().model_dump_json(),
    )
    assert outcome.synthesis is not None
    answer = render(outcome.synthesis)
    assert "45.1%" in answer and "Risks:" in answer and "Limitations:" in answer


def test_synthesize_falls_back_when_the_model_fabricates(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "on")
    fabricated = _candidate(supporting_points=["MSFT's operating margin (TTM) is 99.9%."])
    outcome = synthesize(
        "equity_analyst", "tech", "How do these look?", get_persona("equity_analyst"),
        _evidence(), "mixed", complete=lambda _: fabricated.model_dump_json(),
    )
    assert outcome.synthesis is None


def test_synthesize_falls_back_when_the_model_returns_unusable_output(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "on")
    for payload in ("not json at all", json.dumps({"thesis": "no other fields"})):
        outcome = synthesize(
            "pe_analyst", "tech", "How do these look?", get_persona("pe_analyst"),
            _evidence(), "cautious", complete=lambda _, p=payload: p,
        )
        assert outcome.synthesis is None


def test_synthesis_switch_forces_the_deterministic_path(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "off")
    called = False

    def _complete(_: str) -> str:
        nonlocal called
        called = True
        return _candidate().model_dump_json()

    assert synthesize(
        "pe_analyst", "tech", "How do these look?", get_persona("pe_analyst"),
        _evidence(), "mixed", complete=_complete,
    ).synthesis is None
    assert not called, "the switch must be checked before any provider call"


@pytest.mark.parametrize("evidence", [[]])
def test_no_evidence_never_reaches_the_model(evidence) -> None:
    assert synthesize(
        "pe_analyst", "tech", "How do these look?", get_persona("pe_analyst"),
        evidence, "mixed", complete=lambda _: _candidate().model_dump_json(),
    ).synthesis is None


def test_rejects_a_company_named_in_prose_but_absent_from_the_catalog() -> None:
    """The bug this suite missed: an out-of-scope company written as a proper noun.

    Reproduced from a real answer. "what do you think about snowflake?" was
    all-lowercase, so agent/scope.py did not see a company and no refusal fired;
    the model was then handed the question and wrote a thesis *about* Snowflake
    using META and GOOGL figures. Every number was genuinely retrieved, so the
    numeric checks passed, and "Snowflake" is not ticker-shaped, so the uppercase
    check passed too. Only a catalog check catches it.
    """
    candidate = _candidate(
        thesis="While Snowflake operates in a high-growth tech sector, MSFT screens better.",
        limitations=["Lack of specific data on Snowflake's growth"],
    )
    assert "Snowflake" in out_of_scope_mentions(candidate, _catalog())
    reason = validate(candidate, _evidence(), _catalog())
    assert reason is not None and "outside the sector catalog" in reason


def test_ordinary_capitalised_prose_is_not_read_as_a_company() -> None:
    """Bullets and second sentences start with a capital; none of that is a company."""
    candidate = _candidate(
        thesis="MSFT screens best on operating quality. Additionally, margins look durable.",
        supporting_points=["Market volatility affecting tech stocks"],
        risks=["Potential for overvaluation", "Changing consumer preferences"],
        limitations=["Future growth projections are uncertain", "No direct comparison metrics"],
    )
    assert out_of_scope_mentions(candidate, _catalog()) == []
    assert validate(candidate, _evidence(), _catalog()) is None


def test_out_of_scope_names_are_reported_so_the_caller_can_refuse(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "on")
    draft = _candidate(thesis="MSFT screens well, but Snowflake looks stronger here.")
    outcome = synthesize(
        "mutual_fund_analyst", "tech", "what do you think about snowflake?",
        get_persona("mutual_fund_analyst"), _evidence(), "mixed",
        catalog=_catalog(), complete=lambda _: draft.model_dump_json(),
    )
    assert outcome.synthesis is None
    assert "Snowflake" in outcome.out_of_scope


def test_a_lowercase_question_about_an_uncovered_company_becomes_a_refusal() -> None:
    """The draft is discarded either way; the name decides refusal vs sector answer."""
    assert _query_named_out_of_scope(
        ("Snowflake",), "what do you think about snowflake?"
    ) == ["Snowflake"]
    assert _query_named_out_of_scope(
        ("Snowflake's",), "any view on snowflake?"
    ) == ["Snowflake"]


def test_a_name_the_model_raised_by_itself_does_not_trigger_a_refusal() -> None:
    """Only what the *question* asked about can turn a sector answer into a refusal.

    Otherwise the model name-dropping a peer ("unlike Nvidia...") would refuse a
    perfectly good sector question.
    """
    assert _query_named_out_of_scope(("Nvidia",), "how does this sector look?") == []


def test_financial_acronyms_are_not_read_as_companies_by_either_side() -> None:
    """A live run rejected a good PE answer over "EV". The resolver and the guard
    now share one vocabulary list, so an acronym cannot be a company on one side
    of the boundary and not the other."""
    candidate = _candidate(
        risks=["Screening on EV/EBITDA and FCF, the US names look full versus GAAP earnings."],
    )
    assert out_of_scope_mentions(candidate, _catalog()) == []
    assert validate(candidate, _evidence(), _catalog()) is None


def test_a_bullet_opening_with_a_word_from_the_question_is_not_a_company() -> None:
    """A live run refused "the margin and valuation picture" because the answer
    opened a bullet with "Valuation". Refusing a question the data can answer is
    a worse failure than a plainer answer, so sentence-initial words stay exempt."""
    candidate = _candidate(
        risks=["Valuation looks stretched.", "Market volatility is a factor."],
        limitations=["Growth is measured on trailing data only."],
    )
    assert out_of_scope_mentions(candidate, _catalog()) == []
    assert validate(candidate, _evidence(), _catalog()) is None
