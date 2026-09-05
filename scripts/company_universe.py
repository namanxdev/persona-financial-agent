"""The deliberately small, reviewable company universe."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Company:
    ticker: str
    name: str
    sector: str
    cik: int


COMPANIES: tuple[Company, ...] = (
    Company("AAPL", "Apple Inc.", "tech", 320193),
    Company("MSFT", "Microsoft Corporation", "tech", 789019),
    Company("GOOGL", "Alphabet Inc.", "tech", 1652044),
    Company("META", "Meta Platforms, Inc.", "tech", 1326801),
    Company("ORCL", "Oracle Corporation", "tech", 1341439),
    Company("CSCO", "Cisco Systems, Inc.", "tech", 858877),
    Company("IBM", "International Business Machines Corporation", "tech", 51143),
    Company("ADBE", "Adobe Inc.", "tech", 796343),
    Company("WMT", "Walmart Inc.", "retail", 104169),
    Company("COST", "Costco Wholesale Corporation", "retail", 909832),
    Company("TGT", "Target Corporation", "retail", 27419),
    Company("HD", "The Home Depot, Inc.", "retail", 354950),
    Company("LOW", "Lowe's Companies, Inc.", "retail", 60667),
    Company("BBY", "Best Buy Co., Inc.", "retail", 764478),
    Company("KR", "The Kroger Co.", "retail", 56873),
    Company("DG", "Dollar General Corporation", "retail", 29534),
    Company("UPS", "United Parcel Service, Inc.", "logistics", 1090727),
    Company("FDX", "FedEx Corporation", "logistics", 1048911),
    Company("XPO", "XPO, Inc.", "logistics", 1166003),
    Company("GXO", "GXO Logistics, Inc.", "logistics", 1852244),
    Company("CHRW", "C.H. Robinson Worldwide, Inc.", "logistics", 1043277),
    Company("JBHT", "J.B. Hunt Transport Services, Inc.", "logistics", 728535),
    Company("EXPD", "Expeditors International of Washington, Inc.", "logistics", 746515),
    Company("HUBG", "Hub Group, Inc.", "logistics", 940942),
)


def validate_universe() -> None:
    tickers = [company.ticker for company in COMPANIES]
    if len(tickers) != 24 or len(set(tickers)) != 24:
        raise ValueError("company universe must contain 24 unique tickers")
    counts = {sector: sum(c.sector == sector for c in COMPANIES) for sector in ("tech", "retail", "logistics")}
    if counts != {"tech": 8, "retail": 8, "logistics": 8}:
        raise ValueError(f"company universe must be 8/8/8, got {counts}")
