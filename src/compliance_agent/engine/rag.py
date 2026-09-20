"""Regulatory RAG engine — ingest and query regulatory documents."""

import hashlib
import os
import shutil
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_PERSIST_DIR = ".chroma"
INDEX_MARKER = ".compliance-agent-index"
INDEX_MARKER_CONTENT = "compliance-agent-index-v1\n"


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

    def ingest_directory(self, source_dir: str, reset: bool = False, emit_console: bool = True) -> int:
        """Ingest all .txt and .md files from a directory into the vector store.

        Returns the number of chunks ingested.
        """
        canonical_source = os.path.realpath(os.path.expanduser(source_dir))
        if not os.path.exists(canonical_source):
            raise FileNotFoundError(f"Source directory not found: {source_dir}")
        if not os.path.isdir(canonical_source):
            raise NotADirectoryError(f"Source path is not a directory: {source_dir}")
        source_path = Path(canonical_source)

        reset_target = self._validate_reset_target(source_path) if reset else None
        if reset_target is not None and reset_target.exists():
            shutil.rmtree(reset_target)
            self._vectorstore = None

        text_files = sorted(source_path.rglob("*.txt")) + sorted(source_path.rglob("*.md"))
        source_ids = {self._source_id(filepath, source_path) for filepath in text_files}
        store = self.vectorstore

        if not text_files:
            if emit_console:
                console.print("[yellow]No .txt or .md files found in source directory.[/yellow]")
            if store is not None:
                self._delete_stale_records(store, set(), set())
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
            source_id = self._source_id(filepath, source_path)
            source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            chunks = splitter.create_documents(
                [text],
                metadatas=[
                    {
                        "source": source_id,
                        "source_id": source_id,
                        "source_sha256": source_hash,
                    }
                ],
            )
            for index, chunk in enumerate(chunks):
                chunk.metadata.update(
                    {
                        "source": source_id,
                        "source_id": source_id,
                        "source_sha256": source_hash,
                        "chunk_index": index,
                    }
                )
                digest = hashlib.sha256(f"{source_id}::{index}::{chunk.page_content}".encode("utf-8")).hexdigest()
                ids.append(digest)
                all_docs.append(chunk)

        if not all_docs:
            if emit_console:
                console.print("[yellow]No content found in source documents.[/yellow]")
            if store is not None:
                self._delete_stale_records(store, source_ids, set())
            return 0

        if emit_console:
            console.print(f"[dim]Embedding {len(all_docs)} chunks with {self.model_name}...[/dim]")
        new_ids = set(ids)
        if store is None:
            store = _chroma_class()(
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings,
            )
            self._vectorstore = store
            self._write_ownership_marker()
        existing_ids = {record_id for record_id, _ in self._stored_records(store)} if store is not None else set()
        additions = [(document, record_id) for document, record_id in zip(all_docs, ids) if record_id not in existing_ids]
        added_ids = [record_id for _, record_id in additions]
        try:
            if additions:
                store.add_documents([document for document, _ in additions], ids=added_ids)
        except Exception:
            if added_ids:
                store.delete(ids=added_ids)
            raise

        self._delete_stale_records(store, source_ids, new_ids)
        if emit_console:
            console.print(f"[green]Ingested {len(all_docs)} chunks from {len(text_files)} files.[/green]")
        return len(all_docs)

    @staticmethod
    def _source_id(filepath: Path, source_path: Path) -> str:
        """Return a stable, user-safe source identity relative to the corpus."""
        return filepath.relative_to(source_path).as_posix()

    def _validate_reset_target(self, source_path: Path) -> Path:
        """Reject destructive reset targets that are not dedicated data directories."""
        configured_path = Path(self.persist_dir).expanduser()
        if configured_path.is_symlink():
            raise ValueError("reset requires a safe persistence directory, not a symbolic link")
        persist_path = configured_path.resolve()
        source_resolved = source_path
        forbidden = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve(), source_resolved}
        if persist_path in forbidden or persist_path in source_resolved.parents or persist_path.name in {"", ".", ".."}:
            raise ValueError("reset requires a safe persistence directory distinct from the source directory")
        trusted_roots = (Path.cwd().resolve(), source_resolved)
        if not any(root in persist_path.parents for root in trusted_roots):
            raise ValueError("reset requires the persistence directory to be inside a trusted data root")
        if persist_path.exists() and not persist_path.is_dir():
            raise ValueError("reset requires a safe persistence directory, not a file")
        if persist_path.exists() and any(persist_path.iterdir()):
            marker = persist_path / INDEX_MARKER
            if not marker.is_file() or marker.read_text(encoding="utf-8") != INDEX_MARKER_CONTENT:
                raise ValueError("reset requires a valid compliance-agent ownership marker")
        return persist_path

    def _write_ownership_marker(self) -> None:
        persist_path = Path(self.persist_dir).expanduser().resolve()
        persist_path.mkdir(parents=True, exist_ok=True)
        (persist_path / INDEX_MARKER).write_text(INDEX_MARKER_CONTENT, encoding="utf-8")

    @staticmethod
    def _stored_records(store) -> list[tuple[str, dict]]:
        data = store.get(include=["metadatas"])
        ids = data.get("ids", [])
        metadatas = data.get("metadatas", [])
        return [
            (record_id, metadata or {})
            for record_id, metadata in zip(ids, metadatas)
        ]

    def _delete_stale_records(self, store, current_source_ids: set[str], current_ids: set[str]) -> None:
        ids = [
            record_id
            for record_id, metadata in self._stored_records(store)
            if (
                metadata.get("source_id", metadata.get("source")) not in current_source_ids
                or record_id not in current_ids
            )
        ]
        if ids:
            store.delete(ids=ids)

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
