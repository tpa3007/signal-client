# Vertical Tags and Briefing Layer - 2026-05-19

This note records the second hardening pass after the Aladdin stability work.

## Delivered

1. Split the old broad `geopolitics` classifier into:
   - `us_politics`
   - `international_geopolitics`

   `fetch_active_markets(vertical="geopolitics")` remains a backwards-compatible alias that includes both.

2. Added thematic tags in `market_tags`:
   - `iran_cluster`
   - `middle_east_conflict`
   - `ukraine_russia`
   - `us_primary_2026`
   - `us_cabinet_appointments`
   - `central_bank_fed`
   - `ai_launches`
   - `spacex_launches`

3. Added theme-aware exposure control.
   - `EXPOSURE_THEME_CAP_PCT` defaults to 25% of bankroll.
   - `open_exposure` now returns `by_theme`.
   - `check_exposure` can block a trade on thematic concentration even when vertical cap is still fine.
   - `recommended_stake` shrinkage now includes theme load.

4. Added non-trading monitoring tools:
   - `catalyst_calendar(horizon_days=21)`
   - `due_for_recheck()`

5. Added `daily_research_brief()` as the session-start panel:
   - portfolio risk
   - theme exposure
   - near catalysts
   - due rechecks
   - recent discovery candidates from DB
   - incomplete research dossiers
   - pending outcome reviews

## Doctrine Update

The project should not treat all politics as one risk bucket. A Maine Democratic primary, an Iran meeting market, and a Fed-rate market are different research games and different concentration risks.

The new rule is: vertical tells us the broad domain; thematic tags tell us what correlated narrative can hurt us.
