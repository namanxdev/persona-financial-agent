"""The agent's only path to data: a stdio MCP client session against a
separately-launched server process.

No module under agent/ imports a database driver, and none names the server
package -- every fact the agent can cite arrives through session.call_tool()
over a real subprocess boundary. If the server process dies or a call errors,
McpToolError propagates; there is no direct-handler or database fallback.
The concrete launch command (which module, which interpreter) is owned by
server_launch.py, a neutral module outside both agent/ and the server package.
"""

from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from agent.models import CompanyRow, Direction, FinancialRow, HiringSignalRow, ScreenResult, Sector
from server_launch import DEFAULT_DATABASE, server_command


class McpToolError(RuntimeError):
    """Raised when the MCP server reports isError=True or the transport fails."""


class AgentMcpClient:
    """Owns one stdio subprocess running the MCP server and its client session.

    Use as an async context manager so the subprocess is always torn down:
        async with AgentMcpClient() as client:
            rows = await client.list_companies("tech")
    """

    def __init__(self, database_path: Path = DEFAULT_DATABASE) -> None:
        self._database_path = database_path
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None
        self.tool_calls: list[str] = []  # chronological, including repeats

    async def __aenter__(self) -> "AgentMcpClient":
        command, args, cwd = server_command(self._database_path)
        params = StdioServerParameters(command=command, args=args, cwd=cwd)
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stack.aclose()
        self._session = None

    async def _call(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise McpToolError("MCP session is not connected; use 'async with AgentMcpClient()'")
        self.tool_calls.append(name)
        try:
            result = await self._session.call_tool(name, arguments)
        except Exception as exc:  # transport/subprocess failure -- surface, never fall back
            raise McpToolError(f"{name} transport failure: {exc}") from exc
        if result.isError:
            message = result.content[0].text if result.content else "unknown MCP tool error"
            raise McpToolError(message)
        if result.structuredContent is None:
            raise McpToolError(f"{name} returned no structured content")
        return result.structuredContent

    async def list_companies(self, sector: Sector) -> list[CompanyRow]:
        payload = await self._call("list_companies", {"sector": sector})
        return [CompanyRow.model_validate(row) for row in payload["result"]]

    async def get_financials(self, ticker: str, metrics: list[str]) -> list[FinancialRow]:
        payload = await self._call("get_financials", {"ticker": ticker, "metrics": metrics})
        return [FinancialRow.model_validate(row) for row in payload["result"]]

    async def get_hiring_signals(self, ticker: str, limit: int) -> list[HiringSignalRow]:
        payload = await self._call("get_hiring_signals", {"ticker": ticker, "limit": limit})
        return [HiringSignalRow.model_validate(row) for row in payload["result"]]

    async def run_sector_screen(self, sector: Sector, metric: str, direction: Direction, limit: int) -> ScreenResult:
        payload = await self._call(
            "run_sector_screen", {"sector": sector, "metric": metric, "direction": direction, "limit": limit}
        )
        return ScreenResult.model_validate(payload)
