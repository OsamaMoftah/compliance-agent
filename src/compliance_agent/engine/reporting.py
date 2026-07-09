"""Export compliance reports for review workflows and automation."""

import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from compliance_agent.engine.reasoner import (
    STATUS_FAIL,
    STATUS_NA,
    STATUS_PASS,
    STATUS_WARN,
    ComplianceReport,
)

REPORT_SCHEMA_VERSION = 2
_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}
_STATUS_ORDER = {STATUS_FAIL: 0, STATUS_WARN: 1, STATUS_PASS: 2, STATUS_NA: 3}


def _tool_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("compliance-agent")
    except PackageNotFoundError:
        from compliance_agent import __version__

        return __version__


def _sha256_of(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_provenance(
    policy_path: Optional[str] = None,
    rules_path: Optional[str] = None,
    threshold: Optional[float] = None,
) -> dict:
    """Audit-grade provenance for a report: when, with what, over what."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": "compliance-agent",
        "tool_version": _tool_version(),
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "policy_path": policy_path,
        "policy_sha256": _sha256_of(policy_path),
        "rules_path": rules_path,
        "rule_pack_sha256": _sha256_of(rules_path),
        "threshold": threshold,
    }


def _evidence_entries(predicates: list[dict]) -> list[dict]:
    entries = []
    for predicate in predicates:
        for snippet in predicate.get("snippets", []) if isinstance(predicate, dict) else []:
            entries.append(
                {
                    "predicate": predicate.get("name", "unknown"),
                    "keyword": snippet.get("keyword"),
                    "sentence": snippet.get("sentence", snippet.get("text", "")),
                    "start": snippet.get("start"),
                    "end": snippet.get("end"),
                    "negated": bool(snippet.get("negated")),
                }
            )
    return entries


def report_to_dict(
    report: ComplianceReport,
    metadata: Optional[dict[str, Any]] = None,
    provenance: Optional[dict] = None,
) -> dict:
    """Convert a ComplianceReport into stable JSON-friendly data."""
    meta = metadata or {}
    if provenance is None:
        provenance = build_provenance(
            policy_path=meta.get("policy"),
            rules_path=meta.get("rules"),
            threshold=meta.get("threshold"),
        )

    summary: dict[str, Any] = {
        "overall_score": report.overall_score,
        "risk_level": report.risk_level,
        "passed": report.passed_count,
        "failed": report.failed_count,
        "warnings": report.warn_count,
        "not_applicable": report.na_count,
        "applicable": report.applicable_count,
        "total": report.total_count,
        "severity_breakdown": report.severity_breakdown(),
        "text": report.summary,
    }
    if report.decision:
        summary["decision"] = report.decision
        summary["decision_confidence"] = report.decision_confidence

    return {
        "metadata": meta,
        "provenance": provenance,
        "summary": summary,
        "results": [
            {
                "rule_id": result.rule_id,
                "rule_type": result.rule_type,
                "severity": result.severity,
                "citation": result.citation,
                "description": result.description,
                "status": result.status,
                "passed": result.passed,
                "applicable": result.applicable,
                "strength": result.strength,
                "explanation": result.explanation,
                "predicates": result.predicate_results,
                "matched_predicates": result.predicates_matched,
                "evidence": _evidence_entries(result.predicate_results),
                "recommended_action": _recommended_action(result.status, result.rule_type),
            }
            for result in report.results
        ],
    }


def _sorted_findings(results: list[dict]) -> list[dict]:
    """FAIL before WARN before PASS, critical before major before minor."""
    return sorted(
        results,
        key=lambda r: (
            _STATUS_ORDER.get(r["status"], 9),
            _SEVERITY_ORDER.get(r["severity"], 9),
            r["rule_id"],
        ),
    )


def report_to_markdown(
    report: ComplianceReport,
    metadata: Optional[dict[str, Any]] = None,
    provenance: Optional[dict] = None,
) -> str:
    """Render a ComplianceReport as Markdown for human review."""
    data = report_to_dict(report, metadata, provenance)
    summary = data["summary"]
    prov = data["provenance"]

    lines = [
        "# Compliance Review Report",
        "",
        f"- **Generated:** {prov['generated_at']} (compliance-agent {prov['tool_version']})",
    ]
    if prov.get("policy_path"):
        sha = prov.get("policy_sha256")
        suffix = f" (sha256: `{sha[:16]}…`)" if sha else ""
        lines.append(f"- **Policy:** {prov['policy_path']}{suffix}")
    if prov.get("rules_path"):
        sha = prov.get("rule_pack_sha256")
        suffix = f" (sha256: `{sha[:16]}…`)" if sha else ""
        lines.append(f"- **Rule pack:** {prov['rules_path']}{suffix}")
    if prov.get("threshold") is not None:
        lines.append(f"- **Threshold:** {prov['threshold']}")

    breakdown = summary["severity_breakdown"]
    breakdown_text = ", ".join(f"{count} {sev}" for sev, count in breakdown.items() if count) or "none"
    lines.extend(
        [
            "",
            "## Executive Summary",
            "",
            f"- **Risk level:** {summary['risk_level']}",
            f"- **Overall score:** {summary['overall_score']:.2f}",
            f"- **Rules:** {summary['passed']} passed ({summary['warnings']} marginal), "
            f"{summary['failed']} failed, {summary['not_applicable']} not applicable "
            f"of {summary['total']} total",
            f"- **Failures by severity:** {breakdown_text}",
        ]
    )
    if summary.get("decision"):
        lines.append(f"- **Decision:** {summary['decision']} (confidence {summary['decision_confidence']:.2f})")
    lines.extend(["", f"> {summary['text']}", "", "## Findings", ""])

    applicable = [r for r in data["results"] if r["applicable"]]
    not_applicable = [r for r in data["results"] if not r["applicable"]]

    for result in _sorted_findings(applicable):
        lines.extend(
            [
                f"### {result['status']}: {result['rule_id']} ({result['severity']})",
                "",
                f"- **Type:** {result['rule_type']}",
            ]
        )
        if result["citation"]:
            lines.append(f"- **Citation:** {result['citation']}")
        lines.extend(
            [
                f"- **Description:** {result['description']}",
                f"- **Strength:** {result['strength']:.2f}",
                f"- **Recommended action:** {result['recommended_action']}",
                "",
            ]
        )
        predicate_lines = _format_predicates(result["predicates"])
        if predicate_lines:
            lines.extend(["**Evidence**", "", *predicate_lines, ""])

    if not_applicable:
        lines.extend(["## Not Applicable", ""])
        for result in not_applicable:
            gates = ", ".join(p.get("name", "?") for p in result["predicates"]) or "applicability conditions"
            citation = f" ({result['citation']})" if result["citation"] else ""
            lines.append(f"- **{result['rule_id']}**{citation}: {result['description']} — gate not matched: {gates}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


_HTML_STATUS_COLORS = {
    STATUS_PASS: "#1a7f37",
    STATUS_WARN: "#9a6700",
    STATUS_FAIL: "#cf222e",
    STATUS_NA: "#57606a",
}


def report_to_html(
    report: ComplianceReport,
    metadata: Optional[dict[str, Any]] = None,
    provenance: Optional[dict] = None,
) -> str:
    """Render a self-contained HTML report (no external assets)."""
    data = report_to_dict(report, metadata, provenance)
    summary = data["summary"]
    prov = data["provenance"]
    esc = html.escape

    def badge(status: str) -> str:
        color = _HTML_STATUS_COLORS.get(status, "#57606a")
        style = f"color:#fff;background:{color};padding:2px 8px;border-radius:10px;font-size:12px"
        return f'<span style="{style}">{esc(status)}</span>'

    rows = []
    for r in _sorted_findings([x for x in data["results"] if x["applicable"]]):
        evidence_items = "".join(
            f"<li><code>{esc(str(e['keyword']))}</code>{' <em>(negated)</em>' if e['negated'] else ''}: "
            f"{esc(e['sentence'])}</li>"
            for e in r["evidence"][:6]
        )
        rows.append(
            "<tr>"
            f"<td>{badge(r['status'])}</td>"
            f"<td><strong>{esc(r['rule_id'])}</strong><br><small>{esc(r['citation'])}</small></td>"
            f"<td>{esc(r['severity'])}</td>"
            f"<td>{r['strength']:.2f}</td>"
            f"<td>{esc(r['description'])}<ul>{evidence_items}</ul>"
            f"<small>{esc(r['recommended_action'])}</small></td>"
            "</tr>"
        )
    na_items = "".join(
        f"<li><strong>{esc(r['rule_id'])}</strong>: {esc(r['description'])}</li>"
        for r in data["results"]
        if not r["applicable"]
    )

    decision_html = ""
    if summary.get("decision"):
        decision_html = (
            f"<p><strong>Decision:</strong> {esc(summary['decision'])} "
            f"(confidence {summary['decision_confidence']:.2f})</p>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compliance Review Report</title>
<style>
body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem auto;
       max-width: 960px; padding: 0 1rem; color: #1f2328; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #d0d7de; padding: 8px; text-align: left; vertical-align: top; }}
th {{ background: #f6f8fa; }}
ul {{ margin: 4px 0; padding-left: 18px; }}
.provenance {{ color: #57606a; font-size: 13px; }}
</style>
</head>
<body>
<h1>Compliance Review Report</h1>
<p class="provenance">Generated {esc(prov['generated_at'])} by compliance-agent {esc(str(prov['tool_version']))}
&middot; policy sha256 {esc(str(prov.get('policy_sha256') or 'n/a'))[:16]}
&middot; rule pack sha256 {esc(str(prov.get('rule_pack_sha256') or 'n/a'))[:16]}</p>
<h2>Executive Summary</h2>
<p><strong>Risk level:</strong> {esc(summary['risk_level'])} &middot; <strong>Score:</strong> {summary['overall_score']:.2f}</p>
{decision_html}
<p>{summary['passed']} passed ({summary['warnings']} marginal), {summary['failed']} failed,
{summary['not_applicable']} not applicable of {summary['total']} rules.</p>
<blockquote>{esc(summary['text'])}</blockquote>
<h2>Findings</h2>
<table>
<thead><tr><th>Status</th><th>Rule</th><th>Severity</th><th>Strength</th><th>Detail</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
{'<h2>Not Applicable</h2><ul>' + na_items + '</ul>' if na_items else ''}
</body>
</html>
"""


def write_report(
    report: ComplianceReport,
    output_path: str,
    metadata: Optional[dict[str, Any]] = None,
    provenance: Optional[dict] = None,
) -> Path:
    """Write a compliance report as .json, .md, or .html based on the extension."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()

    if suffix == ".json":
        path.write_text(json.dumps(report_to_dict(report, metadata, provenance), indent=2), encoding="utf-8")
    elif suffix in {".md", ".markdown"}:
        path.write_text(report_to_markdown(report, metadata, provenance), encoding="utf-8")
    elif suffix in {".html", ".htm"}:
        path.write_text(report_to_html(report, metadata, provenance), encoding="utf-8")
    else:
        raise ValueError("Report output must end with .json, .md, .markdown, or .html")

    return path


def _recommended_action(status: str, rule_type: str) -> str:
    if status == STATUS_NA:
        return "No action: rule not applicable to this document. Confirm the applicability gate is correct."
    if status == STATUS_WARN:
        return "Marginal evidence: human reviewer should confirm the policy language actually satisfies this rule."
    if status == STATUS_PASS:
        return "No immediate action. Human reviewer should confirm evidence if this is high risk."
    if rule_type == "prohibition":
        return "Review forbidden evidence and decide whether policy language must be removed or narrowed."
    return "Review missing or weak evidence and decide whether the policy needs stronger language."


def _format_predicates(predicates: list[dict]) -> list[str]:
    lines = []
    for predicate in predicates:
        if "value" in predicate:  # scenario (facts) mode
            lines.append(f"- `{predicate.get('name', 'unknown')}`: value={predicate.get('value', 0):.2f}")
            continue
        status = "found" if predicate.get("matched") else "missing"
        lines.append(f"- `{predicate.get('name', 'unknown')}`: {status}, score={predicate.get('score', 0):.2f}")
        snippets = predicate.get("snippets", [])
        for snippet in snippets[:3]:
            negated = " negated" if snippet.get("negated") else ""
            sentence = snippet.get("sentence", snippet.get("text", ""))
            offsets = f"(chars {snippet.get('start')}–{snippet.get('end')})"
            lines.append(f"  - `{snippet.get('keyword')}`{negated}: “{sentence}” {offsets}")
    return lines
