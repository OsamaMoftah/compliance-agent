"""Compliance checker — orchestrates RAG, drift detection, and rule reasoning."""

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel

from compliance_agent.engine.reasoner import ComplianceReasoner, ComplianceReport, print_report

console = Console()


class ComplianceChecker:
    """Orchestrator for end-to-end compliance checking.

    Combines regulatory RAG context retrieval, semantic drift detection,
    and DDL rule reasoning into a single compliance audit.
    """

    def __init__(self):
        self._rag = None
        self._drift = None

    @property
    def rag(self):
        if self._rag is None:
            from compliance_agent.engine.rag import RegulatoryRAG
            self._rag = RegulatoryRAG()
        return self._rag

    @property
    def drift(self):
        if self._drift is None:
            from compliance_agent.engine.drift import DriftBridge
            self._drift = DriftBridge()
        return self._drift

    def full_check(
        self,
        policy_path: str,
        rules_path: str,
        regulations_dir: Optional[str] = None,
        baseline_path: Optional[str] = None,
        threshold: float = 0.5,
    ) -> dict:
        """Run a complete compliance check on a policy document.

        Args:
            policy_path: Path to the policy document.
            rules_path: Path to YAML rules file.
            regulations_dir: Optional directory of regulatory docs for RAG context.
            baseline_path: Optional previous version for drift comparison.
            threshold: Decision threshold for rule evaluation.

        Returns:
            Dict with full results.
        """
        policy_text = Path(policy_path).read_text(encoding="utf-8")
        policy_name = Path(policy_path).name

        console.print(Panel(f"[bold]Compliance Check: {policy_name}[/bold]", style="blue"))
        console.print()

        # 1. Load rules
        reasoner = ComplianceReasoner(threshold=threshold)
        rules = reasoner.load_rules(rules_path)
        console.print(f"[dim]Loaded {len(rules)} rules from {rules_path}[/dim]")

        # 2. Rule reasoning
        console.print("\n[bold]Step 1: Rule Evaluation[/bold]")
        report = reasoner.evaluate_policy(policy_text, rules)
        print_report(report)

        # 3. Drift detection (if baseline provided)
        drift_result = None
        if baseline_path:
            console.print("\n[bold]Step 2: Drift Detection[/bold]")
            try:
                drift_result = self.drift.detect(baseline_path, policy_path, chunked=True, output_format="table")
            except RuntimeError as e:
                console.print(f"[yellow]Drift detection skipped: {e}[/yellow]")

        # 4. Regulatory context (if regulations provided)
        rag_results = None
        if regulations_dir and Path(regulations_dir).exists():
            console.print("\n[bold]Step 3: Regulatory Context[/bold]")
            try:
                self.rag.ingest_directory(regulations_dir)
                query = f"Requirements for {policy_name.replace('.txt', '').replace('_', ' ')}"
                rag_results = self.rag.query(query, k=3)
                self.rag.print_results(rag_results)
            except Exception as e:
                console.print(f"[yellow]RAG context skipped: {e}[/yellow]")

        # 5. Summary
        console.print()
        console.print(Panel(
            f"Policy: {policy_name}\n"
            f"Rules passed: {report.passed_count}/{report.total_count}\n"
            f"Overall score: {report.overall_score:.2f}\n"
            f"Risk level: {report.risk_level}",
            title="Check Summary",
            style="bold green" if report.risk_level == "LOW" else "bold yellow",
        ))

        return {
            "policy": policy_name,
            "report": report,
            "drift": drift_result,
            "rag": rag_results,
        }


def check_policy(
    policy_path: str,
    rules_path: str,
    regulations_dir: Optional[str] = None,
    baseline_path: Optional[str] = None,
    threshold: float = 0.5,
) -> ComplianceReport:
    """Convenience function for quick policy checks.

    Returns the ComplianceReport directly.
    """
    checker = ComplianceChecker()
    result = checker.full_check(policy_path, rules_path, regulations_dir, baseline_path, threshold)
    return result["report"]
