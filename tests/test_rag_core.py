"""RAG engine tests that need no ML dependencies (error paths, empty states)."""

import pytest

from compliance_agent.engine.rag import RegulatoryRAG


def test_query_without_index_raises(tmp_path):
    rag = RegulatoryRAG(persist_dir=str(tmp_path / "missing" / ".chroma"))
    with pytest.raises(RuntimeError, match="No vector store available"):
        rag.query("test")


def test_ingest_missing_directory_raises(tmp_path):
    rag = RegulatoryRAG(persist_dir=str(tmp_path / ".chroma"))
    with pytest.raises(FileNotFoundError, match="Source directory not found"):
        rag.ingest_directory(str(tmp_path / "nope"))


def test_list_sources_empty_without_index(tmp_path):
    rag = RegulatoryRAG(persist_dir=str(tmp_path / "missing" / ".chroma"))
    assert rag.list_sources() == []


def test_print_results_renders_relevance(capsys, monkeypatch):
    from rich.console import Console

    monkeypatch.setattr("compliance_agent.engine.rag.console", Console(width=200))
    rag = RegulatoryRAG(persist_dir="/nonexistent")
    rag.print_results(
        [
            {"content": "Personal data shall be processed lawfully.", "source": "gdpr.txt", "relevance": 0.8},
            {"content": "x" * 300, "source": "long.txt", "relevance": 0.2},
        ]
    )
    # Rich wraps cells at the captured console width, so compare without whitespace.
    output = "".join(capsys.readouterr().out.split())
    assert "0.80" in output
    assert "0.20" in output
