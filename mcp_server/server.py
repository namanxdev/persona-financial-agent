"""FastMCP stdio server: registers the four database tools and runs the transport.

Note: normally this file is user-owned per AGENTS.md. The user explicitly lifted
that restriction for this session (see task briefing) and asked for a full
implementation rather than a signature-only stub.
"""

import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mcp_server import database as db
from mcp_server import tools
from mcp_server.models import CompanyRow, Direction, FinancialRow, HiringSignalRow, ScreenResult, Sector

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "agent_techhome.db"


def create_server(database_path: Path) -> FastMCP:
    """Build the FastMCP instance. One sqlite3 connection is opened read-only
    and shared by every tool call for the life of the process."""
    server = FastMCP("agent-techhome")
    connection = db.connect(database_path)

    @server.tool()
    async def list_companies(sector: Sector) -> list[CompanyRow]:
        """List companies in one of the three covered sectors."""
        return await tools.list_companies(connection, sector)

    @server.tool()
    async def get_financials(ticker: str, metrics: list[str]) -> list[FinancialRow]:
        """Fetch the newest observation for each requested metric on one ticker."""
        return await tools.get_financials(connection, ticker, metrics)

    @server.tool()
    async def get_hiring_signals(ticker: str, limit: int) -> list[HiringSignalRow]:
        """Fetch the most recent headcount/hiring signals for one ticker."""
        return await tools.get_hiring_signals(connection, ticker, limit)

    @server.tool()
    async def run_sector_screen(sector: Sector, metric: str, direction: Direction, limit: int) -> ScreenResult:
        """Rank companies in a sector by one metric, excluding incomparable rows."""
        return await tools.run_sector_screen(connection, sector, metric, direction, limit)

    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = create_server(args.database.resolve())
    server.run("stdio")


if __name__ == "__main__":
    main()
