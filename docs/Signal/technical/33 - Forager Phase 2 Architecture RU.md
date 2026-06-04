# Forager Phase 2 Architecture RU

Дата: 2026-05-20

## Что добавлено

Phase 2 превращает Forager из машины поиска ссылок в машину чтения документов.

Добавлено:

1. Crawler adapter interface.
2. `SimpleHttpCrawlerAdapter` для обычных HTML/text страниц.
3. `StaticCrawlerAdapter` для воспроизводимых тестов.
4. `Document` persistence.
5. Rule-based claim extraction.
6. Rule-based entity extraction.
7. Entity mentions как связка entity -> document -> thread.
8. Document-level anomalies.
9. Bridge blocker `documents_not_crawled`.

## Новая цепочка

```text
search result
  -> source_raw_item
  -> promoted source
  -> crawled document
  -> claims/entities/mentions
  -> anomalies
  -> research packet
  -> Signal validation
```

Главное: Forager больше не просто говорит “вот странная ссылка”. Он начинает говорить:

- какой документ был прочитан;
- какие утверждения в нем обнаружены;
- какие сущности там встретились;
- какие mentions связывают сущности с документом;
- какие противоречия или плотные entity surfaces заслуживают внимания.

## Почему extraction пока rule-based

Это сознательное решение. LLM extraction будет мощнее, но сначала нужен deterministic baseline, который:

- тестируется;
- не требует API;
- не выдумывает claims;
- сохраняет прямую связь claim -> document;
- дает скелет для будущих LLM/Firecrawl/Playwright extractors.

Rule-based extractor не должен быть “умным аналитиком”. Он должен быть честным сборщиком первичных структур.

## Claims

Claim - это не истина. Это утверждение, найденное в документе.

Forager сейчас выделяет предложения с маркерами:

- will / expected / expects;
- announced / said / claims;
- denied / contradicts / dispute;
- launch / delay / poll / leads;
- Polymarket / odds / probability;
- GitHub / commit / changelog / API / release.

Каждый claim получает:

- `claim_text`;
- `normalized_claim`;
- `claim_type`;
- `stance`;
- `document_id`.

## Entities и mentions

Entity - это объект: человек, организация, домен, GitHub repo, username, event и т.д.

Mention - это место, где entity встретилась в документе.

Это важно для будущего графа. Hidden gem часто рождается не из одного факта, а из связи:

```text
local forum -> unknown actor -> old GitHub issue -> changed roadmap -> Polymarket market misprice
```

## Document anomalies

Появились первые document-level anomalies:

- `document_contradiction_claims` - документ содержит contradiction-oriented claims.
- `dense_entity_surface` - документ раскрывает много сущностей и может быть полезен для graph expansion.

Это не trading edge. Это просьба к Forager/Signal копать глубже.

## Bridge blocker

Если packet построен без crawled documents, Signal bridge добавляет blocker:

```text
documents_not_crawled
```

Так агент не сможет красиво передать в Signal поверхностный packet как будто он был deep research.

## Что стало возможно

Теперь можно сделать такой цикл:

1. `research/start`
2. `search-burst`
3. `crawl-sources`
4. `packet`
5. `signal-bridge`

И получить не только ссылки, но и первичные структуры исследования.

## Phase 3 идеи

### 1. Firecrawl / Playwright adapter

Simple HTTP не хватит для JS-heavy страниц, PDF, paywall snippets, локальных сайтов и архивов. Нужен adapter слой, который можно переключать по source type.

### 2. PDF extraction

Многие hidden gems живут в PDF: filings, reports, poll tables, official notices, archived docs.

### 3. Claim contradiction graph

Нужно связывать claims между собой:

```text
claim A supports claim B
claim C contradicts claim A
claim D updates older claim A
```

### 4. Entity graph expansion

После extraction Forager должен уметь запускать новые query mutations по entity:

```text
entity -> aliases -> old mentions -> related domains -> adjacent markets
```

### 5. Local-language layer

Для Polymarket edge часто критичны корейские, ивритские, испанские, арабские, японские и локальные источники. Нужно фиксировать language и добавлять translation/extraction workflow.

### 6. Absence detector v1

Теперь, когда есть documents/entities/claims, можно искать отсутствие ожидаемых следов не абстрактно, а структурно:

- нет official source;
- нет latest poll;
- нет changelog;
- нет local actor mentions;
- нет resolution authority;
- нет source diversity.

## Проверка

На момент записи:

```text
pytest -q forager
10 passed
```
