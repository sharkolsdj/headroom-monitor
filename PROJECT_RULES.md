# HeadRoom Monitor — Project rules

## Project Goal

HeadRoom Monitor is a **13-week cash-forecasting and liquidity early-warning module** built
as a demo for the **LHoFT Best Case Study Competition (Financial Navigator by A352)**.
It ingests synthetic transaction data, produces a rolling weekly cash forecast, and uses
LangGraph agents to draft narrative alerts — all with a human-in-the-loop approval gate
before any recommended action is surfaced.

---

## Non-Negotiable Rules

| # | Rule |
|---|------|
| 1 | **All cash numbers are computed deterministically inside `engine/`.** LLMs must never perform or verify arithmetic. If an agent needs a number, it reads it from the engine output. |
| 2 | **No real personal data.** The project uses only synthetic datasets. |
| 3 | **Customers are pseudonymised as `CUST_###`** (e.g. `CUST_001`). No real names, account numbers, or identifiers may appear anywhere in the codebase or data. |
| 4 | **Every state change is audit-logged** with timestamp, actor ID, and the reasoning that triggered the change. See `governance/`. |
| 5 | **No financial action without human approval.** Every proposed action must pass through `gate/` and receive explicit human confirmation before it is executed or recorded as decided. |
| 6 | **Never loosen or bypass a check or test to make it pass; report the failure and its cause instead.** Fix the underlying problem in the code or data. |

---

## Folder Map

```
headroom-monitor/
├── config.py          # Central settings loaded from .env
├── pyproject.toml     # Project metadata and dependencies
├── docker-compose.yml # PostgreSQL 16 on port 5433
├── .env.example       # Template — copy to .env, never commit .env
│
├── data/
│   ├── synthetic/     # Deterministically generated demo datasets
│   └── public/        # Reference data (rates, calendars)
│
├── ingestion/         # Parse, validate, stage raw files → Postgres
├── engine/            # Deterministic forecast calculations (no LLMs here)
├── agents/            # LangGraph agents — narrative, routing, alerting
├── gate/              # Human-approval gate for all proposed actions
├── governance/        # Audit-log writers and compliance helpers
├── tracker/           # 13-week rolling position aggregator
├── frontend/          # FastAPI app + REST endpoints
│
├── docs/              # Architecture, data dictionary, API reference
└── tests/             # Pytest suite
```

---

## How to Run Tests

### Prerequisites

1. Copy `.env.example` to `.env` and adjust credentials if needed.
2. Start Postgres: `docker compose up -d`
3. Create and activate the virtual environment:
   ```
   py -m venv .venv
   .venv\Scripts\activate        # Windows
   pip install -e ".[dev]"
   ```

### Run the full test suite

```
pytest
```

### Run only the smoke test (DB connectivity check)

```
pytest tests/test_smoke.py -v
```

---

## LLM Providers

Set `LLM_PROVIDER` in `.env`:

- `local` — uses Ollama with the model named in `OLLAMA_MODEL` (default `llama3.2`)
- `haiku` — calls `claude-haiku-4-5` via the Anthropic API; requires `ANTHROPIC_API_KEY`
