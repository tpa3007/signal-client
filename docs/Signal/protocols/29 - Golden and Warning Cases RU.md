# Golden and Warning Cases RU

Этот протокол фиксирует канонические примеры качества Signal. Его задача - не хвалить удачные ставки и не ругать неудачные, а превращать реальные ledger cases в операционные стандарты для G2/M/R/B/D/C/E.

Главное правило:

```text
Golden case = повторяемый edge-archetype, который можно требовать от будущих кандидатов.
Warning case = повторяемая ловушка, которую будущие кандидаты должны явно проходить через anti-signal gate.
```

## Golden Case 1 - Kim Kyung-soo YES

Market: `Will Kim Kyung-soo win the 2026 Gyeongsangnam Province Gubernatorial Election`

Side: `YES`

Entry: `29%`

Ledger status: `real_money`, `legacy_gate_violation`

Edge type: `local_polling + Korean-language source asymmetry + underfollowed regional election`

Почему это golden case:

- Был конкретный рынок и конкретный side, а не абстрактная история.
- Были локальные корейские источники, не только англоязычный пересказ.
- Было несколько polls, а не один случайный headline.
- Тезис был causal: рынок недооценил Kim из-за слабого внимания к локальной политике.
- Entry 29% был низким относительно polling picture.
- После входа рынок пошёл в сторону тезиса, что не доказывает истинность, но показывает, что вход не был пустой narrative bet.

Что будущий local-election signal должен повторить:

- multiple local polls;
- dates for each poll;
- sample/method if available;
- margin vs opponent;
- trend direction;
- party/institutional context;
- candidate eligibility and nomination mechanics;
- exact resolution wording;
- market liquidity and price history;
- English-market blind spot;
- disconfirming local sources.

Что не считается Kim-like edge:

- `local language` alone;
- candidate mentioned in local news;
- cheap price;
- one poll without context;
- English article summarizing old local data;
- high SDV packet without a polling/mechanics gap.

Required upstream changes:

- G2 may only tag this archetype as suspicion.
- M must require real local-poll path before B.
- R must ask for poll dates, method, margin, eligibility, nomination mechanics, and resolution wording.
- B must collect supporting and disconfirming local-language sources.
- D must separate `source_confidence` from `causal_confidence`.
- E must classify failures as `overtrusted_local_poll`, `wrong_resolution_read`, or `stale_source` when applicable.

## Golden Case 2 - RBA Hike NO

Market: `Will the Reserve Bank of Australia increase the cash rate after the June Meeting`

Side: `NO`

Entry side price: about `19.7%`

Edge type: `central_bank_sequence + policy-mechanics mispricing`

Почему это golden case:

- Тезис не зависел от слуха или одного источника.
- Механика была понятной: recent cut -> hike within weeks requires an exceptional reversal.
- Было понятно, какие факты должны опровергнуть thesis: inflation shock, official guidance shift, emergency conditions.
- Это не cheap lottery, а sequence/procedure edge.

Future standard:

- Identify the last policy move.
- Identify the next scheduled meeting and formal decision source.
- Check inflation/labor/relevant shock data.
- Check central bank guidance and market-implied rates.
- Explain why the market price implies an implausible sequence.

Warning:

- Kelly/EV is useless here without a real probability estimate.
- Macro bracket markets are not automatically language-arbitrage markets.

## Golden Case 3 - GPT-6 Before GTA VI NO

Market: `Will GPT-6 be released before GTA VI`

Side: `NO`

Edge type: `resolution-clause / weird market-mechanics edge`

Почему это golden case:

- Edge был в rule clause, not in generic AI product prediction.
- The 50/50 or fallback mechanics mattered more than ordinary model-release speculation.
- Это заставляет Signal искать "event can happen but resolve differently" situations.

Future standard:

- Extract exact YES and NO resolution paths.
- Identify 50/50, tie, ambiguity, or fallback clauses.
- Ask whether traders price the headline instead of the rule.
- Verify dates, timezone, and product availability definitions.

Warning:

- AI release markets are dangerous when the edge is only "I think model X will/won't launch".
- The acceptable archetype is mechanics, not vibes about model roadmaps.

## Golden Case 4 - Spencer Pratt NO

Market: `Will Spencer Pratt win the 2026 Los Angeles mayoral election`

Side: `NO`

Edge type: `celebrity overpricing + electoral reality`

Почему это golden case:

- Рынок мог переоценивать name recognition / social attention.
- Election mechanics mattered: crowded nonpartisan primary, threshold/path to win, actual polling rank.
- Тезис был проверяемым через polls and institutional mechanics.

Future standard:

- Separate fame from electoral viability.
- Check field size, runoff/primary rules, threshold, latest polls, endorsements, fundraising.
- Ask whether the candidate has a real path, not just media visibility.

