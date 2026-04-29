# Compliance Agent Architecture

## System Overview

Compliance Agent is a modular compliance monitoring pipeline with four core engines and two interfaces (CLI and Streamlit dashboard).

## Core Engines

### 1. RAG Engine (`engine/rag.py`)

The RegulatoryRAG class provides retrieval-augmented generation over regulatory documents.

**Pipeline:**
1. **Ingestion**: Reads regulatory text files from a directory, chunks by paragraph with overlap.
2. **Embedding**: Uses `sentence-transformers/all-MiniLM-L6-v2` for offline embeddings (no API key needed).
3. **Storage**: ChromaDB persistent vector store with metadata (source file, chunk index, regulation name).
4. **Retrieval**: Semantic search returning top-k chunks with relevance scores.
5. **Query**: Retrieves context, then generates a natural language answer using an LLM (optional — falls back to summarization if no LLM configured).

**Design decisions:**
- Local embeddings by default (no API dependency) so the tool works offline.
- ChromaDB over FAISS for persistence, CLI-friendly browsing, and simpler metadata filtering.
- Paragraph-level chunking (preserves regulatory structure better than fixed-size chunks).

### 2. Drift Detection Engine (`engine/drift.py`)

The DriftBridge wraps LegalDrift's statistical detectors and adds structured output.

**Capabilities:**
- Full-document drift detection (Kolmogorov-Smirnov, Mann-Whitney, MMD, Energy Distance).
- Section-by-section chunked detection with alignment.
- History persistence (SQLite/JL) for audit trails.
- Severity scoring and human-readable summaries.

**Design decisions:**
- Wraps LegalDrift's Python API directly (not CLI subprocess) for speed.
- Graceful degradation: if LegalDrift is not installed, the `check` and `drift` commands error with a helpful `pip install legaldrift` message.
- Chunked mode defaults to paragraph boundaries for policy documents.

### 3. Rule Reasoning Engine (`engine/reasoner.py`)

The ComplianceReasoner encodes DDL-style rules and evaluates facts against them.

**Implementation:**
- **Self-contained DDL:** Includes a lightweight differentiable deontic logic implementation (soft AND, OR, NOT, implication, obligation, permission, prohibition).
- **Rule loading:** Parses YAML rule files into structured `ComplianceRule` objects with predicate definitions.
- **Predicate extraction:** Simple regex/rule-based extraction from policy text (matches patterns defined in rule conditions).
- **Reasoning:** For each rule, evaluates predicate truth values, computes obligation/permission/prohibition strengths using soft logic, and resolves conflicts.
- **Confidence scoring:** Weighted aggregation of predicate evidence with configurable thresholds.

**Design decisions:**
- Built-in DDL rather than depending on DiffDDL (avoids pip-installing from git).
- If DiffDDL is installed, the reasoner can optionally use it for complex neural-symbolic scenarios.
- Rules are YAML-based for easy authoring by compliance teams without programming.
- Predicate extraction uses simple keyword matching — deliberately not a complex NLP pipeline (keeps the tool explainable).

### 4. Compliance Checker (`engine/checker.py`)

The ComplianceChecker orchestrates all three engines for a full compliance check:

1. **Regulatory context** (RAG): Retrieves relevant regulation passages for the policy topic.
2. **Drift baseline** (Drift): If a previous version exists, detects what changed.
3. **Rule evaluation** (Reasoner): Extracts predicates from the policy, evaluates against each rule.
4. **Risk scoring**: Aggregates results into a compliance report with risk levels (PASS, WARNING, FAIL).

## CLI Architecture (`cli.py`)

Built with Click. Each subcommand maps to an engine:

```
compliance-agent
├── monitor    → rag.ingest_directory() or rag.query()
├── check      → checker.full_check()
├── drift      → drift.detect() or drift.chunked_detect()
├── reason     → reasoner.evaluate_scenario()
└── dashboard  → streamlit run dashboard/app.py
```

## Dashboard (`dashboard/app.py`)

Streamlit multi-tab application:

1. **Monitor**: Ingest regulations, search the vector index, view relevance scores.
2. **Check**: Upload a policy + rules, see compliance results in a table with risk indicators.
3. **Drift**: Upload two policy versions, see section-by-section comparison with color-coded results.
4. **Reason**: Input a scenario (facts), see DDL reasoning trace and final decision.

## Data Flow (Full Check)

```
policy.txt ──→ ┌─────────────┐
               │ Predicate    │──→ facts (dict of {name: score})
               │ Extractor    │
               └─────────────┘
                       │
                       ▼
               ┌─────────────┐
rules.yaml ──→ │ Compliance  │──→ per-rule results
               │ Reasoner    │     (PASS/WARNING/FAIL)
               └─────────────┘
                       │
                       ▼
               ┌─────────────┐
regulations/─→ │ RAG         │──→ relevant context
               │ Retriever   │
               └─────────────┘
                       │
                       ▼
               ┌─────────────┐
               │ Report      │──→ Markdown + JSON
               │ Generator   │
               └─────────────┘
```

## Extension Points

- **Custom embeddings**: Swap `sentence-transformers` for OpenAI/HuggingFace embeddings via config.
- **Additional rule formats**: The `ComplianceRule` model supports JSON and Python dict inputs beyond YAML.
- **Streaming mode**: The checker supports incremental evaluation for long policies.
- **Multi-jurisdiction**: The rules format already supports `jurisdiction` tags; RAG filtering by jurisdiction is planned.
