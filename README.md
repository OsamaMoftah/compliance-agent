# Compliance Agent

[![CI](https://github.com/OsamaMoftah/compliance-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/OsamaMoftah/compliance-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**End-to-end compliance monitoring agent bridging regulatory intelligence, semantic drift detection, and differentiable rule reasoning.**

Compliance Agent ties together three purpose-built open-source tools into a single operational pipeline:

| Component | What it does | Powered by |
|-----------|-------------|------------|
| Regulatory RAG | Ingests and queries regulations (GDPR, EU AI Act) | LangChain + ChromaDB |
| Drift Detection | Detects meaningful changes between policy versions | [LegalDrift](https://github.com/OsamaMoftah/LegalDrift) |
| Rule Reasoning | Encodes compliance rules as trainable deontic logic | [DiffDDL](https://github.com/OsamaMoftah/DiffDDL) |

> **This is not a replacement for legal review.** A screening layer that flags risks before they reach a lawyer.

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

### 3. Detect drift between policy versions

```bash
compliance-agent drift \
  sample_data/policies/privacy_v1.txt \
  sample_data/policies/privacy_v2.txt
```

### 4. Reason about a scenario

```bash
compliance-agent reason \
  --scenario sample_data/rules/scenario_gdpr_check.yaml \
  --rules sample_data/rules/gdpr_rules.yaml
```

### 5. Launch the dashboard

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
  Rules (YAML) ───────→ [ DiffDDL ] ──────→ Compliance gap
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

---

## Ecosystem

Compliance Agent is the flagship integration of:

- **[LegalDrift](https://github.com/OsamaMoftah/LegalDrift)** — Semantic drift detection for legal documents. Published on PyPI.
- **[DiffDDL](https://github.com/OsamaMoftah/DiffDDL)** — Differentiable deontic logic for compliance automation.

---

## Limitations

- **Not a legal opinion.** This tool screens for risk — it does not make legal determinations.
- **English-only.** Embedding models and regex extractors are English-centric.
- **Plain text only.** Documents must be extracted from PDF/Word before ingestion.
- **Requires well-formed rules.** Start with the bundled examples.

---

## License

MIT License. See [LICENSE](LICENSE).

Compliance Agent is provided as-is, without warranty. Always consult a qualified legal professional.
