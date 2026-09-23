"""The synthesis path is only as safe as its validator, so the validator is the test.

These are pure checks of agent/evidence_guard.py against fixed drafts: cited
evidence that was never retrieved, companies that were never in the data, and
figures the model computed or invented instead of quoting.
"""

import pytest

from agent.evidence_guard import evidence_payload, out_of_scope_mentions, validate
from tests.guard_fixtures import candidate, catalog, evidence


def test_payload_shows_the_model_display_strings_not_raw_floats() -> None:
    payload = evidence_payload(evidence())
    assert [row["display"] for row in payload][:2] == ["45.1%", "36.61x"]
    assert all("value" not in row for row in payload)


def test_candidate_quoting_the_evidence_verbatim_is_accepted() -> None:
    assert validate(candidate(), evidence()) is None


def test_rejects_evidence_ids_that_were_never_retrieved() -> None:
    reason = validate(candidate(evidence_ids=["MSFT:operating_margin_ttm", "NVDA:trailing_pe"]), evidence())
    assert reason is not None and "not retrieved this turn" in reason


def test_rejects_a_fabricated_figure() -> None:
    draft = candidate(supporting_points=["MSFT's operating margin (TTM) is 61.4% as of 2026-09-07."])
    reason = validate(draft, evidence())
    assert reason is not None and "absent from the evidence" in reason


def test_rejects_a_figure_the_model_computed_from_the_evidence() -> None:
    """Even arithmetic over real values is a number no tool returned."""
    reason = validate(candidate(risks=["The two names average 38.8% on the metrics retrieved."]), evidence())
    assert reason is not None and "absent from the evidence" in reason


def test_rejects_a_company_that_was_never_retrieved() -> None:
    reason = validate(candidate(thesis="NVDA is the stronger operator here."), evidence())
    assert reason is not None and "outside the retrieved evidence" in reason


def test_rejects_a_real_figure_attached_to_the_wrong_company() -> None:
    """Both numbers are genuine; the pairing is not. Membership alone would miss this."""
    reason = validate(candidate(supporting_points=["AAPL's operating margin (TTM) is 45.1%."]), evidence())
    assert reason is not None and "absent from the evidence" in reason


def test_allows_discussing_a_retrieved_company_it_did_not_formally_cite() -> None:
    """A live run rejected a good answer for naming AAPL without citing its row."""
    draft = candidate(risks=["AAPL is the weaker operator of the two."], evidence_ids=["MSFT:operating_margin_ttm"])
    assert validate(draft, evidence()) is None


def test_financial_acronyms_are_not_mistaken_for_companies() -> None:
    """A live run rejected a good answer over "EV/EBITDA"; punctuated acronyms must pass."""
    draft = candidate(risks=["On an EV/EBITDA and P/E basis the US names look full, and FCF may lag."])
    assert validate(draft, evidence()) is None


def test_rejects_an_empty_thesis() -> None:
    assert validate(candidate(thesis="   "), evidence()) is not None


def test_rejects_a_company_named_in_prose_but_absent_from_the_catalog() -> None:
    """The bug an earlier suite missed: an out-of-scope company written as a proper noun.

    Reproduced from a real answer. "what do you think about snowflake?" was
    all-lowercase, so agent/scope.py did not see a company and no refusal fired;
    the model was then handed the question and wrote a thesis *about* Snowflake
    using META and GOOGL figures. Every number was genuinely retrieved, so the
    numeric checks passed, and "Snowflake" is not ticker-shaped, so the uppercase
    check passed too. Only a catalog check catches it.
    """
    draft = candidate(
        thesis="While Snowflake operates in a high-growth tech sector, MSFT screens better.",
        limitations=["Lack of specific data on Snowflake's growth"],
    )
    assert "Snowflake" in out_of_scope_mentions(draft, catalog())
    reason = validate(draft, evidence(), catalog())
    assert reason is not None and "outside the sector catalog" in reason


def test_ordinary_capitalised_prose_is_not_read_as_a_company() -> None:
    """Bullets and second sentences start with a capital; none of that is a company."""
    draft = candidate(
        thesis="MSFT screens best on operating quality. Additionally, margins look durable.",
        supporting_points=["Market volatility affecting tech stocks"],
        risks=["Potential for overvaluation", "Changing consumer preferences"],
        limitations=["Future growth projections are uncertain", "No direct comparison metrics"],
    )
    assert out_of_scope_mentions(draft, catalog()) == []
    assert validate(draft, evidence(), catalog()) is None


def test_financial_acronyms_are_not_read_as_companies_by_either_side() -> None:
    """A live run rejected a good PE answer over "EV". The resolver and the guard
    share one vocabulary list, so an acronym cannot be a company on one side of
    the boundary and not the other."""
    draft = candidate(risks=["Screening on EV/EBITDA and FCF, the US names look full versus GAAP earnings."])
    assert out_of_scope_mentions(draft, catalog()) == []
    assert validate(draft, evidence(), catalog()) is None


def test_a_bullet_opening_with_a_word_from_the_question_is_not_a_company() -> None:
    """A live run refused "the margin and valuation picture" because the answer
    opened a bullet with "Valuation". Refusing a question the data can answer is
    a worse failure than a plainer answer, so sentence-initial words stay exempt."""
    draft = candidate(
        risks=["Valuation looks stretched.", "Market volatility is a factor."],
        limitations=["Growth is measured on trailing data only."],
    )
    assert out_of_scope_mentions(draft, catalog()) == []
    assert validate(draft, evidence(), catalog()) is None


def test_negative_dollars_render_with_the_sign_before_the_currency() -> None:
    assert evidence_payload(evidence())[2]["display"] == "-$24.5B"


@pytest.mark.parametrize("sentence", [
    "ORCL generated $24.5M of free cash flow.",  # magnitude: B became M
    "ORCL generated $24.5B of free cash flow.",  # sign dropped
    "MSFT trades at 45.1x earnings.",  # unit: a percent restated as a multiple
    "Apple's operating margin (TTM) is 45.1%.",  # MSFT's figure attached to a company *name*
    "MSFT's operating margin (TTM) is 45.1% as of 2026-09-08.",  # a date nobody retrieved
])
def test_rejects_a_figure_with_the_wrong_sign_unit_magnitude_or_owner(sentence: str) -> None:
    reason = validate(candidate(supporting_points=[sentence]), evidence(), catalog())
    assert reason is not None and "absent from the evidence" in reason


@pytest.mark.parametrize("sentence", [
    "MSFT's operating margin (TTM) is 45.1% as of 2026-09-07.",
    "ORCL's free cash flow (TTM) is -$24.5B.",
    "ORCL's free cash flow (TTM) is −$24.5B.",  # unicode minus
    "ORCL's free cash flow (TTM) is $-24.5B.",  # sign after the currency symbol
    "Microsoft's operating margin (TTM) is 45.1%.",
    "MSFT's CAGR looks durable.",
])
def test_accepts_a_figure_quoted_with_its_sign_unit_and_owner(sentence: str) -> None:
    assert validate(candidate(supporting_points=[sentence]), evidence(), catalog()) is None
