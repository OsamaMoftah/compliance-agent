# Compliance Agent

[![CI](https://github.com/OsamaMoftah/compliance-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/OsamaMoftah/compliance-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**Open-source compliance copilot for screening policies against regulatory obligations, detecting policy drift, and producing explainable review signals for human experts.**

Compliance Agent is a practical screening layer for legal-tech and compliance teams. It helps reviewers find likely gaps, risky policy changes, and supporting regulatory context before a human expert makes the final call.

| Component | What it does | Powered by |
|-----------|-------------|------------|
| Rule Screening | Evaluates explainable YAML rules with severities, citations, applicability gates, and exceptions | Built-in lightweight DDL-style reasoner |
| Regulatory Retrieval | Ingests and queries regulations (GDPR, EU AI Act examples included) | LangChain + ChromaDB (`[rag]` extra) |
| Drift Detection | Detects meaningful changes between policy versions | [LegalDrift](https://github.com/OsamaMoftah/LegalDrift) (`[drift]` extra) |

> **This is not legal advice and is not a replacement for legal review.** Compliance Agent produces review signals, evidence snippets, and risk indicators for qualified humans to evaluate.

---

## Install

```bash
pip install compliance-agent            # lightweight core: rule screening + reports
pip install 'compliance-agent[rag]'     # + regulatory retrieval (ChromaDB, sentence-transformers)
pip install 'compliance-agent[drift]'   # + policy drift detection (LegalDrift)
pip install 'compliance-agent[dashboard]'  # + Streamlit dashboard
pip install 'compliance-agent[all]'     # everything
```

## Quick Start

### 1. Check a policy against rules

```bash
compliance-agent check \
  --policy sample_data/policies/privacy_v1.txt \
  --rules sample_data/rules/gdpr_rules.yaml
```

Exit codes make this CI-friendly: `0` = all applicable rules passed, `1` = findings, `2` = input error. Add `--format json` for machine-readable output and `--verbose` for full per-rule traces.

### 2. Validate a rule pack

```bash
compliance-agent validate-rules --rules sample_data/rules/gdpr_rules.yaml
```

### 3. Generate a review report

```bash
compliance-agent report \
  --policy sample_data/policies/privacy_v1.txt \
  --rules sample_data/rules/gdpr_rules.yaml \
  --output compliance-report.md
```

Reports can be written as Markdown (`.md`) for human review, JSON (`.json`) for automation, or self-contained HTML (`.html`) for sharing. Every report carries an audit provenance block: timestamp, tool version, and SHA-256 hashes of the policy and rule pack. See [docs/report-schema.md](docs/report-schema.md).

### 4. Ingest and query regulations (requires `[rag]`)

```bash
compliance-agent monitor --source ./sample_data/regulations/
compliance-agent monitor --source ./sample_data/regulations/ --query "human oversight"
```

### 5. Detect drift between policy versions (requires `[drift]`)

```bash
compliance-agent drift \
  sample_data/policies/privacy_v1.txt \
  sample_data/policies/privacy_v2.txt
```

### 6. Reason about a scenario

```bash
compliance-agent reason \
  --scenario sample_data/rules/scenario_gdpr_check.yaml \
  --rules sample_data/rules/gdpr_rules.yaml
```

Scenario reasoning resolves obligations, permissions, and prohibitions into a decision: `ALLOW`, `ALLOW_WITH_OBLIGATIONS`, or `BLOCK`.

### 7. Launch the dashboard (requires `[dashboard]`)

```bash
compliance-agent dashboard
```

Every tab has a one-click "use bundled sample data" toggle, and check results can be downloaded as Markdown/JSON reports.

---

## Architecture

```
  Ingest Regulations ──→ [ RAG Engine ] ──→ Relevant context
                                                 ↓
  Policy v1 vs v2 ────→ [ LegalDrift ] ──→ Drift detected
                                                 ↓
  Rules (YAML) ───────→ [ Reasoner ] ─────→ Review signal
                                                 ↓
                                         [ Dashboard / Report ]
```

For detailed architecture, see [docs/architecture.md](docs/architecture.md).

---

## CLI Reference

### `compliance-agent check`

```bash
compliance-agent check --policy <file> --rules <file> \
  [--regulations <dir>] [--baseline <file>] [--threshold 0.5] \
  [--format table|json] [--verbose]
```

### `compliance-agent report`

```bash
compliance-agent report --policy <file> --rules <file> --output report.{md|json|html}
```

### `compliance-agent validate-rules`

```bash
compliance-agent validate-rules --rules <file>
```

### `compliance-agent drift`

```bash
compliance-agent drift <baseline> <current> [--chunk] [--threshold 0.05] [--output json|table]
```

### `compliance-agent reason`

```bash
compliance-agent reason --scenario <file> --rules <file> [--threshold 0.5] [--format table|json]
```

### `compliance-agent monitor`

```bash
compliance-agent monitor --source <dir> [--query "question?"] [--reset]
```

### `compliance-agent dashboard`

```bash
compliance-agent dashboard [--port 8501]
```

---

## Rules Format (YAML, schema v2)

```yaml
schema_version: 2
rules:
  - id: "GDPR-SHARING-001"
    type: "prohibition"              # obligation | permission | prohibition
    severity: "critical"             # critical | major | minor (default: major)
    citation: "GDPR Art. 28"         # shown in reports
    description: "Data must not be shared with third parties without a DPA"
    applies_when:                    # optional: rule is N/A unless this matches
      - name: "shares_with_third_parties"
        keywords: ["third party", "third parties"]
    predicates:                      # for prohibitions: the violation trigger
      - name: "shares_with_third_parties"
        keywords: ["shared with third", "sell data"]
        weight: 1.0
    unless:                          # prohibition exceptions ("unless mitigated")
      - name: "has_dpa"
        keywords: ["data processing agreement"]
```

Semantics:

- `obligation`: required evidence should be present.
- `permission`: enabling evidence should be present.
- `prohibition`: forbidden evidence should be absent — **unless** an `unless` exception is evidenced (`violation = trigger AND NOT exception`).
- `applies_when`: rules gate to **N/A** (excluded from score and risk) when no applicability keyword matches. Negated mentions ("we do not transfer data outside the EU") do not activate the gate.
- Keywords are matched case-insensitively on word boundaries, and negation is detected within the matching sentence (before and after the keyword).
- Statuses: `PASS`, `WARN` (within 0.1 above the threshold — passes, flagged for review), `FAIL`, `N/A`.

**Migrating from v1:** prose `condition:` strings still work (keywords are inferred) but are deprecated — `validate-rules` prints a warning per legacy predicate. Move each condition's key phrases into an explicit `keywords:` list.

Run `validate-rules` before publishing a rule pack. The validator checks missing fields, unknown types/severities/match modes, duplicate IDs, invalid regexes, misplaced `unless` blocks, and invalid weights.

---

## Roadmap

- **v0.3:** LLM-assisted predicate evaluation (verdict + quoted evidence + confidence) with the keyword engine as offline fallback; citation-first retrieval with jurisdiction filters.
- **v0.4:** PDF/DOCX ingestion, community rule packs for GDPR and EU AI Act, GitHub Action integration.
- **v0.5:** dashboard review workflow with finding states, persistent history, benchmark policies with published precision/recall.
- **v1.0:** stable rule schema, tested community rule packs, contributor governance, audit-ready reporting.

---

## Ecosystem

Compliance Agent is designed to interoperate with:

- **[LegalDrift](https://github.com/OsamaMoftah/LegalDrift)** — Semantic drift detection for legal documents. Published on PyPI.
- **[DiffDDL](https://github.com/OsamaMoftah/DiffDDL)** — Differentiable deontic logic for future advanced compliance automation.

---

## Limitations

- **Not a legal opinion.** This tool screens for risk — it does not make legal determinations.
- **Keyword-based matching.** Explainable by design, but it cannot judge nuanced language; WARN/FAIL findings need human review, and PASS findings deserve spot checks.
- **English-only.** Negation patterns and keyword matching are English-centric.
- **Plain text only.** Documents must be extracted from PDF/Word before ingestion.
- **Requires well-formed rules.** Start with the bundled examples and run `validate-rules`.

---

## License

MIT License. See [LICENSE](LICENSE).

Compliance Agent is provided as-is, without warranty. Always consult a qualified legal professional.
