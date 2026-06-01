# How To Run Signal Client

Give this GitHub repository link to Codex / Claude Code and tell it:

> Read `AGENTS.md` / `CLAUDE.md`, then run Signal Client on my Polymarket
> wallet. Do not modify protected logic.

1. Copy `.env.example` to `.env` if you want to configure sharing.
2. Fill in:

```text
SIGNAL_CLIENT_ID=<your-name-or-random-id>
SIGNAL_CLIENT_SHARE_ENDPOINT=<provided-by-Signal-author>
SIGNAL_CLIENT_SHARE_SECRET=<provided-by-Signal-author>
```

3. Run an audit from a wallet:

```powershell
python run_client_audit.py --wallet 0xYourPolymarketWallet
```

4. Or run offline from a local positions file:

```powershell
python run_client_audit.py --positions-json positions.json
```

5. The audit is written locally under `client_audits/`.
6. If the share endpoint is configured, the audit and structured run report are
   sent to the Signal author endpoint automatically according to `rules.json`.
   The wallet address is not included unless you pass `--consent-wallet`.
7. To force sharing when no default endpoint is configured:

```powershell
python run_client_audit.py --wallet 0xYourWallet --share
```

This is research/education only, not financial advice.
