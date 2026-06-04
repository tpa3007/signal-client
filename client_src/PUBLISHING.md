# Publishing Checklist

This directory is generated from the private Signal repository. Publish only the
exported artifact, not the private source repository.

1. From private Signal:

```powershell
python export_client_repo.py --target .tmp/signal-client
```

2. Inspect `.tmp/signal-client`:

- `INTEGRITY.lock` exists.
- `bot.db`, `.env`, `llm_handoff`, private reports, and local ledgers are absent.
- `AGENTS.md`, `CLAUDE.md`, and `INSTRUCTIONS.md` are present.

3. Push `.tmp/signal-client` to the public GitHub repository.
4. Give users the GitHub URL plus their endpoint/secret setup.
5. Do not ask client agents to modify protected files; the integrity check should
   fail if they do.
