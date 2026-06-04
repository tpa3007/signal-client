# Forager Phase 1 Architecture RU

Дата: 2026-05-20

## Что добавлено

Phase 1 превращает Forager из скелета в первую рабочую исследовательскую машину:

1. `source_raw_items` - слой сырых находок до evidence/source.
2. Search adapter interface - можно подключать реальные поисковые API и тестовые источники.
3. Brave Search adapter - включается через `BRAVE_SEARCH_API_KEY`.
4. Search burst workflow - берет query mutations и прогоняет их через search adapter.
5. SQLite persistence - локальная долговременная память Forager.
6. Signal bridge packet - безопасная передача результата в Signal без создания сигнала/позиции.

## Почему source_raw_items важны

До этого была опасная ловушка: агент мог найти статью и сразу воспринимать ее как evidence. Теперь pipeline жестче:

```text
search result -> source_raw_item -> promoted source -> packet -> Signal validation -> evidence only if Signal workflow accepts it
```

Это сохраняет traceability. Мы знаем, какой запрос нашел источник, через какую lens, каким adapter, какой был snippet, weirdness score, relevance score и hash сырого результата.

## Search burst

`run_search_burst` берет первые N query mutations и по каждой делает search call. Каждый найденный результат записывается как `SourceRawItem`.

Если weirdness выше threshold, item продвигается в `Source` и получает anomaly `source_weirdness`.

Это не означает, что Signal должен ставить. Это означает только:

```text
Forager found something worth investigating.
```

## SQLite store

Добавлен `SQLiteForagerStore`. Он хранит:

- threads;
- source_raw_items;
- sources;
- documents;
- entities;
- claims;
- hypotheses;
- anomalies;
- packets.

Store intentionally JSON-first: это быстрее развивать сейчас, чем преждевременно строить тяжелую ORM-схему. При этом у ключевых таблиц есть индексные поля: `thread_id`, `market_id`, `url`, `status`, scores.

## Live search

Реальный поиск включается через composite search adapter:

```text
TAVILY_API_KEY=...
BRAVE_SEARCH_API_KEY=...
```

Приоритет: Tavily -> Brave -> official-source seeds -> Wikipedia -> GDELT. Если платных ключей нет, Forager больше не падает в `NullSearchAdapter`, а работает в degraded режиме через deterministic official seeds, Wikipedia и GDELT. Это не заменяет полноценный web search, но предотвращает пустые blocker-пакеты и сохраняет минимальный путь к источникам.

## Signal bridge

`export_signal_bridge_packet` создает `SignalBridgePacket`.

Он содержит:

- summary;
- weak signals;
- raw source items;
- hypotheses;
- anomalies;
- recommended actions;
- blockers;
- next actions для Signal.

Bridge не может создать:

- signal;
- position;
- fill;
- real-money recommendation.

Граница остается прежней:

```text
Forager discovers. Signal decides.
```

## Что стало возможно

Теперь можно сделать настоящий цикл:

1. Создать thread по рынку Polymarket.
2. Сгенерировать необычные query mutations.
3. Прогнать search burst.
4. Сохранить все сырые находки.
5. Автоматически выделить странные источники.
6. Собрать research packet.
7. Передать packet в Signal как контекст.
8. Signal уже решает, делать ли deep research / checklist / paper signal.

## Следующие идеи Phase 2

### 1. Crawler adapter

Search result мало. Нужно открывать страницы, доставать текст, PDF, markdown, metadata, language, published_at.

### 2. Claim extraction

Forager должен извлекать утверждения:

```text
source says X
source contradicts Y
source implies Z by timing
```

И хранить их отдельно от summary.

### 3. Entity graph

Люди, домены, GitHub repos, алиасы, организации, рынки, регионы, wallets. Hidden gem часто лежит не в статье, а в связи между сущностями.

### 4. Absence detector

Отдельный агент должен искать отсутствие ожидаемых следов: нет changelog, нет filings, нет local endorsements, нет procurement notices, нет API docs, нет final poll.

### 5. Narrative drift monitor

Сравнивать старые и новые формулировки. Если команда меняет “will launch” на “working toward”, Forager должен поднять weak signal.

### 6. Packet ingest into Signal

Нужен безопасный MCP/tool path: Forager packet -> Signal candidate enrichment. Не direct SQL, не one-off script.

## Проверка

На момент записи:

```text
pytest -q forager
7 passed
```
