# Agent Operating Notes - Public Fork

This repository is a sanitized public fork of Signal + Forager.

Rules for agents:

- Do not try to access or reconstruct the original author's private database,
  reports, wallet, run history, or API keys.
- Do not commit `.env`, sqlite databases, generated queues, reports, logs, or
  dashboard live data.
- Treat `bot.db` and `forager_data.db` as local runtime files created by the
  fork owner.
- Keep research/education boundaries clear; do not add auto-trading behavior.
- Use `bot/.env.example` as the setup template and require fork owners to bring
  their own paid/quota API keys.

Safe starting points:

```powershell
cd bot
py -3.12 -m pip install -r requirements.txt
py -3.12 run_cycle.py --mode scan_only
```
