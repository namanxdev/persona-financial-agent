"""Stage 3 gate tests: real stdio MCP, persona divergence, grounding, confidence.

Every answer_query() call here spawns a real mcp_server subprocess (via
agent/mcp_client.py) against the committed database -- nothing is mocked.
"""

import asyncio
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from agent.confidence import Slot, compute_confidence
from agent.core import answer_query
from agent.models import QueryRequest
from agent.scope import resolve_mentions

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "agent_techhome.db"
FORBIDDEN = re.compile(r"\bsqlite3\b|\bimport duckdb\b|\bpsycopg\b")


def _run(request: QueryRequest):
    return asyncio.run(answer_query(request))


def test_agent_package_never_imports_a_db_driver() -> None:
    for path in (ROOT / "agent").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        # Docstrings may *mention* sqlite3 in prose explaining the boundary;
        # only flag it outside of triple-quoted comments/docstrings.
        code = re.sub(r'"""[\s\S]*?"""', "", text)
        assert not FORBIDDEN.search(code), f"forbidden DB-driver reference in {path}"


def test_scope_resolution_refuses_ordinary_mixed_case_name_before_retrieval() -> None:
    response = _run(QueryRequest(query="What do you think about Snowflake?", persona="equity_analyst", sector="tech"))
    assert "snowflake" in response.answer.lower() or "Snowflake" in response.answer
    assert response.confidence == "low"
    assert response.evidence == []
    assert response.companies_referenced == []
    assert response.tools_called == ["list_companies"]  # refused before any screen/financials call


def test_scope_resolution_refuses_unlisted_ticker_style_mention() -> None:
    response = _run(QueryRequest(query="What do you think about RIVN?", persona="pe_analyst", sector="logistics"))
    assert response.confidence == "low"
    assert response.evidence == []
    assert "RIVN" in response.answer


def test_persona_divergence_same_question_same_sector() -> None:
    query = "Is this sector a good place to be putting money to work right now?"
    responses = {
        persona: _run(QueryRequest(query=query, persona=persona, sector="tech"))
        for persona in ("mutual_fund_analyst", "equity_analyst", "pe_analyst")
    }
    sequences = {name: r.tools_called for name, r in responses.items()}
    company_sets = {name: set(r.companies_referenced) for name, r in responses.items()}

    names = list(sequences)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            assert sequences[names[i]] != sequences[names[j]], f"{names[i]} vs {names[j]} tool sequences matched"
            assert company_sets[names[i]] != company_sets[names[j]], f"{names[i]} vs {names[j]} company sets matched"

    for response in responses.values():
        assert response.evidence, "expected grounded evidence for an in-scope sector question"


def test_hiring_signal_stress_test_matches_real_db_value() -> None:
    connection = sqlite3.connect(DATABASE)
    expected = connection.execute(
        "SELECT value FROM hiring_signals WHERE ticker='XPO' ORDER BY observed_on DESC LIMIT 1"
    ).fetchone()[0]
    connection.close()

    response = _run(QueryRequest(
        query="What's the most recent headcount or hiring signal you have for XPO?",
        persona="pe_analyst", sector="logistics",
    ))
    assert response.companies_referenced == ["XPO"]
    headcount_evidence = [item for item in response.evidence if item.field == "headcount"]
    assert headcount_evidence
    assert headcount_evidence[0].value == expected
    assert str(int(expected)) in response.answer or f"{int(expected):,}" in response.answer


def test_every_evidence_item_traces_to_a_real_source_url() -> None:
    response = _run(QueryRequest(query="Which companies here look attractive?", persona="mutual_fund_analyst", sector="retail"))
    assert response.evidence
    for item in response.evidence:
        assert str(item.source_url).startswith("https://")
        assert item.as_of_date <= date.today()


def test_confidence_high_requires_full_freshness_and_coverage() -> None:
    today = date.today()
    fresh_slots = [Slot("AAPL", "revenue", 1.0, today), Slot("AAPL", "margin", 0.2, today)]
    result = compute_confidence(fresh_slots, today=today)
    assert result.coverage == 1.0
    assert result.freshness == 1.0
    assert result.tier == "high"


def test_confidence_drops_to_medium_or_low_with_missing_and_stale_slots() -> None:
    today = date.today()
    slots = [
        Slot("AAPL", "revenue", 1.0, today),
        Slot("AAPL", "margin", None, None),  # missing entirely
        Slot("AAPL", "growth", 0.1, today - timedelta(days=600)),  # stale
    ]
    result = compute_confidence(slots, today=today)
    assert result.coverage < 1.0
    assert result.tier in ("medium", "low")
    assert result.tier != "high"


def test_confidence_treats_future_dates_as_not_fresh() -> None:
    today = date.today()
    slots = [Slot("AAPL", "revenue", 1.0, today + timedelta(days=30))]
    result = compute_confidence(slots, today=today)
    assert result.freshness == 0.0


def test_scope_resolution_matches_alias_and_ticker_case_insensitively() -> None:
    from agent.models import CompanyRow

    catalog = [CompanyRow(ticker="FDX", name="FedEx Corporation", sector="logistics", as_of_date=date.today(), source_url="https://example.com")]
    result = resolve_mentions("tell me about fedex", catalog)
    assert "FDX" in result.matched
    assert result.unmatched == []
