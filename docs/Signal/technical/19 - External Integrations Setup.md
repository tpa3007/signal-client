# External Integrations — Setup Guide

Внешние источники, подключённые к Signal в рамках борьбы с контекстными дырами (OSINT для Rodynske, polling для Maine Gov, source quality для всех остальных). Документ — справочник «что подключено» + «что зарегистрировать тебе самому».

См. также: [17b - Aladdin Owner Manual RU.md](../manuals/17b - Aladdin Owner Manual RU.md) §10 — полная шпаргалка инструментов.

## Подключено keyless (готово к использованию)

| Источник | MCP-инструменты | Use case |
|---|---|---|
| **GDELT 2.0** | `gdelt_search`, `gdelt_volume_timeline` | Глобальный news/event monitoring; narrative heat; actor mention velocity |
| **OSM Nominatim** | `geocode_place` | Place name → lat/lon/bbox. Готовит OSINT-слой для Rodynske/Huliaipilske |
| **Wikipedia REST** | `wiki_summary` | Page extract + Wikidata Q-ID. Первая проверка идентичности нового актора |
| **Wikidata** | `wiki_entity_search`, `wiki_entity_details` | Entity resolution: партии, должности, родственные сущности |
| **SEC EDGAR** | `sec_filings`, `sec_company_facts` | 8-K/10-Q/10-K + XBRL фундаменталка. Snowflake guidance, OpenAI IPO calibration |
| **arXiv** | `arxiv_search` | AI release signals — paper drops часто предшествуют анонсам моделей |
| **GitHub** | `github_repo`, `github_releases`, `github_commits` | Repo activity, release watch. Анонимный режим 60 req/h (с токеном — 5000) |
| **Open-Meteo** | `weather_forecast` | Weather-sensitive markets, election turnout context, conflict mobility |

**Уже видно живьём:**
- `geocode_place("Rodynske, Ukraine")` → 48.354°N, 37.203°E (Покровский район, Донецкая обл.) с bbox.
- `sec_filings("SNOW", types=["10-Q","8-K"])` → последние 5 filings включая 2026-03-31 8-K.
- `wiki_entity_search("Civil Contract Armenia")` → корректный Q-ID партии Пашиняна.

Все 7 источников также зарегистрированы в `sources` table (`source_track_record` их видит), так что `record_evidence` с URL-ами из них автоматически подтянет reliability.

## Подключено с ключами (после первой раунда регистрации)

| Источник | MCP-инструменты | Статус |
|---|---|---|
| **OpenFEC** | `fec_candidate_search`, `fec_candidate_totals`, `fec_late_spending` | ✅ работает. Покрывает только **federal** races (House/Senate/President). State governor НЕ покрывается. |
| **NASA FIRMS** | `firms_thermal_anomalies` | ✅ работает. NRT cap = **5 дней** (не 10). Live: 5 anomalies в 30км / 12 в 50км вокруг Rodynske. |
| **YouTube Data v3** | `youtube_search`, `youtube_channel_info` | ✅ работает. **Внимание:** search costs 100 quota units, дневной лимит 10 000 = ~100 searches/день. |
| **ProPublica Nonprofits** | `propublica_search_orgs`, `propublica_organization` | ✅ работает (GET-only, без auth) |
| **ACLED** | `acled_events_near`, `acled_events_by_country`, `acled_actor_search` | ⚠️ адаптер написан, OAuth токен получается, **но read endpoint возвращает 403** — аккаунт на developer-портале требует отдельной активации API access. Войди в https://acleddata.com/access-data/ и запроси доступ. Когда дадут — заработает автоматически. |

**Live на cohort markets:**

- **YouTube для Nirav Shah (Maine Gov)** — нашёл Maine Public full interview 12 мая, WGME closing statement, NEWS CENTER Maine debate 4 мая. Это **закрывает** контекстную дыру.
- **NASA FIRMS для Rodynske** — 5 fire detections за 5 дней в 30км, 12 в 50км. Active strike/burn activity подтверждена.
- **OpenFEC для Kansas Senate** — Adam Hamilton (S6KS00312, DEM) найден; cycle totals ещё не зафайлены — нормально для primary cycle.

## Опциональные env-переменные (для уже подключённого)

## Опциональные env-переменные (для уже подключённого)

Можно оставить пустыми — всё работает. Поставь — будет лучше:

| ENV | Что улучшит |
|---|---|
| `SIGNAL_CONTACT_EMAIL` | Идентификация в User-Agent. SEC и Nominatim больше любят `noreply@yourdomain` чем `noreply@signal.local`. |
| `GITHUB_TOKEN` | Лимит 60 → 5000 req/h. Создай fine-grained PAT с правом `public_repo` только: https://github.com/settings/tokens?type=beta |

Положи в `bot/.env`:
```
SIGNAL_CONTACT_EMAIL=ты@почта.com
GITHUB_TOKEN=ghp_...
```

---

## Что нужно зарегистрировать тебе (Tier 1, наибольший ROI)

Все эти — **бесплатные**, регистрация занимает минуты. Когда зарегистрируешь — просто положи ключи в `.env` и скажи мне, я добавлю соответствующие интеграции.

### 1. ACLED (Armed Conflict Location & Event Data) — самый ценный для Украина/Россия

Что даёт: structured conflict events (даты, координаты, типы инцидентов, погибшие). Прямо закрывает дыру по Rodynske.

