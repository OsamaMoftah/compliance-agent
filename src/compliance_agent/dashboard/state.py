"""Pure helpers for dashboard search state and filtering."""

from collections.abc import Sequence
from pathlib import Path
from sysconfig import get_path
from typing import Any, Protocol, overload

_QUERY_KEY = "rag_query"
_RESULTS_KEY = "rag_results"


class StateStore(Protocol):
    """Minimal mapping interface shared by dict and Streamlit session state."""

    def __setitem__(self, key: str, value: Any) -> None: ...

    @overload
    def get(self, key: str | int, /) -> Any | None: ...

    @overload
    def get(self, key: str | int, default: Any, /) -> Any: ...

    @overload
    def pop(self, key: str | int, /) -> Any: ...

    @overload
    def pop(self, key: str | int, default: Any, /) -> Any: ...


def resolve_sample_dir(checkout_root: Path | None = None, data_root: Path | None = None) -> Path:
    """Locate samples in a source checkout or an installed wheel's data directory."""
    checkout_samples = (checkout_root or Path.cwd()) / "sample_data"
    if checkout_samples.is_dir():
        return checkout_samples
    install_root = data_root or Path(get_path("data"))
    return install_root / "share" / "compliance-agent" / "sample_data"


def write_search_state(state: StateStore, query: str, results: Sequence[dict]) -> None:
    """Store the latest query and a JSON-friendly copy of its results."""
    state[_QUERY_KEY] = query
    state[_RESULTS_KEY] = list(results)


def read_search_state(state: StateStore) -> dict[str, Any]:
    """Return the latest search state with stable empty defaults."""
    return {
        "query": str(state.get(_QUERY_KEY, "")),
        "results": list(state.get(_RESULTS_KEY, [])),
    }


def clear_search_state(state: StateStore) -> None:
    """Clear query results after reset, failed search, or missing index."""
    state.pop(_QUERY_KEY, None)
    state.pop(_RESULTS_KEY, None)


def filter_search_results(results: Sequence[dict], source: str) -> list[dict]:
    """Filter results by source while preserving retrieval order."""
    if source == "All":
        return list(results)
    return [result for result in results if result.get("source") == source]
