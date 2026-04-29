"""Tests for DDL reasoner."""

import os
import tempfile

from compliance_agent.engine.reasoner import (
    DDL,
    ComplianceReasoner,
    ComplianceRule,
    Predicate,
    extract_predicate,
)


def test_ddl_operations():
    ddl = DDL(fuzzy=True)
    assert abs(ddl.soft_and(0.8, 0.6) - 0.48) < 0.01
    assert abs(ddl.soft_or(0.8, 0.6) - 0.92) < 0.01
    assert abs(ddl.soft_not(0.8) - 0.2) < 0.01
    assert abs(ddl.obligation(0.8) - 0.8) < 0.01
    assert abs(ddl.prohibition(0.3) - 0.7) < 0.01


def test_ddl_resolve_block():
    ddl = DDL()
    decision, confidence = ddl.resolve(obligation=0.3, permission=0.3, prohibition=0.9)
    assert decision == "BLOCK"


def test_ddl_resolve_allow():
    ddl = DDL()
    decision, confidence = ddl.resolve(obligation=0.2, permission=0.8, prohibition=0.1)
    assert decision == "ALLOW"


def test_extract_predicate_matched():
    pred = Predicate(name="has_consent", condition="document contains 'explicit consent'", weight=1.0)
    result = extract_predicate(pred, "We obtain explicit consent from all users.")
    assert result["matched"]
    assert result["score"] > 0


def test_extract_predicate_not_matched():
    pred = Predicate(name="has_encryption", condition="document contains 'encryption'", weight=1.0)
    result = extract_predicate(pred, "We use secure protocols for data transfer.")
    assert not result["matched"]
    assert result["score"] == 0.0


def test_load_rules_from_yaml():
    rules_yaml = """
rules:
  - id: "TEST-001"
    type: "obligation"
    description: "Test obligation rule"
    predicates:
      - name: "test_pred"
        condition: "contains 'test phrase'"
        weight: 1.0
  - id: "TEST-002"
    type: "prohibition"
    description: "Test prohibition rule"
    predicates:
      - name: "bad_pred"
        condition: "contains 'bad thing'"
        weight: 0.8
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(rules_yaml)
        rules_path = f.name

    try:
        reasoner = ComplianceReasoner()
        rules = reasoner.load_rules(rules_path)
        assert len(rules) == 2
        assert rules[0].type == "obligation"
        assert rules[1].type == "prohibition"
    finally:
        os.unlink(rules_path)


def test_evaluate_policy():
    rules = [
        ComplianceRule(
            id="TEST-001",
            type="obligation",
            description="Must have consent",
            predicates=[Predicate(name="has_consent", condition="contains 'consent'", weight=1.0)],
        ),
        ComplianceRule(
            id="TEST-002",
            type="prohibition",
            description="Must not sell data",
            predicates=[Predicate(name="sells_data", condition="contains 'sell data'", weight=0.8)],
        ),
    ]

    reasoner = ComplianceReasoner(threshold=0.3)
    report = reasoner.evaluate_policy(
        "We obtain user consent before processing. We do not sell data to third parties.",
        rules,
    )
    assert report.total_count == 2
    assert report.passed_count >= 1
    assert report.risk_level in ("LOW", "MEDIUM", "HIGH")


def test_evaluate_scenario():
    rules = [
        ComplianceRule(
            id="TEST-001",
            type="obligation",
            description="Must have consent",
            predicates=[Predicate(name="has_consent", condition="consent", weight=1.0)],
        ),
    ]

    reasoner = ComplianceReasoner(threshold=0.5)
    report = reasoner.evaluate_scenario({"has_consent": 0.9}, rules)
    assert report.total_count == 1
    assert report.passed_count == 1


def test_parse_rules_dict():
    data = {
        "rules": [
            {
                "id": "T-001",
                "type": "obligation",
                "description": "Test",
                "predicates": [{"name": "p1", "condition": "test", "weight": 1.0}],
            }
        ]
    }
    reasoner = ComplianceReasoner()
    rules = reasoner.parse_rules_dict(data)
    assert len(rules) == 1
    assert rules[0].id == "T-001"
