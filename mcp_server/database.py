"""Read-only SQLite access for the MCP server.

This is the one module in the whole project allowed to `import sqlite3` for
runtime query serving. It opens the committed database in mode=ro so a bug here
can never mutate the sourced data, and returns plain sqlite3.Row objects that
mcp_server/tools.py shapes into the Pydantic models defined in models.py.
"""

import sqlite3
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def list_companies(connection: sqlite3.Connection, sector: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT ticker, name, sector, source_url, as_of_date FROM companies WHERE sector = ? ORDER BY ticker",
        (sector,),
    ).fetchall()


def ticker_exists(connection: sqlite3.Connection, ticker: str) -> bool:
    row = connection.execute("SELECT 1 FROM companies WHERE ticker = ?", (ticker,)).fetchone()
    return row is not None


def known_metrics(connection: sqlite3.Connection) -> frozenset[str]:
    rows = connection.execute("SELECT DISTINCT metric FROM financial_observations").fetchall()
    return frozenset(row["metric"] for row in rows)


def latest_observation(connection: sqlite3.Connection, ticker: str, metric: str) -> sqlite3.Row | None:
    # ORDER BY as_of_date only (not value) so a newer NULL is never hidden behind
    # an older non-null row presented as current.
    return connection.execute(
        """SELECT id, ticker, metric, value, unit, period_kind, period_start, period_end, source_url, as_of_date
        FROM financial_observations WHERE ticker = ? AND metric = ?
        ORDER BY as_of_date DESC, id DESC LIMIT 1""",
        (ticker, metric),
    ).fetchone()


def source_lineage(connection: sqlite3.Connection, observation_id: int) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT o.metric, o.value, o.unit, o.period_kind, o.period_start, o.period_end,
        o.source_url, o.as_of_date
        FROM financial_lineage l JOIN financial_observations o ON o.id = l.input_observation_id
        WHERE l.observation_id = ? ORDER BY l.id""",
        (observation_id,),
    ).fetchall()


def hiring_signals(connection: sqlite3.Connection, ticker: str, limit: int) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT ticker, signal, signal_kind, value, unit, observed_on, period_end, source_url, as_of_date
        FROM hiring_signals WHERE ticker = ? ORDER BY observed_on DESC, id DESC LIMIT ?""",
        (ticker, limit),
    ).fetchall()
