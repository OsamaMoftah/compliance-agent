# Compliance Agent Professionalization v1 Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with test-first development and a verification checkpoint after every task.

**Goal:** Turn the audited alpha repository into a more trustworthy, maintainable compliance-screening product while preserving its human-review-only boundary.

**Architecture:** Keep the lightweight keyword reasoner as the deterministic core. Add explicit input validation, clause-local negation, source-aware RAG synchronization, structured pipeline results, and stateful dashboard helpers. Add benchmark and security documentation as separate, reproducible layers rather than embedding claims into the evaluator.

**Tech Stack:** Python 3.10+, Click, PyYAML, Rich, pytest, pytest-cov, Ruff, mypy, ChromaDB/LangChain optional RAG, Streamlit optional dashboard, GitHub Actions.

## Global Constraints

- Do not claim legal advice, legal determinations, certified compliance, or audit-grade accuracy.
- Preserve core installation without ML/dashboard dependencies.
- Use TDD: each behavior change begins with a failing regression test.
- Preserve stdout as valid JSON for machine-readable CLI commands; diagnostics go to stderr.
- Reject non-finite numeric values and out-of-range thresholds/facts.
- Do not silently skip requested pipeline stages; represent partial results explicitly.
- Keep policy and regulatory content local by default and avoid leaking absolute paths in shareable reports.
- Maintain at least 80% coverage and test the RAG extra separately.
- Do not modify `main` directly; work on `feat/professionalization-v1`.

---

### Task 1: Correct clause-local negation

**Files:**
- Modify: `src/compliance_agent/engine/reasoner.py`
- Test: `tests/test_reasoner.py`
- Modify: `docs/architecture.md`, `README.md`

**Interfaces:** Keep `extract_predicate(predicate, text, spans=None) -> dict` stable. Add internal clause-span helpers only.

- [x] Add failing tests for a mixed sentence where a negated occurrence and a positive occurrence coexist, for contrast conjunctions, semicolons, post-match negation, and sentence boundaries.
- [x] Run the focused tests and confirm they fail because the later positive match is incorrectly negated.
- [x] Implement clause segmentation at sentence/contrast boundaries and evaluate negation only within the local clause containing the match.
- [x] Preserve evidence offsets and add a clause-local diagnostic field if useful without breaking the report schema.
- [x] Run the focused and full core reasoner tests.

### Task 2: Harden numeric and rule-pack validation

**Files:**
- Modify: `src/compliance_agent/engine/reasoner.py`, `src/compliance_agent/cli.py`
- Test: `tests/test_reasoner.py`, `tests/test_cli.py`
- Modify: `README.md`, `CONTRIBUTING.md`, `docs/report-schema.md`

**Interfaces:** `ComplianceReasoner(threshold: float = 0.5)` remains compatible but rejects invalid thresholds with `ValueError`; `parse_scenario` rejects values outside `[0, 1]`.

- [x] Add failing tests for thresholds below 0, above 1, NaN, and infinity; predicate weights NaN/infinity; and scenario facts below/above the range.
- [x] Implement finite/range validators shared by constructor, rule validation, and scenario parsing.
- [x] Ensure Click converts invalid values into exit code 2 with a human-readable error.
- [x] Update all documentation to state `0.0 < weight <= 1.0`.
- [x] Run focused validation tests and the core suite.

### Task 3: Make RAG ingestion source-aware and safe

**Files:**
- Modify: `src/compliance_agent/engine/rag.py`
- Test: `tests/test_rag.py`, `tests/test_rag_core.py`
- Modify: `docs/architecture.md`, `README.md`

**Interfaces:** Preserve `RegulatoryRAG.ingest_directory(source_dir, reset=False) -> int`; add source synchronization helpers and deterministic metadata.

- [x] Add failing tests for unchanged re-ingestion, changed content, deleted files, renamed files, duplicate basenames, and safe reset paths.
- [x] Implement stable source IDs independent of absolute paths, source/content metadata, and deletion of old chunks for replaced sources.
- [x] Add a corpus manifest or equivalent metadata to remove indexed sources no longer present.
- [x] Guard reset so it only removes an explicitly configured child persistence directory, never a file, current directory, home directory, or filesystem root.
- [x] Ensure source metadata shown in results is safe and user-friendly.
- [x] Run all RAG tests in an environment with the declared extras installed.

