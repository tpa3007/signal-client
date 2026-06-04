from lib.analysis.pace_calculator import detect_pace_market


def test_valuation_threshold_is_not_pace_market():
    assert not detect_pace_market("Will OpenAI's valuation hit (HIGH) $950B by June 30?")
    assert not detect_pace_market("Will SpaceX's valuation hit (HIGH) $2.0T by June 30?")


def test_production_threshold_is_pace_market():
    assert detect_pace_market("Will Acme produce at least 250,000 units by June 30?")
