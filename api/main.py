"""POST /query: the programmatic entry point onto the shared agent function.

This route performs no retrieval or generation of its own: it validates the
request body into QueryRequest and delegates entirely to answer_query, the
same function ui/app.py calls. Invalid persona/sector values never reach this
handler -- Pydantic rejects them while parsing the request body. An MCP/tool
failure surfaces as a 502 rather than a silently degraded answer.

Run with: uvicorn api.main:app --reload
"""

from fastapi import FastAPI, HTTPException

from agent.core import answer_query
from agent.mcp_client import McpToolError
from agent.models import QueryRequest, QueryResponse

app = FastAPI(title="agent-techhome", description="Persona-configurable sector research agent")


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    try:
        return await answer_query(request)
    except McpToolError as exc:
        raise HTTPException(status_code=502, detail=f"MCP tool failure: {exc}") from exc
