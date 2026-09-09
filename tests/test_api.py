"""API tests: POST /query delegates to answer_query and nothing else."""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_query_returns_structured_response_matching_the_contract() -> None:
    response = client.post("/query", json={
        "query": "Which companies in this sector look like attractive buyout targets?",
        "persona": "pe_analyst", "sector": "logistics",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["persona"] == "pe_analyst"
    assert body["sector"] == "logistics"
    assert body["confidence"] in ("low", "medium", "high")
    assert isinstance(body["tools_called"], list) and body["tools_called"][0] == "list_companies"
    assert isinstance(body["companies_referenced"], list)
    assert isinstance(body["evidence"], list)
    for item in body["evidence"]:
        assert set(("evidence_id", "ticker", "field", "value", "unit", "as_of_date", "source_url", "source_lineage")) <= item.keys()


def test_query_rejects_invalid_persona_with_typed_validation_error() -> None:
    response = client.post("/query", json={"query": "hello", "persona": "day_trader", "sector": "tech"})
    assert response.status_code == 422


def test_query_rejects_invalid_sector_with_typed_validation_error() -> None:
    response = client.post("/query", json={"query": "hello", "persona": "equity_analyst", "sector": "manufacturing"})
    assert response.status_code == 422


def test_query_rejects_missing_fields() -> None:
    response = client.post("/query", json={"persona": "equity_analyst", "sector": "tech"})
    assert response.status_code == 422


def test_query_returns_explicit_refusal_for_unknown_company() -> None:
    response = client.post("/query", json={
        "query": "What do you think about Snowflake?", "persona": "equity_analyst", "sector": "tech",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == "low"
    assert body["evidence"] == []
    assert "Snowflake" in body["answer"]


def test_query_tools_called_preserves_repeated_calls() -> None:
    response = client.post("/query", json={
        "query": "Walk me through the margin profile of the companies in your data.",
        "persona": "equity_analyst", "sector": "tech",
    })
    body = response.json()
    assert body["tools_called"].count("get_financials") > 1