### Task 4: Align CLI JSON and pipeline error semantics

**Files:**
- Modify: `src/compliance_agent/cli.py`, `src/compliance_agent/engine/checker.py`, `src/compliance_agent/engine/drift.py`
- Test: `tests/test_cli.py`, `tests/test_checker.py`
- Modify: `docs/report-schema.md`, `docs/architecture.md`

**Interfaces:** Preserve exit codes 0/1/2. Extend JSON results with explicit `drift`, `rag`, and `warnings` fields; use structured partial-stage results.

- [x] Add failing tests proving JSON mode honors baseline and regulations or rejects unsupported combinations clearly.
- [x] Add failing tests for missing optional dependencies and stage failures, ensuring requested stages are not silently represented as success.
- [x] Implement structured stage results and serialize them in JSON while keeping stdout parseable.
- [x] Send warnings/diagnostics to stderr and keep machine output on stdout.
- [x] Run all CLI and checker tests with `json.loads` assertions.

### Task 5: Persist dashboard state and improve UI boundaries

**Files:**
- Modify: `src/compliance_agent/dashboard/app.py`
- Create: `tests/test_dashboard_helpers.py`
- Modify: `docs/architecture.md`, `README.md`

**Interfaces:** Add pure helpers for search state/filtering so they can be tested without Streamlit.

- [x] Add failing tests for storing query results, filtering by source, clearing stale results, and missing-index handling.
- [x] Implement session-state-backed search results and render filtering outside the Search button branch.
- [x] Ensure dashboard downloads pass policy/rule provenance where paths exist and never expose local absolute paths by default.
- [x] Add clear loading, empty, warning, and partial-result states.
- [x] Run helper tests and a dashboard import smoke test when the dashboard extra is installed.

### Task 6: Add benchmark and evaluation framework

**Files:**
- Create: `benchmarks/README.md`, `benchmarks/synthetic_cases.yaml`, `src/compliance_agent/benchmark.py`, `tests/test_benchmark.py`
- Modify: `src/compliance_agent/cli.py`, `pyproject.toml`, `README.md`

**Interfaces:** Add `compliance-agent benchmark --dataset PATH --output table|json|md`; benchmark output contains per-case results and aggregate precision/recall/F1/false-positive/false-negative metrics.

- [x] Add failing tests for dataset validation, expected statuses, evidence matching, and aggregate metrics.
- [x] Implement a small synthetic, versioned benchmark with compliant, non-compliant, negated, exception, applicability, ambiguous, and adversarial cases.
- [x] Keep benchmark labels explicitly synthetic and avoid legal-validity claims.
- [x] Add benchmark execution to developer commands and document interpretation.
- [x] Run benchmark tests and generate a checked-in baseline report only if deterministic.

### Task 7: Add security, packaging, and CI professionalism

**Files:**
- Modify: `.github/workflows/ci.yml`, `pyproject.toml`, `.gitignore`
- Create: `.github/dependabot.yml`, `.github/CODEOWNERS`, `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/feature_request.yml`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `Makefile`
- Modify: `README.md`, `CONTRIBUTING.md`

**Interfaces:** No runtime API changes beyond prior tasks.

- [x] Add tests or smoke commands for wheel build/install and each optional extra import profile.
- [x] Add CI jobs for core matrix, full RAG, package build, benchmark, and security/static checks without weakening existing gates.
- [x] Add dependency automation and immutable action references where practical.
- [x] Document dashboard exposure risks, local vector-store sensitivity, upload limits, and responsible disclosure.
- [x] Add developer commands: `make test`, `make test-full`, `make lint`, `make typecheck`, `make benchmark`, `make build`, `make verify`.
- [x] Report GitHub branch protection as an external settings gate if it cannot be changed through available permissions.

### Task 8: Final verification and review

**Files:**
- Modify only files required by prior tasks.

- [x] Run core tests on the available local interpreter and full tests with RAG extras.
- [x] Run Ruff, mypy, coverage, benchmark, package build, and CLI smoke tests from the built wheel.
- [x] Scan tracked files for secrets and unsafe path handling.
- [x] Run CodeRabbit on the complete feature diff and resolve all critical/warning findings.
- [x] Verify Git status and exact commit/remote branch state before handoff; hosted CI remains a post-push external gate.
- [x] Produce a final handoff separating implemented, locally verified, CI-verified, externally blocked, and unverified items.
