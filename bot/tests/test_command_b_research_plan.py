from types import SimpleNamespace

import run_command_b as b


class _FakeSearch:
    def search(self, query: str, *, count: int):
        return [
            SimpleNamespace(
                url="https://example.com/npm-price",
                title="OpenAI Nasdaq Private Market NPM Price valuation mark",
                snippet="Current NPM Price valuation mark and trading days publication rules.",
                published_at=None,
                source_name="fake",
            ),
            SimpleNamespace(
                url="https://example.com/tender",
                title="OpenAI tender offer secondary sale valuation round",
                snippet="Tender secondary sale and fund mark cross-check for the private company.",
                published_at=None,
                source_name="fake",
            ),
        ][:count]


def test_research_plan_pass_tracks_required_evidence(monkeypatch):
    monkeypatch.setattr(b.forager, "search_adapter", _FakeSearch())
    candidate = {
        "condition_id": "0x1",
        "question": "Will OpenAI's valuation hit (HIGH) $950B by June 30?",
        "first_queries": ["NPM Price OpenAI Nasdaq Private Market valuation"],
        "official_urls": ["https://fe.secondmarket.com/companies/x/data"],
        "research_plan": {
            "decisive_questions": ["What is the latest observable NPM Price?"],
            "required_evidence": [
                "current_or_recent_provider_mark",
                "transaction_or_fund_mark_crosscheck",
                "rule_mechanics_verified",
            ],
        },
    }
    result = b._run_research_plan_pass(candidate)
    assert result["decisive_fact_status"] == "candidate_evidence_found"
    assert result["required_evidence_found"] == 3
    assert result["missing_required_evidence"] == []


def test_research_plan_pass_counts_operator_supporting_urls(monkeypatch):
    class EmptySearch:
        def search(self, query: str, *, count: int):
            return []

    monkeypatch.setattr(b.forager, "search_adapter", EmptySearch())
    candidate = {
        "condition_id": "0x2",
        "question": "Will a local election candidate win?",
        "operator_review": {
            "supporting_source_urls": ["https://example.com/local-poll", "https://example.com/filing"],
        },
        "research_plan": {
            "decisive_questions": ["What do local polls imply?"],
            "required_evidence": [
                "local_poll_or_official_filing",
                "resolution_scope_verified",
                "market_price_staleness_reason",
            ],
        },
    }

    result = b._run_research_plan_pass(candidate)

    assert result["decisive_fact_status"] == "candidate_evidence_found"
    assert result["required_evidence_found"] == 3
    assert result["missing_required_evidence"] == []
    assert all(
        item["status"] in {"found", "operator_seeded_source"}
        for item in result["coverage"].values()
    )
    assert all(
        any(match["source_name"] == "operator_seed" for match in item["matches"])
        for item in result["coverage"].values()
    )


def test_research_plan_filters_irrelevant_fallback_hits(monkeypatch):
    class NoisyFallbackSearch:
        def search(self, query: str, *, count: int):
            return [
                SimpleNamespace(
                    url="https://fred.stlouisfed.org/series/FEDFUNDS",
                    title="FRED Economic Data: FEDFUNDS",
                    snippet="Federal Reserve Economic Data series FEDFUNDS.",
                    published_at=None,
                    source_name="fred",
                ),
                SimpleNamespace(
                    url="https://www.metaculus.com/questions/11667/",
                    title="Will three countries ratify an East African Federation agreement?",
                    snippet="Metaculus question unrelated to the Korean by-election.",
                    published_at=None,
                    source_name="metaculus",
                ),
            ]

    monkeypatch.setattr(b.forager, "search_adapter", NoisyFallbackSearch())
    candidate = {
        "condition_id": "0x3",
        "question": "Will the People Power Party win less than or equal to 1 seat?",
        "research_plan": {
            "decisive_questions": ["What exact seats resolve this market?"],
            "required_evidence": ["local_poll_or_official_filing"],
        },
    }

    result = b._run_research_plan_pass(candidate)

    assert result["decisive_fact_status"] == "search_backend_degraded"
    assert result["results_found"] == 0
    assert result["search_backend_degraded"] is True
    assert result["query_summaries"][0]["filtered_out"] == 2


def test_selected_candidates_filters_by_cid_and_limit(monkeypatch):
    candidates = [
        {"condition_id": "0xaaa111", "question": "First", "slug": "first"},
        {"condition_id": "0xbbb222", "question": "Second", "slug": "second"},
    ]
    monkeypatch.setenv("SIGNAL_COMMAND_B_ONLY_CID", "0xbbb")
    monkeypatch.setenv("SIGNAL_COMMAND_B_LIMIT", "1")

    selected = b._selected_candidates(candidates)

    assert selected == [candidates[1]]
