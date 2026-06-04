# Руководство владельца Signal

Дата: 2026-05-19  
Проект: `C:\Signal`  
Репозиторий: `https://github.com/tpa3007/signal.git`

## 1. Что это за проект

Signal — это локальная исследовательская система для поиска mispriced/hidden-gem рынков Polymarket. Сейчас это не автотрейдер и не система “купил-продал подороже”. Главная идея текущей версии: найти рынок, глубоко разобрать вероятность, принять решение до результата и держать позицию до резолва.

Проект должен помогать думать лучше рынка:

- находить странные, недооцененные или забытые рынки;
- проверять, есть ли реальный edge, а не просто азарт;
- строить dossier по рынку: правила резолва, evidence, акторы, causal factors, сценарии, premortem;
- контролировать риск по вертикалям и темам;
- учиться на исходах, ошибках и false negatives.

Главная фраза проекта:

> Discovery не равно сигнал. Moonshot не равно сигнал. Сигнал появляется только после research gate и pre-bet checklist.

## 2. Что мы имеем сейчас

Текущая версия уже стала не просто скриптом, а маленькой research OS:

1. Локальная SQLite-база `bot/bot.db`: рынки, snapshots, анализы, evidence, сигналы, позиции, outcome reviews и calibration data.
2. MCP-сервер `bot/mcp_server.py`, через который Claude/Codex вызывает инструменты проекта.
3. Discovery layer, который ищет кандидатов и сохраняет найденные рынки в базу.
4. Глубокий research layer: resolution map, evidence, actor map, causal factors, anomalies, scenarios, premortem.
5. Gate перед сигналом: `record_pre_bet_checklist`. Без approved checklist `record_analysis` не должен создавать настоящий сигнал.
6. Risk layer: bankroll, sizing, exposure caps, vertical caps и theme caps.
7. Theme-aware monitoring: система понимает не только “политика/геополитика”, но и кластеры вроде `iran_cluster`, `middle_east_conflict`, `ai_launches`, `spacex_launches`.
8. Moonshot/hidden-gem слой: отдельный watchlist для high-upside идей, которые еще не являются ставками.
9. Learning/calibration слой: отчеты по качеству сигналов, false negatives, post-outcome learning.
10. Документация в `docs/Signal`, где фиксируется развитие проекта и архитектурные решения.

## 3. Главный ежедневный маршрут

Если ты не понимаешь, что запускать, используй этот маршрут.

1. Запусти `daily_research_brief`.

   Это главный обзор дня: открытые позиции, перегрузка по вертикалям и темам, recheck queue, catalysts и кандидаты.

2. Запусти `portfolio_snapshot`.

   Это снимок текущего риска: bankroll, открытые позиции, exposure по vertical/theme, unrealized PnL.

3. Запусти `due_for_recheck`.

   Это очередь рынков, которые пора пересмотреть из-за времени, движения цены или приближения события.

4. Запусти `catalyst_calendar`.

   Это календарь важных дат: резолвы, события, дедлайны, speeches, launches, votes, court dates.

5. Запусти `discovery_scan`.

   Это поиск новых кандидатов. Он может найти интересный рынок, но это еще не сигнал.

6. Если рынок заинтересовал, запусти `backfill_price_history`.

   Это подтянет историю цены и даст контекст: рынок stale, двигается, перегрет, забытый или только что проснулся.

7. Построй dossier:
   - `record_resolution_map`
   - `record_evidence`
   - `record_actor_map`
   - `record_causal_factor`
   - `record_scenario`
   - `record_premortem`
   - при необходимости `record_anomaly`

8. Запусти `record_pre_bet_checklist`.

   Это финальный gate. Если decision не `approved_for_signal`, настоящий сигнал не создаем.

9. Только если checklist approved, запускай `record_analysis`.

   Он создаст analysis, signal, paper position и paper fill. Если это тест или демонстрация, используй `dry_run=True`.

10. После резолва запускай `record_outcome_learning_review`.

   Это превращает результат в обучение: где была ошибка, что рынок видел, чего не видели мы, какой паттерн надо запомнить.

## 4. Самое короткое правило безопасности

