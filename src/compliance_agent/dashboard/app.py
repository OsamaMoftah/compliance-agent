"""Compliance Agent Dashboard — Streamlit application."""

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st
import yaml

from compliance_agent.engine.reasoner import (
    STATUS_FAIL,
    STATUS_NA,
    STATUS_PASS,
    STATUS_WARN,
    ComplianceReasoner,
    RuleValidationError,
    parse_scenario,
)
from compliance_agent.engine.reporting import build_provenance, report_to_dict, report_to_markdown

st.set_page_config(page_title="Compliance Agent", page_icon="\U0001f6e1️", layout="wide")

st.title("\U0001f6e1️ Compliance Agent")
st.markdown("Regulatory intelligence, drift detection, and rule reasoning — in one dashboard.")

SAMPLE_DIR = Path("sample_data")
HAS_SAMPLES = SAMPLE_DIR.exists()

STATUS_ICONS = {STATUS_PASS: "✅", STATUS_WARN: "⚠️", STATUS_FAIL: "❌", STATUS_NA: "➖"}
SEVERITY_BADGES = {"critical": ":red[critical]", "major": ":orange[major]", "minor": ":gray[minor]"}
STATUS_ORDER = {STATUS_FAIL: 0, STATUS_WARN: 1, STATUS_PASS: 2, STATUS_NA: 3}


def _load_rules_or_error(rules_text: str):
    """Parse a rules YAML string; render errors in the UI and return None on failure."""
    try:
        rules_data = yaml.safe_load(rules_text)
    except yaml.YAMLError as e:
        st.error(f"Rules file is not valid YAML: {e}")
        return None
    reasoner = ComplianceReasoner()
    try:
        rules = reasoner.parse_rules_dict(rules_data)
    except RuleValidationError as e:
        st.error("Rules validation failed:")
        for error in e.errors:
            st.markdown(f"- {error}")
        return None
    for warning in reasoner.rule_pack_warnings(rules_data):
        st.warning(warning)
    return rules


def _highlight(sentence: str, keyword: str) -> str:
    """Bold every occurrence of keyword in the sentence (case-insensitive)."""
    if not keyword:
        return sentence
    return re.sub(f"({re.escape(keyword)})", r"**\1**", sentence, flags=re.IGNORECASE)


def _render_evidence(predicate_results: list[dict]) -> None:
    for pred in predicate_results:
        if "value" in pred:  # facts mode
            st.markdown(f"- `{pred.get('name')}`: value = {pred.get('value', 0):.2f}")
            continue
        state = "found" if pred.get("matched") else "missing"
        st.markdown(f"- `{pred.get('name')}`: {state} (score {pred.get('score', 0):.2f})")
        for snippet in pred.get("snippets", [])[:3]:
            sentence = _highlight(snippet.get("sentence", snippet.get("text", "")), snippet.get("keyword", ""))
            negated = " _(negated)_" if snippet.get("negated") else ""
            st.markdown(f"  > {sentence}{negated}")


def _render_results(report, threshold: float) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Risk Level", report.risk_level)
    col2.metric("Score", f"{report.overall_score:.2f}")
    col3.metric("Passed", f"{report.passed_count}/{report.applicable_count} applicable")
    col4.metric("Not applicable", str(report.na_count))

    st.subheader("Rule-by-Rule Results")
    ordered = sorted(report.results, key=lambda r: (STATUS_ORDER.get(r.status, 9), r.rule_id))
    applicable = [r for r in ordered if r.applicable]
    not_applicable = [r for r in ordered if not r.applicable]

    for r in applicable:
        icon = STATUS_ICONS.get(r.status, "")
        badge = SEVERITY_BADGES.get(r.severity, r.severity)
        with st.expander(f"{icon} {r.status} · {r.rule_id} — {r.description[:80]}", expanded=r.status == STATUS_FAIL):
            citation_part = f" · **Citation:** {r.citation}" if r.citation else ""
            st.markdown(f"**Type:** {r.rule_type} · **Severity:** {badge}{citation_part}")
            st.markdown(f"**Strength:** {r.strength:.3f} (threshold {threshold})")
            _render_evidence(r.predicate_results)

    if not_applicable:
        with st.expander(f"➖ Not applicable ({len(not_applicable)} rules)"):
            for r in not_applicable:
                st.markdown(f"- **{r.rule_id}**: {r.description} — applicability gate not matched")


def _download_buttons(report, metadata: dict, key_prefix: str) -> None:
    provenance = build_provenance(threshold=metadata.get("threshold"))
    md = report_to_markdown(report, metadata=metadata, provenance=provenance)
    js = json.dumps(report_to_dict(report, metadata=metadata, provenance=provenance), indent=2)
    col1, col2 = st.columns(2)
    col1.download_button("⬇️ Download Markdown report", md, "compliance-report.md", "text/markdown", key=f"{key_prefix}_md")
    col2.download_button("⬇️ Download JSON report", js, "compliance-report.json", "application/json", key=f"{key_prefix}_json")


