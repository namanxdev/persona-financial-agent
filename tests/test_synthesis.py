"""The synthesis path is only as safe as its validator, so the validator is the test.

Model output is injected rather than fetched, so these run offline and assert on
exactly the failure modes the guard exists to catch: cited evidence that was
never retrieved, companies that were never in the data, and figures the model
computed or invented instead of quoting.
"""

import json
from datetime import date

import pytest

from agent.evidence_guard import evidence_payload, validate
from agent.models import EvidenceItem, Synthesis
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
    result = synthesize(
        "equity_analyst", "tech", "How do these look?", get_persona("equity_analyst"),
        _evidence(), "mixed", complete=lambda _: _candidate().model_dump_json(),
    )
    assert result is not None
    answer = render(result)
    assert "45.1%" in answer and "Risks:" in answer and "Limitations:" in answer


def test_synthesize_falls_back_when_the_model_fabricates(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "on")
    fabricated = _candidate(supporting_points=["MSFT's operating margin (TTM) is 99.9%."])
    result = synthesize(
        "equity_analyst", "tech", "How do these look?", get_persona("equity_analyst"),
        _evidence(), "mixed", complete=lambda _: fabricated.model_dump_json(),
    )
    assert result is None


def test_synthesize_falls_back_when_the_model_returns_unusable_output(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SYNTHESIS", "on")
    for payload in ("not json at all", json.dumps({"thesis": "no other fields"})):
        result = synthesize(
            "pe_analyst", "tech", "How do these look?", get_persona("pe_analyst"),
            _evidence(), "cautious", complete=lambda _, p=payload: p,
        )
        assert result is None


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
    ) is None
    assert not called, "the switch must be checked before any provider call"


@pytest.mark.parametrize("evidence", [[]])
def test_no_evidence_never_reaches_the_model(evidence) -> None:
    assert synthesize(
        "pe_analyst", "tech", "How do these look?", get_persona("pe_analyst"),
        evidence, "mixed", complete=lambda _: _candidate().model_dump_json(),
    ) is None
