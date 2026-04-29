# Contributing to Compliance Agent

## Development Setup

```bash
git clone https://github.com/OsamaMoftah/compliance-agent.git
cd compliance-agent
pip install -e ".[dev]"
pre-commit install
```

## Running Tests

```bash
pytest
pytest --cov=src/compliance_agent
```

## Code Style

- Black with line length 100
- isort with Black profile
- ruff for linting

Run before committing:

```bash
black src/ tests/
isort src/ tests/
ruff check src/ tests/
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

Rules are defined in YAML:

```yaml
rules:
  - id: "MY-RULE-001"
    type: "obligation"       # obligation | permission | prohibition
    description: "What this rule checks"
    predicates:
      - name: "predicate_name"
        condition: "text to search for in the policy"
        weight: 1.0           # 0.0 to 1.0
```

## Adding New Regulatory Documents

Place `.txt` or `.md` files in a directory, then ingest them:

```bash
compliance-agent monitor --source ./my-regulations/
```
