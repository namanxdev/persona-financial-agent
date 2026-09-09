# Manual testing walkthrough

How to drive this thing by hand and check it is actually doing what it claims. Everything below
was run on 2026-09-08 against the committed `data/agent_techhome.db` with no `OPENAI_API_KEY` set,
and the outputs shown are real (trimmed where noted), not illustrative.

Run every command from the repo root.

- [0. One-time setup](#0-one-time-setup)
- [1. The 30-second smoke test](#1-the-30-second-smoke-test)
- [2. Ask one question without starting a server](#2-ask-one-question-without-starting-a-server)
- [3. The Streamlit UI](#3-the-streamlit-ui)
- [4. The API](#4-the-api)
- [5. What to actually check](#5-what-to-actually-check)
- [6. Poking the MCP layer directly](#6-poking-the-mcp-layer-directly)
- [7. Breaking it on purpose](#7-breaking-it-on-purpose)
- [8. What is in the data](#8-what-is-in-the-data)
- [9. Rebuilding the database](#9-rebuilding-the-database)
- [Troubleshooting](#troubleshooting)

## 0. One-time setup

```bash
uv sync
```

That is it. No API key is needed: with `OPENAI_API_KEY` unset the agent uses its deterministic
framing fallback and everything -- UI, API, tests, evals -- runs offline. The database is
committed, so there is nothing to build either.

If you *do* want to exercise the live OpenAI path, put a key in `.env` (`cp .env.example .env`
first). `agent/config.py` reads that file on import. You will see which path ran in the logs:
`framing chosen via OpenAI (gpt-4o-mini): cautious` versus
`framing chosen via deterministic fallback: cautious`.

## 1. The 30-second smoke test

```bash
uv run python -m pytest -q
uv run python evals/run_evals.py
```

Expected, verified:

```
53 passed, 2 warnings in 22.71s
```

```
CASE                               RESULT  DETAIL
divergence_tech_investment_case    PASS    sequences_differ=True sets_differ=True all_have_evidence=True | ...
divergence_retail_attractive_case  PASS    ...
divergence_logistics_outlook_case  PASS    ...
grounding_ups_headcount            PASS    expected UPS.headcount=460000.0, got 460000.0
grounding_msft_operating_margin    PASS    expected MSFT.operating_margin_ttm=0.45111, got 0.45111
grounding_cost_revenue_growth      PASS    expected COST.revenue_growth_yoy=0.215, got 0.215
refusal_unknown_ticker_style       PASS    confidence=low evidence=[] answer="I don't have 'RIVN' ..."
refusal_unknown_mixed_case_name    PASS    confidence=low evidence=[] answer="I don't have 'Snowflake' ..."

8/8 cases passed
```

The `Processing request of type CallToolRequest` lines are the MCP server logging on stderr. That
is the real subprocess doing real work, not noise to worry about. Pipe through
`grep -v "Processing request"` if it gets in the way.

To run a single test:

```bash
uv run python -m pytest tests/test_agent.py::test_persona_divergence_same_question_same_sector -q
uv run python -m pytest tests/test_agent.py -q -k confidence
```

## 2. Ask one question without starting a server

Fastest way to see a real answer end to end. This calls the exact same `answer_query` that both
interfaces call:

```bash
uv run python -c "
import asyncio
from agent.core import answer_query
from agent.models import QueryRequest
r = asyncio.run(answer_query(QueryRequest(
    query='What is the most recent headcount signal you have for UPS?',
    persona='pe_analyst', sector='logistics')))
print(r.answer)
print('confidence:', r.confidence)
print('tools:', r.tools_called)
print('companies:', r.companies_referenced)
"
```

Real output:

```
From a deal/ops view of logistics: the retrieved data argues for caution. UPS's free cash flow
(TTM) is $5.6B as of 2026-09-07. UPS's EV/EBITDA is 9.19x as of 2026-09-07. UPS's latest
hiring/headcount signal: 460,000 employees as of 2026-09-07
(https://finance.yahoo.com/quote/UPS/profile/).
confidence: high
tools: ['list_companies', 'get_financials', 'get_hiring_signals']
companies: ['UPS']
```

Note the tool trace. Because the query named UPS, scope resolution matched it and the agent took
the company-focus path -- no sector screen at all. Ask something with no company name in it and
`run_sector_screen` shows up instead.

The `-c` form matters: it puts the repo root on `sys.path`. A script saved elsewhere fails with
`ModuleNotFoundError: No module named 'agent'` unless you save it in the repo root.

## 3. The Streamlit UI

```bash
uv run streamlit run ui/app.py
```

Two things to exercise: **Ask** (one persona) and **Compare all three personas** (the same
question through all three, side by side, with a banner stating whether the tool sequences and
company sets actually all differ). The compare view is the fastest way to check the central
requirement -- it takes ~40s because it runs three real MCP sessions plus three model calls.

If `OPENAI_API_KEY` is set, an accepted answer shows a **Thesis structure** block with the
model's supporting points, risks, limitations, and the evidence ids it cited. If that block is
missing and the caption reads "Composed deterministically", the model's draft was rejected by
`agent/evidence_guard.py` -- the reason is logged as `synthesis rejected: <reason>` in the
terminal running Streamlit. Both outcomes are correct behaviour; the rejection is the safety net
doing its job.

Opens on <http://localhost:8501>. Pick a persona and a sector from the two dropdowns (all 9
combinations are valid and meaningfully different), type a question, hit **Ask**.

The page renders five things. Check all five, not just the prose:

| Section | What it should show |
| --- | --- |
| Answer | Persona-framed prose. Every number in it should appear in the evidence table below. |
| Companies referenced | The tickers actually cited, derived from evidence rows, not from the prose. |
| Evidence | One row per cited fact, with `as_of_date` and a clickable `source_url`. |
| Confidence | HIGH / MEDIUM / LOW, computed -- see [section 5](#5-what-to-actually-check). |
| Tool call trace | The ordered MCP calls, repeats included. This is the persona fingerprint. |

Questions worth trying:

- `Which companies here look like attractive buyout targets?` -- run it three times, once per
  persona, same sector. The tool trace should differ each time.
- `What is the most recent headcount or hiring signal you have for FedEx?`
- `How is Snowflake doing?` (tech) -- should refuse outright.
- `What about Target?` (retail) -- should resolve to TGT.
- `The target market for these companies is shrinking -- thoughts?` (retail) -- should *not*
  resolve to TGT; it stays a sector-wide query. That distinction is the case-sensitivity rule in
  `agent/scope.py`, and it is the kind of thing worth re-checking if you touch that file.

## 4. The API

```bash
uv run uvicorn api.main:app --reload
```

Swagger UI at <http://localhost:8000/docs> is the easiest way to poke it by hand. From a shell:

```bash
curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query":"Which companies look like attractive buyout targets?",
       "persona":"pe_analyst","sector":"logistics"}'
```

Real response, answer field trimmed:

```json
{
  "answer": "From a deal/ops view of logistics: the retrieved data argues for caution. Pulls raw
    cash-flow and multiple data across the whole sector first, then screens liabilities-to-equity
    ascending ... Ranked by liabilities/equity, #1: JBHT at 1.22x (as of 2025-12-31). Ranked by
    liabilities/equity, #2: CHRW at 1.74x (as of 2025-12-31). Excluded from the liabilities/equity
    screen -- EXPD (no liabilities_to_equity observation on file); FDX (...); GXO (...); HUBG (...);
    UPS (...); XPO (...). CHRW's free cash flow (TTM) is $480.6M as of 2026-09-07. ...",
  "persona": "pe_analyst",
  "sector": "logistics",
  "companies_referenced": ["CHRW", "EXPD", "FDX", "GXO", "HUBG", "JBHT", "UPS", "XPO"],
  "evidence": [ "one row per cited fact" ],
  "confidence": "...",
  "tools_called": ["list_companies", "get_financials", "..."]
}
```

Valid values: `persona` is one of `mutual_fund_analyst`, `equity_analyst`, `pe_analyst`; `sector`
is one of `tech`, `retail`, `logistics`.

Out-of-scope company, verified:

```bash
curl -s -X POST http://localhost:8000/query -H "Content-Type: application/json" \
  -d '{"query":"How is Snowflake doing?","persona":"equity_analyst","sector":"tech"}'
```

```json
{"answer":"I don't have 'Snowflake' in the tech sector dataset, so I can't answer about it -- I
won't guess from general knowledge. Ask about one of the covered tech companies instead.",
"persona":"equity_analyst","sector":"tech","companies_referenced":[],"evidence":[],
"confidence":"low","tools_called":["list_companies"]}
```

Note that `tools_called` stops at `list_companies`. The refusal happens *before* retrieval, not
after a failed lookup.

A bad persona returns `422` from Pydantic before the handler ever runs (verified):

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query":"hi","persona":"day_trader","sector":"tech"}'
# 422
```

## 5. What to actually check

These are the claims worth verifying by hand, and how.

**Persona changes retrieval, not just wording.** Ask the *same* question in the *same* sector under
all three personas and compare `tools_called`. Verified for tech:

| Persona | Tool sequence | Companies surfaced |
| --- | --- | --- |
| `mutual_fund_analyst` | `list_companies`, `run_sector_screen`, 6x `get_financials`, 2x `get_hiring_signals` | AAPL, CSCO, GOOGL, META, MSFT, ORCL |
| `equity_analyst` | `list_companies`, `run_sector_screen`, 6x `get_financials`, `run_sector_screen` | AAPL, ADBE, GOOGL, IBM, META, MSFT, ORCL |
| `pe_analyst` | `list_companies`, 8x `get_financials`, `run_sector_screen`, 3x `get_hiring_signals` | all 8 tech tickers |

The equity analyst is the only persona that screens twice (operating margin, then P/E ascending).
The PE analyst is the only one that pulls financials *before* screening. Honest caveat: because the
PE persona pulls the whole cohort first, its company set differs by construction -- the
mutual-fund-vs-equity difference (CSCO against ADBE/IBM) is the genuinely data-driven one.

**Every number is grounded.** Take any figure out of the answer prose and find it in the evidence
table. There should be no orphans: prose is assembled from evidence rows by templates in
`agent/grounding.py`, and the model never sees a value. To convince yourself the model cannot
invent numbers, run the same query with and without `OPENAI_API_KEY` -- the opening framing
sentence may change, the figures cannot.

**Confidence is computed, not guessed.** The rule lives in `agent/confidence.py`: one slot per
(company, required metric) plus one per requested hiring signal;
`score = 0.65 * coverage + 0.35 * freshness`; **high** additionally requires every required slot
dated within 180 days; **medium** needs `score >= 0.50`; everything else is **low**. A future date
scores 0, not fresh. Sanity check it by comparing a query answered from Yahoo TTM metrics (dated at
build time, so fresh) against one leaning on `liabilities_to_equity`, where 11 of 24 companies have
no row at all and those slots count as missing.

**Screens are honest about gaps.** A `run_sector_screen` answer names what it *excluded* and why
("no liabilities_to_equity observation on file"). A screen that silently ranked 2 of 8 names as if
it had looked at the whole sector would be the bug.

**The agent cannot reach the database directly.** This should print nothing at all:

```bash
grep -rn "sqlite3\|duckdb\|psycopg" agent/
```

## 6. Poking the MCP layer directly

The four tools are plain async functions taking a connection, so you can call them without the
agent and without the subprocess:

```bash
uv run python -c "
import asyncio
from pathlib import Path
from mcp_server import database as db, tools
conn = db.connect(Path('data/agent_techhome.db'))
screen = asyncio.run(tools.run_sector_screen(conn, 'tech', 'operating_margin_ttm', 'desc', 3))
for row in screen.rows: print(row.rank, row.ticker, row.value, row.as_of_date)
print('excluded:', [e.ticker for e in screen.excluded])
"
```

Other arguments worth trying: `get_financials(conn, 'MSFT', ['operating_margin_ttm','trailing_pe'])`,
`get_hiring_signals(conn, 'UPS', 3)`, `list_companies(conn, 'retail')`. Bad inputs should raise
rather than return empty -- unknown ticker, unknown metric, `limit` outside 1-24, bad direction.

Running `uv run python -m mcp_server.server` on its own just sits there waiting for JSON-RPC on
stdin. That is correct stdio-server behaviour, not a hang. Ctrl-C out of it.

## 7. Breaking it on purpose

The design claim is that failures surface instead of quietly degrading into an answer from model
memory. Two ways to confirm.

**Point the client at a database that does not exist.** The server process dies at startup and the
error propagates -- verified: the session raises `McpError: Connection closed` during initialize,
before any tool call, and no answer is produced.

```bash
uv run python -c "
import asyncio
from pathlib import Path
from agent.mcp_client import AgentMcpClient
async def go():
    async with AgentMcpClient(Path('data/nope.db')) as c:
        await c.list_companies('tech')
asyncio.run(go())
"
```

**Same failure through the interfaces.** Temporarily rename `data/agent_techhome.db` and hit the
API: you get a `502` (`api/main.py` maps `McpToolError` to 502), and Streamlit shows an error box
instead of an answer. Rename it back afterwards -- it is a committed file, not a build artifact.

## 8. What is in the data

Verified against the committed database:

- 24 companies, 8 per sector. 918 rows in `financial_observations`, 1,160 in `financial_lineage`,
  24 in `hiring_signals` (one non-null sourced headcount per company).
- tech: `AAPL ADBE CSCO GOOGL IBM META MSFT ORCL`
- retail: `BBY COST DG HD KR LOW TGT WMT`
- logistics: `CHRW EXPD FDX GXO HUBG JBHT UPS XPO`

Look around yourself:

```bash
uv run python -c "
import sqlite3
c = sqlite3.connect('data/agent_techhome.db')
print(sorted(r[0] for r in c.execute('SELECT DISTINCT metric FROM financial_observations')))
print(c.execute('SELECT ticker, signal, value, as_of_date FROM hiring_signals LIMIT 3').fetchall())
"
```

Known thin spots, worth knowing before reading any screen as gospel: `liabilities_to_equity`
resolves for only 13 of 24 tickers and `fcf_margin` for 17 of 24 (uneven SEC XBRL tag coverage),
and the Yahoo-sourced metrics (`market_cap`, `trailing_pe`, `enterprise_to_ebitda`, the `_ttm`
family) are point-in-time observations captured at build time, not filed fiscal periods.

## 9. Rebuilding the database

You do not need to. The committed snapshot is what everything is tested against, and a rebuild
re-dates every Yahoo observation, which moves confidence tiers and eval expectations with it.

If you want to anyway, the safe form replays the cached source responses with no network and writes
to a scratch file:

```bash
uv run python scripts/build_db.py --offline --database data/scratch.db
```

A live rebuild needs a real contact identity -- SEC rejects placeholder User-Agents:

```bash
export SEC_USER_AGENT="agent-techhome your-real-email@your-domain.com"
uv run python scripts/build_db.py
```

Either way the build writes to a temp file in the same directory, validates it
(`scripts/validate_db.py` checks counts, provenance, period semantics, and lineage), and only then
atomically replaces the target. A failed build leaves the previous database untouched.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `ModuleNotFoundError: No module named 'agent'` | An ad-hoc script run from outside the repo root. Use `uv run python -c` from the root, or save the file in the root. The three real entry points (Streamlit, uvicorn, the scripts) each put the root on `sys.path` themselves. |
| Console full of `Processing request of type CallToolRequest` | Normal -- that is the MCP subprocess logging on stderr. Pipe through `grep -v "Processing request"`. |
| `uv run python -m mcp_server.server` appears to hang | Correct: it is a stdio server waiting for JSON-RPC on stdin. |
| Answer has no numbers and confidence is `low` | Either an out-of-scope refusal, or the persona's screen metric has no rows for that sector. Check `tools_called` and the excluded list. |
| Every answer sounds the same across personas | Check `tools_called` first. If the traces differ, the graded property is working -- only the opening framing sentence shares vocabulary. |
| Wanted the LLM path, got the deterministic fallback | `.env` missing or `OPENAI_API_KEY` empty. `agent/config.py` only loads `.env` from the repo root, and a real exported env var takes precedence over the file. |
| `PytestCacheWarning: Access is denied` on `.pytest_cache` | Harmless local directory permissions; the tests still pass. |
