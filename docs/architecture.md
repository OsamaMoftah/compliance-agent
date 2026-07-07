# Compliance Agent Architecture

## System Overview

Compliance Agent is a modular compliance screening pipeline with three core engines and two interfaces (CLI and Streamlit dashboard). The core install is a pure-Python rule reasoner; retrieval, drift detection, and the dashboard are optional extras.

## Core Engines

### 1. Rule Reasoning Engine (`engine/reasoner.py`)

The ComplianceReasoner evaluates schema-v2 rules against policy text or scenario facts.

**Rule schema v2:**
- Predicates carry explicit `keywords` (exact phrases, word-boundary matched, case-insensitive) and/or `patterns` (regex). Legacy v1 prose `condition` strings are still accepted — keywords are inferred — with a deprecation warning from `validate-rules`.
- `match: any` (default) treats keywords as alternative phrasings: one non-negated hit scores 1.0. `match: all` scores graded coverage (matched terms / total terms).
- Rules carry `severity` (critical/major/minor), `citation`, an optional `applies_when` applicability gate, and — for prohibitions — an optional `unless` block of exception predicates.

**Evaluation pipeline (text mode):**
1. The policy is split into sentence spans once per document.
2. Each predicate's terms are matched with word boundaries; negation is detected **within the matched sentence only**, both before the keyword ("do not", "never", "without", …) and after it ("… is prohibited").
3. Predicate scores are aggregated per rule as a weighted mean (`Σ(score·w)/Σ(w)`) — the same aggregation used in facts mode.
4. Deontic semantics: obligations/permissions score the evidence directly; prohibitions compute `violation = trigger AND NOT exception` with the soft-logic ops, then `strength = NOT violation`.
5. Rules whose `applies_when` gate has no non-negated match report status **N/A** and are excluded from scoring and risk.
6. Status per rule: PASS, WARN (within 0.1 above the threshold — passes but flagged for review), FAIL, or N/A.
7. Overall score is a severity-weighted mean over applicable rules; risk is HIGH on any critical failure or >30% failures, MEDIUM on any failure or warning, LOW otherwise.

**Scenario mode** evaluates the same rules against a facts dict (`{predicate_name: confidence}`) and additionally resolves the aggregate obligation pressure / permission level / violation level through `DDL.resolve()` into a decision: ALLOW, ALLOW_WITH_OBLIGATIONS, or BLOCK.

**Design decisions:**
- Built-in soft-logic DDL rather than depending on DiffDDL (avoids pip-installing from git).
- Rules are YAML-based for authoring by compliance teams without programming.
- Matching is deliberately keyword-based, not an NLP pipeline, to keep every finding explainable: each score traces to quoted sentences with character offsets.

### 2. RAG Engine (`engine/rag.py`, extra: `[rag]`)

The RegulatoryRAG class provides semantic retrieval over regulatory documents.

**Pipeline:**
1. **Ingestion**: reads `.txt`/`.md` files, chunks with `RecursiveCharacterTextSplitter` (500 chars, 80 overlap).
2. **Embedding**: `sentence-transformers/all-MiniLM-L6-v2` locally (no API key needed).
3. **Storage**: ChromaDB persistent vector store; chunk IDs are content hashes, so re-ingestion **upserts instead of duplicating**.
4. **Retrieval**: top-k semantic search returning raw distance plus a normalized relevance score (`1/(1+distance)`).

There is no LLM answer-generation step: the engine returns ranked passages for a human (or the checker) to read.

### 3. Drift Detection Engine (`engine/drift.py`, extra: `[drift]`)

The DriftBridge wraps LegalDrift's statistical detectors and adds structured output.

- Full-document drift detection and section-by-section chunked detection with alignment.
- Configurable p-value threshold (`--threshold`, default 0.05).
- Graceful degradation: without LegalDrift installed, drift commands fail with an install hint; the `check` pipeline skips the step with a warning.

## Compliance Checker (`engine/checker.py`)

Orchestrates the engines for `compliance-agent check`:

1. **Rule evaluation** (always): statuses, severities, and evidence per rule.
2. **Drift baseline** (if `--baseline` given and LegalDrift installed).
3. **Regulatory context** (if `--regulations` given and the RAG extra installed).
4. **Summary panel**: pass counts over applicable rules, failures by severity, overall score, risk level.

## Reporting (`engine/reporting.py`)

`write_report` renders a ComplianceReport as JSON, Markdown, or self-contained HTML. Every report carries a provenance block (timestamp, tool version, report schema version, SHA-256 of the policy and rule pack, threshold) and per-finding quoted evidence with character offsets. See [report-schema.md](report-schema.md).

## CLI Architecture (`cli.py`)

Built with Click. Exit codes: `0` success / all rules passed, `1` findings, `2` usage or input error — so `check` can gate CI pipelines.

```
compliance-agent
├── monitor         → rag.ingest_directory() or rag.query()
├── check           → checker.full_check()          [--format json, --verbose]
├── report          → write_report()                [.json | .md | .html]
├── validate-rules  → reasoner.validate_rules_file() + warnings
├── drift           → drift.detect()                [--threshold]
├── reason          → reasoner.evaluate_scenario()  [--format json]
└── dashboard       → streamlit run dashboard/app.py
```

## Dashboard (`dashboard/app.py`, extra: `[dashboard]`)

Streamlit multi-tab application:

1. **Monitor**: ingest regulations, search with relevance scores and source filtering.
2. **Check Policy**: one-click bundled sample data or uploads; status chips (PASS/WARN/FAIL/N/A) with severity badges and citations; evidence rendered as quoted sentences with matched keywords highlighted; Markdown/JSON report downloads.
3. **Detect Drift**: upload two versions (or use the samples); section-by-section color-coded results.
4. **Reason**: scenario facts + rules; decision headline (ALLOW/ALLOW_WITH_OBLIGATIONS/BLOCK) with confidence.

A sidebar keeps the last 10 checks of the session (time, risk, score).

## Packaging

Core dependencies are `click`, `rich`, `pyyaml` only. Extras: `[rag]`, `[drift]`, `[dashboard]`, `[all]`. This keeps `pip install compliance-agent` free of the ML stack.

## Extension Points

- **Custom embeddings**: pass `model_name` to `RegulatoryRAG`.
- **Rule packs**: any YAML file matching the v2 schema; `validate-rules` checks structure, types, severities, regexes, and duplicate IDs before use.
- **Automation**: `check --format json` plus exit codes for CI; `report -o out.json` for downstream tooling.
