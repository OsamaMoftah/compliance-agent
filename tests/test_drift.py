"""Tests for the drift bridge, using the stubbed legaldrift module from conftest."""

import sys

import pytest

from compliance_agent.engine.drift import DriftBridge
from tests.conftest import FakeDetector


@pytest.fixture
def policies(tmp_path):
    v1 = tmp_path / "v1.txt"
    v2 = tmp_path / "v2.txt"
    v1.write_text("Data is retained for 12 months.", encoding="utf-8")
    v2.write_text("Data is retained for 24 months.", encoding="utf-8")
    return str(v1), str(v2)


def test_detect_full(stub_legaldrift, policies):
    bridge = DriftBridge()
    result = bridge.detect(*policies, output_format="json")
    assert result["drift_detected"] is True
    assert result["p_value"] == 0.01
    assert result["confidence"] == pytest.approx(0.99)


def test_detect_full_table_output(stub_legaldrift, policies):
    bridge = DriftBridge()
    result = bridge.detect(*policies, output_format="table")
    assert result["drift_detected"] is True


def test_detect_threshold_passthrough(stub_legaldrift, policies):
    bridge = DriftBridge()
    bridge.detect(*policies, output_format="json", threshold=0.10)
    assert FakeDetector.last_threshold == 0.10


def test_detect_chunked(stub_legaldrift, policies):
    bridge = DriftBridge()
    result = bridge.detect(*policies, chunked=True, output_format="json")
    assert result["chunked"] is True
    assert result["sections"][0]["section"] == "Section 1"
    assert result["sections"][0]["status"] == "DRIFT"


def test_detect_chunked_table_output(stub_legaldrift, policies):
    bridge = DriftBridge()
    result = bridge.detect(*policies, chunked=True, output_format="table")
    assert result["chunked"] is True


def test_detect_missing_file(stub_legaldrift, policies, tmp_path):
    bridge = DriftBridge()
    with pytest.raises(FileNotFoundError):
        bridge.detect(str(tmp_path / "nope.txt"), policies[1])


def test_missing_legaldrift_raises_runtime_error(monkeypatch, policies):
    monkeypatch.setitem(sys.modules, "legaldrift", None)
    bridge = DriftBridge()
    with pytest.raises(RuntimeError, match="LegalDrift is not installed"):
        bridge.detect(*policies)
