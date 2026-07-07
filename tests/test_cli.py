"""CLI tests: happy paths, error paths, and exit codes."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from compliance_agent.cli import main

VALID_RULES = """
schema_version: 2
rules:
  - id: "T-CONSENT"
    type: "obligation"
    severity: "critical"
    description: "Must obtain consent"
    predicates:
      - name: "has_consent"
        keywords: ["user consent"]
        weight: 1.0
"""

FAILING_RULES = """
schema_version: 2
rules:
  - id: "T-ENCRYPTION"
    type: "obligation"
    description: "Must encrypt"
    predicates:
      - name: "has_encryption"
        keywords: ["encryption"]
        weight: 1.0
"""

INVALID_RULES = """
rules:
  - id: "T-BAD"
    type: "requirement"
    description: "Bad type"
    predicates:
      - name: "p"
        keywords: ["x"]
"""

SCENARIO = """
scenario:
  description: "test scenario"
  facts:
    - predicate: "has_consent"
      value: 0.9
"""


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "policy.txt").write_text("We always obtain user consent before processing.", encoding="utf-8")
    (tmp_path / "rules.yaml").write_text(VALID_RULES, encoding="utf-8")
    (tmp_path / "failing_rules.yaml").write_text(FAILING_RULES, encoding="utf-8")
    (tmp_path / "invalid_rules.yaml").write_text(INVALID_RULES, encoding="utf-8")
    (tmp_path / "scenario.yaml").write_text(SCENARIO, encoding="utf-8")
    (tmp_path / "bad_scenario.yaml").write_text("just a string", encoding="utf-8")
    return tmp_path


def test_check_passes_with_exit_zero(runner, workspace):
    result = runner.invoke(main, ["check", "-p", str(workspace / "policy.txt"), "-r", str(workspace / "rules.yaml")])
    assert result.exit_code == 0, result.output


def test_check_findings_exit_one(runner, workspace):
    result = runner.invoke(
        main, ["check", "-p", str(workspace / "policy.txt"), "-r", str(workspace / "failing_rules.yaml")]
    )
    assert result.exit_code == 1


def test_check_missing_policy_exit_two(runner, workspace):
    result = runner.invoke(main, ["check", "-p", str(workspace / "nope.txt"), "-r", str(workspace / "rules.yaml")])
    assert result.exit_code == 2
    assert "not found" in result.output


def test_check_invalid_rules_exit_two(runner, workspace):
    result = runner.invoke(
        main, ["check", "-p", str(workspace / "policy.txt"), "-r", str(workspace / "invalid_rules.yaml")]
    )
    assert result.exit_code == 2
    assert "validation failed" in result.output


def test_check_json_format(runner, workspace):
    result = runner.invoke(
        main,
        ["check", "-p", str(workspace / "policy.txt"), "-r", str(workspace / "rules.yaml"), "--format", "json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["summary"]["risk_level"] == "LOW"
    assert data["provenance"]["policy_sha256"]


def test_validate_rules_ok(runner, workspace):
    result = runner.invoke(main, ["validate-rules", "-r", str(workspace / "rules.yaml")])
    assert result.exit_code == 0
    assert "valid" in result.output


def test_validate_rules_invalid_exit_one(runner, workspace):
    result = runner.invoke(main, ["validate-rules", "-r", str(workspace / "invalid_rules.yaml")])
    assert result.exit_code == 1
    assert "type must be one of" in result.output


def test_validate_rules_warns_on_legacy_conditions(runner, tmp_path):
    (tmp_path / "legacy.yaml").write_text(
        """
rules:
  - id: "L-1"
    type: "obligation"
    description: "Legacy"
    predicates:
      - name: "p"
        condition: "document mentions encryption"
""",
        encoding="utf-8",
    )
    result = runner.invoke(main, ["validate-rules", "-r", str(tmp_path / "legacy.yaml")])
    assert result.exit_code == 0
    assert "Warning" in result.output


def test_reason_happy_path(runner, workspace):
    result = runner.invoke(
        main, ["reason", "-s", str(workspace / "scenario.yaml"), "-r", str(workspace / "rules.yaml")]
    )
    assert result.exit_code == 0, result.output
    assert "Decision" in result.output


def test_reason_malformed_scenario_exit_two(runner, workspace):
    result = runner.invoke(
        main, ["reason", "-s", str(workspace / "bad_scenario.yaml"), "-r", str(workspace / "rules.yaml")]
    )
    assert result.exit_code == 2
    assert "Invalid scenario" in result.output


def test_reason_json_format(runner, workspace):
    result = runner.invoke(
        main,
        ["reason", "-s", str(workspace / "scenario.yaml"), "-r", str(workspace / "rules.yaml"), "--format", "json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["summary"]["decision"] in {"ALLOW", "ALLOW_WITH_OBLIGATIONS", "BLOCK"}


@pytest.mark.parametrize("extension", ["md", "json", "html"])
def test_report_formats(runner, workspace, extension):
    output = workspace / f"report.{extension}"
    result = runner.invoke(
        main,
        ["report", "-p", str(workspace / "policy.txt"), "-r", str(workspace / "rules.yaml"), "-o", str(output)],
    )
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert output.read_text(encoding="utf-8").strip()


def test_report_bad_extension_exit_two(runner, workspace):
    result = runner.invoke(
        main,
        ["report", "-p", str(workspace / "policy.txt"), "-r", str(workspace / "rules.yaml"), "-o", str(workspace / "report.pdf")],
    )
    assert result.exit_code == 2


def test_report_missing_policy_exit_two(runner, workspace):
    result = runner.invoke(
        main,
        ["report", "-p", str(workspace / "nope.txt"), "-r", str(workspace / "rules.yaml"), "-o", str(workspace / "r.md")],
    )
    assert result.exit_code == 2


def test_drift_missing_file_exit_two(runner, workspace):
    result = runner.invoke(main, ["drift", str(workspace / "nope.txt"), str(workspace / "policy.txt")])
    assert result.exit_code == 2
    assert "not found" in result.output


def test_version(runner):
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "compliance-agent" in result.output


def test_check_sample_data_end_to_end(runner):
    """The bundled demo must exit 0 (no failures)."""
    root = Path(__file__).parent.parent
    result = runner.invoke(
        main,
        [
            "check",
            "-p", str(root / "sample_data" / "policies" / "privacy_v1.txt"),
            "-r", str(root / "sample_data" / "rules" / "gdpr_rules.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
