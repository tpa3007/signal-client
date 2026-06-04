import run_command_p as p


def test_parse_npm_mechanics_extracts_core_rules():
    market = {
        "question": "Will SpaceX's valuation hit $1.75T by June 30?",
        "description": (
            "This market will resolve to Yes if SpaceX's private market valuation, "
            "as measured by the NPM Price reported by Nasdaq Private Market, LLC "
            "(NPM), reaches or exceeds the listed amount. NPM Prices are published "
            "for trading days only and are updated once daily at 1:00 PM ET on the "
            "following calendar day. If the company completes an IPO or direct "
            "listing before the end of the specified period, public market "
            "capitalization will be considered. If the listed company is acquired, "
            "merges into another entity, or otherwise ceases to exist, only NPM "
            "valuations achieved prior to completion will be considered. Revisions "
            "to previously published NPM data made after their initial release will "
            "not be considered, unless made to correct clearly erroneous data. "
            "The resolution source is https://fe.secondmarket.com/companies/x/data."
        ),
        "endDate": "2026-07-01T00:00:00Z",
    }
    mechanics = p.parse_npm_mechanics(market)
    assert mechanics.provider == "Nasdaq Private Market (NPM)"
    assert mechanics.metric == "NPM Price"
    assert mechanics.threshold == "$1.75T"
    assert mechanics.direction == ">="
    assert mechanics.publication_cadence == "trading_days_only"
    assert "1:00 PM ET" in mechanics.reporting_lag
    assert mechanics.ipo_clause is True
    assert mechanics.corporate_action_clause is True
    assert mechanics.revision_rule is not None
    assert mechanics.source_url == "https://fe.secondmarket.com/companies/x/data"


def test_parse_npm_mechanics_respects_low_high_direction_labels():
    low = p.parse_npm_mechanics({
        "question": "Will Canva's valuation hit (LOW) $40B by June 30?",
        "description": "Resolves using the NPM Price reported by Nasdaq Private Market.",
    })
    high = p.parse_npm_mechanics({
        "question": "Will OpenAI's valuation hit (HIGH) $950B by June 30?",
        "description": "Resolves using the NPM Price reported by Nasdaq Private Market.",
    })
    assert low.direction == "<="
    assert high.direction == ">="


def test_private_market_detection_with_company_valuation_hint():
    market = {
        "question": "Will Anthropic's valuation hit $1.5T by June 30?",
        "description": "Rules pending.",
        "slug": "will-anthropics-valuation-hit-high-1pt5t-by-june-30",
    }
    assert p.is_private_market(market) is True


def test_mechanics_score_penalizes_missing_oracle_rules():
    mechanics = p.parse_npm_mechanics({
        "question": "Will OpenAI's valuation hit $1T by Dec 31?",
        "description": "This resolves based on valuation.",
    })
    assert p._mechanics_score(mechanics) < 0.5
    assert "provider_not_explicit" in mechanics.ambiguity_flags


def test_select_private_queue_caps_company_concentration():
    candidates = []
    for i in range(4):
        candidates.append({
            "company": "Anthropic",
            "yes_price": 0.5,
            "research_priority_score": 1 - i / 10,
            "mechanics_score": 1,
            "volume": 5000,
            "end_date": "2026-07-01T00:00:00Z",
        })
    candidates.append({
        "company": "OpenAI",
        "yes_price": 0.5,
        "research_priority_score": 0.5,
        "mechanics_score": 1,
        "volume": 5000,
        "end_date": "2026-07-01T00:00:00Z",
    })
    selected = p.select_private_queue(candidates, n=4)
    assert [c["company"] for c in selected] == ["Anthropic", "OpenAI"]
