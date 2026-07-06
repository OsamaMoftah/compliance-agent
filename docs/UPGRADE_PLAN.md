# Upgrade Plan: Logic, UI, and Output (v0.1 → v0.2 "AAA track")

This plan addresses the defects confirmed in the code review (2026-07-06) and upgrades the
reasoning engine, the CLI/dashboard UX, and the report output. It is ordered so every phase
leaves the app shippable, and the golden test in Phase 1 locks in the headline fix: the
bundled demo policy must stop scoring HIGH risk.

Verified defects this plan fixes:

| # | Defect | Evidence |
|---|--------|----------|
| D1 | Keyword inference drops terms (`"SCCs, BCRs, or adequacy decision"` → `['sccs']`) and extracts generic words (`"data"` alone satisfies the retention predicate) | reasoner.py:221 `_parse_condition_keywords` |
| D2 | Any single keyword hit saturates predicate score to 1.0 | reasoner.py:177 `min(1.0, sum(counts))` |
| D3 | Prohibition rules cannot express mitigation; a policy sharing data WITH a DPA scores identically (0.30 FAIL) to one without | reasoner.py:464 + `GDPR-SHARING-001` |
| D4 | Negation window crosses sentence boundaries ("There is no fee. We sell data" → "sell data" treated as negated) | reasoner.py:204 `_is_negated` |
| D5 | No applicability concept: AI Act rules FAIL (strength 0.0) on a policy that doesn't use AI, dragging the compliant demo policy to HIGH risk | schema + `_determine_risk_level` |
| D6 | Aggregation inconsistent between paths: same rule scores 0.5 via `evaluate_policy` (divides by count) and 1.0 via `evaluate_scenario` (divides by weight sum) | reasoner.py:459 vs 437 |
| D7 | CLI/dashboard crash with tracebacks on missing files, malformed scenario YAML, invalid rules | cli.py:88,140; app.py:67,164 |
| D8 | RAG re-ingestion duplicates chunks in shared `.chroma`; distance shown as unlabeled "Score" | rag.py:45,98; checker.py:89 |
| D9 | Report output lacks timestamps, tool/rule-pack versions, statuses beyond PASS/FAIL | reporting.py |
| D10 | Dead DDL code (`soft_and/or/implies`, `resolve`, `conflict_score` never called); "typecheck" CI job runs ruff | reasoner.py:83; ci.yml |

---

## Phase 1 — Reasoning engine correctness (`engine/reasoner.py`)

### 1.1 Rule schema v2

New optional fields, fully backward compatible with v1 (v1 `condition` prose still accepted,
parsed by the existing keyword inference, but validation emits a deprecation warning).

```yaml
schema_version: 2
rules:
  - id: "GDPR-SHARING-001"
    type: "prohibition"
    severity: "major"            # critical | major | minor (default major)
    citation: "GDPR Art. 28"     # free text, shown in reports
    description: "Data must not be shared without a DPA"
    applies_when:                # rule is N/A unless these match (optional)
      - keywords: ["third party", "third parties", "share data", "sharing"]
    predicates:                  # for prohibition: the *violation trigger*
      - name: "shares_with_third_parties"
        keywords: ["share data", "sharing data", "sell data", "disclose data"]
        weight: 1.0
    unless:                      # exception/mitigation predicates (prohibition only)
      - name: "has_dpa"
        keywords: ["data processing agreement", "data processing agreements", "DPA"]
```

Key points:
- `keywords` (exact phrases, case-insensitive) and optional `patterns` (regex) replace prose
  `condition` inference. Explicit lists fix D1.
- `applies_when` gate → `status: N/A` when unmatched; N/A rules are excluded from the overall
  score and risk level. Fixes D5.
- `unless` block for prohibitions implements "prohibited unless mitigated" using the existing
  DDL soft ops: `violation = soft_and(trigger, soft_not(exception))`,
  `strength = soft_not(violation)`. Fixes D3 and finally uses the DDL for real (D10).
- `severity` feeds risk scoring (1.4) and report grouping (Phase 4).

Implementation:
- Extend `Predicate` (add `keywords: list[str]`, `patterns: list[str]`) and `ComplianceRule`
  (add `severity`, `citation`, `applies_when: list[Predicate]`, `unless: list[Predicate]`).
- Extend `validate_rules_dict`: validate new fields, require `keywords`/`patterns`/`condition`
  (at least one), reject `unless` on non-prohibition rules, warn on v1 prose conditions.
