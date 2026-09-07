"""Persona retrieval policies -- CONTRACTS.md 'Persona retrieval'.

Normally user-owned per AGENTS.md; the user explicitly lifted that restriction
for this session and asked for a full implementation, not a stub.

Each policy fixes which metrics the persona treats as required (these become
confidence slots), which metric/direction it screens the sector on, how many
names it keeps, and the literal tool-call order it follows. The three policies
are deliberately built from different real DB columns so retrieval -- not just
prose -- diverges: mutual fund screens growth, equity screens margin then
re-screens valuation, PE pulls raw financials before screening leverage.

Deviation from CONTRACTS.md: PersonaPolicy adds two optional fields,
`secondary_screen_metric`/`secondary_screen_direction`, both defaulting to
None. The equity analyst is the only persona that runs a second
run_sector_screen call (margin, then valuation) per the persona table in
CONTRACTS.md, and the base schema has no field for a second screen's metric.
Every field CONTRACTS.md specifies is still present and required.
"""

from pydantic import BaseModel

from agent.models import Direction, PersonaName


class MetricRequest(BaseModel):
    metric: str
    required: bool


class PersonaPolicy(BaseModel):
    name: PersonaName
    metrics: list[MetricRequest]
    screen_metric: str
    screen_direction: Direction
    result_limit: int
    tool_plan: list[str]
    ranking_rationale: str
    secondary_screen_metric: str | None = None
    secondary_screen_direction: Direction | None = None


_POLICIES: dict[PersonaName, PersonaPolicy] = {
    "mutual_fund_analyst": PersonaPolicy(
        name="mutual_fund_analyst",
        metrics=[
            MetricRequest(metric="revenue_growth_yoy", required=True),
            MetricRequest(metric="price_to_sales_ttm", required=True),
            MetricRequest(metric="fcf_margin", required=False),
        ],
        screen_metric="revenue_growth_yoy",
        screen_direction="desc",
        result_limit=6,
        tool_plan=["list_companies", "run_sector_screen", "get_financials", "get_hiring_signals"],
        ranking_rationale=(
            "Ranks the sector by trailing revenue growth as a proxy for durable, "
            "benchmark-beating growth, then checks price/sales and FCF margin so "
            "growth isn't being bought at an unsupportable multiple."
        ),
    ),
    "equity_analyst": PersonaPolicy(
        name="equity_analyst",
        metrics=[
            MetricRequest(metric="operating_margin_ttm", required=True),
            MetricRequest(metric="diluted_eps", required=True),
            MetricRequest(metric="trailing_pe", required=True),
        ],
        screen_metric="operating_margin_ttm",
        screen_direction="desc",
        result_limit=6,
        secondary_screen_metric="trailing_pe",
        secondary_screen_direction="asc",
        tool_plan=["list_companies", "run_sector_screen", "get_financials", "run_sector_screen"],
        ranking_rationale=(
            "Ranks the sector by trailing operating margin first (the fundamentals "
            "signal), then re-screens the same cohort by trailing P/E ascending to "
            "see which of the higher-margin names are still reasonably priced."
        ),
    ),
    "pe_analyst": PersonaPolicy(
        name="pe_analyst",
        metrics=[
            MetricRequest(metric="free_cash_flow_ttm", required=True),
            MetricRequest(metric="enterprise_to_ebitda", required=True),
            MetricRequest(metric="liabilities_to_equity", required=False),
        ],
        screen_metric="liabilities_to_equity",
        screen_direction="asc",
        result_limit=3,
        tool_plan=["list_companies", "get_financials", "run_sector_screen", "get_hiring_signals"],
        ranking_rationale=(
            "Pulls raw cash-flow and multiple data across the whole sector first, "
            "then screens liabilities-to-equity ascending to find balance-sheet "
            "capacity for additional leverage -- a short list of cash-generative "
            "names with room to lever up, not just the biggest or fastest growing."
        ),
    ),
}


def get_persona(persona: PersonaName) -> PersonaPolicy:
    return _POLICIES[persona]


def list_personas() -> tuple[PersonaName, ...]:
    return tuple(_POLICIES.keys())
