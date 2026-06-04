# Forager Phase 16 — Cognitive Ecology Layer

Дата: 2026-05-20
Статус: implemented

## Зачем это нужно

Документ `FORAGER NEXT EVOLUTION.md` описал следующий скачок Forager: перейти от линейного research engine к self-evolving cognitive ecosystem.

Phase 16 реализует первый полноценный слой этой идеи: Forager теперь не только собирает информацию, но и оценивает собственную исследовательскую среду.

Главное: этот слой ничего не пишет в Signal и не создает evidence. Он управляет вниманием, бюджетом, подозрением, dream-гипотезами и приоритетами дальнейшего копания.

## Новая команда

```python
ForagerService.build_cognitive_ecology_snapshot(thread_id, CognitiveEcologyRequest(...))
```

API:

```http
POST /threads/{thread_id}/cognitive-ecology
```

## Центральный объект

`CognitiveEcologySnapshot`

Он содержит:

- `thread_state`
- `heat`
- `gravity_fields`
- `dream_hypotheses`
- `anti_consensus_reviews`
- `narrative_trajectory`
- `ecosystem_simulations`
- `entity_dna_profiles`
- `suspicion_signal`
- `information_weather`
- `identity_topologies`
- `cross_market_relations`
- `query_mutation_learning`
- `meta_cognition`
- `next_actions`

Boundary:

```text
CognitiveEcologySnapshot: research steering only; does not create evidence, signals, positions, or fills.
```

## Что реализовано из FORAGER NEXT EVOLUTION

### 1. Information Gravity Engine

`InformationGravityField` считает, какие entities притягивают внимание.

Учитывается:

- anomaly density
- contradiction density
- cross-language mentions
- temporal instability
- unresolved thread pull
- recursive pull strength

Если gravity высокая, Forager рекомендует:

- `allocate_more_budget`
- `spawn_more_agents`
- `increase_watch_frequency`
- `deep_archive_search`

### 2. Persistent Unresolved Threads

`PersistentThreadState` вводит состояния:

- `dormant`
- `simmering`
- `active`
- `obsession`

Если heat/gravity/weirdness высокие, thread становится obsession-thread и получает короткий revisit interval.

### 3. Cognitive Heat System

`CognitiveHeat` считает динамический heat:

- contradiction density
- novelty
- uncertainty
- source proliferation
- drift score

Heat влияет на:

- budget multiplier
- recursion depth
- swarm size
- next actions

### 4. Dream Layer

`DreamHypothesis` создает speculative hypotheses через recombination.

Важно:

```text
DreamHypothesis: speculative only; not evidence and not a Signal input.
```

Dream layer генерирует новые поисковые запросы, но не создает факты.

### 5. Anti-Consensus Architecture

`AntiConsensusReview` создает 5 постоянных когнитивных ролей:

- Nihilist
- Believer
- Operator
- Statistician
- Historian

Их задача — поддерживать напряжение, а не приходить к красивому консенсусу.

### 6. Narrative Physics Layer

`NarrativeTrajectory` отслеживает:

- confidence direction
- semantic shift
- emotional shift
- fragmentation
- fear/certainty spikes

### 7. Information Ecosystem Simulation

`EcosystemSimulation` отвечает на вопрос: если гипотеза верна, какие маркеры должны появиться дальше?

Это counterfactual watch plan, не evidence.

### 8. Entity DNA

`EntityDNA` дает entity “характер”:

- secrecy level
- hype behavior
- historical accuracy proxy
- contradiction tolerance
- language distribution
- release/delay pattern
- narrative style

### 9. Recursive Suspicion Engine

`SuspicionSignal` повышает подозрение, если одновременно:

- растет contradiction density
- evidence quality тонкая
- narrative shift есть
- language layer расходится
- graph становится страннее

### 10. Information Weather

`InformationWeatherReport` классифицирует среду:

- `calm`
- `front`
- `turbulence`
- `storm`

Weather влияет на рекомендации: больше skepticism, ниже confidence, чаще monitoring.

### 11. Long-Memory Identity Tracking

`IdentityTopology` собирает:

- aliases
- domain fingerprints
- repo fingerprints
- narrative fingerprints
- persistence score

### 12. Cross-Market Intelligence

`CrossMarketRelation` ищет связи между markets через shared entities.

### 13. Self-Evolving Query Mutation

`QueryMutationLearning` считает по lens:

- attempts
- promoted sources
- alpha proxy score
- recommendation: `amplify`, `prune`, `keep_testing`

### 14. Research Ecology Dashboard Foundation

Phase 16 пока не рисует dashboard, но создает данные для будущего radar/war-room/cognitive observatory:

- heat zones
- obsession threads
- gravity clusters
- contradiction storms
- narrative collapse candidates
- unresolved ecosystems

### 15. Meta-Cognition Layer

`MetaCognitionReport` анализирует Forager как систему:

- agent error risks
- archetype alpha rates
- hallucination patterns
- swarm degradation
- skepticism gap
- recursion utility
- lessons

## Persistence

Добавлено хранение:

- InMemory: `cognitive_ecology_snapshots`
- SQLite: `forager_cognitive_ecology_snapshots`

## API

```http
POST /threads/{thread_id}/cognitive-ecology
```

Request:

```json
{
  "include_dream_layer": true,
  "include_cross_market": true,
  "max_dream_threads": 4,
  "max_gravity_entities": 8
}
```

## Инварианты

1. Cognitive Ecology не создает evidence.
2. Dream hypotheses не идут в Signal.
3. Cross-market relation — это research lead, не causal proof.
4. Heat и suspicion управляют вниманием, а не являются probability.
5. Anti-consensus roles специально biased; их не надо “исправлять”.
6. Meta-cognition оценивает качество мышления Forager, а не рынок напрямую.

## Следующий шаг

Phase 17 должен превратить Phase 16 из snapshot-layer в scheduler:

- автоматически поднимать obsession threads
- пересчитывать heat по расписанию
- запускать dream cycle по всем unresolved threads
- обновлять query mutation policy
- отдавать dashboard-ready ecology feed
