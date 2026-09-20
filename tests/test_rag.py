"""Tests for Regulatory RAG engine."""

import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("langchain_text_splitters", reason="langchain-text-splitters not installed")
pytest.importorskip("chromadb", reason="chromadb not installed")
pytest.importorskip("sentence_transformers", reason="sentence-transformers not installed")

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
    assert 0.0 < results[0]["relevance"] <= 1.0


def test_reingest_is_idempotent(sample_regulations):
    rag = RegulatoryRAG(persist_dir=os.path.join(sample_regulations, ".chroma"))
    rag.ingest_directory(sample_regulations, reset=True)
    first = rag.vectorstore.get()
    rag.ingest_directory(sample_regulations)  # no reset: must upsert, not duplicate
    second = rag.vectorstore.get()
    assert len(second["ids"]) == len(first["ids"])


def test_query_without_index():
    rag = RegulatoryRAG(persist_dir="/nonexistent/path")
    with pytest.raises(RuntimeError, match="No vector store available"):
        rag.query("test")


def test_ingest_empty_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        rag = RegulatoryRAG(persist_dir=os.path.join(tmpdir, ".chroma"))
        count = rag.ingest_directory(tmpdir, reset=True)
        assert count == 0


def test_reingest_changed_source_replaces_old_chunks(sample_regulations):
    rag = RegulatoryRAG(persist_dir=os.path.join(sample_regulations, ".chroma"))
    rag.ingest_directory(sample_regulations, reset=True)
    source = Path(sample_regulations) / "gdpr.txt"

    source.write_text("The updated regulation requires human oversight and clear retention limits.")
    rag.ingest_directory(sample_regulations)

    documents = rag.vectorstore.get()["documents"]
    joined = "\n".join(documents)
    assert "Personal data shall be processed" not in joined
    assert "human oversight" in joined


def test_reingest_removes_deleted_sources(sample_regulations):
    second = Path(sample_regulations) / "ai-act.txt"
    second.write_text("Providers must document human oversight.")
    rag = RegulatoryRAG(persist_dir=os.path.join(sample_regulations, ".chroma"))
    rag.ingest_directory(sample_regulations, reset=True)

    second.unlink()
    rag.ingest_directory(sample_regulations)

    assert rag.list_sources() == ["gdpr.txt"]


def test_reingest_empty_directory_removes_all_sources(sample_regulations):
    rag = RegulatoryRAG(persist_dir=os.path.join(sample_regulations, ".chroma"))
    rag.ingest_directory(sample_regulations, reset=True)
    (Path(sample_regulations) / "gdpr.txt").unlink()

    rag.ingest_directory(sample_regulations)

    assert rag.list_sources() == []


def test_reingest_rename_replaces_source_identity(sample_regulations):
    source = Path(sample_regulations) / "gdpr.txt"
    renamed = Path(sample_regulations) / "privacy.txt"
    rag = RegulatoryRAG(persist_dir=os.path.join(sample_regulations, ".chroma"))
    rag.ingest_directory(sample_regulations, reset=True)

    source.rename(renamed)
    rag.ingest_directory(sample_regulations)

    assert rag.list_sources() == ["privacy.txt"]


def test_duplicate_basenames_keep_relative_source_paths(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "policy.txt").write_text("Alpha requirements.")
    (tmp_path / "b" / "policy.txt").write_text("Beta requirements.")
    rag = RegulatoryRAG(persist_dir=str(tmp_path / ".chroma"))

    rag.ingest_directory(str(tmp_path), reset=True)

    assert rag.list_sources() == ["a/policy.txt", "b/policy.txt"]


def test_reset_rejects_source_directory_as_persistence_target(tmp_path):
    source = tmp_path / "regulations"
    source.mkdir()
    (source / "policy.txt").write_text("Policy text.")
    rag = RegulatoryRAG(persist_dir=str(source))

    with pytest.raises(ValueError, match="safe persistence directory"):
        rag.ingest_directory(str(source), reset=True)


def test_reset_rejects_persistence_ancestor_of_source(tmp_path):
    source = tmp_path / "regulations"
    source.mkdir()
    (source / "policy.txt").write_text("Policy text.")
    rag = RegulatoryRAG(persist_dir=str(tmp_path))

    with pytest.raises(ValueError, match="safe persistence directory"):
        rag.ingest_directory(str(source), reset=True)


def test_failed_reingestion_preserves_previous_index(sample_regulations, monkeypatch):
    rag = RegulatoryRAG(persist_dir=os.path.join(sample_regulations, ".chroma"))
    rag.ingest_directory(sample_regulations, reset=True)
    before = list(rag.vectorstore.get()["documents"])

    def fail_add(*args, **kwargs):
        raise RuntimeError("embedding failed")

    monkeypatch.setattr(rag.vectorstore, "add_documents", fail_add)
    source = Path(sample_regulations) / "gdpr.txt"
    source.write_text("Changed regulation text.")

    with pytest.raises(RuntimeError, match="embedding failed"):
        rag.ingest_directory(sample_regulations)

    assert rag.vectorstore.get()["documents"] == before
