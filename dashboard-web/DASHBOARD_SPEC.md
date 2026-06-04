# Signal Dashboard — Техническое задание на редизайн

**Версия:** 1.0  
**Дата:** 2026-06-01  
**Статус:** Проектирование

---

## 1. Контекст и назначение

Signal — система предиктивной аналитики для торговли на рынке предсказаний Polymarket. 70% работы выполняет оператор вручную через Claude Code: находит рынки с edge, анализирует источники, принимает решения. Задача дашборда — дать оператору единое место для:

- Просмотра текущих позиций с живыми ценами
- Чтения цепочки рассуждений модели как дневника
- Оценки качества каждого решения (почему взяли, как сыграло)
- Мониторинга аномалий и kill criteria
- Ретроспективного анализа паттернов и ошибок

Дашборд не торгует сам — это **editorial intelligence board**, не трейдинг-терминал.

---

## 2. Аудитория и контекст использования

**Основной пользователь:** один оператор (себя), технически грамотный, работает с Claude Code ежедневно.

**Сценарии использования:**
- Утром: проверить открытые позиции, посмотреть что изменилось в ценах overnight
- После цикла: прочитать дневник форейджера по новым маркетам
- Перед решением войти: просмотреть аналогичные закрытые позиции
- Ретроспектива: найти паттерн ошибок за последний месяц

**Контекст просмотра:**
- Широкий монитор (1440px+), возможно два окна рядом
- Редко мобильный (но поддержать базово)
- Не нужен real-time sub-second — достаточно обновления раз в минуту

---

## 3. Источники данных

### 3.1 Статичный JSON-снимок
Файл `signal-dashboard.json` генерируется командой `python export_dashboard_data.py`.

Содержит:
```
summary           — агрегированные метрики портфеля
signals[]         — все сигналы с полным контекстом
diary[]           — глобальный дневник (все entries всех сигналов)
workflowRuns[]    — история запусков пайплайна
modelEvolution[]  — хроника изменений системы
```

Каждый сигнал содержит:
```
conditionId        — уникальный идентификатор рынка
title              — вопрос рынка
category           — Geopolitics / Elections / Macro / AI / Private Markets
status             — COMMITTED / DRAFT / CLOSED
side               — YES / NO
sideEntryPrice     — цена входа
currentSidePrice   — текущая цена (из снимка, перекрывается живыми ценами)
unrealizedPnl      — текущий P&L (пересчитывается при живых ценах)
edge               — оцениваемое преимущество в %
confidence         — уверенность оператора
thesis             — тезис: почему рынок ошибается
evidence[]         — источники и их стойкость
actors[]           — акторы, их мотивы и вероятные действия
gateCheck          — результаты предторгового чеклиста
monitorRecommendation — HOLD / REVIEW / EXIT
monitorReason      — обоснование рекомендации
diaryEntries[]     — цепочка рассуждений (от гипотезы до резолюции)
review             — постмортем (только для закрытых)
```

### 3.2 Live Polymarket API (browser-side)
`GET https://gamma-api.polymarket.com/markets?condition_id={cid}`

Поле `outcomePrices` — JSON-строка `"[yes_price, no_price]"`.

Используется для: обновления `currentYesPrice / currentNoPrice / unrealizedPnl` открытых позиций каждые 60 секунд прямо в браузере. Бэкенд не нужен.

### 3.3 llm_handoff diary entries
Форейджер записывает цепочку рассуждений в `bot/llm_handoff/` как JSON-файлы. Типы:
- `hypothesis_*` — гипотезы по маркету (YES/NO/UNCERTAIN, confidence, evidence_score)
- `dossier_draft_*` — второй слой: kill criteria, сценарии, премортемы, confidence adjustment
- `monitoring_draft_*` — мониторинг открытой позиции: рекомендация HOLD/REVIEW/EXIT, kill criteria

Экспортер собирает их в `diaryEntries[]` per signal и в глобальный `diary[]`.

---

## 4. Разделы и функционал

### 4.1 Portfolio (главный экран)

**Метрики (верхняя полоса):**
- Реальный капитал в рынке (сумма `realBetUsd` открытых позиций)
- Paper exposure (сумма `allocatedCapital` paper-позиций)
- Unrealized P&L с live-ценами (автообновляется)
- Средний edge по всем сигналам

**Attention strip:**
- Список позиций требующих внимания (EXIT/REVIEW или истекающих <3d)
- Клик переходит к детальной карточке

**Список сигналов:**
- Фильтры: статус (все/в рынке/черновики/закрытые), тип капитала (все/реальный/paper)
- Сортировка: по риску / по P&L / по expiry / по edge / по дате
- Поиск по тексту
- Карточка сигнала: категория, заголовок, направление, entry → текущая, P&L

