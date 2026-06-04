# Forager Core Priorities — Working Discovery Engine First

Дата: 2026-05-20
Статус: implemented

## Главная коррекция курса

Forager накопил много сильных идей: cognitive ecology, dream layer, narrative physics, infection models, attention economy, deep-time memory.

Эти идеи остаются полезными как north star, но они не должны быть центром текущего продукта.

Главный принцип:

```text
A beautiful research philosophy is worthless without a working discovery engine.
```

## Текущий рабочий центр

Сейчас ядро Forager должно быть только таким:

```text
a recursive weak-signal discovery engine
with adaptive research attention
```

Не oracle.
Не autonomous trader.
Не simulated cognition universe.

Boundary:

```text
Forager discovers.
Signal decides.
Learning calibrates both.
```

## Core System 1 — Strong Recursive Research Loop

Новая команда:

```python
ForagerService.run_core_research_loop(CoreResearchLoopRequest(...))
```

API:

```http
POST /research/core-loop
```

Workflow:

```text
market/question
↓
query mutation
↓
search burst
↓
crawl
↓
document extraction
↓
entity extraction
↓
claim extraction
↓
graph expansion
↓
recursive search
↓
contradiction detection
↓
evidence drafts
↓
packet generation
↓
Signal bridge
```

## Request

```json
{
  "seed_query": "market or research question",
  "market_id": "optional_market_id",
  "depth": "deep",
  "recursive_rounds": 2,
  "max_queries_per_round": 5,
  "results_per_query": 4,
  "max_sources_per_round": 6,
  "promote_threshold": 0.35,
  "include_local_language": true,
  "execute_translations": false,
  "run_semantic_graph": true,
  "build_evidence_drafts": true,
  "require_disconfirming_evidence": false
}
```

## Result

`CoreResearchLoopResult` содержит:

- `thread_id`
- `market_id`
- `packet_id`
- `signal_bridge`
- `steps`
- `counts`
- `blockers`
- `next_actions`

Boundary:

```text
CoreResearchLoopResult: Forager discovers; Signal decides.
```

## Core System 2 — Minimal Attention System

Новая команда:

```python
ForagerService.build_minimal_attention_state(MinimalAttentionRequest(...))
```

API:

```http
POST /attention/minimal
```

Это единственный cognitive layer, который считается core на текущем этапе.

Он считает:

- `attention_score`
- `heat`
- `decay_rate`
- `contradiction_density`
- `unresolved_pull`
- `obsession_probability`
- `actions`

Actions:

```text
allocate_more_budget
increase_recursion_depth
increase_monitoring
revisit_thread
spawn_more_queries
decay_thread
archive_thread
maintain
```

## Что считается obsession сейчас

Простое правило:

```text
high heat
+
high contradiction
+
unresolved pull
=
obsession candidate
```

Никакой obsession infection.
Никакой narrative virology.
Никаких synthetic adversaries в core path.

## Что делать с Phase 16-17

Phase 16 и Phase 17 остаются в проекте как experimental/north-star layers.

Их нельзя использовать как доказательство качества Forager, пока core loop не начинает стабильно находить полезные weak signals на реальных рынках.

Их статус:

```text
experimental research steering, not core alpha engine
```

## Proof Of Life

Не считается proof of life:

- красивый ecology snapshot;
- dream hypothesis;
- narrative weather;
- infection model;
- cognitive universe.

Считается proof of life:

```text
Forager found a weak signal that Signal would have missed.
```

## Near-Term Roadmap

### Stage 1

Довести до боевого состояния:

- recursive research loop;
- graph exploration;
- contradiction detection;
- local-language layer;
- packet generation.

### Stage 2

Использовать только minimal attention:

- thread heat;
- thread decay;
- obsession threshold;
- revisit prioritization.

### Stage 3

Dashboard:

- graph visualization;
- packet inspection;
- thread visualization;
- core loop trace;
- minimal attention queue.

### Stage 4

Deep Signal integration:

- Signal consumes packets;
- Signal reruns models;
- Signal changes confidence;
- Signal reprioritizes markets.

### Stage 5

Real investigations:

- observe alpha;
- observe failed recursion;
- observe hallucinations;
- calibrate weak signals.

## Operating Rule For Agents

Until Forager consistently produces valuable research findings on real markets:

```text
Do not add new conceptual layers.
Improve the recursive loop.
Improve source coverage.
Improve extraction.
Improve graph recursion.
Improve contradiction detection.
Improve local-language discovery.
Improve packet quality.
```
