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
from agent.models import CompanyRow, QueryRequest, QueryResponse
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

        return _build_response(request, policy, bundle, client.tool_calls, companies)


def _query_named_out_of_scope(names: tuple[str, ...], query: str) -> list[str]:
    """Names a discarded draft used that the question named too.

    agent/scope.py only recognises a company written as a proper noun, so an
    all-lowercase "what do you think about snowflake?" reaches retrieval as an
    ordinary sector question. If the model then writes about a company the
    catalog does not contain, and the question names it as well, the question
    was about a company outside the dataset and the refusal is the right reply.

    Only the name is taken from the discarded draft, only after the catalog has
    already rejected it, and the reply itself is a fixed template -- no model
    text reaches the user.
    """
    lowered = query.lower()
    found: list[str] = []
    for name in names:
        bare = name[:-2] if name.endswith("'s") else name
        if bare.lower() in lowered and bare not in found:
            found.append(bare)
    return found


def _build_response(
    request: QueryRequest,
    policy: PersonaPolicy,
    bundle: RetrievalBundle,
    tools_called: list[str],
    catalog: list[CompanyRow],
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
    result = synthesize(
        request.persona, request.sector, request.query, policy, evidence, framing.stance, catalog
    )
    refused = _query_named_out_of_scope(result.out_of_scope, request.query)
    if refused:
        return QueryResponse(
            answer=out_of_scope_answer(request.sector, refused),
            persona=request.persona,
            sector=request.sector,
            companies_referenced=[],
            evidence=[],
            confidence="low",
            tools_called=list(tools_called),
        )
    synthesis = result.synthesis
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