**Детальная карточка:**
- Полный тезис (blockquote)
- Probability gap visualization (market vs model на шкале)
- Monitor panel: рекомендация + дата expiry + SDV + kill criteria coverage
- Evidence ledger (до 4 источников)
- Actor map (до 4 акторов)
- Gate check (ликвидность, spread, риск-лимиты)
- **Reasoning chain** — хронология: сигнал создан → форейджер → мониторинг → резолюция
- Для закрытых: outcome + realized P&L + заметки постмортема

### 4.2 Дневник (Diary)

Глобальный хронологический feed всех рассуждений системы.

**Фильтры по типу:**
- Все
- Форейджер (dossier entries с гипотезами)
- Мониторинг (command F entries)
- Сигналы (моменты создания)
- Завершённые (резолюции)

**Entry card:**
- Дата + тип-бейдж + ссылка на рынок
- Заголовок (для monitoring — HOLD/REVIEW/EXIT badge)
- Краткое тело (первые 260 символов)
- Expandable: гипотезы с direction/confidence, kill criteria, сценарии
- Для dossier: signal_decision_value, confidence_adjustment

**Назначение раздела:**
Читать как дневник. "23 мая: Форейджер проверил Болсонаро — 6 гипотез, dominant whale NO, рекомендация высокое значение. 24 мая: сигнал создан с edge 12%. 27 мая: мониторинг — HOLD, новых дисконфирмирующих сигналов нет."

### 4.3 Эволюция модели

Хроника архитектурных изменений системы Signal.

- Timeline-записи: дата, версия, статус изменения, описание
- Метрики (total signals, open, paper accuracy)
- History последних workflow runs

---

## 5. Технические требования

### 5.1 Стек
- **Frontend:** React 18 + Vite (уже есть)
- **CSS:** vanilla CSS (никаких CSS-фреймворков — дизайн должен быть уникальным)
- **Deployment:** Vercel (static SPA)
- **Live prices:** browser → Polymarket CLOB/Gamma API напрямую (CORS открытый)
- **Data refresh:** static JSON обновляется локально через `python export_dashboard_data.py` + git push

### 5.2 Performance
- First meaningful paint < 1s (JSON ~500KB gzipped ~50KB)
- Live price update интервал: 60s
- Infinite scroll или виртуализация для diary feed (200+ entries)

### 5.3 Отсутствие бэкенда
Дашборд — полностью статический SPA. Никакого серверного кода, никакой БД в браузере. Все данные — из JSON-снимка + прямые запросы к Polymarket API.

---

## 6. Дизайн-направления для экспериментов

Ниже — 6 различных направлений. Каждое представляет полноценный дизайн-язык. **Рекомендую попробовать минимум 2-3 перед финальным выбором.** Ни одно не является обязательным — это отправные точки для экспериментов.

---

### 6.1 High Editorial (газетный)

**Вдохновение:** Financial Times, The Economist, дорогие журналы о финансах.

**Характеристики:**
- Шрифт с засечками для заголовков (Georgia / Playfair Display / Cormorant Garamond)
- Моноширинный для цифр и кодов (IBM Plex Mono / Roboto Mono)
- Цветовая палитра: кремовый фон `#FAF8F2`, чёрные заголовки, золото `#9B865A` как акцент
- Вертикальная типографика, сильные weights (900 для лейблов, 300-400 для длинных текстов)
- Минимум цвета — только где несёт смысл (зелёный = в плюс, красный = в минус)
- Grid как у газеты: широкие колонки, чёткие линии разделителей
- Нет теней, нет gradients, нет rounded corners

**Signature elements:**
- Заголовок в стиле газеты: `SIGNAL · EDITORIAL BOARD · JUNE 2026`
- Разделители как горизонтальные правила с засечками по краям: `── OPEN POSITIONS ──`
- Числа набраны крупно, почти как pullquote

---

### 6.2 Neumorphism (мягкий 3D)

**Вдохновение:** dribbble-neomorphism 2020, мягкие shadows, материальный дизайн 3.0.

**Характеристики:**
- Светлый монохромный фон `#E8E0DC` или `#ECEFF1`
- Элементы "выдавлены" из фона: `box-shadow: 6px 6px 12px rgba(0,0,0,0.12), -6px -6px 12px rgba(255,255,255,0.8)`
- Pressed state: инвертированные shadows (вдавленный эффект)
- Цвет: практически монохромный, акценты только на важных числах
- Border-radius: 12-16px на карточках, 999px на чипах
- Текст: Inter или SF Pro, medium weight

**Риски:** плохая читаемость мелкого текста. Если идёте в этот стиль — увеличьте размер шрифта до 14px minimum для body.

