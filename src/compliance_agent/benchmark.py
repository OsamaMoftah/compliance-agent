"""Deterministic synthetic evaluation for rule-pack behavior."""

from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.table import Table

from compliance_agent.engine.reasoner import ComplianceReasoner

console = Console()
_VALID_STATUSES = {"PASS", "WARN", "FAIL", "N/A"}


def load_dataset(path: str) -> dict[str, Any]:
    """Load and validate a versioned benchmark dataset."""
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Benchmark dataset not found: {path}")
    try:
        data = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Benchmark dataset is not valid YAML: {exc}") from exc

    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Benchmark dataset must be a mapping with version: 1.")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark dataset must contain a non-empty cases list.")

    for index, case in enumerate(cases, 1):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            raise ValueError(f"{prefix} must be a mapping.")
        if not isinstance(case.get("id"), str) or not case["id"].strip():
            raise ValueError(f"{prefix}.id must be a non-empty string.")
        if not isinstance(case.get("policy"), str):
            raise ValueError(f"{prefix}.policy must be a string.")
        if not isinstance(case.get("rules"), list) or not case["rules"]:
            raise ValueError(f"{prefix}.rules must be a non-empty list.")
        if not isinstance(case.get("expected"), dict) or not case["expected"]:
            raise ValueError(f"{prefix}.expected must be a non-empty mapping.")
        for rule_id, status in case["expected"].items():
            if not isinstance(rule_id, str) or status not in _VALID_STATUSES:
                raise ValueError(f"{prefix}.expected must map rule IDs to valid statuses.")

    return data


def _metrics(true_positive: int, false_positive: int, false_negative: int, true_negative: int) -> dict[str, float]:
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    false_positive_rate = false_positive / (false_positive + true_negative) if false_positive + true_negative else 0.0
    false_negative_rate = false_negative / (false_negative + true_positive) if false_negative + true_positive else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": false_positive_rate,
        "false_negative_rate": false_negative_rate,
    }


def run_benchmark(path: str) -> dict[str, Any]:
    """Evaluate synthetic cases and return stable machine-readable metrics."""
    dataset = load_dataset(path)
    reasoner = ComplianceReasoner()
    case_results = []
    status_matches = 0
    evidence_matches = 0
    evidence_total = 0
    tp = fp = fn = tn = 0

    for case in dataset["cases"]:
        rules_data = {"schema_version": 2, "rules": case["rules"]}
        rules = reasoner.parse_rules_dict(rules_data)
        report = reasoner.evaluate_policy(case["policy"], rules)
        actual = {result.rule_id: result.status for result in report.results}
        expected = case["expected"]
        case_status_matches = sum(1 for rule_id, status in expected.items() if actual.get(rule_id) == status)
        status_matches += case_status_matches

        for rule_id, expected_status in expected.items():
            actual_status = actual.get(rule_id, "MISSING")
            expected_fail = expected_status == "FAIL"
            actual_fail = actual_status == "FAIL"
            if expected_fail and actual_fail:
                tp += 1
            elif not expected_fail and actual_fail:
                fp += 1
            elif expected_fail and not actual_fail:
                fn += 1
            else:
                tn += 1

        case_evidence_matches = 0
        expected_evidence = case.get("expected_evidence", {})
        for rule_id, terms in expected_evidence.items():
            if not isinstance(terms, list):
                raise ValueError(f"Case {case['id']} expected_evidence for {rule_id} must be a list.")
            result = next((item for item in report.results if item.rule_id == rule_id), None)
            evidence_text = " ".join(
                str(snippet.get("sentence", ""))
                for predicate in (result.predicate_results if result else [])
                for snippet in predicate.get("snippets", [])
            ).lower()
            for term in terms:
                evidence_total += 1
                if str(term).lower() in evidence_text:
                    evidence_matches += 1
                    case_evidence_matches += 1

        case_results.append(
            {
                "id": case["id"],
                "status_matches": case_status_matches,
                "statuses_expected": len(expected),
                "evidence_matches": case_evidence_matches,
                "actual": actual,
            }
        )

    total_statuses = sum(item["statuses_expected"] for item in case_results)
    return {
        "dataset_version": dataset["version"],
        "cases": len(case_results),
        "status_matches": status_matches,
        "status_total": total_statuses,
        "evidence_matches": evidence_matches,
        "evidence_total": evidence_total,
        "metrics": _metrics(tp, fp, fn, tn),
        "case_results": case_results,
    }


def benchmark_to_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# Synthetic Compliance Benchmark",
        "",
        "> Synthetic regression measurements only; these results do not validate legal interpretation.",
        "",
        f"- Cases: {report['cases']}",
        f"- Status matches: {report['status_matches']}/{report['status_total']}",
        f"- Evidence matches: {report['evidence_matches']}/{report['evidence_total']}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {name} | {value:.3f} |" for name, value in metrics.items())
    return "\n".join(lines) + "\n"


def print_benchmark(report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    table = Table(title="Synthetic Compliance Benchmark")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    table.add_row("Cases", str(report["cases"]))
    table.add_row("Status matches", f"{report['status_matches']}/{report['status_total']}")
    table.add_row("Evidence matches", f"{report['evidence_matches']}/{report['evidence_total']}")
    for name, value in metrics.items():
        table.add_row(name, f"{value:.3f}")
    console.print(table)
