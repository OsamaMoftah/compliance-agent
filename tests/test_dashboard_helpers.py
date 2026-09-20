import compliance_agent.dashboard.state as dashboard_state
from compliance_agent.dashboard.state import (
    clear_search_state,
    filter_search_results,
    read_search_state,
    write_search_state,
)


def test_search_state_round_trip_and_source_filtering():
    state = {}
    results = [
        {"source": "gdpr.txt", "content": "Consent", "relevance": 0.9},
        {"source": "ai-act.txt", "content": "Oversight", "relevance": 0.8},
    ]

    write_search_state(state, "human oversight", results)

    assert read_search_state(state) == {"query": "human oversight", "results": results}
    assert filter_search_results(results, "gdpr.txt") == [results[0]]
    assert filter_search_results(results, "All") == results


def test_clear_search_state_removes_stale_results():
    state = {"rag_query": "old", "rag_results": [{"source": "old.txt"}]}

    clear_search_state(state)

    assert read_search_state(state) == {"query": "", "results": []}


def test_resolve_sample_dir_prefers_checkout_and_falls_back_to_installed_data(tmp_path):
    resolve_sample_dir = getattr(dashboard_state, "resolve_sample_dir", None)
    assert callable(resolve_sample_dir)
    checkout = tmp_path / "checkout"
    checkout_samples = checkout / "sample_data"
    checkout_samples.mkdir(parents=True)
    data_root = tmp_path / "environment"
    installed_samples = data_root / "share" / "compliance-agent" / "sample_data"
    installed_samples.mkdir(parents=True)

    assert resolve_sample_dir(checkout, data_root) == checkout_samples

    checkout_samples.rmdir()
    assert resolve_sample_dir(checkout, data_root) == installed_samples
