# signal-client

Public, data-free Signal client artifact.

It lets a user run a read-only portfolio audit on their own Polymarket wallet.
It does not contain the author's private `bot.db`, Signal ledger, reports,
calibration history, or real-money positions.

The intended flow is:

1. A user gives this GitHub repo link to Codex / Claude Code.
2. The agent reads `AGENTS.md` / `CLAUDE.md` and enters CLIENT MODE.
3. The agent helps configure the user's API/share settings.
4. The agent runs `run_client_audit.py`.
5. The user receives a local `.md` audit, and the Signal author receives the
   audit + anonymized run report when the endpoint is configured.

Run:

```powershell
python run_client_audit.py --wallet 0xYourPolymarketWallet
```

See `INSTRUCTIONS.md` and the client-mode contracts in `AGENTS.md`/`CLAUDE.md`.
