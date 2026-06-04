# Forager Phase 6 Architecture RU

Дата: 2026-05-20

## Что добавлено

Phase 6 добавляет полноценный Rich Crawling Layer.

Forager теперь умеет не просто делать HTTP GET, а маршрутизировать запросы к специализированным адаптерам в зависимости от URL, соблюдать rate limits и hard caps через budget ledger.

## Архитектура слоя

```text
CrawlRouter
    ├── budget check (CrawlBudgetLedger)
    ├── robots.txt check (RobotsPolicyChecker, optional)
    ├── route by URL pattern
    │       github.com         → GitHubCrawlerAdapter
    │       *.pdf / /pdf/      → PdfCrawlerAdapter
    │       web.archive.org    → WaybackCrawlerAdapter
    │       /rss /feed *.rss   → RssCrawlerAdapter
    │       everything else    → SimpleHttpCrawlerAdapter
    └── record request in budget
```

## CrawlBudgetLedger

Отслеживает потребление ресурсов:

- `max_requests_per_domain` — не более N запросов к одному домену за сессию
- `min_delay_seconds` — минимальный интервал между запросами к тому же домену
- `max_bytes_per_session` — hard cap на суммарный объём загруженных данных
- `max_requests_per_session` — hard cap на число запросов за сессию

Если лимит превышен — `CrawlBudgetExhausted` блокирует вызов до HTTP. Ошибка всплывает как structured blocker в `crawl_sources`.

## RobotsPolicyChecker

Использует `urllib.robotparser` (stdlib).

Кешируется per-domain. Fail-open: если robots.txt недоступен — URL разрешается.

По умолчанию `check_robots=False` в `CrawlRouter` чтобы не делать лишних запросов к robots.txt в тестах.

## Специализированные адаптеры

### RssCrawlerAdapter
- Парсит RSS 2.0 и Atom через `xml.etree.ElementTree` (stdlib)
- Возвращает `CrawledDocument` с конкатенированными item/entry текстами
- Метод `parse_feed(xml, max_chars)` тестируется напрямую без сети

### WaybackCrawlerAdapter
- Запрашивает Wayback CDX API для нахождения последнего 200-статусного snapshot
- Если URL уже `web.archive.org` — загружает напрямую
- Не требует ключа API

### GitHubCrawlerAdapter
- Маршрутизирует по типу URL: README / issues list / single issue / releases / commits
- Использует GitHub REST API (публичный, без ключа для публичных репо)
- `GITHUB_TOKEN` поднимает rate limit с 60 до 5000 req/h

### PdfCrawlerAdapter
- Приоритет: `pypdf` (optional dep)
- Fallback: regex extraction из BT/ET блоков (работает для простых PDF без FlateDecode)
- Production: рекомендуется Firecrawl для надёжного PDF

### FirecrawlCrawlerAdapter
- Требует `FIRECRAWL_API_KEY` и `pip install requests`
- Поднимает `ConfigError` при отсутствии ключа
- Полноценная реализация через Firecrawl v1 scrape API

### PlaywrightCrawlerAdapter
- Требует `pip install playwright && playwright install chromium`
- Поднимает `ConfigError` при отсутствии пакета
- Для JS-heavy страниц, SPA, динамического контента

## build_default_router()

Вспомогательная функция для быстрого старта:

```python
from forager.crawl_router import build_default_router

router = build_default_router(policy=CrawlPolicy(min_delay_seconds=1.0))
service = ForagerService(crawler_adapter=router)
```

Бэкэнд — `SimpleHttpCrawlerAdapter` для всех типов. Можно передать специализированные адаптеры при инициализации `CrawlRouter` напрямую.

## Интеграция с сервисом

`ForagerService` принимает любой `CrawlerAdapter`. `CrawlRouter` прозрачно заменяет `SimpleHttpCrawlerAdapter`:

```python
service = ForagerService(
    crawler_adapter=CrawlRouter(
        adapters={
            "http":    SimpleHttpCrawlerAdapter(),
            "github":  GitHubCrawlerAdapter(api_token="..."),
            "rss":     RssCrawlerAdapter(),
            "wayback": WaybackCrawlerAdapter(),
            "pdf":     PdfCrawlerAdapter(),
        },
        policy=CrawlPolicy(max_requests_per_domain=30, min_delay_seconds=1.0),
        check_robots=True,
    )
)
```

## Ограничения Phase 6

- `PdfCrawlerAdapter` без `pypdf` работает только для простых single-byte PDF
- `WaybackCrawlerAdapter` и `GitHubCrawlerAdapter` требуют реальной сети — тесты используют StaticCrawlerAdapter через router
- `FirecrawlCrawlerAdapter` и `PlaywrightCrawlerAdapter` — стабы, не имеют unit-тестов (требуют внешних ресурсов)
- Budget ledger хранится in-memory — не персистируется между запусками ForagerService

## Новые файлы

```text
forager/crawl_budget.py      — CrawlPolicy, CrawlBudgetLedger, RobotsPolicyChecker
forager/crawl_rss.py         — RssCrawlerAdapter
forager/crawl_wayback.py     — WaybackCrawlerAdapter
forager/crawl_github.py      — GitHubCrawlerAdapter
forager/crawl_pdf.py         — PdfCrawlerAdapter
forager/crawl_firecrawl.py   — FirecrawlCrawlerAdapter (stub)
forager/crawl_playwright.py  — PlaywrightCrawlerAdapter (stub)
forager/crawl_router.py      — CrawlRouter, build_default_router
```

## Проверка

На момент записи:

```text
pytest -q forager
53 passed
```

Phase 6 добавил 26 новых тестов:
- budget enforcement (6 тестов)
- CrawlRouter routing + budget (5 тестов)
- RSS 2.0 / Atom parsing (3 теста)
- PDF fallback extraction (2 теста)
- GitHub URL routing / path parsing (6 тестов)
- ForagerService + CrawlRouter integration (2 теста)