- Migrate `sample_data/rules/gdpr_rules.yaml` to schema v2 with correct keyword lists and
  `applies_when` gates on the AI Act rules.

### 1.2 Matching engine rewrite (`extract_predicate`)

- **Sentence segmentation**: split text on sentence boundaries (regex on `.!?` + newline
  handling — no NLP dependency). Negation is evaluated *within the matched sentence only*,
  and both before the keyword (`do not`, `never`, `without`) and after it in copular forms
  (`X is prohibited`, `X is not permitted`). Fixes D4.
- **Graded scoring**: replace the saturating count with
  `coverage = matched_keywords / total_keywords` blended with diminishing-returns occurrence
  credit: `score = coverage * (1 - 0.5 ** occurrences_of_best_keyword)` is too clever — use
  simply `score = coverage`, occurrences reported as evidence only. One generic keyword out
  of four no longer yields 1.0. Fixes D2.
- Keep the returned dict shape (`name/matched/score/evidence/snippets`) so reporting keeps
  working; add `sentence` to each snippet for better evidence display.

### 1.3 Unified aggregation

Single helper used by both `_evaluate_rule` and `_evaluate_rule_with_facts`:
`aggregate(values, weights) = Σ(v·w) / Σ(w)`. Fixes D6. Property test asserts both paths
produce the same strength for equivalent inputs.

### 1.4 Statuses and risk model

- `RuleResult.status`: `PASS | FAIL | WARN | N/A` (WARN = within ±0.1 of threshold; keeps the
  boolean `passed` for backward compat).
- `overall_score`: severity-weighted mean of strengths over applicable rules only
  (critical=3, major=2, minor=1).
- `risk_level`: `HIGH` if any critical FAIL or >30% applicable rules FAIL; `MEDIUM` if any
  FAIL/WARN; `LOW` otherwise. `_determine_risk_level` actually uses its inputs now.
- `evaluate_scenario` additionally runs `DDL.resolve()` across the obligation/permission/
  prohibition strengths and emits a `decision: ALLOW | ALLOW_WITH_OBLIGATIONS | BLOCK` on the
  report (D10 — wires in the dead conflict-resolution code).

### 1.5 Golden test (locks the fix in)

`tests/test_golden_sample.py`: run `sample_data/policies/privacy_v1.txt` against the migrated
`gdpr_rules.yaml`; assert risk == LOW, AI Act rules == N/A, GDPR-SHARING-001 == PASS (DPA
present). Add regression tests for D1–D6 mirroring the review reproductions.

---

## Phase 2 — Robustness (CLI, RAG, packaging)

### 2.1 CLI hardening (`cli.py`)

- Wrap every command in consistent error handling: missing files, YAML parse errors, and
  `RuleValidationError` produce one-line red messages, never tracebacks (D7).
- Exit codes: `0` = check passed, `1` = findings (FAIL rules), `2` = usage/input error —
  makes `check` usable in CI pipelines.
- Validate scenario file shape (must be mapping; `facts` list entries must have `predicate`)
  with a helpful message; share one `load_scenario_facts()` helper with the dashboard
  (currently duplicated logic).
- `--format json` option on `check` and `reason` for machine-readable output.
- Read version once from `importlib.metadata` (drop the three hardcoded copies).

### 2.2 RAG fixes (`engine/rag.py`)

- Idempotent ingestion: hash each chunk (source path + content) into the Chroma document ID so
  re-ingesting is a no-op instead of duplicating (D8); `full_check` no longer degrades the
  index on every run.
- Migrate deprecated imports → `langchain-huggingface` (`HuggingFaceEmbeddings`) and
  `langchain-chroma` (`Chroma`); stop touching the private `_collection` (use
  `get()` on the public API).
- Convert distance → similarity (`1 / (1 + distance)`) and label it "relevance" in CLI table
  and dashboard.

### 2.3 Packaging (`pyproject.toml`)

- Core deps: `click`, `rich`, `pyyaml` only. Extras: `[rag]` (chromadb, langchain-*,
  sentence-transformers), `[drift]` (legaldrift), `[dashboard]` (streamlit), `[all]`.
- Delete unused deps: `langchain`, `langchain-openai`, `pydantic`, `pandas`, `plotly`,
  `python-dotenv`.
- `requires-python = ">=3.10"` (matches classifiers/ruff/black).
- CLI `monitor`/`drift`/`dashboard` print an install hint naming the right extra when the
  import fails.

---

## Phase 3 — UI upgrade (`dashboard/app.py` + CLI output)

### 3.1 Dashboard

