# Contributing to Compliance Agent

## Development Setup

```bash
git clone https://github.com/OsamaMoftah/compliance-agent.git
cd compliance-agent
pip install -e ".[dev]"       # core + lint/type/test tooling
pip install -e ".[all,dev]"   # add this to also work on RAG/drift/dashboard code
pre-commit install
```

The core install (`dev` only) is enough for `reasoner.py`, `reporting.py`, and `cli.py` work.
RAG tests (`tests/test_rag.py`) auto-skip without the `[rag]` extra; drift tests use a stubbed
`legaldrift` module (`tests/conftest.py`) so they run without the real package.

## Running Tests

```bash
pytest
pytest --cov=src/compliance_agent --cov-report=term
```

## Code Style

- `ruff` for linting (line length 130, see `pyproject.toml`)
- `mypy` for type checking

Run before committing:

```bash
ruff check src/ tests/
mypy src/
```

## Project Structure

```
src/compliance_agent/
├── __init__.py
├── cli.py              # Click CLI
├── engine/             # Core engines
│   ├── rag.py          # Regulatory RAG (ingest, query)
│   ├── drift.py        # LegalDrift bridge
│   ├── reasoner.py     # DDL rule reasoning
│   └── checker.py      # Compliance orchestrator
└── dashboard/          # Streamlit UI
    └── app.py

tests/                  # pytest test suite

sample_data/            # Bundled example data
├── regulations/        # Sample regulatory texts
├── policies/           # Sample policy documents
└── rules/              # Sample YAML rule files
```

## Adding New Rules

Rules are defined in YAML (schema v2 — see [README.md](README.md#rules-format-yaml-schema-v2)
and [docs/architecture.md](docs/architecture.md) for the full semantics):

```yaml
schema_version: 2
rules:
  - id: "MY-RULE-001"
    type: "obligation"       # obligation | permission | prohibition
    severity: "major"        # critical | major | minor
    citation: "Reg. Art. X"  # optional, shown in reports
    description: "What this rule checks"
    predicates:
      - name: "predicate_name"
        keywords: ["exact phrase to search for", "an alternative phrasing"]
        weight: 1.0           # 0.0 to 1.0
```

Always run `compliance-agent validate-rules -r your_rules.yaml` before opening a PR that adds
or edits a rule pack — it checks structure, types, severities, regex validity, duplicate IDs,
and flags legacy `condition:` predicates that should be migrated to explicit `keywords`.

## Adding New Regulatory Documents

Place `.txt` or `.md` files in a directory, then ingest them:

```bash
compliance-agent monitor --source ./my-regulations/
```
