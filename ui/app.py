"""Streamlit chat/Q&A interface for the persona + sector configurable agent.

This calls `agent.core.answer_query` directly -- the same function the FastAPI
route calls -- so there is exactly one orchestration implementation with two
entry points. It must never import `mcp_server`, call the API over HTTP, or
re-implement any retrieval/composition logic itself.
"""

import asyncio
import sys
from pathlib import Path

import streamlit as st

# `streamlit run ui/app.py` puts only ui/ on sys.path (streamlit.web.bootstrap._fix_sys_path),
# and this project is never installed into the environment, so the repo root has to be added
# here -- the same bootstrap scripts/build_db.py and evals/run_evals.py already use. pytest
# (`python -m`) and uvicorn (--app-dir defaults to ".") each get it for free; Streamlit does not.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core import answer_query  # noqa: E402 (path setup must run first)
from agent.models import (  # noqa: E402
    Confidence,
    EvidenceItem,
    PersonaName,
    QueryRequest,
    QueryResponse,
    Sector,
    Synthesis,
)

PERSONA_LABELS: dict[PersonaName, str] = {
    "mutual_fund_analyst": "Mutual Fund Analyst",
    "equity_analyst": "Equity Analyst",
    "pe_analyst": "PE Analyst",
}
SECTOR_LABELS: dict[Sector, str] = {
    "tech": "Tech",
    "retail": "Retail",
    "logistics": "Logistics",
}
CONFIDENCE_MARKERS: dict[Confidence, str] = {
    "high": ":green[HIGH]",
    "medium": ":orange[MEDIUM]",
    "low": ":red[LOW]",
}


def run_query(request: QueryRequest) -> QueryResponse:
    """Bridge the sync Streamlit callback to the async shared agent function.

    A fresh event loop per call is the simplest correct bridge here: each
    Streamlit rerun is a new top-to-bottom script execution, not a long-lived
    async context, so there is no loop to reuse across calls.
    """
    return asyncio.run(answer_query(request))


def _evidence_row(item: EvidenceItem) -> dict[str, str | float | int | None]:
    return {
        "ticker": item.ticker,
        "field": item.field,
        "value": item.value,
        "unit": item.unit,
        "as_of_date": item.as_of_date.isoformat(),
        "source_url": str(item.source_url),
    }


def render_synthesis(synthesis: Synthesis) -> None:
    """Show the model's structure only after it survived validation.

    When this block is absent the deterministic composer wrote the answer --
    either no key is configured, or the model's draft cited evidence or figures
    that agent/evidence_guard.py could not match to a retrieved row.
    """
    with st.expander("Thesis structure (model-written, evidence-validated)", expanded=True):
        for label, items in (
            ("Supporting points", synthesis.supporting_points),
            ("Risks", synthesis.risks),
            ("Limitations", synthesis.limitations),
        ):
            if items:
                st.markdown(f"**{label}**")
                st.markdown("\n".join(f"- {item}" for item in items))
        st.caption("Evidence cited: " + ", ".join(synthesis.evidence_ids))


def render_response(response: QueryResponse) -> None:
    st.subheader("Answer")
    st.write(response.answer)
    if response.synthesis is not None:
        render_synthesis(response.synthesis)
    else:
        st.caption("Composed deterministically from evidence templates (no validated model draft).")

    st.subheader("Companies referenced")
    st.write(", ".join(response.companies_referenced) if response.companies_referenced else "None")

    st.subheader("Evidence")
    if response.evidence:
        st.dataframe(
            [_evidence_row(item) for item in response.evidence],
            column_config={"source_url": st.column_config.LinkColumn("source_url")},
            hide_index=True,
        )
    else:
        st.write("No evidence rows were returned for this query.")

    st.subheader("Confidence")
    st.markdown(CONFIDENCE_MARKERS[response.confidence])

    st.subheader("Tool call trace")
    if response.tools_called:
        st.write("\n".join(f"{i}. {name}" for i, name in enumerate(response.tools_called, start=1)))
    else:
        st.write("No tools were called.")


def main() -> None:
    st.set_page_config(page_title="Agent Techhome", layout="wide")
    st.title("Sector Research Agent")
    st.caption(
        "Persona and sector are selected independently (9 valid combinations). "
        "The agent retrieves data live over MCP for every answer -- a dead MCP "
        "process surfaces as an error here, never as an answer from model memory."
    )

    persona_col, sector_col = st.columns(2)
    persona_label = persona_col.selectbox("Persona", list(PERSONA_LABELS.values()))
    sector_label = sector_col.selectbox("Sector", list(SECTOR_LABELS.values()))
    persona = next(name for name, label in PERSONA_LABELS.items() if label == persona_label)
    sector = next(name for name, label in SECTOR_LABELS.items() if label == sector_label)

    query = st.text_area("Question", placeholder="e.g. Which companies here look like attractive buyout targets?")
    if not st.button("Ask", type="primary"):
        return
    if not query.strip():
        st.warning("Enter a question before submitting.")
        return

    with st.spinner("Querying the agent (live MCP retrieval + model call)..."):
        try:
            request = QueryRequest(query=query, persona=persona, sector=sector)
            response = run_query(request)
        except Exception as exc:
            # Deliberately broad: an MCP transport failure, a provider error, and a
            # validation error must all reach the user as an error. Narrowing this
            # would risk a failure mode that renders as a silently empty page, which
            # is exactly what "never fall back to model memory" has to rule out.
            st.error(f"Query failed ({type(exc).__name__}): {exc}")
            return

    render_response(response)


if __name__ == "__main__":
    main()
