"""Compliance Agent Dashboard — Streamlit application."""

import streamlit as st
import yaml

from compliance_agent.engine.drift import DriftBridge
from compliance_agent.engine.rag import RegulatoryRAG
from compliance_agent.engine.reasoner import ComplianceReasoner

st.set_page_config(page_title="Compliance Agent", page_icon="\U0001f6e1\ufe0f", layout="wide")

st.title("\U0001f6e1\ufe0f Compliance Agent")
st.markdown("Regulatory intelligence, drift detection, and rule reasoning — in one dashboard.")

tab1, tab2, tab3, tab4 = st.tabs(["Monitor", "Check Policy", "Detect Drift", "Reason"])

# ---------------------------------------------------------------------------
# Tab 1: Monitor (Regulatory RAG)
# ---------------------------------------------------------------------------

with tab1:
    st.header("Regulatory Monitor")
    st.markdown("Ingest regulatory documents and query them with natural language.")

    col1, col2 = st.columns([1, 1])
    with col1:
        reg_dir = st.text_input("Regulations directory", "./sample_data/regulations/")
        if st.button("Ingest Regulations", type="primary"):
            with st.spinner("Ingesting documents..."):
                rag = RegulatoryRAG()
                count = rag.ingest_directory(reg_dir, reset=True)
                st.success(f"Ingested {count} chunks")
                sources = rag.list_sources()
                if sources:
                    st.info(f"Sources: {', '.join(sources)}")

    with col2:
        query_text = st.text_input("Query regulations", placeholder="e.g., What does the AI Act say about human oversight?")
        if query_text and st.button("Search"):
            rag = RegulatoryRAG()
            if rag.vectorstore is None:
                st.warning("No index found. Ingest documents first.")
            else:
                results = rag.query(query_text, k=5)
                for i, r in enumerate(results, 1):
                    score_color = "green" if r["score"] < 0.5 else "orange"
                    with st.expander(f"#{i} [{r['source']}] — Score: {r['score']:.3f}"):
                        st.markdown(r["content"])

# ---------------------------------------------------------------------------
# Tab 2: Check Policy
# ---------------------------------------------------------------------------

with tab2:
    st.header("Policy Compliance Check")

    policy_file = st.file_uploader("Upload policy document (.txt)", type=["txt"])
    rules_file = st.file_uploader("Upload rules file (.yaml)", type=["yaml", "yml"])
    threshold = st.slider("Detection threshold", 0.0, 1.0, 0.5, 0.05)

    if policy_file and rules_file and st.button("Run Compliance Check", type="primary"):
        policy_text = policy_file.read().decode("utf-8")
        rules_text = rules_file.read().decode("utf-8")
        rules_data = yaml.safe_load(rules_text)

        reasoner = ComplianceReasoner(threshold=threshold)
        rules = reasoner.parse_rules_dict(rules_data)

        with st.spinner("Evaluating policy against rules..."):
            report = reasoner.evaluate_policy(policy_text, rules)

        # Summary metrics
        col1, col2, col3 = st.columns(3)
        col1.metric("Risk Level", report.risk_level)
        col2.metric("Score", f"{report.overall_score:.2f}")
        col3.metric("Passed", f"{report.passed_count}/{report.total_count}")

        # Results table
        st.subheader("Rule-by-Rule Results")
        for r in report.results:
            icon = "\u2705" if r.passed else "\u274c"
            with st.expander(f"{icon} {r.rule_id} — {r.description[:80]}"):
                st.markdown(f"**Type:** {r.rule_type}")
                st.markdown(f"**Strength:** {r.strength:.3f}")
                st.markdown(f"**Explanation:** {r.explanation}")

        # Overall bar
        st.subheader("Compliance by Rule")
        chart_data = [{"rule": r.rule_id[-8:], "strength": r.strength, "threshold": threshold} for r in report.results]
        st.bar_chart(chart_data, x="rule", y=["strength", "threshold"])


