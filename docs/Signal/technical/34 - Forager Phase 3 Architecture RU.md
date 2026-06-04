# Forager Phase 3 Architecture RU

Дата: 2026-05-20

## Что добавлено

Phase 3 добавляет Forager первые элементы исследовательской нервной системы:

1. Entity relation graph.
2. Claim relation graph.
3. Graph expansion queries.
4. Local-language research profile.
5. SQLite persistence для graph relations и language profiles.
6. API endpoints для `expand-graph` и `local-language-profile`.

## Зачем это нужно

Hidden gem обычно не выглядит как один сильный источник. Чаще это цепочка слабых признаков:

```text
странная ссылка -> документ -> claim -> entity -> соседний actor -> старый источник -> contradiction -> новый query
```

Phase 3 начинает сохранять такие цепочки как структуру, а не как красивый текст в отчете.

## Entity graph

Forager строит `EntityRelation` из co-mentions: если две сущности встречаются в одном документе, между ними создается связь.

Это не доказывает причинность. Это значит:

```text
these entities share an information surface
```

Поле `strength` растет, если связь встречается в нескольких документах.

## Claim graph

Forager строит `ClaimRelation` между claims, если они имеют общий topic language.

Если один из claims contradiction-oriented, relation получает тип:

```text
contradicts
```

И создается anomaly:

```text
claim_contradiction_graph
```

Это важно: теперь противоречие живет не только как sentence в документе, а как relation между claims.

## Graph expansion queries

Из extracted entities Forager генерирует новые поисковые ветки. Например:

```text
Entity -> contradiction query
Entity -> archival query
Entity -> technical query
Entity -> low-visibility query
```

Это первый шаг к рекурсивному Forager: не только искать по исходному рынку, а находить соседние объекты и идти дальше.

## Local-language profile

Forager теперь фиксирует языковую слепую зону.

`LocalLanguageProfile` хранит:

- detected languages;
- primary language;
- needs_translation;
- suggested local-language queries;
- source document ids;
- notes.

Если найден non-English слой, создается anomaly:

```text
local_language_research_required
```

Это особенно важно для Polymarket: edge часто возникает там, где англоязычный рынок не читает локальные источники.

## Что это дает Signal

Signal не должен принимать graph relations как evidence автоматически.

Но Signal получает более богатый context:

- какие entities связаны;
- какие claims противоречат друг другу;
- какие языковые ветки не закрыты;
- какие новые queries Forager предлагает запустить.

## Текущий workflow

```text
research/start
search-burst
crawl-sources
expand-graph
local-language-profile
packet
signal-bridge
```

## Ограничения Phase 3

- Entity graph пока основан на co-mentions, не на доказанной причинности.
- Claim graph rule-based, без semantic embeddings.
- Local-language profile не переводит документы, только фиксирует необходимость слоя.
- Expansion queries пока не запускаются автоматически как recursive swarm.

Это намеренно: сначала сохраняем надежную структуру, потом добавляем ум.

## Phase 4 идеи

### 1. Recursive graph search

Forager должен уметь брать top entities и запускать search burst по ним автоматически, но с лимитами глубины и budget.

### 2. Semantic claim graph

Добавить embeddings/LLM для relation detection:

```text
supports / contradicts / updates / reframes / weakens
```

### 3. Translation queue

Создать очередь документов, которые требуют перевода и повторного extraction.

### 4. Evidence draft layer

Forager сможет предлагать evidence drafts, но Signal должен подтверждать их через legal write path.

### 5. Graph dashboard

Нужно визуально видеть:

- entities;
- relations;
- contradiction clusters;
- language gaps;
- unexplored expansion queries.

## Проверка

На момент записи:

```text
pytest -q forager
13 passed
```
