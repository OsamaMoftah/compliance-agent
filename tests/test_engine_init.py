"""Lazy-import surface of compliance_agent.engine."""

import pytest


def test_lazy_exports_resolve():
    from compliance_agent import engine

    assert engine.ComplianceReasoner is not None
    assert engine.ComplianceChecker is not None
    assert engine.DriftBridge is not None
    assert engine.RegulatoryRAG is not None


def test_unknown_attribute_raises():
    from compliance_agent import engine

    with pytest.raises(AttributeError, match="has no attribute"):
        engine.does_not_exist