## Candidate Golden Case - OpenAI $950B NO

Market: `Will OpenAI's valuation hit $950B by June 30`

Side: `NO`

Edge type: `private-provider-metric mechanics`

Status: candidate golden case only if provider mechanics are actually verified.

What must be true:

- Resolution is tied to a concrete provider metric such as NPM Price.
- Latest provider mark is known.
- Update cadence and publication lag are known.
- Threshold mechanics are verified.
- Tender/secondary/fund-mark evidence is checked.
- The market is mispricing provider mechanics, not merely debating OpenAI fundamentals.

Failure mode:

```text
OpenAI is worth/not worth X
=> therefore signal
```

Correct mode:

```text
NPM/provider metric cannot/can cross X by deadline under its publication mechanics
=> possible signal
```

## Warning Case 1 - OpenAI Not IPO YES

Market: `Will OpenAI not IPO by December 31, 2026`

Side: `YES`

Problem archetype: `model/timeline overconfidence`

What likely went wrong:

- Thesis may have over-weighted lack of public S-1.
- Timeline logic can be overwhelmed by structural change, private-market mechanics, direct-listing assumptions, or market interpretation.
- Confidence may have exceeded causal evidence.

Future block:

- Require exact IPO definition and resolution source.
- Require a live timeline model with multiple paths.
- Require disconfirming evidence: bank mandates, confidential filing possibility, direct listing, tender/secondary events.
- Do not approve if the thesis is mostly "standard timeline says unlikely".

## Warning Case 2 - Gemini / AI Release Markets

Examples:

- `Gemini flagship YES` resolved/expired badly.
- `Gemini 3.5 released NO` moved against thesis.

Problem archetype: `wording/release ambiguity`

Common traps:

- announced vs released;
- preview vs generally available;
- model family vs exact model name;
- benchmark leadership vs product availability;
- deadline timezone;
- unofficial leaks.

Future block:

- R must build a full release-definition map.
- B must find official product/source evidence, not rumors.
- D must block if product naming ambiguity is unresolved.
- E should classify failures as `wrong_resolution_read`, `deadline_misread`, or `model_overconfidence`.

## Warning Case 3 - Sorin Grindeanu PM YES

Market: `Will Sorin Grindeanu be the next Prime Minister of Romania`

Side: `YES`

Problem archetype: `cheap optionality trap`

What went wrong:

- Cheap price looked interesting.
- The thesis likely lacked a concrete appointment path.
- Old articles / entity mentions can create fake plausibility.

Future block:

- Require current coalition math and formal appointment process.
- Require a named path from current office holders to the candidate.
- Require fresh local sources.
- Cheap price alone is never an edge.

## Warning Case 4 - Israel/Iran Geopolitical Tails

Problem archetype: `geopolitical plausibility != resolution probability`

Common traps:

- event is possible;
- news volume is high;
- officials discuss scenario;
- market is cheap;
- deadline is close.

Correct standard:

- Who must do what?
- Before what exact deadline?
- Which source resolves it?
- What makes current price wrong?
- What evidence would falsify the path?
- Is this correlated with existing portfolio exposure?

Future block:

- D should block if thesis is only "tension high / event possible".
- H should cap correlated Middle East / diplomatic breakthrough exposure.
- C should require operator probability and cluster exposure check.

## How Commands Must Use These Cases

G:

- Finds broad universe only.
- Never labels a case as golden-quality.

G2:

- Outputs suspicion/anomaly.
- Must fill `g2_review_frame`.
- Must not treat local language, cheap price, or near deadline as edge.

M:

- Uses golden cases as upgrade templates.
- Uses warning cases as default rejects.
- Should ask: "Which golden archetype does this resemble, and which warning trap could it be?"

R:

- Converts the candidate into an `edge_thesis`.
- Must explicitly state whether the candidate resembles a golden case or warning case.

B:

- Collects evidence against the golden-case requirements.
- Must search for disconfirming evidence, not just support.

D:

- Formalizes only if the candidate passes the golden-case standard or has a clearly different but equally explicit thesis.
- Blocks warning-case patterns unless operator override is explicit and sourced.

C:

- Records only after operator handoff.
- Does not make judgment.

E:

- On every closed/resolved case, updates this protocol when the case becomes canonical.
- Every learning review should answer:

```text
Did this become a golden case, a warning case, or neither?
Which upstream command should change?
```

## Short Checklist

Before a new candidate can be called "strong", answer:

```text
1. Which golden case does it resemble?
2. Which warning case could it secretly be?
3. What decisive fact separates the two?
4. Has that fact been checked with relevant sources?
5. Has disconfirming evidence been searched?
6. Does the operator have an explicit probability range?
7. Does portfolio exposure allow this bet?
```

If the answer to 1 is "none" and the answer to 2 is "one of the warnings", the candidate should be rejected or left as watch.
