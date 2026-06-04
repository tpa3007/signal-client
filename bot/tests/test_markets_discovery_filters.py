import pytest

from markets import fetch_active_markets


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def get(self, *args, **kwargs):
        self.calls += 1
        if self.calls > 1:
            return FakeResponse([])
        return FakeResponse(self.payload)


@pytest.mark.anyio
async def test_discovery_scan_can_keep_extreme_price_markets():
    payload = [
        {
            "conditionId": "0xcheap",
            "question": "Will a long-shot political event happen by June 30?",
            "slug": "cheap-event",
            "volumeNum": "150",
            "endDate": "2026-06-30T00:00:00Z",
            "outcomePrices": '["0.01","0.99"]',
        }
    ]

    strict = await fetch_active_markets(
        FakeClient(payload),
        max_pages=2,
        discovery_mode=True,
        min_volume_usd=100,
        days_min=1,
        days_max=365,
    )
    widened = await fetch_active_markets(
        FakeClient(payload),
        max_pages=2,
        discovery_mode=True,
        min_volume_usd=100,
        days_min=1,
        days_max=365,
        min_yes_price=0.005,
        max_yes_price=0.995,
    )

    assert strict == []
    assert len(widened) == 1
    assert widened[0].condition_id == "0xcheap"
