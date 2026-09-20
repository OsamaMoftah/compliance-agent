"""Pure helpers for dashboard search state and filtering."""

from collections.abc import MutableMapping, Sequence
from typing import Any

_QUERY_KEY = "rag_query"
_RESULTS_KEY = "rag_results"


def write_search_state(state: MutableMapping[str, Any], query: str, results: Sequence[dict]) -> None:
    """Store the latest query and a JSON-friendly copy of its results."""
    state[_QUERY_KEY] = query
    state[_RESULTS_KEY] = list(results)


def read_search_state(state: MutableMapping[str, Any]) -> dict[str, Any]:
    """Return the latest search state with stable empty defaults."""
    return {
        "query": str(state.get(_QUERY_KEY, "")),
        "results": list(state.get(_RESULTS_KEY, [])),
    }


def clear_search_state(state: MutableMapping[str, Any]) -> None:
    """Clear query results after reset, failed search, or missing index."""
    state.pop(_QUERY_KEY, None)
    state.pop(_RESULTS_KEY, None)


def filter_search_results(results: Sequence[dict], source: str) -> list[dict]:
    """Filter results by source while preserving retrieval order."""
    if source == "All":
        return list(results)
    return [result for result in results if result.get("source") == source]