```text
daily_research_brief
-> discovery_scan
-> market_research_memory
-> dossier
-> record_pre_bet_checklist
-> record_analysis только при approved_for_signal
```

Нет approved checklist — нет сигнала.

## 5. Основные инструменты MCP

### Intake и briefing

`daily_research_brief`  
Главная стартовая точка дня. Собирает портфель, риски, recheck queue, catalysts и кандидатов.

`catalyst_calendar`  
Показывает ближайшие важные события и резолвы. Нужен, чтобы не пропустить рынок, где probability может резко измениться.

`due_for_recheck`  
Очередь рынков, которые пора пересмотреть из-за времени, движения цены или приближения события.

`fetch_candidates`  
Базовый способ достать кандидатов с Polymarket по фильтрам.

`backfill_price_history`  
Подтягивает историю цен по рынку. Важен перед глубоким анализом, потому что без истории трудно понять stale/momentum/market memory.

`analysis_log`  
Показывает прошлые анализы и сигналы.

`performance_report`  
Сводка по результатам и performance.

`daily_run_status` и `finalize_daily_run`  
Служебные инструменты для учета ежедневного цикла.

### Discovery

`discovery_scan`  
Ищет рынки-кандидаты. Сейчас умеет сохранять найденные рынки и snapshots в базу. Это вход в воронку, а не решение о ставке.

`discovery_overlap_with_open_positions`  
Проверяет, не пересекается ли новый кандидат с уже открытыми позициями/темами.

### Research memory

`market_research_memory`  
Показывает, что система уже знает про рынок: прошлые evidence, analysis, checklist, signals, notes.

`record_evidence`  
Записывает факт/источник/наблюдение. Это кирпичик dossier.

`record_forecast_update`  
Фиксирует изменение вероятности по мере появления новой информации.

`record_analysis`  
Главный инструмент записи финального анализа. Сейчас он должен создавать сигнал только после approved pre-bet checklist. Для демонстраций использовать `dry_run=True`.

### Hold gate и resolution-first thinking

`record_resolution_map`  
Описывает правила резолва: что считается YES/NO, какие источники решают, где ambiguity, какие ловушки формулировки.

`record_pre_bet_checklist`  
Финальный gate перед сигналом. Система сама смотрит, достаточно ли dossier: resolution map, evidence, scenarios, premortem и т.д.

`record_outcome_learning_review`  
Пост-мортем после результата. Нужен, чтобы проект становился умнее, а не просто копил ставки.

`resolution_first_queue`  
Очередь рынков, где надо сначала разобраться с резолвом.

### Causal thinking

`record_actor_map`  
Записывает ключевых акторов: люди, организации, партии, компании, суды, регуляторы, команды.

`record_causal_factor`  
Фиксирует причинный фактор: что реально может двигать вероятность исхода.

`record_anomaly`  
Фиксирует странность: рынок не двигается на новости, цена не совпадает с evidence, есть необычный spread/liquidity/attention pattern.

`record_scenario`  
Строит сценарии: bull/base/bear, paths to YES/NO, timing, blockers.

`record_premortem`  
Вопрос: “Почему эта идея может оказаться плохой?” Один из самых важных инструментов против самообмана.

`contrarian_brief`  
Помогает увидеть обратную сторону идеи: что рынок может понимать лучше нас.

### Hidden gems и moonshots

`record_hidden_gem_review`  
Записывает review по кандидату hidden gem: почему рынок может быть недооценен, какие есть признаки неэффективности.

`hidden_gem_watchlist`  
Список hidden-gem кандидатов, которые еще не обязательно готовы к сигналу.

`record_moonshot_review`  
Отдельный слой для high-upside рынков с маленькой ценой, но не случайных. Это “энтузиазм с фильтром”.

`moonshot_watchlist`  
Очередь moonshot-кандидатов. Это не список покупок, а список идей для жесткой проверки.

### Portfolio и risk

`portfolio_snapshot`  
Главный снимок портфеля и риска.

`exposure_check`  
Проверяет, не перегружена ли вертикаль или тема перед новой позицией.

