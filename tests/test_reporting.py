"""Tests for compliance report export."""

import json
import tempfile
from pathlib import Path

from compliance_agent.engine.reasoner import ComplianceReasoner, ComplianceRule, Predicate
from compliance_agent.engine.reporting import report_to_dict, report_to_markdown, write_report


def _sample_report():
    rules = [
        ComplianceRule(
            id="TEST-CONSENT",
            type="obligation",
            description="Consent required",
            predicates=[Predicate(name="has_consent", condition="contains 'explicit consent'")],
        )
    ]
    reasoner = ComplianceReasoner(threshold=0.5)
    return reasoner.evaluate_policy("We collect data after explicit consent.", rules)


def test_report_to_dict_includes_summary_and_evidence_snippets():
    data = report_to_dict(_sample_report(), metadata={"policy": "policy.txt"})

    assert data["metadata"]["policy"] == "policy.txt"
    assert data["summary"]["total"] == 1
    assert data["results"][0]["rule_id"] == "TEST-CONSENT"
    assert data["results"][0]["predicates"][0]["snippets"][0]["text"]


def test_report_to_markdown_includes_findings():
    markdown = report_to_markdown(_sample_report(), metadata={"policy": "policy.txt", "rules": "rules.yaml"})

    assert "# Compliance Review Report" in markdown
    assert "TEST-CONSENT" in markdown
    assert "explicit consent" in markdown


def test_write_report_json_and_markdown():
    report = _sample_report()
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "report.json"
        md_path = Path(tmpdir) / "report.md"

        write_report(report, str(json_path))
        write_report(report, str(md_path))

        assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["total"] == 1
        assert "Compliance Review Report" in md_path.read_text(encoding="utf-8")