def _remember(kind: str, name: str, report) -> None:
    history = st.session_state.setdefault("history", [])
    history.append(
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "kind": kind,
            "name": name,
            "risk": report.risk_level,
            "score": f"{report.overall_score:.2f}",
        }
    )
    del history[:-10]


with st.sidebar:
    st.header("Session history")
    history = st.session_state.get("history", [])
    if not history:
        st.caption("Checks you run will appear here.")
    for entry in reversed(history):
        color = {"LOW": "green", "MEDIUM": "orange", "HIGH": "red"}.get(entry["risk"], "gray")
        st.markdown(f"`{entry['time']}` {entry['kind']} **{entry['name']}** — :{color}[{entry['risk']}] ({entry['score']})")

tab1, tab2, tab3, tab4 = st.tabs(["Monitor", "Check Policy", "Detect Drift", "Reason"])

# ---------------------------------------------------------------------------
# Tab 1: Monitor (Regulatory RAG)
# ---------------------------------------------------------------------------

with tab1:
    st.header("Regulatory Monitor")
    st.markdown("Ingest regulatory documents and query them with natural language.")

    try:
        from compliance_agent.engine.rag import RegulatoryRAG

        rag_available = True
    except ImportError:
        rag_available = False
        st.info("RAG dependencies are not installed. Install with: `pip install 'compliance-agent[rag]'`")

    if rag_available:
        col1, col2 = st.columns([1, 1])
        with col1:
            default_dir = str(SAMPLE_DIR / "regulations") if HAS_SAMPLES else ""
            reg_dir = st.text_input("Regulations directory", default_dir)
            if st.button("Ingest Regulations", type="primary"):
                try:
                    with st.spinner("Ingesting documents..."):
                        rag = RegulatoryRAG()
                        count = rag.ingest_directory(reg_dir, reset=True)
                    st.success(f"Ingested {count} chunks")
                    sources = rag.list_sources()
                    if sources:
                        st.info(f"Index contents: {', '.join(sources)}")
                except FileNotFoundError as e:
                    st.error(str(e))

        with col2:
            query_text = st.text_input("Query regulations", placeholder="e.g., What does the AI Act say about human oversight?")
            if query_text and st.button("Search"):
                rag = RegulatoryRAG()
                if rag.vectorstore is None:
                    st.warning("No index found. Ingest documents first.")
                else:
                    results = rag.query(query_text, k=5)
                    sources = sorted({r["source"] for r in results})
                    chosen = st.selectbox("Filter by source", ["All"] + sources)
                    for i, r in enumerate(results, 1):
                        if chosen != "All" and r["source"] != chosen:
                            continue
                        with st.expander(f"#{i} [{r['source']}] — Relevance: {r['relevance']:.2f}"):
                            st.markdown(r["content"])

# ---------------------------------------------------------------------------
# Tab 2: Check Policy
# ---------------------------------------------------------------------------

with tab2:
    st.header("Policy Compliance Check")

    use_sample = False
    if HAS_SAMPLES:
        use_sample = st.toggle("Use bundled sample data (privacy_v1 + GDPR/AI Act rules)", key="sample_check")

    policy_text: Optional[str]
    rules_text: Optional[str]
    if use_sample:
        policy_text = (SAMPLE_DIR / "policies" / "privacy_v1.txt").read_text(encoding="utf-8")
        rules_text = (SAMPLE_DIR / "rules" / "gdpr_rules.yaml").read_text(encoding="utf-8")
        policy_name = "privacy_v1.txt"
    else:
        policy_file = st.file_uploader("Upload policy document (.txt)", type=["txt"])
        rules_file = st.file_uploader("Upload rules file (.yaml)", type=["yaml", "yml"])
        policy_text = policy_file.read().decode("utf-8", errors="replace") if policy_file else None
        rules_text = rules_file.read().decode("utf-8", errors="replace") if rules_file else None
        policy_name = policy_file.name if policy_file else "policy"

    threshold = st.slider(
        "Decision threshold", 0.0, 1.0, 0.5, 0.05,
        help="Rules with compliance strength below this fail; within 0.1 above it they are flagged as marginal (WARN).",
    )

    if policy_text and rules_text and st.button("Run Compliance Check", type="primary"):
        rules = _load_rules_or_error(rules_text)
        if rules:
            reasoner = ComplianceReasoner(threshold=threshold)
            with st.spinner("Evaluating policy against rules..."):
                report = reasoner.evaluate_policy(policy_text, rules)
            _remember("check", policy_name, report)
            _render_results(report, threshold)
            st.subheader("Export")
            _download_buttons(report, {"policy": policy_name, "threshold": threshold}, "check")

# ---------------------------------------------------------------------------
# Tab 3: Detect Drift
# ---------------------------------------------------------------------------

