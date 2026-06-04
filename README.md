# Signal + Forager

Public, source-only fork of the Signal research system and Forager research
engine. This export intentionally contains no author database, personal
portfolio, real-money positions, local run reports, queues, logs, or API keys.

## What Is Included

- `bot/`: Signal command runners, MCP tools, scoring/risk/research helpers,
  tests, and migrations.
- `forager/`: recursive research engine, search/crawl/extraction graph, tests.
- `dashboard-web/`: dashboard source with empty public data placeholders.
- `api/`: client run and ingest API contracts.
- `client_src/`: lightweight public client/launcher tools.
- `docs/Signal/`: architecture, protocol, technical, workflow, and manual docs
  with personal reports excluded.

## What Is Not Included

- `bot.db`, `forager.db`, sqlite backups, wallet config, `.env`, API keys.
- Generated queues/results/reasoning memos/manual shortlist reports.
- Real-money portfolio history and dashboard live portfolio data.
- Personal research reports under `docs/Signal/reports` and root `docs/*.md`.

## Setup

```powershell
cd bot
py -3.12 -m pip install -r requirements.txt
copy .env.example .env
py -3.12 -m pytest -q
```

Free/keyless paths work without paid search keys where the code supports them.
Paid or quota-limited providers such as Brave, Tavily, Anthropic, OpenAI,
YouTube, Reddit, and ACLED must be configured by the fork owner in `.env`.

## Run

```powershell
cd bot
py -3.12 run_cycle.py --mode scan_only
py -3.12 run_command_w.py --top 50
```

Research/education only. No auto-trading.
