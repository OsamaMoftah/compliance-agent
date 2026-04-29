"""Tests for compliance checker."""

import os
import tempfile
from pathlib import Path

import yaml

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
