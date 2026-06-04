# Signal Client Access Product

## Honest status

The current public `signal-client` repository is not yet the full product. It is
a safe client artifact: contracts, integrity checks, local lightweight audit,
hosted-run launcher, and report sharing.

The full product requires hosted execution. If a user receives the full Signal +
Forager source on their own machine, they can read it, patch it, remove checks,
and inspect implementation details. Agent rules and hash locks help with honest
users and LLM workflows, but they are not a security boundary.

## Required product boundary

Use this split:

- Public repo: `tpa3007/signal-client`
  - no private Signal/Forager source;
  - no author database, reports, portfolios, calibration history, or handoffs;
  - only `AGENTS.md`, `CLAUDE.md`, instructions, integrity lock, local lite
    audit, and hosted launcher.
- Private runner: full Signal + Forager checkout
  - runs in a fresh isolated workspace per client run;
  - uses an isolated SQLite database and Forager store per run;
  - has the author's private thresholds, gates, source logic, and command code;
  - can send the final client report and author training copy.
- Queue/API layer:
  - public client submits wallet/positions + command list;
  - private worker consumes job;
  - user polls status and downloads `.md`;
  - author receives `.md` plus structured run-report.

## Client flow

1. User gives `https://github.com/tpa3007/signal-client.git` to Codex or Claude
   Code.
2. Agent reads `AGENTS.md` / `CLAUDE.md`.
3. Agent configures `.env` with author-provided run endpoint and shared secret.
4. Agent runs:

```powershell
python run_signal_machine.py --wallet 0xUserWallet --poll
```

5. The public launcher queues:

```text
G -> G2 -> M -> R -> B -> D -> W -> PORTFOLIO_AUDIT
```

6. The private worker creates the final Markdown report and structured
   `run_report.json`.
7. The client sees only the final report. The author receives the same report
   and metadata for product/model improvement.

## Security rules

- Do not ship full Signal/Forager source to the user if secrecy matters.
- Do not run client jobs against the author's live `bot.db`.
- Do not reuse author report folders or handoff folders for client runs.
- Use one fresh workspace and one fresh DB per client run.
- Make the API write-only from the public client side: submit job, poll own
  `run_id`, receive final report.
- Wallet identity is excluded from the author copy unless explicit consent is
  present.
- The product is research/education only and does not execute trades.

## Implementation pieces now present

- Public hosted launcher: `client_src/run_signal_machine.py`
- Queue API contract: `api/client_runs.py`
- Existing share ingest: `api/ingest.py`
- Public exporter: `export_client_repo.py`
- Isolated DB hook: `SIGNAL_DB_PATH` in `bot/config.py`

## Remaining production work

1. Deploy `api/client_runs.py` and `api/ingest.py`.
2. Add a private worker service that watches the queue directory/storage.
3. Run the worker in a clean container image made from the private repo.
4. For each job, set:

```text
SIGNAL_DB_PATH=/runs/<run_id>/bot.db
FORAGER_DB_PATH=/runs/<run_id>/forager.db
SIGNAL_PROFILE=client
```

5. Execute the command sequence and write:

```text
/runs/<run_id>/client_report.md
/runs/<run_id>/run_report.json
/runs/<run_id>/status.json
```

6. Push the refreshed public artifact to `tpa3007/signal-client`.
