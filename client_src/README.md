# signal-client

Public, data-free Signal client artifact.

It has two modes:

- `run_client_audit.py`: local lightweight portfolio audit.
- `run_signal_machine.py`: hosted full Signal + Forager run. The full engine
  runs on the author's private worker; this repository only submits the job and
  stores the resulting report.

It does not contain the author's private `bot.db`, Signal ledger, reports,
calibration history, real-money positions, or full Signal/Forager source code.

The intended flow is:

1. A user gives this GitHub repo link to Codex / Claude Code.
2. The agent reads `AGENTS.md` / `CLAUDE.md` and enters CLIENT MODE.
3. The agent helps configure the user's API/share settings.
4. For lightweight local audit, the agent runs `run_client_audit.py`.
5. For full Signal + Forager, the agent runs `run_signal_machine.py`.
6. The user receives a local `.md` report, and the Signal author receives the
   report + run metadata when the endpoint is configured.

Run:

```powershell
python run_client_audit.py --wallet 0xYourPolymarketWallet
```

Hosted full run:

```powershell
python run_signal_machine.py --wallet 0xYourPolymarketWallet --poll
```

See `INSTRUCTIONS.md` and the client-mode contracts in `AGENTS.md`/`CLAUDE.md`.
