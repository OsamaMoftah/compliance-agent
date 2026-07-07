"""Golden end-to-end test: the bundled demo must produce sane results.

This is the regression net for the v0.1 defect where the bundled (compliant)
sample policy scored HIGH risk because AI Act rules failed on a non-AI policy
and keyword inference produced generic terms.
"""

from pathlib import Path

import pytest
import yaml

from compliance_agent.engine.reasoner import (
    STATUS_NA,
    STATUS_PASS,
    ComplianceReasoner,
    parse_scenario,
)

REPO_ROOT = Path(__file__).parent.parent
RULES = REPO_ROOT / "sample_data" / "rules" / "gdpr_rules.yaml"
POLICY_V1 = REPO_ROOT / "sample_data" / "policies" / "privacy_v1.txt"
POLICY_V2 = REPO_ROOT / "sample_data" / "policies" / "privacy_v2.txt"
SCENARIO = REPO_ROOT / "sample_data" / "rules" / "scenario_gdpr_check.yaml"


@pytest.fixture(scope="module")
def reasoner():
    return ComplianceReasoner(threshold=0.5)


@pytest.fixture(scope="module")
def rules(reasoner):
    return reasoner.load_rules(str(RULES))


def test_bundled_rules_are_valid(reasoner):
    assert reasoner.validate_rules_file(str(RULES)) == []


def test_sample_policy_v1_is_low_risk(reasoner, rules):
    report = reasoner.evaluate_policy(POLICY_V1.read_text(encoding="utf-8"), rules)
    assert report.risk_level == "LOW", report.summary
    assert report.failed_count == 0, [r.rule_id for r in report.results if r.status == "FAIL"]


def test_ai_act_rules_not_applicable_to_non_ai_policy(reasoner, rules):
    report = reasoner.evaluate_policy(POLICY_V1.read_text(encoding="utf-8"), rules)
    by_id = {r.rule_id: r for r in report.results}
    for rule_id in ("AI-ACT-HIGH-RISK-001", "AI-ACT-TRANSPARENCY-001", "AI-ACT-OVERSIGHT-001"):
        assert by_id[rule_id].status == STATUS_NA, f"{rule_id} should be N/A on a non-AI policy"
    # Negated transfers ("we do not transfer ... outside the EU") gate out the transfer rule.
    assert by_id["GDPR-TRANSFER-001"].status == STATUS_NA


def test_dpa_mitigation_passes_sharing_prohibition(reasoner, rules):
    report = reasoner.evaluate_policy(POLICY_V1.read_text(encoding="utf-8"), rules)
    sharing = next(r for r in report.results if r.rule_id == "GDPR-SHARING-001")
    assert sharing.status == STATUS_PASS
    assert sharing.strength > 0.9


def test_sample_policy_v2_ai_rules_apply(reasoner, rules):
    """v2 mentions AI systems, so AI Act rules must be evaluated, not N/A."""
    report = reasoner.evaluate_policy(POLICY_V2.read_text(encoding="utf-8"), rules)
    by_id = {r.rule_id: r for r in report.results}
    assert by_id["AI-ACT-OVERSIGHT-001"].applicable
    assert by_id["AI-ACT-OVERSIGHT-001"].status == STATUS_PASS  # "human oversight review"
    assert by_id["GDPR-TRANSFER-001"].applicable  # SCC transfers to the US
    assert by_id["GDPR-TRANSFER-001"].status == STATUS_PASS


def test_bundled_scenario_parses_and_evaluates(reasoner, rules):
    data = yaml.safe_load(SCENARIO.read_text(encoding="utf-8"))
    description, facts = parse_scenario(data)
    assert description
    assert facts["has_consent"] == 1.0

    report = reasoner.evaluate_scenario(facts, rules)
    assert report.decision in {"ALLOW", "ALLOW_WITH_OBLIGATIONS", "BLOCK"}
    by_id = {r.rule_id: r for r in report.results}
    # Scenario has an automated-processing gate but a weak opt-out fact.
    assert by_id["GDPR-AUTOMATED-001"].status == "FAIL"
    # High-risk AI gate (0.3) is below threshold, so the rule is N/A.
    assert by_id["AI-ACT-HIGH-RISK-001"].status == STATUS_NA
