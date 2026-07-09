"""Regulatory RAG engine — ingest and query regulatory documents."""

import hashlib
import os
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_PERSIST_DIR = ".chroma"


def _embeddings_class():
    # Imported dynamically (not `from x import Y`) so mypy sees a single Any-typed
    # result regardless of which optional package is installed, instead of two
    # static class definitions that only conflict under some install profiles.
    import importlib

    try:
        module = importlib.import_module("langchain_huggingface")
    except ImportError:
        module = importlib.import_module("langchain_community.embeddings")
    return module.HuggingFaceEmbeddings


def _chroma_class():
    import importlib

    try:
        module = importlib.import_module("langchain_chroma")
    except ImportError:
        module = importlib.import_module("langchain_community.vectorstores")
    return module.Chroma


class RegulatoryRAG:
    """Retrieval over regulatory documents.

    Ingests regulatory text files, chunks them, produces embeddings,
    and supports semantic search queries. Ingestion is idempotent: chunk IDs
    are content hashes, so re-ingesting the same corpus upserts rather than
    duplicating.
    """

    def __init__(self, persist_dir: str = DEFAULT_PERSIST_DIR, model_name: str = DEFAULT_MODEL):
        self.persist_dir = persist_dir
        self.model_name = model_name
        self._embeddings = None
        self._vectorstore = None

    @property
    def embeddings(self):
        if self._embeddings is None:
            self._embeddings = _embeddings_class()(model_name=self.model_name)
        return self._embeddings

    @property
    def vectorstore(self):
        if self._vectorstore is None and os.path.exists(self.persist_dir):
            self._vectorstore = _chroma_class()(
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings,
            )
        return self._vectorstore

    def ingest_directory(self, source_dir: str, reset: bool = False) -> int:
        """Ingest all .txt and .md files from a directory into the vector store.

        Returns the number of chunks ingested.
        """
        source_path = Path(source_dir)
        if not source_path.exists():
            raise FileNotFoundError(f"Source directory not found: {source_dir}")

        if reset and os.path.exists(self.persist_dir):
            import shutil

            shutil.rmtree(self.persist_dir)
            self._vectorstore = None

        text_files = sorted(source_path.rglob("*.txt")) + sorted(source_path.rglob("*.md"))
        if not text_files:
            console.print("[yellow]No .txt or .md files found in source directory.[/yellow]")
            return 0

        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=80,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        all_docs = []
        ids = []
        for filepath in text_files:
            text = filepath.read_text(encoding="utf-8")
            if not text.strip():
                continue
            chunks = splitter.create_documents(
                [text],
                metadatas=[{"source": filepath.name, "path": str(filepath)}],
            )
            for index, chunk in enumerate(chunks):
                digest = hashlib.sha256(f"{filepath}::{index}::{chunk.page_content}".encode("utf-8")).hexdigest()
                ids.append(digest)
                all_docs.append(chunk)

        if not all_docs:
            console.print("[yellow]No content found in source documents.[/yellow]")
            return 0

        console.print(f"[dim]Embedding {len(all_docs)} chunks with {self.model_name}...[/dim]")
        store = self.vectorstore
        if store is None:
            store = _chroma_class()(
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings,
            )
            self._vectorstore = store
        # Deterministic content-hash IDs make this an upsert, not a duplicate.
        store.add_documents(all_docs, ids=ids)
        console.print(f"[green]Ingested {len(all_docs)} chunks from {len(text_files)} files.[/green]")
        return len(all_docs)

    def query(self, question: str, k: int = 5) -> list[dict]:
        """Query the vector store and return top-k results.

        Each result carries both the raw ``distance`` (lower is better) and a
        normalized ``relevance`` in (0, 1] (higher is better).
        """
        if self.vectorstore is None:
            raise RuntimeError(
                "No vector store available. Run ingest_directory() first, "
                "or ensure the persist directory exists."
            )

        results = self.vectorstore.similarity_search_with_score(question, k=k)
        return [
            {
                "content": doc.page_content,
                "source": doc.metadata.get("source", "unknown"),
                "distance": float(score),
                "relevance": 1.0 / (1.0 + float(score)),
            }
            for doc, score in results
        ]

    def list_sources(self) -> list[str]:
        """List all unique source files in the vector store."""
        if self.vectorstore is None:
            return []
        metadata = self.vectorstore.get(include=["metadatas"])
        sources = set()
        for meta in metadata.get("metadatas", []):
            if meta and "source" in meta:
                sources.add(meta["source"])
        return sorted(sources)

    def print_results(self, results: list[dict]) -> None:
        """Pretty-print query results."""
        table = Table(title="Regulatory Query Results", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Relevance", style="cyan", width=10)
        table.add_column("Source", style="green", width=20)
        table.add_column("Content", width=80)

        for i, r in enumerate(results, 1):
            relevance = r.get("relevance", 0.0)
            style = "green" if relevance >= 0.5 else "yellow"
            table.add_row(
                str(i),
                f"[{style}]{relevance:.2f}[/{style}]",
                r["source"],
                r["content"][:200] + ("..." if len(r["content"]) > 200 else ""),
            )

        console.print(table)
