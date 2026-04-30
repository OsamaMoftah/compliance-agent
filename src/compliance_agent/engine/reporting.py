"""Export compliance reports for review workflows and automation."""

import json
from pathlib import Path
from typing import Any, Optional

from compliance_agent.engine.reasoner import ComplianceReport


def report_to_dict(report: ComplianceReport, metadata: Optional[dict[str, Any]] = None) -> dict:
    """Convert a ComplianceReport into stable JSON-friendly data."""
    return {
        "metadata": metadata or {},
        "summary": {
            "overall_score": report.overall_score,
            "risk_level": report.risk_level,
            "passed": report.passed_count,
            "failed": report.failed_count,
            "total": report.total_count,
            "text": report.summary,
        },
        "results": [
            {
                "rule_id": result.rule_id,
                "rule_type": result.rule_type,
                "description": result.description,
                "status": "PASS" if result.passed else "FAIL",
                "passed": result.passed,
                "strength": result.strength,
                "explanation": result.explanation,
                "predicates": result.predicate_results,
                "matched_predicates": result.predicates_matched,
                "recommended_action": _recommended_action(result.passed, result.rule_type),
            }
            for result in report.results
        ],
    }


def report_to_markdown(report: ComplianceReport, metadata: Optional[dict[str, Any]] = None) -> str:
    """Render a ComplianceReport as Markdown for human review."""
    data = report_to_dict(report, metadata)
    meta = data["metadata"]
    summary = data["summary"]
    lines = [
        "# Compliance Review Report",
        "",
    ]
    if meta:
        lines.extend(
            [
                f"- **Policy:** {meta.get('policy', 'unknown')}",
                f"- **Rules:** {meta.get('rules', 'unknown')}",
                f"- **Threshold:** {meta.get('threshold', 'unknown')}",
                "",
            ]
        )

    lines.extend(
        [
            "## Summary",
            "",
            f"- **Risk level:** {summary['risk_level']}",
            f"- **Overall score:** {summary['overall_score']:.2f}",
            f"- **Rules passed:** {summary['passed']}/{summary['total']}",
            f"- **Review summary:** {summary['text']}",
            "",
            "## Findings",
            "",
        ]
    )

    for result in data["results"]:
        lines.extend(
            [
                f"### {result['status']}: {result['rule_id']}",
                "",
                f"- **Type:** {result['rule_type']}",
                f"- **Description:** {result['description']}",
                f"- **Strength:** {result['strength']:.2f}",
                f"- **Recommended action:** {result['recommended_action']}",
                "",
            ]
        )
        predicate_lines = _format_predicates(result["predicates"])
        if predicate_lines:
            lines.extend(["**Evidence**", "", *predicate_lines, ""])
        lines.extend([result["explanation"], ""])

    return "\n".join(lines).rstrip() + "\n"


def write_report(report: ComplianceReport, output_path: str, metadata: Optional[dict[str, Any]] = None) -> Path:
    """Write a compliance report as .json or .md based on the output extension."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()

    if suffix == ".json":
        path.write_text(json.dumps(report_to_dict(report, metadata), indent=2), encoding="utf-8")
    elif suffix in {".md", ".markdown"}:
        path.write_text(report_to_markdown(report, metadata), encoding="utf-8")
    else:
        raise ValueError("Report output must end with .json, .md, or .markdown")

    return path


def _recommended_action(passed: bool, rule_type: str) -> str:
    if passed:
        return "No immediate action. Human reviewer should confirm evidence if this is high risk."
    if rule_type == "prohibition":
        return "Review forbidden evidence and decide whether policy language must be removed or narrowed."
    return "Review missing or weak evidence and decide whether the policy needs stronger language."


def _format_predicates(predicates: list[dict]) -> list[str]:
    lines = []
    for predicate in predicates:
        status = "found" if predicate.get("matched") else "missing"
        lines.append(f"- `{predicate.get('name', 'unknown')}`: {status}, score={predicate.get('score', 0):.2f}")
        snippets = predicate.get("snippets", [])
        for snippet in snippets[:3]:
            negated = " negated" if snippet.get("negated") else ""
            lines.append(f"  - `{snippet.get('keyword')}`{negated}: {snippet.get('text')}")
    return lines
