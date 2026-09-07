"""Subprocess launch spec for the stdio MCP server.

Lives outside both agent/ and mcp_server/ on purpose: agent/ must never
reference the server package by name -- MCP is a protocol boundary, and the
agent should not read as reaching into the server package even in a string
literal (see agent/models.py for the same reasoning applied to types). The one
place that knows the server is invoked as `python -m mcp_server.server` is
this small neutral module; agent/mcp_client.py and any other entry point
(api, ui, evals, tests) import it from here rather than hardcoding it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = ROOT / "data" / "agent_techhome.db"


def server_command(database_path: Path) -> tuple[str, list[str], str]:
    """Returns (command, args, cwd) to launch the MCP server over stdio."""
    return sys.executable, ["-m", "mcp_server.server", "--database", str(database_path)], str(ROOT)
