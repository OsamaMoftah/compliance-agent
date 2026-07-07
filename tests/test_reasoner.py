"""Tests for DDL reasoner."""

import os
import tempfile

from compliance_agent.engine.reasoner import (
    DDL,
    ComplianceReasoner,
    ComplianceRule,
    Predicate,
    RuleValidationError,
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
    assert report.passed_count == 2
    assert report.risk_level in ("LOW", "MEDIUM", "HIGH")


def test_prohibition_fails_when_forbidden_evidence_is_present():
    rules = [
        ComplianceRule(
            id="TEST-PROHIBIT",
            type="prohibition",
            description="Must not sell data",
            predicates=[Predicate(name="sells_data", condition="contains 'sell data'", weight=1.0)],
        ),
    ]

    reasoner = ComplianceReasoner(threshold=0.5)
    report = reasoner.evaluate_policy("We may sell data to advertising partners.", rules)

    assert report.failed_count == 1
    assert report.results[0].strength < 0.5


def test_prohibition_passes_when_evidence_is_negated():
    rules = [
        ComplianceRule(
            id="TEST-PROHIBIT",
            type="prohibition",
            description="Must not sell data",
            predicates=[Predicate(name="sells_data", condition="contains 'sell data'", weight=1.0)],
        ),
    ]

    reasoner = ComplianceReasoner(threshold=0.5)
    report = reasoner.evaluate_policy("We do not sell data to third parties.", rules)

    assert report.passed_count == 1
    assert report.results[0].strength == 1.0


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


def test_parse_rules_dict_rejects_invalid_rule_type():
    data = {
        "rules": [
            {
                "id": "T-001",
                "type": "requirement",
                "description": "Test",
                "predicates": [{"name": "p1", "condition": "test", "weight": 1.0}],
            }
        ]
    }
    reasoner = ComplianceReasoner()

    try:
        reasoner.parse_rules_dict(data)
    except RuleValidationError as e:
        assert "type must be one of" in str(e)
    else:
        raise AssertionError("Expected RuleValidationError")


def test_validate_rules_dict_rejects_duplicate_ids_and_bad_weights():
    data = {
        "rules": [
            {
                "id": "T-001",
                "type": "obligation",
                "description": "Test",
                "predicates": [{"name": "p1", "condition": "test", "weight": 1.2}],
            },
            {
                "id": "T-001",
                "type": "permission",
                "description": "Duplicate",
                "predicates": [{"name": "p2", "condition": "test"}],
            },
        ]
    }
    reasoner = ComplianceReasoner()
    errors = reasoner.validate_rules_dict(data)

    assert any("duplicates" in error for error in errors)
    assert any("weight must be" in error for error in errors)


# ---------------------------------------------------------------------------
# Regression tests for the v0.1 logic defects (D1-D6)
# ---------------------------------------------------------------------------


def test_d1_explicit_keywords_are_not_dropped():
    """v2 keyword lists check every alternative; comma-separated conditions no longer lose terms."""
    pred = Predicate(
        name="has_safeguards",
        keywords=["SCCs", "BCRs", "adequacy decision"],
    )
    result = extract_predicate(pred, "Transfers rely on an adequacy decision by the Commission.")
    assert result["matched"]
    assert result["score"] == 1.0

    result = extract_predicate(pred, "Transfers rely on BCRs approved by the lead authority.")
    assert result["matched"]


def test_d2_generic_word_no_longer_saturates_inferred_score():
    """A single generic word ('data') must not fully satisfy an inferred v1 condition."""
    pred = Predicate(name="has_retention_policy", condition="document specifies data retention period")
    result = extract_predicate(pred, "we collect data.")
    assert result["score"] < 0.5


def test_d2_keyword_word_boundaries():
    """Short keywords must not match inside other words ('AI' inside 'email')."""
    pred = Predicate(name="uses_ai", keywords=["AI"])
    result = extract_predicate(pred, "Contact us by email for details.")
    assert not result["matched"]


def test_d3_prohibition_unless_exception_mitigates():
    """'Prohibited unless mitigated': a DPA must flip the sharing prohibition to pass."""
    rule = ComplianceRule(
        id="P-SHARE",
        type="prohibition",
        description="No sharing without DPA",
        predicates=[Predicate(name="shares", keywords=["shared with third"], weight=1.0)],
        unless=[Predicate(name="has_dpa", keywords=["data processing agreement"], weight=1.0)],
    )
    reasoner = ComplianceReasoner(threshold=0.5)

    with_dpa = reasoner.evaluate_policy(
        "Data is shared with third parties under a strict data processing agreement.", [rule]
    )
    without_dpa = reasoner.evaluate_policy("Data is shared with third parties freely.", [rule])

    assert with_dpa.results[0].passed
    assert not without_dpa.results[0].passed
    assert with_dpa.results[0].strength > without_dpa.results[0].strength


def test_d4_negation_does_not_cross_sentence_boundary():
    pred = Predicate(name="sells_data", keywords=["sell data"])
    text = "There is no fee for our service. We sell data to partners."
    result = extract_predicate(pred, text)
    assert result["matched"], "match in a separate sentence must not inherit negation"
    assert result["score"] == 1.0


def test_d4_post_keyword_negation_detected():
    pred = Predicate(name="sells_data", keywords=["selling user data"])
    result = extract_predicate(pred, "Selling user data is strictly prohibited.")
    assert not result["matched"]


def test_d5_applies_when_gates_to_not_applicable():
    rule = ComplianceRule(
        id="AI-1",
        type="obligation",
        description="AI oversight",
        predicates=[Predicate(name="has_oversight", keywords=["human oversight"])],
        applies_when=[Predicate(name="uses_ai", keywords=["AI system"])],
    )
    reasoner = ComplianceReasoner(threshold=0.5)
    report = reasoner.evaluate_policy("We process payroll data. No machine learning involved.", [rule])

    result = report.results[0]
    assert result.status == "N/A"
    assert not result.applicable
    assert result.passed  # N/A is not a failure
    assert report.risk_level == "LOW"


def test_d6_aggregation_parity_between_paths():
    """The text path and facts path must weight predicates identically."""
    rule = ComplianceRule(
        id="O-1",
        type="obligation",
        description="Encryption",
        predicates=[Predicate(name="has_encryption", keywords=["encryption"], weight=0.5)],
    )
    reasoner = ComplianceReasoner(threshold=0.5)

    text_strength = reasoner.evaluate_policy("We use encryption everywhere.", [rule]).results[0].strength
    facts_strength = reasoner.evaluate_scenario({"has_encryption": 1.0}, [rule]).results[0].strength

    assert text_strength == facts_strength == 1.0


def test_warn_status_near_threshold():
    reasoner = ComplianceReasoner(threshold=0.5)
    rule = ComplianceRule(
        id="O-WARN",
        type="obligation",
        description="Two of four alternatives present",
        predicates=[
            Predicate(
                name="p",
                keywords=["alpha", "beta", "gamma", "delta"],
                match="all",
            )
        ],
    )
    report = reasoner.evaluate_policy("alpha and beta are covered.", [rule])
    result = report.results[0]
    assert result.strength == 0.5
    assert result.status == "WARN"
    assert result.passed


def test_critical_failure_drives_high_risk():
    rules = [
        ComplianceRule(
            id="C-1",
            type="obligation",
            severity="critical",
            description="Critical control",
            predicates=[Predicate(name="p", keywords=["nonexistent-control"])],
        ),
        ComplianceRule(
            id="M-1",
            type="obligation",
            severity="minor",
            description="Minor control",
            predicates=[Predicate(name="q", keywords=["logging"])],
        ),
        ComplianceRule(
            id="M-2",
            type="obligation",
            severity="minor",
            description="Minor control 2",
            predicates=[Predicate(name="r", keywords=["logging"])],
        ),
        ComplianceRule(
            id="M-3",
            type="obligation",
            severity="minor",
            description="Minor control 3",
            predicates=[Predicate(name="s", keywords=["logging"])],
        ),
    ]
    reasoner = ComplianceReasoner(threshold=0.5)
    report = reasoner.evaluate_policy("We maintain logging for all access events.", rules)
    assert report.risk_level == "HIGH"


def test_scenario_decision_block():
    rules = [
        ComplianceRule(
            id="P-1",
            type="prohibition",
            description="No selling data",
            predicates=[Predicate(name="sells_data", keywords=["sell data"])],
        ),
    ]
    reasoner = ComplianceReasoner(threshold=0.5)
    report = reasoner.evaluate_scenario({"sells_data": 0.9}, rules)
    assert report.decision == "BLOCK"


def test_scenario_decision_allow():
    rules = [
        ComplianceRule(
            id="O-1",
            type="obligation",
            description="Consent",
            predicates=[Predicate(name="has_consent", keywords=["consent"])],
        ),
    ]
    reasoner = ComplianceReasoner(threshold=0.5)
    report = reasoner.evaluate_scenario({"has_consent": 0.95}, rules)
    assert report.decision == "ALLOW"


def test_scenario_unmet_obligations_allow_with_obligations():
    rules = [
        ComplianceRule(
            id="O-1",
            type="obligation",
            description="Consent",
            predicates=[Predicate(name="has_consent", keywords=["consent"])],
        ),
    ]
    reasoner = ComplianceReasoner(threshold=0.5)
    report = reasoner.evaluate_scenario({"has_consent": 0.1}, rules)
    assert report.decision == "ALLOW_WITH_OBLIGATIONS"


def test_validate_rejects_unless_on_obligation():
    data = {
        "rules": [
            {
                "id": "O-1",
                "type": "obligation",
                "description": "Bad",
                "predicates": [{"name": "p", "keywords": ["x"]}],
                "unless": [{"name": "e", "keywords": ["y"]}],
            }
        ]
    }
    errors = ComplianceReasoner().validate_rules_dict(data)
    assert any("only allowed on prohibition" in e for e in errors)


def test_validate_rejects_invalid_severity_and_regex():
    data = {
        "rules": [
            {
                "id": "O-1",
                "type": "obligation",
                "severity": "catastrophic",
                "description": "Bad",
                "predicates": [{"name": "p", "patterns": ["([unclosed"]}],
            }
        ]
    }
    errors = ComplianceReasoner().validate_rules_dict(data)
    assert any("severity must be" in e for e in errors)
    assert any("invalid regex" in e for e in errors)


def test_rule_pack_warnings_flag_legacy_conditions():
    data = {
        "rules": [
            {
                "id": "L-1",
                "type": "obligation",
                "description": "Legacy",
                "predicates": [{"name": "p", "condition": "document mentions encryption"}],
            }
        ]
    }
    warnings = ComplianceReasoner.rule_pack_warnings(data)
    assert len(warnings) == 1
    assert "legacy prose" in warnings[0]


def test_parse_scenario_rejects_non_mapping():
    import pytest

    from compliance_agent.engine.reasoner import parse_scenario

    with pytest.raises(ValueError, match="YAML mapping"):
        parse_scenario("just a string")


def test_parse_scenario_accepts_list_and_mapping_facts():
    from compliance_agent.engine.reasoner import parse_scenario

    _, facts = parse_scenario({"scenario": {"facts": [{"predicate": "a", "value": 0.7}]}})
    assert facts == {"a": 0.7}

    _, facts = parse_scenario({"facts": {"b": 1.5}})
    assert facts == {"b": 1.0}  # clamped