`mark_to_market_all`  
Переоценивает открытые позиции по текущим market prices.

`pending_outcome_reviews`  
Показывает, по каким закрытым/созревшим позициям еще не сделан learning review.

`record_fill`  
Ручная запись fill. Обычно `record_analysis` сам создает paper fill, поэтому вручную использовать аккуратно.

### Live/manual positions

`record_live_position`  
Ручная запись реальной позиции. Использовать только если ты действительно хочешь отразить live-позицию в базе.

`mark_live_position`  
Пометить позицию как live.

`live_positions_summary`  
Сводка по live позициям.

`open_signals`  
Открытые сигналы/позиции.

`resolve_closed`  
Закрытие/резолв позиций.

`vertical_breakdown`  
Разбивка по вертикалям.

`get_market_details`  
Детали рынка с Polymarket/Gamma API.

### Calibration и обучение

`forecast_quality_report`  
Как хорошо калиброваны прогнозы.

`false_negative_review`  
Разбор рынков, которые мы не взяли, но они оказались хорошими.

`market_move_after_analysis`  
Смотрит, как рынок двигался после нашего анализа. Это важно для понимания, был ли timing edge.

`research_completeness_score`  
Оценка полноты dossier.

`incomplete_research_queue`  
Очередь рынков, где анализ недособран.

`signal_quality_report`  
Качество сигналов и их паттерны.

`signal_regression_benchmark`  
Бенчмарк против старых кейсов, чтобы новая версия не стала хуже.

## 6. Вертикали и темы

Вертикаль — грубая категория рынка. Сейчас основные:

- `us_politics`
- `international_geopolitics`
- `tech_business`
- `science_space`

Старый `geopolitics` оставлен как alias для обратной совместимости, но лучше постепенно мыслить точнее.

Тема — более узкий кластер риска. Например:

- `iran_cluster`
- `middle_east_conflict`
- `ukraine_russia`
- `us_primary_2026`
- `us_cabinet_appointments`
- `central_bank_fed`
- `ai_launches`
- `spacex_launches`

Почему это важно: два рынка могут выглядеть разными, но на самом деле зависеть от одного события. Theme caps защищают от иллюзии диверсификации.

## 7. За что отвечают файлы и скрипты

### Главные файлы

`bot/mcp_server.py`  
Главная точка входа для Claude/Codex MCP. В обычной жизни именно через него надо работать с инструментами проекта.

`bot/config.py`  
Настройки: bankroll, thresholds, confidence gates, exposure caps, verticals, theme tags. Если меняешь риск-логику, чаще всего смотри сюда.

`bot/db.py`  
SQLite schema и низкоуровневые helpers. Здесь создаются таблицы и миграции.

`bot/markets.py`  
Работа с Polymarket/Gamma API, нормализация рынков, классификация vertical/theme.

`bot/tools/`  
Главная папка современной логики. Здесь находятся MCP-инструменты по слоям: discovery, research, hold, causal, gems, portfolio, calibration.

`bot/lib/`  
Внутренние helper-модули: sizing, risk, portfolio utils, formatting, shared logic.

`bot/tests/`  
Тесты. После серьезных изменений запускать pytest.

### Старые или вспомогательные скрипты

`bot/app.py`  
Streamlit dashboard. Полезен как визуальный черновик, но он устаревший относительно MCP-логики. Не считать его главным интерфейсом.

`bot/dashboard.py`  
Терминальный dashboard. Может быть полезен для быстрого обзора, но тоже не главный слой принятия решений.

`bot/paper_loop.py`  
Legacy orchestrator через Anthropic API. Сейчас не основной путь. Не запускать по привычке, пока не будет отдельного решения обновить его под новую архитектуру.

`bot/research.py`  
Legacy research engine для старого `paper_loop.py`. Не путать с `bot/tools/research.py`, который сейчас является частью актуальной MCP-архитектуры.

`bot/report.py`  
Старые отчеты. Может быть полезен для идей, но не центр проекта.

`bot/backfill_live.py`  
One-off script для старых live-позиций. Не запускать casually, потому что он может менять состояние базы.

