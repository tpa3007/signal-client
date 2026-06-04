# Signal Dashboard — развёртывание и автосинхронизация

Дашборд — статический SPA. Данные обновляются локальным демоном, который пишет JSON
и пушит в git; Vercel автоматически передеплоивает.

```
bot/sync_daemon.py  ──pull prices──▶ Polymarket Gamma API
        │
        ├─ write snapshots → bot.db
        ├─ run export_dashboard_data.py → signal-dashboard.json
        └─ git commit + push ──▶ GitHub ──▶ Vercel autodeploy
```

---

## 1. Демон синхронизации

```powershell
cd C:\Signal\bot

# одиночный проход (без git):
python sync_daemon.py --once

# цикл каждые 15 минут:
python sync_daemon.py --interval 900

# цикл + git push для автодеплоя Vercel:
python sync_daemon.py --interval 900 --push
```

Что делает за один проход:
1. Тянет живые YES/NO цены по всем открытым позициям (Gamma API).
2. Пишет свежие снимки в `bot.db` (`source='daemon'`) — так JSON отражает
   актуальные марки даже когда браузер закрыт.
3. Перегенерирует `signal-dashboard.json`.
4. С флагом `--push` — коммитит и пушит JSON.

Демон только вставляет ценовые снимки (как обычный fetch-путь). Он **не создаёт**
сигналы, позиции или fills.

---

## 2. Автозапуск через Windows Task Scheduler

Вместо постоянно висящего процесса — запуск раз в N минут по расписанию ОС.

```powershell
# Создать задачу: каждые 15 минут, скрытно, с git push
$action  = New-ScheduledTaskAction -Execute "python" `
    -Argument "sync_daemon.py --once --push" `
    -WorkingDirectory "C:\Signal\bot"

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName "SignalDashboardSync" `
    -Action $action -Trigger $trigger `
    -Description "Sync Signal dashboard JSON + push to Vercel" `
    -RunLevel Limited
```

Управление:
```powershell
Start-ScheduledTask  -TaskName "SignalDashboardSync"   # запустить сейчас
Get-ScheduledTask    -TaskName "SignalDashboardSync"   # статус
Unregister-ScheduledTask -TaskName "SignalDashboardSync" -Confirm:$false  # удалить
```

> Для git push без интерактивного запроса пароля настройте кэширование креденшелов
> (`git config --global credential.helper manager`) или используйте deploy-токен.

---

## 3. Vercel (однократная настройка)

1. Подключите GitHub-репозиторий в Vercel.
2. **Root Directory:** `dashboard-web`
3. Framework Preset: **Vite** (определяется автоматически, есть `vercel.json`).
4. Build Command: `npm run build` · Output: `dist`.

`vercel.json` уже настроен:
- SPA-rewrites (всё кроме `/data/` → `index.html`)
- `signal-dashboard.json` отдаётся с `must-revalidate` — браузер всегда берёт свежий снимок.

После настройки каждый `git push` с обновлённым JSON триггерит передеплой (~30с).

---

## 4. Локальная разработка

```powershell
cd C:\Signal\dashboard-web
npm install
npm run dev        # http://127.0.0.1:5173
npm run build      # проверка production-сборки
```

Живые цены открытых позиций браузер тянет сам (хук `usePolymarketPrices`, 60с),
поэтому даже между запусками демона открытые позиции показывают актуальную цену.
