"""Build the sourced SQLite database and replace the prior copy only after validation."""

import argparse
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Protocol

# Direct execution sets sys.path to scripts/; add the repository root for package imports.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.company_universe import COMPANIES, Company, validate_universe
from scripts.database_writer import create_database
from scripts.derive_metrics import derive_metrics
from scripts.sec_source import SecClient
from scripts.source_models import Fact, ListingSnapshot, MarketSnapshot
from scripts.validate_db import validate_database
from scripts.yfinance_source import YahooClient

class SecSource(Protocol):
    def company_facts(self, company: Company) -> tuple[list[Fact], str, date]: ...


class YahooSource(Protocol):
    def snapshots(self, company: Company) -> tuple[ListingSnapshot, list[MarketSnapshot]]: ...


def rebuild_database(destination: Path, sec: SecSource, yahoo: YahooSource) -> None:
    validate_universe()
    listings: dict[str, ListingSnapshot] = {}
    sec_urls: dict[str, str] = {}
    raw_facts: list[Fact] = []
    market: list[MarketSnapshot] = []
    company_dates: dict[str, date] = {}
    for company in COMPANIES:
        listing, snapshots = yahoo.snapshots(company)
        facts, sec_url, sec_observed_on = sec.company_facts(company)
        listings[company.ticker] = listing
        sec_urls[company.ticker] = sec_url
        raw_facts.extend(facts)
        market.extend(snapshots)
        company_dates[company.ticker] = sec_observed_on
        print(f"fetched {company.ticker}: {len(facts)} SEC facts, {len(snapshots)} Yahoo metrics")
    all_facts = raw_facts + derive_metrics(raw_facts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f"{destination.name}.tmp-", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        create_database(
            temporary,
            ROOT / "scripts" / "schema.sql",
            COMPANIES,
            listings,
            sec_urls,
            all_facts,
            market,
            company_dates,
        )
        validate_database(temporary)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    print(f"validated and replaced {destination}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "agent_techhome.db")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".source-cache")
    parser.add_argument("--offline", action="store_true", help="replay immutable cached responses without network")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    user_agent = os.environ.get("SEC_USER_AGENT", "")
    if not args.offline and not user_agent:
        raise SystemExit("SEC_USER_AGENT is required; use a real contact identity (see .env.example)")
    sec = SecClient(user_agent=user_agent, cache_dir=args.cache_dir, offline=args.offline)
    yahoo = YahooClient(cache_dir=args.cache_dir, offline=args.offline)
    rebuild_database(args.database.resolve(), sec, yahoo)


if __name__ == "__main__":
    main()
