"""Compliance engine package — lazy imports to avoid mandatory ML deps."""


def __getattr__(name):
    if name == "RegulatoryRAG":
        from compliance_agent.engine.rag import RegulatoryRAG
        return RegulatoryRAG
    if name == "DriftBridge":
        from compliance_agent.engine.drift import DriftBridge
        return DriftBridge
    if name == "ComplianceReasoner":
        from compliance_agent.engine.reasoner import ComplianceReasoner
        return ComplianceReasoner
    if name == "ComplianceChecker":
        from compliance_agent.engine.checker import ComplianceChecker
        return ComplianceChecker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
