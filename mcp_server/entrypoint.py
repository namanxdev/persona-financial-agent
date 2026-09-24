"""Start the existing database server with the SEC registry tool attached."""

import argparse
from pathlib import Path

from mcp_server import tools
from mcp_server.models import ListedCompanyRow
from mcp_server.registry import ListedRegistry
from mcp_server.server import DEFAULT_DATABASE, ROOT, create_server

DEFAULT_REGISTRY = ROOT / "data" / "listed_companies.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    server = create_server(args.database.resolve())
    registry = ListedRegistry.load(args.registry.resolve())

    @server.tool()
    async def lookup_companies(names: list[str], tickers: list[str]) -> list[ListedCompanyRow]:
        """Look up candidate names/tickers in SEC's registry of US-listed companies."""
        return await tools.lookup_companies(registry, names, tickers)

    server.run("stdio")


if __name__ == "__main__":
    main()