Регистрация: https://developer.acleddata.com/ → подтверди email → API key + Access token.

ENV:
```
ACLED_API_KEY=...
ACLED_EMAIL=твой@email.com
```

Лимит: 5000 запросов/месяц на free tier.

### 2. NASA FIRMS — thermal anomalies / fires

Что даёт: near-real-time fire detection из MODIS/VIIRS satellites. Не доказывает захват, но показывает интенсивность ударов в bbox.

Регистрация: https://firms.modaps.eosdis.nasa.gov/api/map_key/ → email подтверждение → MAP_KEY.

ENV:
```
NASA_FIRMS_MAP_KEY=...
```

Лимит: 5000 req/10min.

### 3. OpenFEC — US federal campaign finance

Что даёт: fundraising, committee filings, candidate data. Прямо закрывает дыру по Maine Gov / Kansas Senate / любым US Senate/Governor primaries.

Регистрация: https://api.open.fec.gov/developers/ → free key мгновенно.

ENV:
```
OPENFEC_API_KEY=...
```

Лимит: 1000 req/час, 7500 req/день.

### 4. ProPublica — Congress + Campaign Finance

Что даёт: дополнительный слой поверх FEC + Congress voting records.

Регистрация: https://www.propublica.org/datastore/api → email request → API key (обычно ответ в течение дня).

ENV:
```
PROPUBLICA_API_KEY=...
```

### 5. OpenSanctions — entity intelligence

Что даёт: sanctioned entities, PEPs, beneficial owners. Полезно для actor maps в geopolitics.

Регистрация: https://www.opensanctions.org/api/ → free tier 100 req/день, нужен email.

ENV:
```
OPENSANCTIONS_API_KEY=...
```

## Tier 2 — менее срочно, более специализированно

### 6. Sentinel Hub (satellite imagery)

Регистрация: https://www.sentinel-hub.com/ → free trial (30 дней), потом ограниченный free tier через Copernicus Data Space.

ENV:
```
SENTINEL_HUB_CLIENT_ID=...
SENTINEL_HUB_CLIENT_SECRET=...
```

Сложно использовать без скриптов обработки изображений. Можно отложить.

### 7. Reddit API

Регистрация: https://www.reddit.com/prefs/apps → "create app" (script type) → ID + secret.

ENV:
```
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USER_AGENT=signal-research-bot/1.0
```

Лимит: 100 req/min.

### 8. YouTube Data API

Регистрация: https://console.cloud.google.com/ → create project → enable YouTube Data API v3 → credentials → API key.

ENV:
```
YOUTUBE_API_KEY=...
```

Лимит: 10000 units/день (1 search = 100 units, так что ~100 searches/day).

## Tier 3 — keyless, но ещё не подключено

Эти будут добавлены по запросу — не требуют твоих действий:

- **ReliefWeb API** — humanitarian crisis context (после Nov 2025 нужен `appname` параметр, не key)
- **OFAC SDN list** — прямое скачивание .xml файла с treasury.gov
- **EU/UK sanctions lists** — RSS/CSV downloads
- **OpenSky Network** — flight/airspace context (anonymous reads)
- **HDX/HAPI** — humanitarian data exchange

Если нужен какой-то конкретно из этого списка — скажи, добавлю.

## Tier 4 — за рамками

Эти платные или требуют сложной интеграции:

- Bloomberg, Reuters Connect — платные
- Decision Desk HQ — публичных API нет
- Various polling aggregators — обычно scraping, не API

## Как проверить статус подключений

```python
integrations_status()
```

Возвращает:
```json
{
  "keyless_ready": ["GDELT", "Nominatim", "Wikipedia/Wikidata", "SEC EDGAR", "arXiv", "GitHub", "Open-Meteo"],
  "env_keys_detected": { "SIGNAL_CONTACT_EMAIL": false, "GITHUB_TOKEN": false, ... },
  "not_yet_implemented_but_keyless": [...],
  "not_yet_implemented_needs_key": [...]
}
```

## Что я буду делать после регистрации ключей

Когда передашь любой из ключей выше — я подключу соответствующую интеграцию по приоритету:

1. **ACLED** (если есть) → tools/integrations.py + `acled_events_near(lat, lon, radius_km, days_back)` + `acled_actor_search(actor, days_back)`. Подкрепляет Rodynske, Huliaipilske, Knesset markets.
2. **OpenFEC** (если есть) → `fec_candidate(name)`, `fec_fundraising(candidate_id, cycle)`, `fec_late_spending(candidate_id)`. Закрывает Maine Gov, Kansas Senate, Michigan Gov.
3. **NASA FIRMS** (если есть) → `firms_thermal_anomalies(bbox, days_back)`. Доп. контекст для конфликтных markets.
4. Остальные — по мере прихода ключей.

После каждого ключа — добавлю тесты, обновлю owner manual, прогоню `signal_regression_benchmark`, и сделаю отдельный коммит. Никаких других изменений system state.

## Связанные файлы

- [bot/lib/integrations/](../../bot/lib/integrations/) — 7 keyless клиентов
- [bot/tools/integrations.py](../../bot/tools/integrations.py) — 14 MCP-инструментов
- [bot/tests/test_integrations.py](../../bot/tests/test_integrations.py) — mock-based тесты
- `bot/.env` (gitignored) — твои ключи
