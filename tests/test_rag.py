"""Tests for Regulatory RAG engine."""

import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("langchain_text_splitters", reason="langchain-text-splitters not installed")
pytest.importorskip("langchain_community", reason="langchain-community not installed")

from compliance_agent.engine.rag import RegulatoryRAG


@pytest.fixture
def sample_regulations():
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_file = Path(tmpdir) / "gdpr.txt"
        reg_file.write_text(
            "Personal data shall be processed lawfully, fairly, and transparently. "
            "Data must be collected for specified, explicit, and legitimate purposes. "
            "Data minimization requires adequate, relevant, and limited collection."
        )
        yield tmpdir


def test_ingest_directory(sample_regulations):
    rag = RegulatoryRAG(persist_dir=os.path.join(sample_regulations, ".chroma"))
    count = rag.ingest_directory(sample_regulations, reset=True)
    assert count > 0
    sources = rag.list_sources()
    assert "gdpr.txt" in sources


def test_query(sample_regulations):
    rag = RegulatoryRAG(persist_dir=os.path.join(sample_regulations, ".chroma"))
    rag.ingest_directory(sample_regulations, reset=True)
    results = rag.query("lawful processing")
    assert len(results) > 0
    assert "source" in results[0]
    assert "content" in results[0]


def test_query_without_index():
    rag = RegulatoryRAG(persist_dir="/nonexistent/path")
    with pytest.raises(RuntimeError, match="No vector store available"):
        rag.query("test")


def test_ingest_empty_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        rag = RegulatoryRAG(persist_dir=os.path.join(tmpdir, ".chroma"))
        count = rag.ingest_directory(tmpdir, reset=True)
        assert count == 0
