"""Side-by-side persona comparison: the central claim, made checkable at a glance.

The same question is run through all three personas against the same sector and
laid out one dimension per row. The point is not three opinions -- it is that
the *retrieval* differs: different metrics requested, a different screen, a
different tool sequence, a different set of companies surfaced. Reading three
paragraphs makes that hard to see; putting the tool traces next to each other
makes it obvious.

Rendering only. Every value shown comes from a QueryResponse the shared
agent.core.answer_query produced -- this module runs no retrieval of its own.
"""

from typing import Callable

import streamlit as st

from agent.models import PersonaName, QueryRequest, QueryResponse, Sector
from agent.personas import get_persona
from ui.text import md_safe

PERSONA_ORDER: tuple[PersonaName, ...] = ("mutual_fund_analyst", "equity_analyst", "pe_analyst")
_LABELS: dict[PersonaName, str] = {
    "mutual_fund_analyst": "Mutual Fund Analyst",
    "equity_analyst": "Equity Analyst",
    "pe_analyst": "PE Analyst",
}
_CONFIDENCE_MARKERS: dict[str, str] = {
    "high": ":green[HIGH]",
    "medium": ":orange[MEDIUM]",
    "low": ":red[LOW]",
}


def _tool_sequence(response: QueryResponse) -> str:
    """Collapse consecutive repeats: `get_financials` x6 reads better than six lines."""
    collapsed: list[tuple[str, int]] = []
    for name in response.tools_called:
        if collapsed and collapsed[-1][0] == name:
            collapsed[-1] = (name, collapsed[-1][1] + 1)
        else:
            collapsed.append((name, 1))
    return " -> ".join(name if count == 1 else f"{name} x{count}" for name, count in collapsed)


def _divergence_note(responses: dict[PersonaName, QueryResponse]) -> None:
    sequences = {name: tuple(r.tools_called) for name, r in responses.items()}
    company_sets = {name: frozenset(r.companies_referenced) for name, r in responses.items()}
    pairs = [(a, b) for i, a in enumerate(PERSONA_ORDER) for b in PERSONA_ORDER[i + 1:]]
    tools_differ = all(sequences[a] != sequences[b] for a, b in pairs)
    sets_differ = all(company_sets[a] != company_sets[b] for a, b in pairs)
    if tools_differ and sets_differ:
        st.success("All three personas produced a different tool sequence *and* a different company set.")
    else:
        # Surfaced rather than hidden: if personas converge on a question, that is
        # a real property of this question and the reviewer should see it.
        st.warning(
            f"Tool sequences all differ: {tools_differ}. Company sets all differ: {sets_differ}. "
            "Convergence here is a property of this question, not a fallback."
        )


def _render_column(persona: PersonaName, response: QueryResponse) -> None:
    policy = get_persona(persona)
    st.markdown(f"#### {_LABELS[persona]}")
    st.markdown(_CONFIDENCE_MARKERS[response.confidence])

    st.markdown("**Metrics this persona requires**")
    st.markdown("\n".join(f"- {metric.metric}" for metric in policy.metrics))
    st.markdown(f"**Screen:** `{policy.screen_metric}` {policy.screen_direction}")
    if policy.secondary_screen_metric:
        st.markdown(f"**Then:** `{policy.secondary_screen_metric}` {policy.secondary_screen_direction}")

    st.markdown("**Tool sequence**")
    st.code(_tool_sequence(response), language=None)

    st.markdown("**Companies surfaced**")
    st.write(", ".join(response.companies_referenced) or "None")

    st.markdown("**Answer**")
    st.write(md_safe(response.answer))

    if response.synthesis is not None and response.synthesis.risks:
        st.markdown("**Risks**")
        st.markdown("\n".join(f"- {md_safe(risk)}" for risk in response.synthesis.risks))

    st.caption(f"{len(response.evidence)} evidence rows")


def compare_personas(
    query: str, sector: Sector, runner: Callable[[QueryRequest], QueryResponse]
) -> None:
    """Run one question through all three personas and render them side by side."""
    responses: dict[PersonaName, QueryResponse] = {}
    progress = st.progress(0.0, text="Running all three personas over live MCP retrieval...")
    for index, persona in enumerate(PERSONA_ORDER, start=1):
        try:
            responses[persona] = runner(QueryRequest(query=query, persona=persona, sector=sector))
        except Exception as exc:
            progress.empty()
            st.error(f"{_LABELS[persona]} failed ({type(exc).__name__}): {exc}")
            return
        progress.progress(index / len(PERSONA_ORDER), text=f"{_LABELS[persona]} done")
    progress.empty()

    _divergence_note(responses)
    for column, persona in zip(st.columns(len(PERSONA_ORDER)), PERSONA_ORDER):
        with column:
            _render_column(persona, responses[persona])