- **Quick-start**: "Use bundled sample data" button on every tab so the first-run experience
  is one click (loads `sample_data/…`), alongside the existing uploaders.
- **Check tab**:
  - Status chips: ✅ PASS / ❌ FAIL / ⚠️ WARN / ➖ N/A, severity badge, and citation per rule.
  - Evidence rendered as quoted sentences with the matched keyword **bolded** (uses the new
    `sentence` field from 1.2), instead of a truncated explanation string.
  - Findings sorted FAIL-critical first; N/A collapsed into a footer expander.
  - `st.download_button` for the Markdown and JSON report (calls `write_report` renderers) —
    the dashboard finally produces the same artifact as the CLI.
  - All engine errors (`RuleValidationError`, bad YAML) caught → `st.error` with the
    validation list, no stack traces (D7).
- **Drift tab**: temp-file cleanup in `finally`; severity color scale legend.
- **Reason tab**: show the new `DDL.resolve()` decision (ALLOW / ALLOW_WITH_OBLIGATIONS /
  BLOCK) as the headline metric with confidence; facts table instead of markdown list.
- **Monitor tab**: relevance (not raw distance), source filter dropdown, and an "index
  contents" caption (chunk count per source).
- Session-state history: last 10 checks in a sidebar with timestamp + risk level, re-viewable
  without re-running (groundwork for the v0.5 review workflow).

### 3.2 CLI output

- `print_report`: add Status column (PASS/FAIL/WARN/N/A with colors), severity, citation;
  move the long explanation to an optional `--verbose` detail block; summary panel shows
  severity breakdown ("1 critical failure, 2 major warnings") instead of raw counts.
- `check` summary panel colors by the new risk model.

---

## Phase 4 — Output/report upgrade (`engine/reporting.py`)

- **Provenance block** (audit-grade, D9): ISO-8601 timestamp, tool version, rule-pack SHA-256,
  policy file SHA-256, threshold, schema version — in both JSON and Markdown.
- **Markdown layout**: executive summary (risk, decision, severity breakdown) → findings
  grouped by severity (critical first) → each finding shows citation, quoted evidence
  sentences with character offsets, and recommended action → N/A rules listed in an appendix
  with the unmatched `applies_when` gate shown.
- **JSON schema v2**: add `status`, `severity`, `citation`, `applicable`, `evidence[]`
  (sentence, offsets, negated), `provenance{}`. Document the schema in
  `docs/report-schema.md`. Keep existing keys so current consumers don't break.
- **HTML export** (`.html`): self-contained single file rendered from the same dict (simple
  template, no new deps) — what compliance teams actually attach to review tickets.

---

## Phase 5 — Tests, CI, docs

- `tests/test_cli.py` with `click.testing.CliRunner`: every command's happy path + every
  error path added in 2.1 (asserting exit codes 0/1/2).
- `tests/test_drift.py` with a stubbed `legaldrift` module (unit-level, no ML download).
- Negation/applicability/exception/aggregation-parity unit tests (Phase 1 regressions).
- CI: rename "typecheck" job to lint, add a real `mypy src/` job (start permissive:
  `--ignore-missing-imports`), add `--cov-fail-under=85`, pip caching, and run the default
  matrix with core-only deps + one job with `[all]` extras for RAG tests.
- Rewrite `docs/architecture.md` to match reality (remove claims of LLM answer generation,
  SQLite history, streaming mode); document rule schema v2 in README with a v1→v2 migration
  note.

---

## Sequencing and acceptance criteria

| Phase | Depends on | Done when |
|-------|-----------|-----------|
| 1 Logic | — | Golden test green: sample policy = LOW risk, AI Act rules N/A, DPA mitigation works; D1–D6 regression tests pass |
| 2 Robustness | 1 | No command can emit a traceback for bad input; `pip install .` pulls no ML deps; re-running `check --regulations` twice yields identical index size |
| 3 UI | 1, 2 | One-click sample-data demo works end-to-end; reports downloadable from dashboard; no stack traces in UI |
| 4 Output | 1 | Reports carry provenance + statuses + citations; JSON schema documented; HTML export renders |
| 5 Tests/CI | 1–4 | mypy job green, coverage ≥85%, CLI/drift suites green on 3.10–3.12 |

Out of scope for this pass (next milestone, per review Tier 3): LLM-assisted predicate
evaluation with quoted-evidence verdicts, hybrid BM25+embedding retrieval with article-level
citations, PDF/DOCX ingestion, GitHub Action, and the persistent review workflow.
