# Forager Phase 17 — Attention Ecology, Obsession Dynamics and Pre-Emergence Intelligence

Дата: 2026-05-20
Статус: implemented

## Главная идея

Phase 17 превращает Forager из scheduler-based research system в attention orchestration engine.

Принцип:

```text
Research threads should compete for survival.
```

Phase 17 не создает evidence, signal, position или fill. Он перераспределяет исследовательское внимание между threads и говорит, где усиливать копание, где ждать, а где охлаждать runaway-подозрение.

## Новая команда

```python
ForagerService.build_attention_orchestration_plan(AttentionOrchestrationRequest(...))
```

API:

```http
POST /attention-orchestration
```

## Центральный объект

`AttentionOrchestrationPlan`

Содержит:

- `attention_state`
- `thread_profiles`
- `obsession_propagations`
- `ecosystem_pressures`
- `pre_emergence_fields`
- `narrative_organisms`
- `synthetic_adversaries`
- `narrative_infections`
- `immune_responses`
- `deep_time_patterns`
- `reality_mismatches`
- `ecology_feed`
- `meta_evolution`
- `next_actions`

Boundary:

```text
AttentionOrchestrationPlan: reallocates research attention only; Signal still decides.
```

## 1. Attention Economy Layer

`AttentionEconomyState` хранит:

- total attention budget
- active threads
- pressure level
- attention distribution

`ThreadAttentionProfile` считает по thread:

- attention score
- energy
- decay rate
- curiosity pull
- narrative instability
- evidence hunger
- gravity influence
- ecosystem pressure
- survival probability

Low-value threads decays. Hot/unstable threads получают больше внимания.

## 2. Obsession Escalation Layer

Obsession теперь не просто label.

Если thread имеет высокий attention/heat/gravity/weirdness, он влияет на:

- recursion
- monitoring
- anti-consensus
- archive search
- dream cycle
- cross-market analysis

`ObsessionPropagation` показывает, какие threads заражаются от obsession-thread через shared entities, cross-market relation или heat.

## 3. Ecosystem Pressure Layer

`EcosystemPressure` считает:

- contradiction overlap
- entity overlap
- instability velocity
- unresolved density
- pressure score

Это позволяет увидеть ситуацию, где отдельный thread слабый, но вся экосистема вокруг него становится напряженной.

## 4. Pre-Emergence Detection Layer

`PreEmergenceField` отвечает на фразу:

```text
Something is forming here.
```

Учитывает:

- signal fragments
- pre-narrative tension
- coherence score
- latent market probability

Это слой до headline, до formalized event, иногда даже до рынка.

## 5. Narrative Organism Layer

`NarrativeOrganism` дает narrative жизненный цикл:

- birth
- growth
- mutation
- fragmentation
- adaptation
- collapse
- absorption

Forager теперь может сказать:

```text
narrative_is_mutating_to_survive_contradiction
```

или:

```text
narrative_confidence_is_collapsing
```

## 6. Synthetic Adversary Layer

`SyntheticAdversary` моделирует временных adversaries:

- market manipulator
- coordinated PR defender
- timeline obfuscator

Это simulated opposition intelligence, не evidence.

## 7. Narrative Infection Model

`NarrativeInfection` считает:

- infection rate
- cross-community jump rate
- semantic mutation rate
- resistance score
- containment score

## 8. Cognitive Immune System

`CognitiveImmuneResponse` защищает Forager от:

- recursive paranoia
- pattern psychosis
- hallucinated coordination
- runaway obsession
- synthetic alpha illusions

Cooling actions:

- cap confidence
- force disconfirming search
- pause Signal handoff
- limit obsession spread
- reduce dream weight

## 9. Deep Time Memory

`DeepTimePattern` фиксирует recurring structures:

- hype delay cycles
- roadmap softening
- fear spike reversal
- manipulation-like recurrence

Пока это heuristic layer. В будущих фазах он должен подключиться к long-memory outcome database.

## 10. Reality Surface Mapping

`RealitySurfaceMismatch` ищет misalignment между слоями:

- market layer
- narrative layer
- infrastructure layer
- emotional layer

Высокий distortion score = возможная зона hidden alpha.

## 11. Scheduler Evolution

Phase 17 не является cron-layer.

Он делает:

- dynamic budget redistribution
- obsession escalation
- low-value decay
- immune response triggering
- ecosystem recalculation
- swarm reprioritization

## 12. Research Ecology Feed

`ResearchEcologyFeed` — dashboard-ready слой до полноценного UI:

- heat zones
- obsession threads
- gravity clusters
- contradiction storms
- emerging narratives
- ecosystem pressure
- narrative infection
- cognitive instability alerts

## 13. Meta-Cognition Evolution

`MetaCognitiveEvolution` агрегирует:

- alpha archetypes
- hallucination clusters
- swarm failure modes
- recursion quality
- skepticism gap
- evolution recommendations

## Persistence

Добавлено:

- InMemory: `attention_orchestration_plans`
- SQLite: `forager_attention_orchestration_plans`

## Request

```json
{
  "total_attention_budget": 1.0,
  "max_active_threads": 12,
  "obsession_threshold": 0.72,
  "immune_threshold": 0.65,
  "pre_emergence_threshold": 0.45
}
```

## Инварианты

1. Attention orchestration не является Signal decision.
2. Obsession не повышает probability само по себе.
3. Pre-emergence field не является доказательством.
4. Synthetic adversary outputs не являются claims.
5. Immune response может остановить runaway research даже при высоком heat.
6. Signal принимает решение; Forager чувствует tension before consensus.

## Следующий шаг

Phase 18 должен сделать этот слой live-loop:

- сохранять историю attention redistribution
- сравнивать attention decisions с outcome learning
- обучать thresholds
- строить dashboard-ready API feed
- создавать долгоживущие ecology episodes
