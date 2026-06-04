# Forager Phase 5 Architecture RU

Дата: 2026-05-20

## Что добавлено

Phase 5 замыкает цикл перевода, который Phase 4 открыл через Translation Queue.

Теперь Forager может:

1. Взять документ из очереди перевода (Korean, Hebrew, Spanish и т.д.).
2. Передать его через TranslationAdapter.
3. Создать TranslatedDocument с сохранённым качеством и именем адаптера.
4. Запустить extraction на переведённом тексте → получить Claims и Entities в English.
5. Записать ClaimTranslationLink для каждого извлечённого утверждения — трассировка обратно к оригинальному документу.
6. Обновить статус TranslationQueueItem → done / blocked.
7. Если перевод провалился или качество низкое — создать Anomaly и заблокировать элемент.

## Translation Adapter

Ключевой принцип: Forager не знает, как переводить. Он знает только интерфейс.

```text
TranslationAdapter
    -> StaticTranslationAdapter  (тесты)
    -> FailingTranslationAdapter (тест error path)
    -> OpenAITranslationAdapter  (следующий шаг)
    -> DeepLTranslationAdapter   (альтернатива)
```

`TranslationOutput`:
- `translated_text`
- `quality_score` (0.0–1.0)
- `adapter_name`
- `source_lang`, `target_lang`

Если `quality_score < min_quality_threshold` — документ не обрабатывается, anomaly `translation_low_quality` создаётся.

## TranslatedDocument

`TranslatedDocument` — отдельная модель (не вариант Document).

Хранит:
- `original_document_id` — откуда пришёл исходный текст
- `translation_quality` — для оценки достоверности утверждений
- `translated_by` — какой адаптер выполнил перевод
- `translation_status` — `translated / failed / low_quality`

Prefix: `tdoc_`

## ClaimTranslationLink

Связывает каждое утверждение, извлечённое из переведённого документа, обратно к оригинальному документу.

```text
Claim (English, document_id=tdoc_...)
    -> ClaimTranslationLink
        -> original_document_id (Korean doc)
        -> translated_document_id
        -> translation_quality
        -> source_language
```

Это критически важно для Signal: теперь Signal может видеть, пришло ли утверждение из прямого английского источника или через перевод с качеством 0.82.

Prefix: `ctlink_`

## Extraction pipeline на переведённом тексте

Forager использует proxy Document с `id = translated_doc.id` чтобы прогнать уже существующий `extract_document()`.

Это значит:
- Claims, Entities, EntityMentions, Anomalies — всё создаётся по стандартному пути.
- Claims имеют `document_id = translated_doc.id` — трассировка к переводу.
- Extraction hints (will, contradicts, denied...) работают, потому что текст теперь на English.

## Текущий полный workflow

```text
research/start
search-burst
crawl-sources
expand-graph
local-language-profile
translation-queue        (Phase 4)
execute-translations     (Phase 5)
packet
signal-bridge
```

## Новый endpoint

```text
POST /threads/{thread_id}/execute-translations
```

Request:
- `max_items` — сколько элементов очереди обработать за один вызов (default: 10)
- `min_quality_threshold` — порог качества перевода (default: 0.40)

Response (`TranslationExecutionResult`):
- `translated` — успешно переведено
- `failed` — ошибка адаптера
- `low_quality` — ниже порога
- `claims_extracted` — утверждений извлечено из переводов
- `entities_extracted`
- `errors`
- `translated_document_ids`

## Statuses и anomaly types

TranslationQueueItem status transitions:
```text
pending -> in_progress -> done
pending -> in_progress -> blocked  (если ошибка или low quality)
```

Новые anomaly types:
- `translation_failed` — адаптер выбросил исключение
- `translation_low_quality` — quality < threshold

## SQLite persistence

Две новые таблицы:

```sql
forager_translated_documents
    (id, thread_id, original_document_id, translation_status, json)

forager_claim_translation_links
    (id, thread_id, translated_claim_id, original_document_id, json)
```

## Ограничения Phase 5

- `StaticTranslationAdapter` только для тестов — не использует реальный LLM.
- `OpenAITranslationAdapter` не реализован (Phase 6 или отдельный PR).
- Нет budget tracking по стоимости перевода (важно для production).
- Нет retry logic при временных ошибках адаптера.
- Claim matching один-к-одному не реализован — каждый translated claim создаёт свой link к original_document, не к конкретному original claim.

## Проверка

На момент записи:

```text
pytest -q forager
27 passed
```

Phase 5 добавил 10 новых тестов:
- create translated document
- extract claims and entities from translated text
- create claim translation links
- mark queue item done
- idempotency (second call processes no items)
- blocker on adapter failure
- skip low quality translation
- SQLite persistence: translated documents
- SQLite persistence: claim translation links
- SQLite persistence: updated queue status
