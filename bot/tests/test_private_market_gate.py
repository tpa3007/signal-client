import run_command_d as d


def test_private_market_approval_requires_provider_mark_verification():
    candidate = {
        "archetype": "private_market_valuation",
        "question": "Will OpenAI's valuation hit (HIGH) $950B by June 30?",
        "private_market_mechanics": {"provider": "Nasdaq Private Market (NPM)"},
        "operator_review": {
            "approved_for_d": True,
            "operator_probability": 0.55,
            "supporting_source_urls": [
                "https://fe.secondmarket.com/companies/x/data",
                "https://example.com/secondary",
            ],
        },
    }

    missing = d._private_market_verification_missing(candidate)
    assert "latest_provider_mark" in missing
    assert "provider_mark_source_url" in missing
    assert "provider_mark_checked_at" in missing
    assert "rule_mechanics_verified" in missing


def test_private_market_verification_accepts_explicit_operator_fields():
    candidate = {
        "archetype": "private_market_valuation",
        "question": "Will OpenAI's valuation hit (HIGH) $950B by June 30?",
        "private_market_mechanics": {"provider": "Nasdaq Private Market (NPM)"},
        "operator_review": {
            "approved_for_d": True,
            "operator_probability": 0.55,
            "latest_provider_mark": "$900B",
            "provider_mark_source_url": "https://fe.secondmarket.com/companies/x/data",
            "provider_mark_checked_at": "2026-05-24T12:00:00Z",
            "rule_mechanics_verified": True,
        },
    }

    assert d._private_market_verification_missing(candidate) == []
