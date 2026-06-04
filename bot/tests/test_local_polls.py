from lib.integrations import local_polls
from lib.integrations.local_polls import PollSnapshot, format_polls_for_forager


def test_unverified_search_snippet_poll_is_not_injected_by_default():
    snap = PollSnapshot(
        source_name="Korean polls (Naver aggregation)",
        source_url="https://search.naver.com/search.naver?where=news",
        region="korean",
        poll_date="2026-05-24",
        leading_candidate="Kim Kwan-young",
        leading_pct=43.2,
        runner_up_pct=39.7,
        lead_margin=3.5,
        fetch_ok=False,
        source_quality="unverified_search_snippet",
    )

    assert local_polls.ALLOW_UNVERIFIED_POLL_SNIPPETS is False
    assert format_polls_for_forager([snap], market_price=0.41) is None


def test_verified_poll_snapshot_can_be_formatted():
    snap = PollSnapshot(
        source_name="Verified local article",
        source_url="https://example.com/poll",
        region="korean",
        poll_date="2026-05-24",
        leading_candidate="Kim Kwan-young",
        leading_pct=43.2,
        runner_up_pct=39.7,
        lead_margin=3.5,
        fetch_ok=True,
        source_quality="verified_article",
    )

    block = format_polls_for_forager([snap], market_price=0.41)
    assert block is not None
    assert "Kim Kwan-young" in block
