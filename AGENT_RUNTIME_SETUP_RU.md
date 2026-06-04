# Agent Runtime Setup — Signal + Forager

Этот документ — runtime-контракт: как поднять окружение, чтобы агент (Claude / Codex / ChatGPT) мог легально выполнять мастер-команды Signal и Forager.

Operating contracts отвечают на вопрос «**что** агенту разрешено делать».
Этот файл отвечает на вопрос «**где** агенту вообще доступны легальные tool paths».

Если runtime не поднят, агент обязан остановиться с blocker (см. секцию «Что делать, если агент пишет `signal_mcp_server_not_connected`» в конце).

---

## 0. TL;DR — минимальный setup перед новым чатом

В двух разных терминалах PowerShell:

**Терминал A — Forager API:**

```powershell
cd C:\Signal
$env:FORAGER_DB_PATH = "C:\Signal\data\forager.sqlite3"
# опционально, если используешь Brave Search:
# $env:BRAVE_SEARCH_API_KEY = "your_key"
C:\Signal\.tools\python312\python.exe -m uvicorn apps.api.main:app --app-dir forager --host 127.0.0.1 --port 8765
```

**Терминал B — health-check Forager:**

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health | Select-Object -ExpandProperty Content
# ожидаем: {"status":"ok","service":"forager"}
```

**Signal MCP** регистрируется в конфиге Claude/Codex, не как отдельный сервис:

```json
{
  "mcpServers": {
    "polymarket-research": {
      "command": "C:\\Signal\\.tools\\python312\\python.exe",
      "args": ["C:\\Signal\\bot\\mcp_server.py"],
      "cwd": "C:\\Signal\\bot"
    }
  }
}
```

После этого открыть новый чат и запустить нужную мастер-команду из `docs/Signal/workflows/SIGNAL_FORAGER_MASTER_COMMANDS_RU.md`.

---

## 1. Signal MCP — подключение к агент-сессии

### Что это

`bot/mcp_server.py` — FastMCP сервер, который регистрирует все одобренные write-paths Signal:

- `start_workflow_run` / `record_workflow_step` / `finish_workflow_run`
- `research_ledger`, `portfolio_snapshot`, `open_signals`, `incomplete_research_queue`, `pending_outcome_reviews`
- `master_maintenance_audit`, `master_discovery_research_cycle`, `master_market_discovery`, `api_research_enrichment`, `master_learning_cycle`
- `record_resolution_map`, `record_evidence`, `record_actor_map`, `record_causal_factor`, `record_scenario`, `record_premortem`, `record_hidden_gem_review`, `record_moonshot_review`, `record_pre_bet_checklist`, `record_analysis`, `record_forecast_update`, `record_outcome_learning_review`, `record_signal_quality_review`, `record_signal_archetype`
- `validate_signal_gate`, `aladdin_signal_commit`, `record_real_manual_trade`, `record_fill`

Без этого MCP server **любая запись research facts через агента — нарушение `WRITE_POLICY`**.

### Команда запуска (для справки)

```powershell
C:\Signal\.tools\python312\python.exe C:\Signal\bot\mcp_server.py
```

`cwd` обязательно `C:\Signal\bot` — иначе `import db` упадёт.

### Конфиг агента

Добавь в MCP config Claude Code / Codex (`%APPDATA%\Claude\claude_desktop_config.json` или эквивалент):

```json
{
  "mcpServers": {
    "polymarket-research": {
      "command": "C:\\Signal\\.tools\\python312\\python.exe",
      "args": ["C:\\Signal\\bot\\mcp_server.py"],
      "cwd": "C:\\Signal\\bot"
    }
  }
}
```

После правки конфига **перезапусти агент-сессию полностью** (старая сессия не подхватит новые MCP servers).

### Health-check внутри агента

В новом чате попроси агента сделать ToolSearch:

```
query: "select:start_workflow_run,research_ledger,master_discovery_research_cycle"
```

Если все три tool-а резолвятся — Signal MCP подключён.

---

## 2. Forager API — отдельный процесс

### Что это

FastAPI-приложение `forager/apps/api/main.py`. Базовые эндпойнты:

- `GET  /health` — liveness
- `POST /research/core-loop` — **default Forager core path** (см. `docs/Signal/technical/49`)
- `POST /attention/minimal` — **default minimal attention path**
- `POST /research/start`, `POST /threads/{id}/search-burst`, `GET /threads/{id}/signal-bridge`, и др.

Phase 16/17 ecology layers (`/ecology/*`, `/dream/*`, `/narrative/*`, `/infection/*`) — **experimental**, не использовать как core proof.

### Запуск

```powershell
cd C:\Signal
$env:FORAGER_DB_PATH = "C:\Signal\data\forager.sqlite3"
C:\Signal\.tools\python312\python.exe -m uvicorn apps.api.main:app --app-dir forager --host 127.0.0.1 --port 8765
```

Если `FORAGER_DB_PATH` не задан, store будет `InMemoryForagerStore` — данные сгорят при рестарте. Для серьёзных запусков всегда задавай путь к SQLite. Каталог `C:\Signal\data\` создай заранее:

```powershell
New-Item -ItemType Directory -Force C:\Signal\data | Out-Null
```

### Опциональные переменные окружения

```powershell
# Brave Search adapter (forager/forager/search/adapters.py)
$env:BRAVE_SEARCH_API_KEY = "..."
# дополнительные source adapters — см. forager/forager/search/ и forager/forager/integrations/
```

Без `BRAVE_SEARCH_API_KEY` поиск будет работать только через те адаптеры, для которых ключи не нужны или уже подняты.

### Health-check

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health | Select-Object -ExpandProperty Content
# {"status":"ok","service":"forager"}
```

Если эндпойнт молчит больше 2 секунд — Forager не поднялся, смотри stderr процесса в Терминале A.

### Внимание: Forager не доступен агенту как MCP-сервер

Forager — это HTTP API. Агент дотягивается до него либо через MCP-обёртку (если она зарегистрирована — см. `bot/tools/integrations.py` / `forager` tools), либо через `WebFetch` / `curl`-аналог. Если в твоей сессии нет ни того, ни другого:

- Forager runtime считается недоступным;
- агент обязан вернуть blocker `forager_runtime_not_available`;
- допустима частичная команда (только Signal-half), как описано в `SIGNAL_FORAGER_MASTER_COMMANDS_RU.md` §A шаг 9.

---

## 3. Чек-лист перед запуском мастер-команды

Прогони перед каждым новым чатом:

- [ ] `C:\Signal\.tools\python312\python.exe` существует
- [ ] `bot.db` доступна на запись (Signal SQLite)
- [ ] `C:\Signal\data\forager.sqlite3` создаётся / доступна на запись
- [ ] Signal MCP зарегистрирован в конфиге агента и сессия перезапущена
- [ ] Forager API процесс жив, `/health` возвращает `ok`
- [ ] (если нужен Brave) `BRAVE_SEARCH_API_KEY` выставлен в окружении Forager-процесса
- [ ] В агент-сессии ToolSearch резолвит хотя бы `start_workflow_run`, `research_ledger`, `master_discovery_research_cycle`

Только после этого копируй текст мастер-команды из `docs/Signal/workflows/SIGNAL_FORAGER_MASTER_COMMANDS_RU.md`.

---

## 4. Health debug — что делать, если ломается

| Симптом | Вероятная причина | Что делать |
|---------|------------------|------------|
| `start_workflow_run`/`research_ledger` не находятся ToolSearch-ем | Signal MCP не зарегистрирован, либо сессия не перезапущена после правки конфига | Перезапустить агент. Проверить путь к `python.exe` и `cwd=C:\Signal\bot`. |
| Signal MCP падает с `ModuleNotFoundError: db` | Неверный `cwd` | Поставить `"cwd": "C:\\Signal\\bot"` в конфиге |
| Signal MCP падает с `ModuleNotFoundError: mcp` | Зависимости не доустановлены | `C:\Signal\.tools\python312\python.exe -m pip install -r C:\Signal\bot\requirements.txt` |
| Forager `/health` не отвечает | uvicorn не поднялся | Проверить stderr Терминала A, чаще всего — занят порт 8765 или нет `apps.api.main` |
| Forager `/research/core-loop` пишет, но данные пропадают | Не задан `FORAGER_DB_PATH`, используется in-memory store | Перезапустить с `$env:FORAGER_DB_PATH` |
| `BRAVE_SEARCH_API_KEY` не используется | Переменная выставлена в Терминале B, а не в Терминале A | Выставлять переменные **в том же терминале, где стартует uvicorn**, до запуска |

---

## 5. Что делать, если агент пишет `signal_mcp_server_not_connected`

Это **не ошибка агента**, это срабатывание защиты по `AGENT_OPERATING_CONTRACT §1.13` и `WRITE_POLICY` «Missing Tool Rule». Агент сделал правильно, что остановился.

Действия оператора:

1. Открыть этот файл (`AGENT_RUNTIME_SETUP_RU.md`).
2. Пройти секции §1 и §2.
3. Прогнать чек-лист §3.
4. Открыть **новый** чат (текущая сессия уже без MCP — её не оживить).
5. Скопировать ту же мастер-команду из `SIGNAL_FORAGER_MASTER_COMMANDS_RU.md` без изменений.

Что **запрещено** делать в ответ на этот blocker:

- редактировать промпт, чтобы агент «как-нибудь обошёл»;
- разрешать прямые SQLite writes;
- разрешать one-off Python insert scripts;
- генерировать кандидатов «по памяти модели» вместо живого discovery.

Все эти обходы нарушают `WRITE_POLICY`, `AGENT_OPERATING_CONTRACT §1.8–§1.10` и принцип ledger-as-authority (`RESEARCH_LEDGER_STATUS_RULES`).

---

## 6. Где это упоминается

- `AGENT_STARTUP_SEQUENCE.md` §1 — список обязательного чтения. Этот runtime файл подключается отдельно как операционный setup, не как research contract.
- `docs/Signal/workflows/SIGNAL_FORAGER_MASTER_COMMANDS_RU.md` — мастер-команды; они *предполагают*, что runtime поднят по этому документу.
- `forager/OPERATING_CONTRACT.md` — научная граница Forager. Этот файл говорит «**как** Forager поднять», operating contract — «**что** Forager делать нельзя».

---

## Final rule

```text
Operating contracts — что разрешено.
Runtime setup — где это вообще можно сделать.
Если runtime не поднят — не workflow, а blocker.
```
