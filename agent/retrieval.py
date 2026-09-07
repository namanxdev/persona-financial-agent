"""Executes one persona's retrieval plan against a live MCP session.

Two paths, chosen by agent/core.py based on scope resolution:
- Company focus: the query named specific in-catalog tickers -- fetch their
  financials/hiring directly instead of running a generic sector screen.
- Sector wide: run the persona's screen(s), then enrich the ranked names with
  any remaining required metrics, then hiring where the policy calls for it.

Every data access goes through AgentMcpClient (agent/mcp_client.py); this
module never touches a database driver, matching the rest of agent/.
"""

from dataclasses import dataclass, field

from agent.confidence import Slot
from agent.mcp_client import AgentMcpClient
from agent.models import CompanyRow, FinancialRow, HiringSignalRow, ScreenResult, Sector
from agent.personas import PersonaPolicy


@dataclass
class RetrievalBundle:
    primary_screen: ScreenResult | None = None
    secondary_screen: ScreenResult | None = None
    financials: dict[str, list[FinancialRow]] = field(default_factory=dict)
    hiring: dict[str, list[HiringSignalRow]] = field(default_factory=dict)
    slots: list[Slot] = field(default_factory=list)


def _metric_names(policy: PersonaPolicy, exclude: set[str]) -> list[str]:
    return [m.metric for m in policy.metrics if m.metric not in exclude]


def _slots_from_financials(financials: dict[str, list[FinancialRow]], required: set[str]) -> list[Slot]:
    if not required:
        return []
    slots: list[Slot] = []
    for ticker, rows in financials.items():
        covered = {row.metric for row in rows if row.metric in required}
        slots.extend(Slot(ticker, row.metric, row.value, row.as_of_date) for row in rows if row.metric in required)
        slots.extend(Slot(ticker, metric, None, None) for metric in required - covered)
    return slots


def _slots_from_screen(screen: ScreenResult, metric: str, required: bool) -> list[Slot]:
    if not required:
        return []
    return [Slot(row.ticker, metric, row.value, row.as_of_date) for row in screen.rows] + [
        Slot(item.ticker, metric, None, None) for item in screen.excluded
    ]


def _slots_from_hiring(hiring: dict[str, list[HiringSignalRow]], tickers: list[str]) -> list[Slot]:
    slots = []
    for ticker in tickers:
        rows = hiring.get(ticker, [])
        slots.append(Slot(ticker, "hiring_signal", rows[0].value, rows[0].as_of_date) if rows else Slot(ticker, "hiring_signal", None, None))
    return slots


async def _pe_style_plan(client: AgentMcpClient, policy: PersonaPolicy, sector: Sector, companies: list[CompanyRow]) -> RetrievalBundle:
    """financials across the whole cohort, then a leverage screen, then hiring on the shortlist."""
    bundle = RetrievalBundle()
    required = {m.metric for m in policy.metrics if m.required}
    metrics = _metric_names(policy, exclude=set())
    for company in companies:
        rows = await client.get_financials(company.ticker, metrics)
        if rows:
            bundle.financials[company.ticker] = rows
    bundle.slots.extend(_slots_from_financials(bundle.financials, required))

    screen = await client.run_sector_screen(sector, policy.screen_metric, policy.screen_direction, policy.result_limit)
    bundle.primary_screen = screen
    bundle.slots.extend(_slots_from_screen(screen, policy.screen_metric, policy.screen_metric in required))

    shortlist = [row.ticker for row in screen.rows]
    for ticker in shortlist:
        bundle.hiring[ticker] = await client.get_hiring_signals(ticker, 1)
    bundle.slots.extend(_slots_from_hiring(bundle.hiring, shortlist))
    return bundle


async def _screen_first_plan(client: AgentMcpClient, policy: PersonaPolicy, sector: Sector) -> RetrievalBundle:
    """Screen first (mutual fund / equity style), then enrich the ranked names."""
    bundle = RetrievalBundle()
    required = {m.metric for m in policy.metrics if m.required}
    consumed_by_screen = {policy.screen_metric} | ({policy.secondary_screen_metric} if policy.secondary_screen_metric else set())

    screen = await client.run_sector_screen(sector, policy.screen_metric, policy.screen_direction, policy.result_limit)
    bundle.primary_screen = screen
    bundle.slots.extend(_slots_from_screen(screen, policy.screen_metric, policy.screen_metric in required))
    ranked_tickers = [row.ticker for row in screen.rows]

    extra_metrics = _metric_names(policy, exclude=consumed_by_screen)
    for ticker in ranked_tickers:
        if extra_metrics:
            rows = await client.get_financials(ticker, extra_metrics)
            if rows:
                bundle.financials[ticker] = rows
    bundle.slots.extend(_slots_from_financials(bundle.financials, required - consumed_by_screen))

    if policy.secondary_screen_metric:
        secondary = await client.run_sector_screen(
            sector, policy.secondary_screen_metric, policy.secondary_screen_direction or "desc", policy.result_limit
        )
        bundle.secondary_screen = secondary
        bundle.slots.extend(_slots_from_screen(secondary, policy.secondary_screen_metric, policy.secondary_screen_metric in required))

    if "get_hiring_signals" in policy.tool_plan:
        focus = ranked_tickers[:2]
        for ticker in focus:
            bundle.hiring[ticker] = await client.get_hiring_signals(ticker, 1)
        bundle.slots.extend(_slots_from_hiring(bundle.hiring, focus))
    return bundle


async def run_sector_wide(client: AgentMcpClient, policy: PersonaPolicy, sector: Sector, companies: list[CompanyRow]) -> RetrievalBundle:
    if policy.tool_plan[1] == "get_financials":
        return await _pe_style_plan(client, policy, sector, companies)
    return await _screen_first_plan(client, policy, sector)


async def run_company_focus(client: AgentMcpClient, policy: PersonaPolicy, tickers: list[str], query: str) -> RetrievalBundle:
    bundle = RetrievalBundle()
    required = {m.metric for m in policy.metrics if m.required}
    metrics = _metric_names(policy, exclude=set())
    for ticker in tickers:
        rows = await client.get_financials(ticker, metrics)
        if rows:
            bundle.financials[ticker] = rows
    bundle.slots.extend(_slots_from_financials(bundle.financials, required))

    hiring_words = ("headcount", "hiring", "employee", "staff", "workforce")
    if any(word in query.lower() for word in hiring_words) or "get_hiring_signals" in policy.tool_plan:
        for ticker in tickers:
            bundle.hiring[ticker] = await client.get_hiring_signals(ticker, 3)
        bundle.slots.extend(_slots_from_hiring(bundle.hiring, tickers))
    return bundle
