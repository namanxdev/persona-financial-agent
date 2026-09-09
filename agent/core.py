"""Shared agent entry point: the one orchestration function behind both interfaces.

FastAPI (api/main.py) and Streamlit (ui/app.py) both call answer_query and
nothing else -- one implementation, two entry points. Every request opens a
fresh stdio MCP session; there is no caching and no fallback to model
knowledge if the server or a tool call fails.
"""

from datetime import date

from agent.confidence import compute_confidence
from agent.grounding import compose_answer, out_of_scope_answer
from agent.llm import choose_framing
from agent.mcp_client import AgentMcpClient
from agent.models import QueryRequest, QueryResponse
from agent.personas import PersonaPolicy, get_persona
from agent.retrieval import RetrievalBundle, run_company_focus, run_sector_wide
from agent.scope import resolve_mentions
from agent.synthesis import render, synthesize


async def answer_query(request: QueryRequest) -> QueryResponse:
    policy = get_persona(request.persona)
    async with AgentMcpClient() as client:
        companies = await client.list_companies(request.sector)
        scope = resolve_mentions(request.query, companies)

        if scope.unmatched:
            return QueryResponse(
                answer=out_of_scope_answer(request.sector, scope.unmatched),
                persona=request.persona,
                sector=request.sector,
                companies_referenced=[],
                evidence=[],
                confidence="low",
                tools_called=list(client.tool_calls),
            )

        if scope.matched:
            bundle = await run_company_focus(client, policy, sorted(scope.matched), request.query)
        else:
            bundle = await run_sector_wide(client, policy, request.sector, companies)

        return _build_response(request, policy, bundle, client.tool_calls)


def _build_response(
    request: QueryRequest, policy: PersonaPolicy, bundle: RetrievalBundle, tools_called: list[str]
) -> QueryResponse:
    signal_values = [float(slot.value) for slot in bundle.slots if isinstance(slot.value, (int, float))]
    framing = choose_framing(request.persona, request.sector, request.query, signal_values)
    answer, evidence = compose_answer(
        request.persona,
        request.sector,
        policy,
        framing,
        bundle.primary_screen,
        bundle.secondary_screen,
        bundle.financials,
        bundle.hiring,
    )
    # Deterministic composition always runs first: it produces the evidence set and
    # the answer that ships whenever synthesis is unavailable or fails validation.
    synthesis = synthesize(
        request.persona, request.sector, request.query, policy, evidence, framing.stance
    )
    if synthesis is not None:
        answer = render(synthesis)
    confidence = compute_confidence(bundle.slots, today=date.today()).tier if evidence else "low"
    companies_referenced = sorted({item.ticker for item in evidence})
    return QueryResponse(
        answer=answer,
        persona=request.persona,
        sector=request.sector,
        companies_referenced=companies_referenced,
        evidence=evidence,
        confidence=confidence,
        tools_called=list(tools_called),
        synthesis=synthesis,
    )
