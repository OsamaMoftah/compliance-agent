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
