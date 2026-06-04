# Poll To Seat Model — первый механический election layer

Дата: 2026-05-19

## Зачем это нужно

Signal не должен просто читать новости и говорить “кажется да/нет”. Для election markets часто alpha находится в механике:

- thresholds;
- wasted votes;
- fragmented opposition;
- alliance/bloc rules;
- seat allocation;
- tie-break rules;
- undecided allocation.

`poll_to_seat_model` — первый инструмент, который переводит polling headline в приблизительную seat картину.

## Что добавлено

Новый pure module:

`bot/lib/election_model.py`

Новый MCP tool:

`poll_to_seat_model(...)`

Регистрация:

`bot/tools/elections.py` подключен в `bot/mcp_server.py`.

Тесты:

`bot/tests/test_election_model.py`

## Как работает

Вход:

- `target`: партия/блок, по которому считаем most-seats probability;
- `contenders`: список партий/блоков с poll share;
- `party_threshold`: например 4%;
- `bloc_threshold`: например 8%;
- `total_seats`: по умолчанию 101;
- `tie_breaker`: по умолчанию `raw_votes`;
- `scenarios`: стресс-сценарии с вероятностями и poll adjustments.

Модель:

1. Парсит poll shares. Можно вводить `32.5` или `0.325`.
2. Применяет party/bloc thresholds.
3. Исключает below-threshold votes как wasted.
4. Нормализует qualifying vote.
5. Делает D'Hondt allocation.
6. Проверяет, получает ли target most seats.
7. Прогоняет scenario tree и считает weighted probability.

## Важное про adjustments

Scenario adjustments — это percentage points, если число по модулю >= 1.

Примеры:

- `{"Civil Contract": -5}` = минус 5 percentage points;
- `{"Strong Armenia": 15}` = плюс 15 percentage points;
- `{"A": 0.05}` = плюс 5 percentage points как share delta.

Это было специально зафиксировано тестом, потому что первая версия ошибочно трактовала `+1` как +100%.

## Armenia Run

Пример входных данных по Civil Contract market:

```json
{
  "target": "Civil Contract",
  "total_seats": 101,
  "party_threshold": 4,
  "bloc_threshold": 8,
  "tie_breaker": "raw_votes",
  "contenders": [
    {"name":"Civil Contract", "poll":32.5, "kind":"party"},
    {"name":"Strong Armenia", "poll":10.1, "kind":"bloc", "threshold":8},
    {"name":"Armenia Alliance", "poll":4.4, "kind":"bloc", "threshold":8},
    {"name":"Prosperous Armenia", "poll":3.4, "kind":"party", "threshold":4},
    {"name":"Bright Armenia", "poll":2.5, "kind":"party", "threshold":4},
    {"name":"Other listed forces", "poll":7.1, "kind":"party", "threshold":4}
  ]
}
```

Base result:

| Party/bloc | Poll | Threshold | Approx seats |
|---|---:|---:|---:|
| Civil Contract | 32.5% | 4% | 67 |
| Strong Armenia | 10.1% | 8% | 20 |
| Other listed forces | 7.1% | 4% | 14 |

Excluded in base:

- Armenia Alliance, 4.4%, bloc threshold 8%;
- Prosperous Armenia, 3.4%, party threshold 4%;
- Bright Armenia, 2.5%, party threshold 4%.

This is the key insight: Civil Contract does not need majority raw support. If opposition votes are fragmented or wasted below thresholds, Civil Contract can dominate qualifying seats.

## Armenia Scenario Result

Scenario tree used:

| Scenario | Probability | Result |
|---|---:|---|
| Poll baseline / fragmented opposition | 55% | Civil Contract most seats |
| Moderate anti-incumbent break | 25% | Civil Contract most seats |
| Strong challenger consolidation | 12% | Strong Armenia most seats |
| Threshold chaos / smaller parties qualify | 8% | Civil Contract most seats |

Weighted result:

- Civil Contract most seats: **88%**
- Civil Contract not most seats: **12%**

Market NO around 11c therefore does **not** have enough edge yet. This confirms the previous no-signal decision.

## What This Changes

Before this model:

> “Civil Contract has 32.5%, but maybe NO has hidden edge because politics is messy.”

After this model:

> “NO only becomes interesting if a challenger consolidates enough to exceed Civil Contract in raw support or if threshold dynamics change sharply. Fragmentation actually helps Civil Contract.”

This is the kind of reasoning Signal needs: rules + mechanics + scenario stress, not vibes.

## Limitations

This is a first-pass model. It does not yet fully model:

- Armenia stable-majority bonus / second-round mechanics;
- reserved seats;
- exact country-specific tie-breaks beyond `raw_votes`;
- polling error distributions;
- correlation between undecided allocation and turnout;
- alliances forming or collapsing after poll fieldwork.

## Next Improvements

1. Add Monte Carlo polling-error simulation.
2. Add country presets: Armenia, Israel, Netherlands, EU Parliament.
3. Add `minimum_forces` / reserved-seat logic where relevant.
4. Add source-backed poll registry, so every poll input has pollster/date/sample/method.
5. Connect model output to `record_forecast_update` automatically.
6. Create false-negative tracking: if model says “no signal” and market later moves, record why.

## Current Decision

Armenia Civil Contract NO remains:

`watchlist_research_only_model_confirms_no_signal`

This is good. Signal is now better at explaining why it refuses an attractive-looking high-payout idea.