with tab3:
    st.header("Policy Drift Detection")

    use_sample_drift = False
    if HAS_SAMPLES:
        use_sample_drift = st.toggle("Use bundled sample policies (v1 vs v2)", key="sample_drift")

    v1_bytes: Optional[bytes]
    v2_bytes: Optional[bytes]
    if use_sample_drift:
        v1_bytes = (SAMPLE_DIR / "policies" / "privacy_v1.txt").read_bytes()
        v2_bytes = (SAMPLE_DIR / "policies" / "privacy_v2.txt").read_bytes()
    else:
        col1, col2 = st.columns(2)
        with col1:
            v1_file = st.file_uploader("Baseline version (.txt)", type=["txt"], key="v1")
        with col2:
            v2_file = st.file_uploader("Current version (.txt)", type=["txt"], key="v2")
        v1_bytes = v1_file.read() if v1_file else None
        v2_bytes = v2_file.read() if v2_file else None

    chunked = st.checkbox("Section-by-section comparison", value=True)
    st.caption("Legend: \U0001f534 drift · \U0001f7e2 stable · \U0001f7e1 new section · ⚪ removed section")

    if v1_bytes and v2_bytes and st.button("Detect Drift", type="primary"):
        from compliance_agent.engine.drift import DriftBridge

        v1_path = v2_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f1:
                f1.write(v1_bytes)
                v1_path = f1.name
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f2:
                f2.write(v2_bytes)
                v2_path = f2.name

            with st.spinner("Analyzing semantic drift..."):
                bridge = DriftBridge()
                result = bridge.detect(v1_path, v2_path, chunked=chunked, output_format="json")

            if result.get("chunked"):
                sections = result["sections"]
                drift_count = sum(1 for s in sections if s["status"] == "DRIFT")
                st.metric("Drifting Sections", f"{drift_count}/{len(sections)}")

                for s in sections:
                    icon_map = {"DRIFT": "\U0001f534", "OK": "\U0001f7e2", "ADDED": "\U0001f7e1", "REMOVED": "⚪"}
                    icon = icon_map.get(s["status"], "❓")
                    p_value = f"p={s['p_value']:.4f}" if isinstance(s.get("p_value"), float) else ""
                    st.markdown(f"{icon} **{s['section']}** — {s['status']} {p_value}")
            else:
                st.metric("Drift Detected", str(result.get("drift_detected", False)))
                st.metric("P-value", f"{result.get('p_value', 0):.4f}")
                st.metric("Severity", f"{result.get('severity', 0):.4f}")
        except RuntimeError as e:
            st.error(str(e))
            st.info("Install LegalDrift: pip install 'compliance-agent[drift]'")
        finally:
            for path in (v1_path, v2_path):
                if path and os.path.exists(path):
                    os.unlink(path)

# ---------------------------------------------------------------------------
# Tab 4: Reason
# ---------------------------------------------------------------------------

with tab4:
    st.header("Scenario Reasoning")

    use_sample_reason = False
    if HAS_SAMPLES:
        use_sample_reason = st.toggle("Use bundled sample scenario + rules", key="sample_reason")

    scenario_text: Optional[str]
    rules_text_r: Optional[str]
    if use_sample_reason:
        scenario_text = (SAMPLE_DIR / "rules" / "scenario_gdpr_check.yaml").read_text(encoding="utf-8")
        rules_text_r = (SAMPLE_DIR / "rules" / "gdpr_rules.yaml").read_text(encoding="utf-8")
        scenario_name = "scenario_gdpr_check.yaml"
    else:
        scenario_file = st.file_uploader("Upload scenario file (.yaml)", type=["yaml", "yml"], key="scenario")
        rule_file_r = st.file_uploader("Upload rules file (.yaml)", type=["yaml", "yml"], key="rules_reason")
        scenario_text = scenario_file.read().decode("utf-8", errors="replace") if scenario_file else None
        rules_text_r = rule_file_r.read().decode("utf-8", errors="replace") if rule_file_r else None
        scenario_name = scenario_file.name if scenario_file else "scenario"

    threshold_r = st.slider("Decision threshold", 0.0, 1.0, 0.5, 0.05, key="thresh_r")

    if scenario_text and rules_text_r and st.button("Run Reasoning", type="primary"):
        rules = _load_rules_or_error(rules_text_r)
        facts = None
        if rules:
            try:
                scenario_data = yaml.safe_load(scenario_text)
                description, facts = parse_scenario(scenario_data)
            except (yaml.YAMLError, ValueError) as e:
                st.error(f"Invalid scenario file: {e}")

        if rules and facts is not None:
            reasoner = ComplianceReasoner(threshold=threshold_r)
            with st.spinner("Running DDL reasoning..."):
                report = reasoner.evaluate_scenario(facts, rules)
            _remember("reason", scenario_name, report)

            decision_color = {"ALLOW": "green", "ALLOW_WITH_OBLIGATIONS": "orange", "BLOCK": "red"}.get(report.decision, "gray")
            st.markdown(f"## Decision: :{decision_color}[{report.decision}]")
            st.caption(f"Confidence {report.decision_confidence:.2f} — {description or scenario_name}")

            col1, col2 = st.columns(2)
            col1.metric("Risk Level", report.risk_level)
            col2.metric("Overall Score", f"{report.overall_score:.2f}")

            st.subheader("Facts")
            st.table([{"predicate": k, "value": f"{v:.2f}"} for k, v in sorted(facts.items())])

            _render_results(report, threshold_r)
            st.subheader("Export")
            _download_buttons(report, {"scenario": scenario_name, "threshold": threshold_r}, "reason")
