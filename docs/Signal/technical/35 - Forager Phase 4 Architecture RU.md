# Forager Phase 4 Architecture RU

Дата: 2026-05-20

## Что добавлено

Phase 4 делает две важные вещи:

1. Recursive graph search.
2. Translation queue.

Теперь Forager может не только построить graph expansion queries, но и ограниченно запустить по ним новый search burst. Также non-English documents больше не теряются как notes: они попадают в отдельную очередь перевода.

## Recursive graph search

Workflow:

```text
expand_graph
-> expansion_queries
-> limited search burst
-> source_raw_items
-> promoted sources
```

Это первый шаг к recursive Forager.

Ключевой принцип: recursion must be bounded.

Поэтому `RecursiveSearchRequest` содержит:

- `max_queries`;
- `results_per_query`;
- `promote_threshold`;
- `max_entities`;
- `mutations_per_entity`.

Forager не может уйти в бесконечное копание. Он делает ограниченный шаг и фиксирует, что нашел.

## Translation queue

Workflow:

```text
crawled document
-> language != en
-> translation queue item
-> blocker/context for later extraction
```

`TranslationQueueItem` хранит:

- thread_id;
- document_id;
- source_id;
- url;
- original language;
- target language;
- status;
- priority;
- reason.

Пока Phase 4 не переводит текст. Это правильно: сначала нужна очередь и traceability, потом execution layer.

## Почему это важно

Много edge на Polymarket появляется из-за двух вещей:

1. Англоязычный рынок не читает локальные источники.
2. Важный сигнал находится не по исходному market query, а через соседнюю entity.

Phase 4 закрывает обе архитектурные дыры.

## Новые endpoints

```text
POST /threads/{thread_id}/recursive-graph-search
POST /threads/{thread_id}/translation-queue
```

## Ограничения

- Recursive graph search пока не запускает crawl автоматически по новым promoted sources.
- Translation queue пока не исполняет перевод.
- Нет budget ledger для рекурсии.
- Нет scoring качества expansion queries.

Это будет в следующих фазах.

## Проверка

На момент записи:

```text
pytest -q forager
17 passed
```
