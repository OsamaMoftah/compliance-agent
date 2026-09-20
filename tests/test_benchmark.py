import pytest

from compliance_agent.benchmark import load_dataset, run_benchmark


def test_run_benchmark_reports_failure_metrics_and_evidence(tmp_path):
    dataset = tmp_path / "cases.yaml"
    dataset.write_text(
        """
version: 1
cases:
  - id: compliant
    policy: We obtain explicit consent from users.
    rules:
      - id: CONSENT
        type: obligation
        description: Consent is required.
        predicates:
          - name: consent
            keywords: [explicit consent]
    expected:
      CONSENT: PASS
    expected_evidence:
      CONSENT: [explicit consent]
  - id: missing
    policy: We collect information.
    rules:
      - id: CONSENT
        type: obligation
        description: Consent is required.
        predicates:
          - name: consent
            keywords: [explicit consent]
    expected:
      CONSENT: FAIL
""",
        encoding="utf-8",
    )

    report = run_benchmark(str(dataset))

    assert report["cases"] == 2
    assert report["status_matches"] == 2
    assert report["evidence_matches"] == 1
    assert report["metrics"] == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "false_positive_rate": 0.0,
        "false_negative_rate": 0.0,
    }


def test_load_dataset_rejects_invalid_cases(tmp_path):
    dataset = tmp_path / "invalid.yaml"
    dataset.write_text("version: 1\ncases: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty"):
        load_dataset(str(dataset))


@pytest.mark.parametrize(
    ("rules", "expected", "message"),
    [
        (
            """      - id: FIRST
        type: obligation
        description: First.
        predicates:
          - name: first
            keywords: [first]
      - id: SECOND
        type: obligation
        description: Second.
        predicates:
          - name: second
            keywords: [second]
""",
            "      FIRST: PASS\n",
            "exactly match rule IDs",
        ),
        (
            """      - id: FIRST
        type: obligation
        description: First.
        predicates:
          - name: first
            keywords: [first]
""",
            "      FIRST: PASS\n      UNKNOWN: FAIL\n",
            "exactly match rule IDs",
        ),
        (
            """      - id: DUPLICATE
        type: obligation
        description: First.
        predicates:
          - name: first
            keywords: [first]
      - id: DUPLICATE
        type: prohibition
        description: Second.
        predicates:
          - name: second
            keywords: [second]
""",
            "      DUPLICATE: PASS\n",
            "unique non-empty IDs",
        ),
    ],
)
def test_load_dataset_requires_one_expectation_per_unique_rule(tmp_path, rules, expected, message):
    dataset = tmp_path / "invalid-rule-map.yaml"
    dataset.write_text(
        "version: 1\ncases:\n  - id: mapping\n    policy: Test policy.\n    rules:\n"
        + rules
        + "    expected:\n"
        + expected,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_dataset(str(dataset))


def test_load_dataset_rejects_duplicate_case_ids(tmp_path):
    dataset = tmp_path / "duplicate-cases.yaml"
    dataset.write_text(
        """
version: 1
cases:
  - id: duplicate
    policy: First.
    rules:
      - id: RULE-1
        type: obligation
        description: First.
        predicates: [{name: first, keywords: [first]}]
    expected: {RULE-1: PASS}
  - id: duplicate
    policy: Second.
    rules:
      - id: RULE-2
        type: obligation
        description: Second.
        predicates: [{name: second, keywords: [second]}]
    expected: {RULE-2: PASS}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unique"):
        load_dataset(str(dataset))


@pytest.mark.parametrize(
    "expected_evidence",
    [
        "[RULE-1]",
        "{UNKNOWN: [first]}",
        "{RULE-1: []}",
        "{RULE-1: [1]}",
    ],
)
def test_load_dataset_validates_expected_evidence(tmp_path, expected_evidence):
    dataset = tmp_path / "invalid-evidence.yaml"
    dataset.write_text(
        """
version: 1
cases:
  - id: evidence
    policy: First.
    rules:
      - id: RULE-1
        type: obligation
        description: First.
        predicates: [{name: first, keywords: [first]}]
    expected: {RULE-1: PASS}
    expected_evidence: """
        + expected_evidence
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected_evidence"):
        load_dataset(str(dataset))