# ---------------------------------------------------------------------------
# Tab 3: Detect Drift
# ---------------------------------------------------------------------------

with tab3:
    st.header("Policy Drift Detection")

    col1, col2 = st.columns(2)
    with col1:
        v1_file = st.file_uploader("Baseline version (.txt)", type=["txt"], key="v1")
    with col2:
        v2_file = st.file_uploader("Current version (.txt)", type=["txt"], key="v2")

    chunked = st.checkbox("Section-by-section comparison", value=True)

    if v1_file and v2_file and st.button("Detect Drift", type="primary"):
        with st.spinner("Analyzing semantic drift..."):
            bridge = DriftBridge()

            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f1:
                f1.write(v1_file.read())
                v1_path = f1.name
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f2:
                f2.write(v2_file.read())
                v2_path = f2.name

            try:
                result = bridge.detect(v1_path, v2_path, chunked=chunked, output_format="json")
                if result.get("chunked"):
                    sections = result["sections"]
                    drift_count = sum(1 for s in sections if s["status"] == "DRIFT")
                    st.metric("Drifting Sections", f"{drift_count}/{len(sections)}")

                    for s in sections:
                        icon_map = {"DRIFT": "\U0001f534", "OK": "\U0001f7e2", "ADDED": "\U0001f7e1", "REMOVED": "\u26aa"}
                        icon = icon_map.get(s["status"], "\u2753")
                        st.markdown(f"{icon} **{s['section']}** — {s['status']} (p={s.get('p_value', 'N/A'):.4f})")
                else:
                    drift = result.get("drift_detected", False)
                    st.metric("Drift Detected", str(drift))
                    st.metric("P-value", f"{result.get('p_value', 0):.4f}")
                    st.metric("Severity", f"{result.get('severity', 0):.4f}")
            except RuntimeError as e:
                st.error(str(e))
                st.info("Install LegalDrift: pip install legaldrift")

            import os
            os.unlink(v1_path)
            os.unlink(v2_path)

# ---------------------------------------------------------------------------
# Tab 4: Reason
# ---------------------------------------------------------------------------

with tab4:
    st.header("Scenario Reasoning")

    scenario_file = st.file_uploader("Upload scenario file (.yaml)", type=["yaml", "yml"], key="scenario")
    rule_file_r = st.file_uploader("Upload rules file (.yaml)", type=["yaml", "yml"], key="rules_reason")
    threshold_r = st.slider("Decision threshold", 0.0, 1.0, 0.5, 0.05, key="thresh_r")

    if scenario_file and rule_file_r and st.button("Run Reasoning", type="primary"):
        scenario_data = yaml.safe_load(scenario_file.read().decode("utf-8"))
        rules_data = yaml.safe_load(rule_file_r.read().decode("utf-8"))

        facts = scenario_data.get("scenario", scenario_data).get("facts", scenario_data.get("facts", {}))
        if isinstance(facts, list):
            facts = {f["predicate"]: f.get("value", 1.0) for f in facts}

        reasoner = ComplianceReasoner(threshold=threshold_r)
        rules = reasoner.parse_rules_dict(rules_data)

        with st.spinner("Running DDL reasoning..."):
            report = reasoner.evaluate_scenario(facts, rules)

        st.metric("Risk Level", report.risk_level)
        st.metric("Overall Score", f"{report.overall_score:.2f}")

        st.subheader("Facts")
        for k, v in facts.items():
            st.markdown(f"- **{k}**: {v:.2f}")

        st.subheader("Results")
        for r in report.results:
            icon = "\u2705" if r.passed else "\u274c"
            with st.expander(f"{icon} {r.rule_id} — {r.description[:80]}"):
                st.markdown(f"**Decision:** {r.rule_type.upper()}")
                st.markdown(f"**Strength:** {r.strength:.3f}")
                st.markdown(f"**Explanation:** {r.explanation}")