**Signature elements:**
- Метрики как "циферблаты" — круглые карточки с крупной цифрой внутри
- Кнопки выдавлены из поверхности
- Активное состояние — вдавлено

---

### 6.3 Dark Terminal (Bloomberg-inspired)

**Вдохновение:** Bloomberg Terminal, TradingView dark, Hacker News.

**Характеристики:**
- Тёмный фон: `#0D1117` (GitHub dark) или `#0A0A0A`
- Монохромный + неоновые акценты: `#00FF41` (зелёный матрица) или `#FFD700` (жёлтый Bloomberg)
- Весь текст — моноширинный шрифт (JetBrains Mono / IBM Plex Mono)
- Таблицы и сетки — основной layout
- Минималистичные borders: `1px solid rgba(255,255,255,0.08)`
- Scanline эффект (опционально, тонкий)
- Uppercase везде

**Signature elements:**
- Header как системная строка: `[SIG] POLYMARKET RESEARCH BOT v3.0 | UTC 2026-06-01 14:23:05`
- Статусы как ASCII-индикаторы: `[■■■■□] 82%` или `▲ +$14.20`
- Live badge пульсирует: `● LIVE`
- Reasoning diary как "логи" с timestamp prefix: `[2026-05-23T10:41:41Z] DOSSIER: ...`

---

### 6.4 Swiss/Bauhaus (брутальная сетка)

**Вдохновение:** Helvetica Now, Swiss International Style, Massimo Vignelli, brutalist web.

**Характеристики:**
- Жёсткая модульная сетка, нет отступления от неё ни на пиксель
- Цвет: чёрный + белый + один акцентный (красный `#E53E3E` или синий `#2B6CB0`)
- Helvetica / Arial / Inter Extra Bold для заголовков
- Никакого декора — только информационная иерархия
- Таблицы как основной способ показа данных
- Огромные числа (статистика): 72px+

**Signature elements:**
- Навигация: чёрный прямоугольник на весь header, белый текст uppercase
- Активный раздел: красный прямоугольник под номером/буквой
- Карточки: прямые углы, чёрная border 2px
- Diary: нумерованный список как газетная колонка

---

### 6.5 Minimalist Zen (японский минимализм)

**Вдохновение:** Muji, 1-line.io, Linear.app, Notion.

**Характеристики:**
- Белый или очень светлый фон `#FAFAFA`
- Практически нет цвета: только текст и пространство
- Маленький шрифт (11-12px) для мета-данных, крупный (24-28px) для ключевых числе
- Тонкие линии: `1px solid #F0F0F0`
- Spacing — главный инструмент иерархии (не шрифт, не цвет)
- Анимации: только opacity transition 200ms
- Никаких теней, никаких иконок (только текст)

**Signature elements:**
- Все цифры в monospace, выровнены по правому краю
- Карточки — просто bordered boxes, никакого background
- Diary: minimal timeline как линия с точками
- Status: просто текст с цветом (зелёный/красный) без бейджей

---

### 6.6 Data Viz First (информационная визуализация)

**Вдохновение:** Nate Silver's 538, The Pudding, Observablehq.

**Характеристики:**
- Данные визуализируются везде где это возможно (не просто числа)
- Probability bar для каждого сигнала (цветной gradient market→model)
- Sparklines для истории цены
- Confidence circles вместо числовых рейтингов
- PnL waterfalls, portfolio allocation pie
- Цветовая схема: diverging colorscale (синий=NO выгодно, красный=YES выгодно)
- Светлый фон, data-ink ratio максимальный (по Tufte)

**Signature elements:**
- Portfolio view: scatter plot edge vs confidence, каждая точка = позиция
- Signal card: мини-chart "price journey" за время жизни позиции
- Diary: timeline с осью X = дата, Y = confidence
- Hypothesis display: diverging bar chart YES vs NO confidence

---

## 7. Компонентная архитектура (рекомендуемая)

```
App
├── Topbar
│   ├── Brand
│   ├── LiveBadge
│   └── MainNav (Portfolio | Дневник | Эволюция)
│
├── PortfolioView
│   ├── MetricGrid (4 карточки)
│   ├── AttentionStrip
│   └── PortfolioGrid
│       ├── SignalList
│       │   ├── PortfolioTools (search + sort)
│       │   ├── StatusTabs
│       │   ├── CapitalSegment
│       │   └── SignalCard[]
│       └── SignalDetail
│           ├── DetailHeader
│           ├── AllocationBox (type + P&L)
│           ├── MonitorPanel
│           ├── EdgeMap (probability scale)
│           ├── ThesisSection
│           ├── EvidenceLedger
│           ├── ActorMap
│           ├── GateGrid
│           └── ReasoningChain (diary timeline)
│
├── DiaryView
│   ├── DiaryHead
│   ├── DiaryFilters
│   └── DiaryFeed
│       └── DiaryEntryCard[]
│           ├── DiaryCardHead (date + type + signal link)
│           ├── DiaryCardBody (heading + body text)
│           └── DiaryDetail (expandable: hyps + kill criteria + scenarios)
│
└── ModelEvolution
    ├── EvolutionHead
    ├── EvolutionMetrics
    ├── Timeline
    │   └── TimelineItem[]
    └── WorkflowPanel
```

