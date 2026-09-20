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
