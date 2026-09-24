# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A persona-configurable financial research agent over 24 US-listed companies (8 each in tech,
retail, logistics). It answers questions from a committed SQLite snapshot that it reaches **only**
through an MCP tool boundary. One shared orchestration function, `agent.core.answer_query`, is
exposed twice: FastAPI `POST /query` and a Streamlit UI.

Local-only planning docs (all gitignored, deliberately unpublished): `ASSIGNMENT.md` is the source
of truth for requirements, `AGENTS.md` the build constraints, `CONTRACTS.md` the module contracts,
`DECISIONS.md`, `IMPLEMENTATION_PLAN.md`, `REVIEW_CHECKLIST.md`, `STAGE1_STATUS.md`. Read
`ASSIGNMENT.md` and `AGENTS.md` before changing behaviour. `README.md` is the published doc and
must stay accurate; `MANUAL_TESTING.md` is the hands-on walkthrough.

## Commands

Python 3.12 + `uv`. All commands run from the repo root.

```bash
uv sync                                    # install
uv run python -m pytest -q                 # full suite (168 tests, hermetic -- see tests/conftest.py)
uv run python -m pytest tests/test_agent.py::test_persona_divergence_same_question_same_sector -q   # one test
uv run python evals/run_evals.py           # 9 eval cases, pass/fail table, nonzero exit on failure
uv run uvicorn api.main:app --reload       # API on :8000 (/docs for Swagger)
uv run streamlit run ui/app.py             # UI on :8501
uv run python scripts/build_db.py          # rebuild DB from live SEC+Yahoo (needs SEC_USER_AGENT)
uv run python scripts/build_db.py --offline   # rebuild by replaying .source-cache/, no network
uv run python scripts/build_registry.py    # refresh SEC registry (needs SEC_USER_AGENT)
```

There is no linter or formatter configured. CI (`.github/workflows/ci.yml`) runs the suite and the
evals on every push and PR, keyless, so the deterministic path is what gets verified there.
`requirements.txt` is exported from `uv.lock` for Streamlit Cloud and must be regenerated whenever
`pyproject.toml` changes.

## Hard constraints

These are graded requirements, not preferences. Violating one invalidates the design.

1. **Nothing under `agent/` may import a database driver.** `grep -rn "sqlite3\|duckdb\|psycopg" agent/`
   must return nothing. The agent's only data path is `AgentMcpClient` over a real stdio subprocess.
   `mcp_server/database.py` is the single module allowed to `import sqlite3` at runtime (read-only,
   `mode=ro`); `scripts/` and `evals/cases.py` also use it, deliberately, outside the agent path.
2. **`agent/` never names the `mcp_server` package** — not even in a string. The launch command lives
   in `server_launch.py`, a neutral root module both sides import.
3. **Persona changes retrieval, not tone.** Each `PersonaPolicy` fixes its own metrics, screen
   metric/direction, result limit, and literal tool-call order. If all three personas produce the
   same tool sequence, the primary criterion has failed — fix the policy, never the prompt.
4. **No fabrication, no fallback to model knowledge.** A registry-confirmed listed company outside
   the sector catalog gets an explicit refusal before financial retrieval. A dead MCP process surfaces as an error (502 in the API,
   `st.error` in the UI). Missing values stay `NULL`, never zero or estimated. Model-written prose
   ships only if `agent/evidence_guard.validate` passes it; otherwise the deterministic answer
   ships instead.
5. **Every row carries `source_url` and `as_of_date`,** on every table including lineage.
6. **No file over 200 lines.** Split instead. Ask before adding a dependency outside `mcp`, `fastapi`,
   `streamlit`, `openai`, `yfinance`, `requests`, `pydantic`, `pytest`.

## Architecture

**Request flow** (`agent/core.py:answer_query`, a fresh MCP subprocess for retrieval, no caching):

```
QueryRequest -> AgentMcpClient (stdio subprocess: python -m mcp_server.entrypoint)
             -> list_companies(sector)              # always the first tool call
             -> scope.resolve_mentions              # catalog matches and candidates
             -> lookup_companies (if candidates)     # SEC confirmation; outside company -> refusal
             -> retrieval.run_company_focus | run_sector_wide   # persona-driven tool plan
             -- retrieval MCP session closes; the rest runs in a worker thread --
             -> llm.choose_framing                  # sees labeled values, returns one stance
                                                    # word; keyless it is always "neutral"
             -> grounding.compose_answer            # templates filled from EvidenceItem rows
             -> synthesis.synthesize                # model writes the thesis; evidence_guard
                                                    # may open a fresh MCP registry session to
                                                    # validate names, or discard the draft
             -> confidence.compute_confidence       # derived from slots, never model-chosen
             -> QueryResponse
```

**Layer boundaries that matter:**

- `agent/models.py` defines the agent's *own* copy of the wire types. It does not import
  `mcp_server.models`. MCP is a protocol boundary — responses are validated from JSON into agent-owned
  Pydantic classes. Changing a shape means editing both sides.
- `agent/retrieval.py` has two plan shapes selected by `policy.tool_plan[1]`: `_pe_style_plan`
  (financials across the whole cohort, then screen, then hiring on the shortlist) and
  `_screen_first_plan` (screen, enrich ranked names, optional second screen, optional hiring).
  `agent/focus.py` then adds the question's focus from a closed keyword list: extra metrics on
  the company-focus path, one extra screen on the sector path unless the persona already screens
  that metric. Focus metrics are required confidence slots. Never let a model choose metrics.
