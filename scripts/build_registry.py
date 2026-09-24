"""Refresh the committed SEC listed-company snapshot after complete validation."""

import json
import os
import re
import sqlite3
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
DESTINATION = ROOT / "data" / "listed_companies.json"
DATABASE = ROOT / "data" / "agent_techhome.db"
EXCHANGES = {"NYSE", "Nasdaq", "CBOE"}
# Build-time review aid only. Runtime company detection never consults this list.
COMMON_WORDS = set("AI ALL AND ARE AS AT BE BIG BY CAN CAR CAT CO COST DAY DO END EV FAR FOR FREE GO GM HAS HE HER HIS HOME HOW I IN IS IT KEY LOW MAN MAY ME MY NET NEW NO NOT NOW OF OFF ON ONE OR OUR OUT PAY PER RED RUN SEE SHE SO SUN TAX THE TO TOP TWO UP US USE VIA WAR WAY WE WHO WHY WIN YES YOU".split())


def catalog_tickers(database: Path) -> set[str]:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        return {row[0] for row in connection.execute("SELECT ticker FROM companies")}
    finally:
        connection.close()


def validate_snapshot(payload: dict[str, Any], database: Path) -> list[list[Any]]:
    fields = payload.get("fields")
    if fields != ["cik", "name", "ticker", "exchange"]:
        raise ValueError("unexpected SEC registry fields")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("SEC registry data must be a list")
    rows: list[list[Any]] = []
    for row in data:
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError("malformed SEC registry row")
        cik, name, ticker, exchange = row
        if exchange not in EXCHANGES:
            continue
        if not isinstance(cik, int) or cik <= 0 or not isinstance(name, str) or not name.strip():
            raise ValueError("SEC registry row lacks cik or name")
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("SEC registry row lacks ticker")
        rows.append(row)
    if len(rows) < 5_000:
        raise ValueError(f"SEC registry has fewer than 5,000 listed rows: {len(rows)}")
    missing = catalog_tickers(database) - {row[2] for row in rows}
    if missing:
        raise ValueError(f"SEC registry is missing catalog tickers: {sorted(missing)}")
    return rows


def build_registry(destination: Path, database: Path, user_agent: str) -> list[list[Any]]:
    if "@" not in user_agent or "example.com" in user_agent.lower() or "name@domain" in user_agent.lower():
        raise ValueError("SEC_USER_AGENT must contain a real contact email")
    response = requests.get(SOURCE_URL, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}, timeout=45)
    response.raise_for_status()
    rows = validate_snapshot(response.json(), database)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f"{destination.name}.tmp-", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("{\n")
            stream.write(f'  "source_url": {json.dumps(SOURCE_URL)},\n')
            stream.write(f'  "as_of_date": {json.dumps(date.today().isoformat())},\n')
            stream.write('  "fields": ["cik", "name", "ticker", "exchange"],\n')
            stream.write('  "data": [\n')
            for index, row in enumerate(rows):
                suffix = "," if index < len(rows) - 1 else ""
                stream.write(f"    {json.dumps(row, ensure_ascii=False)}{suffix}\n")
            stream.write("  ]\n}\n")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return rows


def main() -> None:
    user_agent = os.environ.get("SEC_USER_AGENT", "")
    if not user_agent and (ROOT / ".env").is_file():
        for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if raw.startswith("SEC_USER_AGENT="):
                user_agent = raw.partition("=")[2].strip().strip('"').strip("'")
    if not user_agent:
        raise SystemExit("SEC_USER_AGENT is required; use a real contact identity")
    rows = build_registry(DESTINATION, DATABASE, user_agent)
    print(f"validated and replaced {DESTINATION} with {len(rows)} rows")
    collisions = sorted({str(row[2]) for row in rows if re.fullmatch(r"[A-Z]{2,3}", str(row[2])) and row[2] in COMMON_WORDS})
    print(f"Possible English/finance word ticker collisions: {', '.join(collisions)}")


if __name__ == "__main__":
    main()
