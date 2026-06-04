from forager.memory import SQLiteForagerStore
from forager.models import DepthMode, ResearchStartRequest, SearchBurstRequest
from forager.search import SearchResult, StaticSearchAdapter
from forager.service import ForagerService


def _service_with_static_results(store=None):
    adapter = StaticSearchAdapter(
        default_results=[
            SearchResult(
                url="https://github.com/example/hidden-project/issues/17",
                title="Deleted roadmap contradicts launch story",
                snippet="maintainer removed milestone after unusual timing",
                source_name="static",
                raw={"rank": 1},
            ),
            SearchResult(
                url="https://local-forum.example/archive/thread.pdf",
                title="Archived local forum thread nobody cites",
                snippet="old cached PDF with pre-hype discussion",
                source_name="static",
                raw={"rank": 2},
            ),
        ]
    )
    return ForagerService(store=store, search_adapter=adapter)


def test_search_burst_writes_raw_items_and_promotes_weird_sources():
    service = _service_with_static_results()
    result = service.start_research(
        ResearchStartRequest(seed_query="hidden project launch market", market_id="market_phase1", depth=DepthMode.SHALLOW)
    )
    thread_id = result["thread"]["id"]

    burst = service.run_search_burst(thread_id, SearchBurstRequest(max_queries=2, results_per_query=2))
    state = service.get_thread(thread_id)

    assert burst["queries_attempted"] == 2
    assert burst["raw_items_written"] == 4
    assert state["raw_items"]
    assert state["sources"]
    assert state["anomalies"]
    assert all(item["raw_json_hash"] for item in state["raw_items"])


def test_sqlite_store_persists_threads_raw_items_and_packets(tmp_path):
    db_path = tmp_path / "forager.sqlite3"
    service = _service_with_static_results(SQLiteForagerStore(db_path))
    result = service.start_research(ResearchStartRequest(seed_query="obscure election market", market_id="market_sqlite"))
    thread_id = result["thread"]["id"]
    service.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=2))
    packet = service.build_packet(thread_id)

    reopened = SQLiteForagerStore(db_path)

    assert reopened.require_thread(thread_id).market_id == "market_sqlite"
    assert len(reopened.thread_raw_items(thread_id)) == 2
    assert reopened.latest_packet_for_thread(thread_id).id == packet.id
    assert reopened.latest_packet_for_market("market_sqlite").id == packet.id


def test_signal_bridge_packet_never_approves_signal_directly():
    service = _service_with_static_results()
    result = service.start_research(ResearchStartRequest(seed_query="will hidden project launch by June", market_id="market_bridge"))
    thread_id = result["thread"]["id"]
    service.run_search_burst(thread_id, SearchBurstRequest(max_queries=1, results_per_query=1))
    service.build_packet(thread_id)

    bridge = service.export_signal_bridge_packet(thread_id)

    assert bridge.boundary == "Forager discovers; Signal decides."
    assert bridge.market_id == "market_bridge"
    assert bridge.source_items
    assert "run_signal_pre_bet_gate_if_candidate_survives" in bridge.signal_next_actions
    assert not any(action in bridge.signal_next_actions for action in ["create_signal", "create_position", "record_fill"])
