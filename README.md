# Compliance Agent

[![CI](https://github.com/OsamaMoftah/compliance-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/OsamaMoftah/compliance-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**Open-source compliance copilot for screening policies against regulatory obligations, detecting policy drift, and producing explainable review signals for human experts.**

Compliance Agent is a practical screening layer for legal-tech and compliance teams. It helps reviewers find likely gaps, risky policy changes, and supporting regulatory context before a human expert makes the final call.

| Component | What it does | Powered by |
|-----------|-------------|------------|
| Regulatory Retrieval | Ingests and queries regulations (GDPR, EU AI Act examples included) | LangChain + ChromaDB |
| Drift Detection | Detects meaningful changes between policy versions | [LegalDrift](https://github.com/OsamaMoftah/LegalDrift) |
| Rule Screening | Evaluates explainable YAML rules for obligations, permissions, and prohibitions | Built-in lightweight DDL-style reasoner |

> **This is not legal advice and is not a replacement for legal review.** Compliance Agent produces review signals, evidence snippets, and risk indicators for qualified humans to evaluate.

---

## Quick Start

```bash
pip install compliance-agent
```

### 1. Ingest regulatory documents

```bash
compliance-agent monitor --source ./sample_data/regulations/
```

### 2. Check a policy against rules

```bash
compliance-agent check \
  --policy sample_data/policies/privacy_v1.txt \
  --rules sample_data/rules/gdpr_rules.yaml
```

### 3. Validate a rule pack

```bash
compliance-agent validate-rules \
  --rules sample_data/rules/gdpr_rules.yaml
```

### 4. Generate a review report

```bash
compliance-agent report \
  --policy sample_data/policies/privacy_v1.txt \
  --rules sample_data/rules/gdpr_rules.yaml \
  --output compliance-report.md
```

Reports can be written as Markdown (`.md`) for human review or JSON (`.json`) for automation.

### 5. Detect drift between policy versions

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

### 7. Launch the dashboard

```bash
compliance-agent dashboard
```

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

### `compliance-agent monitor`

```bash
compliance-agent monitor --source <dir> [--query "question?"] [--reset]
```

### `compliance-agent check`

```bash
compliance-agent check --policy <file> --rules <file> [--regulations <dir>]
```

### `compliance-agent validate-rules`

```bash
compliance-agent validate-rules --rules <file>
```

### `compliance-agent report`

```bash
compliance-agent report --policy <file> --rules <file> --output report.md
compliance-agent report --policy <file> --rules <file> --output report.json
```

### `compliance-agent drift`

```bash
compliance-agent drift <baseline> <current> [--chunk] [--output json|table]
```

### `compliance-agent reason`

```bash
compliance-agent reason --scenario <file> --rules <file> [--threshold 0.5]
```

### `compliance-agent dashboard`

```bash
compliance-agent dashboard [--port 8501]
```

---

## Rules Format (YAML)

```yaml
rules:
  - id: "GDPR-CONSENT-001"
    type: "obligation"
    description: "Consent must be obtained before processing personal data"
    predicates:
      - name: "has_consent"
        condition: "document contains explicit consent language"
        weight: 1.0
```

Rule types have explicit screening semantics:

- `obligation`: required evidence should be present.
- `permission`: enabling evidence should be present.
- `prohibition`: forbidden evidence should be absent.

Run `validate-rules` before publishing a rule pack. The validator checks for missing fields, unknown rule types, duplicate IDs, empty predicates, and invalid weights.

---

## Roadmap

- **v0.2:** stronger rule validation, clearer rule semantics, JSON/Markdown reports, better evidence snippets.
- **v0.3:** citation-first regulatory retrieval, jurisdiction/framework filters, improved drift risk labels.
- **v0.4:** community rule packs for GDPR and EU AI Act, benchmark policies, GitHub Action integration.
- **v0.5:** dashboard review workflow with finding states, historical checks, and downloadable reports.
- **v1.0:** stable rule schema, tested community rule packs, contributor governance, and reliable audit-ready reporting.

---

## Ecosystem

Compliance Agent is designed to interoperate with:

- **[LegalDrift](https://github.com/OsamaMoftah/LegalDrift)** — Semantic drift detection for legal documents. Published on PyPI.
- **[DiffDDL](https://github.com/OsamaMoftah/DiffDDL)** — Differentiable deontic logic for future advanced compliance automation.

---

## Limitations

- **Not a legal opinion.** This tool screens for risk — it does not make legal determinations.
- **English-only.** Embedding models and regex extractors are English-centric.
- **Plain text only.** Documents must be extracted from PDF/Word before ingestion.
- **Requires well-formed rules.** Start with the bundled examples.
- **Screening semantics are conservative.** Human reviewers must confirm findings, especially where policy language is ambiguous.

---

## License

MIT License. See [LICENSE](LICENSE).

Compliance Agent is provided as-is, without warranty. Always consult a qualified legal professional.