---

## 8. Интерактивность и состояние

### Глобальное состояние
```javascript
view            // "PORTFOLIO" | "DIARY" | "MODEL_EVOLUTION"
selectedId      // id выбранного сигнала
statusFilter    // "ALL" | "COMMITTED" | "DRAFT" | "CLOSED"
capitalFilter   // "ALL" | "REAL" | "PAPER"
search          // строка поиска
sortMode        // "RISK" | "RECENT" | "PNL" | "EXPIRY" | "EDGE"
mobileView      // "LIST" | "DETAIL"
isModalOpen     // bool для модала создания черновика
```

### Переходы
- Клик на signal в DiaryView → устанавливает `view="PORTFOLIO"` + `selectedId`
- Клик на signal в AttentionStrip → устанавливает `selectedId` + `mobileView="DETAIL"`
- "Новое исследование" → открывает modal (draft-only, не пишет в БД)

### Live prices
```javascript
usePolymarketPrices(openConditionIds)
// → каждые 60s обновляет currentYesPrice/currentNoPrice/unrealizedPnl
// → показывает LiveBadge со статусом и временем
```

---

## 9. Что НЕ входит в scope дашборда

- Реальное размещение ордеров (только просмотр)
- Запись в базу данных
- Аутентификация (внутренний инструмент)
- Пуш-уведомления (не нужны)
- Исторические графики цены (nice to have, не критично)
- Сравнение с другими трейдерами/портфелями

---

## 10. Файловая структура

```
dashboard-web/
├── src/
│   ├── App.jsx                   # Главный компонент
│   ├── usePolymarketPrices.js    # Live price hook
│   ├── styles.css                # Все стили
│   └── main.jsx                  # Entry point
├── public/
│   └── data/
│       └── signal-dashboard.json # Генерируется bot/export_dashboard_data.py
├── package.json
└── vite.config.js (если нужен)
```

---

## 11. Параметры для оценки качества дизайна

Хороший дизайн для этого дашборда отвечает на эти вопросы:

1. **Ориентация:** За 3 секунды понятно — что сейчас открыто, в плюсе или минусе?
2. **Приоритет:** Самое важное (EXIT/REVIEW) визуально выделено без усилий?
3. **Дневник:** Читается как нарратив, а не как таблица данных?
4. **Плотность:** Не режет глаза, но и нет пустого места на мониторе 1440px?
5. **Уникальность:** Не похож на стандартный crypto dashboard / Binance / TradingView?

---

## 12. Текущее состояние (baseline)

Реализовано:
- [x] React SPA с Vite
- [x] Portfolio view: метрики, attention strip, список, детальная карточка
- [x] Live prices через `usePolymarketPrices` hook (60s polling, Gamma API)
- [x] LIVE badge в топбаре
- [x] Дневник (DiaryView) — global feed
- [x] ReasoningChain в SignalDetail
- [x] Modal создания черновика
- [x] Model Evolution раздел
- [x] Export скрипт с diary entries из llm_handoff
- [x] **Sparklines** — путь цены YES per position (из 31k snapshots), с линией входа
- [x] **Smart money panel** — позиционирование умных кошельков, agreement с нашей стороной, timing α
- [x] **Analytics view** — калибровка (predicted vs actual по бакетам), Brier vs market, экспозиция по категориям и архетипам

- [x] **Переключатель тем** — live A/B между Editorial / Terminal / Swiss (топбар, сохраняется в localStorage через `data-theme` + CSS-переменные)
- [x] **Auto-sync demon** (`bot/sync_daemon.py`) + Vercel config + DEPLOYMENT.md
- [x] **Brier + калибровка** активированы → панель аналитики наполнена

Не реализовано / улучшения:
- [ ] Ещё 3 дизайн-направления из списка (Neumorphism, Zen, Data-Viz) как темы
- [ ] Sparkline прямо в карточке списка (сейчас только в detail)
- [ ] Win rate trend во времени (нужно больше резолюций)
- [ ] Поиск внутри diary
- [ ] Export diary как PDF/Markdown
- [ ] Vercel deployment + CI/CD (git push → autodeploy)
- [ ] Windows Task Scheduler для `export_dashboard_data.py` каждые 15 мин
