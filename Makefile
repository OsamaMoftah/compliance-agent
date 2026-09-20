.PHONY: test test-full lint typecheck benchmark build verify

test:
	pytest --cov=src/compliance_agent --cov-report=term --cov-fail-under=80

test-full:
	pytest --cov=src/compliance_agent --cov-report=term --cov-fail-under=80

lint:
	ruff check src/ tests/

typecheck:
	mypy src/

benchmark:
	compliance-agent benchmark --dataset benchmarks/synthetic_cases.yaml --output table

build:
	python -m build

verify: lint typecheck test benchmark build