`archive/demos/`  
Архив демонстрационных скриптов. Не запускать против live `bot.db`, если специально не делаешь dry-run/эксперимент.

## 8. Что запускать из терминала

Все команды ниже выполнять из `C:\Signal\bot`.

Установка зависимостей:

```powershell
cd C:\Signal\bot
py -3.12 -m pip install -r requirements.txt
```

Запуск тестов:

```powershell
cd C:\Signal\bot
py -3.12 -m pytest -q
```

Streamlit dashboard, если хочется посмотреть старый UI:

```powershell
cd C:\Signal\bot
streamlit run app.py
```

Терминальный dashboard:

```powershell
cd C:\Signal\bot
py -3.12 dashboard.py
```

Live terminal dashboard:

```powershell
cd C:\Signal\bot
py -3.12 dashboard.py --live
```

Главная работа проекта сейчас должна идти не через эти dashboard-скрипты, а через MCP-инструменты.

## 9. Как думать про moonshots

Moonshot-слой нужен, но он не должен превращать проект в казино.

Правильная логика:

1. Сначала рынок попадает в moonshot watchlist из-за asymmetric upside.
2. Потом проходит обычный research pipeline.
3. Потом проходит pre-bet checklist.
4. Потом sizing engine режет размер, если confidence низкий или тема перегружена.

Moonshot — это кандидат на более глубокое исследование, а не разрешение брать любой high payout.

## 10. Как не испортить базу

1. Для демо использовать `dry_run=True`.
2. Не запускать архивные demo scripts против `bot/bot.db`.
3. Не создавать signal без `record_pre_bet_checklist`.
4. Не использовать `record_live_position`, если позиция не реальная.
5. Перед крупными экспериментами делать backup `bot/bot.db`.
6. Если видишь illustrative/demo данные в живой базе, лучше вынести их в архив или удалить после backup.

## 11. Что дальше улучшать

Ближайшие сильные направления:

1. Новый dashboard, который отображает именно современную research OS: daily brief, risk caps, theme clusters, recheck queue, dossier completeness.
2. Source registry: список источников по типам, надежности, latency и bias.
3. Anomaly inbox: отдельная очередь странных рынков, где цена не реагирует на новости или рынок неверно интерпретирует правила.
4. Research paper export: превращать цепочку анализов, ошибок и learning reviews в материал для исследовательской работы.
5. Signal benchmark suite: регулярно проверять, что новая версия не стала хуже старой.
6. Telegram/news ingestion позже, когда будет стабильный способ доступа и понятная source hygiene.
7. Better resolution parser: автоматический разбор формулировки рынка и warning по ambiguous terms.
8. Retrospective engine: “что мы должны были увидеть раньше?” после каждого важного исхода.

## 12. Ментальная модель проекта

Signal должен быть не “ботом, который угадывает”, а исследовательской лабораторией.

Каждый рынок проходит путь:

```text
Candidate
-> Hidden gem / Moonshot / Normal discovery
-> Resolution-first check
-> Evidence dossier
-> Actor and causal model
-> Scenario tree
-> Premortem
-> Pre-bet checklist
-> Signal or no-signal
-> Hold to resolution
-> Outcome learning
-> Calibration memory
```

Цель не просто найти одну удачную ставку. Цель — построить систему мышления, которая со временем начинает видеть:

- где рынок ленится;
- где рынок слишком буквально читает headline;
- где резолв устроен иначе, чем думает толпа;
- где важный актор имеет incentive сделать действие;
- где событие выглядит маловероятным, но path dependency уже включилась;
- где цена маленькая не потому, что шанс нулевой, а потому что рынок не смотрит.

## 13. Если совсем коротко

Обычный день:

```text
1. daily_research_brief
2. portfolio_snapshot
3. due_for_recheck
4. catalyst_calendar
5. discovery_scan
6. backfill_price_history для интересных рынков
7. dossier tools
8. record_pre_bet_checklist
9. record_analysis только если approved
10. outcome review после резолва
```

Главный интерфейс: MCP tools.  
Главная база: `bot/bot.db`.  
Главная папка логики: `bot/tools`.  
Главный принцип: не сигнал без полного исследования.
