"""Regulatory RAG engine — ingest and query regulatory documents."""

import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

console = Console()

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_PERSIST_DIR = ".chroma"


class RegulatoryRAG:
    """Retrieval-augmented generation over regulatory documents.

    Ingests regulatory text files, chunks them, produces embeddings,
    and supports semantic search queries.
    """

    def __init__(self, persist_dir: str = DEFAULT_PERSIST_DIR, model_name: str = DEFAULT_MODEL):
        self.persist_dir = persist_dir
        self.model_name = model_name
        self._embeddings = None
        self._vectorstore = None

    @property
    def embeddings(self):
        if self._embeddings is None:
            from langchain_community.embeddings import HuggingFaceEmbeddings
            self._embeddings = HuggingFaceEmbeddings(model_name=self.model_name)
        return self._embeddings

    @property
    def vectorstore(self):
        if self._vectorstore is None and os.path.exists(self.persist_dir):
            from langchain_community.vectorstores import Chroma
            self._vectorstore = Chroma(
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

        text_files = list(source_path.rglob("*.txt")) + list(source_path.rglob("*.md"))
        if not text_files:
            console.print("[yellow]No .txt or .md files found in source directory.[/yellow]")
            return 0

        from langchain.text_splitter import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=80,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        all_docs = []
        for filepath in text_files:
            text = filepath.read_text(encoding="utf-8")
            if not text.strip():
                continue
            chunks = splitter.create_documents(
                [text],
                metadatas=[{"source": filepath.name, "path": str(filepath)}],
            )
            all_docs.extend(chunks)

        if not all_docs:
            console.print("[yellow]No content found in source documents.[/yellow]")
            return 0

        console.print(f"[dim]Embedding {len(all_docs)} chunks with {self.model_name}...[/dim]")
        from langchain_community.vectorstores import Chroma
        self._vectorstore = Chroma.from_documents(
            documents=all_docs,
            embedding=self.embeddings,
            persist_directory=self.persist_dir,
        )
        console.print(f"[green]Ingested {len(all_docs)} chunks from {len(text_files)} files.[/green]")
        return len(all_docs)

    def query(self, question: str, k: int = 5) -> list[dict]:
        """Query the vector store and return top-k results."""
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
                "score": float(score),
            }
            for doc, score in results
        ]

    def list_sources(self) -> list[str]:
        """List all unique source files in the vector store."""
        if self.vectorstore is None:
            return []
        collection = self.vectorstore._collection
        metadata = collection.get(include=["metadatas"])
        sources = set()
        for meta in metadata.get("metadatas", []):
            if meta and "source" in meta:
                sources.add(meta["source"])
        return sorted(sources)

    def print_results(self, results: list[dict]) -> None:
        """Pretty-print query results."""
        table = Table(title="Regulatory Query Results", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Score", style="cyan", width=8)
        table.add_column("Source", style="green", width=20)
        table.add_column("Content", width=80)

        for i, r in enumerate(results, 1):
            score = r["score"]
            score_style = "green" if score < 0.5 else "yellow"
            table.add_row(
                str(i),
                f"[{score_style}]{score:.3f}[/{score_style}]",
                r["source"],
                r["content"][:200] + ("..." if len(r["content"]) > 200 else ""),
            )

        console.print(table)
