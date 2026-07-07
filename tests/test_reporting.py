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


def test_provenance_includes_hashes_and_versions(tmp_path):
    from compliance_agent.engine.reporting import build_provenance

    policy = tmp_path / "policy.txt"
    policy.write_text("We collect data after explicit consent.", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    rules.write_text("rules: []", encoding="utf-8")

    prov = build_provenance(str(policy), str(rules), threshold=0.5)
    assert prov["generated_at"]
    assert prov["tool_version"]
    assert prov["report_schema_version"] == 2
    assert len(prov["policy_sha256"]) == 64
    assert len(prov["rule_pack_sha256"]) == 64
    assert prov["threshold"] == 0.5


def test_report_dict_includes_status_severity_and_evidence():
    data = report_to_dict(_sample_report())
    result = data["results"][0]
    assert result["status"] == "PASS"
    assert result["severity"] in {"critical", "major", "minor"}
    assert result["applicable"] is True
    assert result["evidence"][0]["sentence"]
    assert isinstance(result["evidence"][0]["start"], int)
    assert data["summary"]["severity_breakdown"] == {"critical": 0, "major": 0, "minor": 0}


def test_markdown_groups_findings_and_lists_not_applicable():
    from compliance_agent.engine.reasoner import ComplianceReasoner, ComplianceRule, Predicate
    from compliance_agent.engine.reporting import report_to_markdown

    rules = [
        ComplianceRule(
            id="NA-RULE",
            type="obligation",
            description="AI rule",
            predicates=[Predicate(name="oversight", keywords=["human oversight"])],
            applies_when=[Predicate(name="uses_ai", keywords=["AI system"])],
        ),
        ComplianceRule(
            id="FAIL-RULE",
            type="obligation",
            severity="critical",
            citation="GDPR Art. 32",
            description="Encryption required",
            predicates=[Predicate(name="enc", keywords=["encryption"])],
        ),
    ]
    report = ComplianceReasoner(threshold=0.5).evaluate_policy("We collect names and emails.", rules)
    markdown = report_to_markdown(report, metadata={"policy": "p.txt"})

    assert "## Executive Summary" in markdown
    assert "### FAIL: FAIL-RULE (critical)" in markdown
    assert "GDPR Art. 32" in markdown
    assert "## Not Applicable" in markdown
    assert "NA-RULE" in markdown


def test_html_report_renders_and_escapes():
    from compliance_agent.engine.reporting import report_to_html

    html_text = report_to_html(_sample_report(), metadata={"policy": "<script>.txt"})
    assert html_text.startswith("<!DOCTYPE html>")
    assert "Compliance Review Report" in html_text
    assert "<script>.txt" not in html_text  # metadata must not inject raw HTML


def test_write_report_html(tmp_path):
    path = tmp_path / "report.html"
    write_report(_sample_report(), str(path))
    assert path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_write_report_rejects_unknown_extension(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="must end with"):
        write_report(_sample_report(), str(tmp_path / "report.pdf"))