- `agent/grounding.py` produces the deterministic answer: every sentence is a template filled from
  an `EvidenceItem` a tool returned this turn. It always runs -- it yields the evidence set, and it
  is the answer whenever synthesis is unavailable or rejected.
- `agent/synthesis.py` + `agent/evidence_guard.py` are the LLM answer path. The model sees the
  evidence as *display strings only* (never raw floats) and returns JSON: thesis,
  supporting_points, risks, limitations, evidence_ids. `evidence_guard.validate` then rejects
  unretrieved evidence ids, tickers never retrieved, figures absent from the display strings
  as typed quantities (invented, computed, or with sign/magnitude/unit changed), dates no row
  carries, figures attached to the wrong company in a single-company sentence (named by ticker
  or by company name), and any company name absent from the sector catalog. Rejection falls back to
  `grounding.py`. The guarantee is the validator, not the prompt -- if you weaken `validate`, you
  have weakened the whole design, so change it only alongside a test in `tests/test_evidence_guard.py`.
  `AGENT_SYNTHESIS=off` forces the deterministic path; `tests/conftest.py` sets it so the suite
  never calls a provider.
- `agent/scope.py` extracts candidates without a vocabulary list. `lookup_companies` confirms them
  against a dated SEC snapshot. Two- and three-letter ticker hits need company usage context;
  longer ticker hits and name hits are companies. Drafts use the same registry check in
  `agent/company_guard.py`; failed lookups discard the draft.
- A lowercase mention of a company outside the dataset ("what about snowflake?") is invisible to
  `scope.py` by construction. It is caught after retrieval instead: if the model's draft names a
  company the catalog lacks *and* the question named it too, `core._query_named_out_of_scope`
  turns the turn into the standard refusal. Only the name comes from the discarded draft, and only
  after the catalog rejected it -- the reply is still a template.
- `agent/confidence.py` builds one `Slot` per (company, required metric) plus one per requested
  hiring signal, then scores `0.65*coverage + 0.35*freshness`. **High** additionally requires every
  required slot fresh within 180 days. Future dates score 0, not fresh. The rule is documented in
  README.md — keep the two in sync.
- `mcp_server/entrypoint.py` exposes five typed tools (`list_companies`, `lookup_companies`,
  `get_financials`, `get_hiring_signals`, `run_sector_screen`) — no generic SQL tool.
  `server.py` retains the four database registrations; the entry point attaches the registry
  tool, whose logic lives in `registry.py` and `tools.py`.
- `scripts/` is the offline build pipeline, unused at query time: SEC XBRL company facts +
  `yfinance` -> `derive_metrics.py` (ratios computed only when units and periods are compatible,
  recording lineage rows) -> `database_writer.py` -> `validate_db.py`. `build_db.py` writes to a
  temp file in the same directory, validates, and atomically replaces `data/agent_techhome.db` only
  on success, so a failed refresh leaves the previous database intact.

**Schema** (`scripts/schema.sql`): row-per-fact, not a wide table. `financial_observations` carries
`period_kind` (`instant`/`quarter`/`fiscal_year`/`ttm`/`observation`) so a filed annual flow, a
balance-sheet instant, and a Yahoo point-in-time snapshot stay distinguishable.
`financial_lineage` is a many-to-many join from a derived metric to every constituent observation.

## Working notes

- The committed `data/agent_techhome.db` is tracked on purpose — reviewers run without rebuilding.
  Don't regenerate it casually; a rebuild changes every Yahoo `as_of_date` and therefore eval
  expectations and confidence tiers.
- `evals/cases.py` reads expected values via a direct `sqlite3` query — a deliberately different code
  path from the agent's MCP retrieval, so the assertion is that two independent paths agree.
- `OPENAI_API_KEY` is optional. Unset, `choose_framing` returns the `neutral` stance (averaging
  mixed-unit values says nothing) and everything still runs offline. `agent/config.py` loads `.env` on import; a real exported env var wins.
- Style: type hints everywhere, Pydantic for anything crossing a boundary, no bare `except`,
  comments explain *why*, no emoji.

CLAUDE.md
Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

Tradeoff: These guidelines bias toward caution over speed. For trivial tasks, use judgment.

1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

State your assumptions explicitly. If uncertain, ask.
If multiple interpretations exist, present them - don't pick silently.
If a simpler approach exists, say so. Push back when warranted.
If something is unclear, stop. Name what's confusing. Ask.
2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

No features beyond what was asked.
No abstractions for single-use code.
No "flexibility" or "configurability" that wasn't requested.
No error handling for impossible scenarios.
If you write 200 lines and it could be 50, rewrite it.
Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

3. Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:

Don't "improve" adjacent code, comments, or formatting.
Don't refactor things that aren't broken.
Match existing style, even if you'd do it differently.
If you notice unrelated dead code, mention it - don't delete it.
When your changes create orphans:

Remove imports/variables/functions that YOUR changes made unused.
Don't remove pre-existing dead code unless asked.
The test: Every changed line should trace directly to the user's request.

4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

"Add validation" → "Write tests for invalid inputs, then make them pass"
"Fix the bug" → "Write a test that reproduces it, then make it pass"
"Refactor X" → "Ensure tests pass before and after"
For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

These guidelines are working if: fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
