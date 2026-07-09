"""Tests for compliance checker."""

import tempfile
from pathlib import Path

import pytest

from compliance_agent.engine.checker import ComplianceChecker, check_policy


def test_full_check_basic():
    with tempfile.TemporaryDirectory() as tmpdir:
        policy_path = Path(tmpdir) / "policy.txt"
        policy_path.write_text(
            "We obtain explicit user consent before collecting data. "
            "We encrypt all personal data at rest and in transit. "
            "Users can request data deletion at any time."
        )

        rules_path = Path(tmpdir) / "rules.yaml"
        rules_path.write_text(
            """
rules:
  - id: "TEST-CONSENT"
    type: "obligation"
    description: "Must obtain consent"
    predicates:
      - name: "has_consent"
        condition: "consent"
        weight: 1.0
  - id: "TEST-ENCRYPTION"
    type: "obligation"
    description: "Must encrypt data"
    predicates:
      - name: "has_encryption"
        condition: "encrypt"
        weight: 0.8
"""
        )

        checker = ComplianceChecker()
        result = checker.full_check(
            policy_path=str(policy_path),
            rules_path=str(rules_path),
            threshold=0.3,
        )
        report = result["report"]
        assert report.total_count == 2


def test_check_policy_convenience():
    with tempfile.TemporaryDirectory() as tmpdir:
        policy_path = Path(tmpdir) / "policy.txt"
        policy_path.write_text("We obtain explicit user consent.")

        rules_path = Path(tmpdir) / "rules.yaml"
        rules_path.write_text(
            """
rules:
  - id: "T"
    type: "obligation"
    description: "Consent required"
    predicates:
      - name: "has_consent"
        condition: "consent"
        weight: 1.0
"""
        )

        report = check_policy(
            policy_path=str(policy_path),
            rules_path=str(rules_path),
            threshold=0.3,
        )
        assert report.passed_count == 1


def test_full_check_missing_policy_raises(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        """
rules:
  - id: "T"
    type: "obligation"
    description: "Consent"
    predicates:
      - name: "has_consent"
        keywords: ["consent"]
"""
    )
    checker = ComplianceChecker()
    with pytest.raises(FileNotFoundError, match="Policy file not found"):
        checker.full_check(policy_path=str(tmp_path / "nope.txt"), rules_path=str(rules_path))


def test_full_check_with_baseline_and_regulations(stub_legaldrift, tmp_path):
    """Drift (stubbed) and RAG (gracefully skipped without ML deps) branches."""
    policy = tmp_path / "policy_v2.txt"
    policy.write_text("We obtain user consent before processing.", encoding="utf-8")
    baseline = tmp_path / "policy_v1.txt"
    baseline.write_text("We obtain consent before processing.", encoding="utf-8")
    regulations = tmp_path / "regs"
    regulations.mkdir()
    (regulations / "gdpr.txt").write_text("Consent must be freely given.", encoding="utf-8")

    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        """
schema_version: 2
rules:
  - id: "T-CONSENT"
    type: "obligation"
    description: "Consent required"
    predicates:
      - name: "has_consent"
        keywords: ["consent"]
"""
    )

    checker = ComplianceChecker()
    result = checker.full_check(
        policy_path=str(policy),
        rules_path=str(rules_path),
        regulations_dir=str(regulations),
        baseline_path=str(baseline),
    )
    assert result["report"].passed_count == 1
    assert result["drift"] is not None
    assert result["drift"]["chunked"] is True
