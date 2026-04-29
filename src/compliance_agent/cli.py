"""Command-line interface for Compliance Agent."""

import sys
from pathlib import Path

import click
from rich.console import Console

from compliance_agent.engine.checker import ComplianceChecker
from compliance_agent.engine.reasoner import ComplianceReasoner, print_report

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="compliance-agent")
def main():
    """Compliance Agent — regulatory intelligence, drift detection, and rule reasoning."""
    pass


@main.command()
@click.option("--source", "-s", required=True, help="Directory containing regulatory documents")
@click.option("--query", "-q", default=None, help="Query the index instead of ingesting")
@click.option("--reset", is_flag=True, help="Clear existing index before ingesting")
def monitor(source, query, reset):
    """Ingest and query regulatory documents using RAG."""
    from compliance_agent.engine.rag import RegulatoryRAG

    rag = RegulatoryRAG()

    if query:
        if rag.vectorstore is None:
            console.print("[red]No index found. Run 'compliance-agent monitor --source <dir>' first.[/red]")
            sys.exit(1)

        console.print(f"[bold]Query:[/bold] {query}")
        results = rag.query(query)
        rag.print_results(results)
    else:
        rag.ingest_directory(source, reset=reset)
        console.print(f"\n[green]Ready. Try:[/green] compliance-agent monitor --source {source} --query \"Your question\"")
        if sources := rag.list_sources():
            console.print(f"\n[dim]Indexed sources: {', '.join(sources)}[/dim]")


@main.command()
@click.option("--policy", "-p", required=True, help="Policy document to check")
@click.option("--rules", "-r", required=True, help="YAML rules file")
@click.option("--regulations", default=None, help="Directory of regulatory docs for RAG context")
@click.option("--baseline", default=None, help="Previous policy version for drift comparison")
@click.option("--threshold", default=0.5, type=float, help="Decision threshold (default: 0.5)")
def check(policy, rules, regulations, baseline, threshold):
    """Run a full compliance check on a policy document."""
    checker = ComplianceChecker()
    checker.full_check(
        policy_path=policy,
        rules_path=rules,
        regulations_dir=regulations,
        baseline_path=baseline,
        threshold=threshold,
    )


@main.command()
@click.argument("baseline")
@click.argument("current")
@click.option("--chunk", "-c", is_flag=True, help="Section-by-section detection")
@click.option("--output", "-o", type=click.Choice(["table", "json"]), default="table", help="Output format")
def drift(baseline, current, chunk, output):
    """Detect semantic drift between two policy versions."""
    from compliance_agent.engine.drift import DriftBridge

    bridge = DriftBridge()
    try:
        bridge.detect(baseline, current, chunked=chunk, output_format=output)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)


@main.command()
@click.option("--scenario", "-s", required=True, help="YAML scenario file with facts")
@click.option("--rules", "-r", required=True, help="YAML rules file")
@click.option("--threshold", default=0.5, type=float, help="Decision threshold")
def reason(scenario, rules, threshold):
    """Evaluate a compliance scenario against DDL rules."""
    import yaml

    data = yaml.safe_load(Path(scenario).read_text(encoding="utf-8"))
    facts = data.get("scenario", data).get("facts", data.get("facts", {}))
    if isinstance(facts, list):
        facts = {f["predicate"]: f.get("value", 1.0) for f in facts}

    reasoner = ComplianceReasoner(threshold=threshold)
    rule_list = reasoner.load_rules(rules)

    console.print(f"[bold]Scenario:[/bold] {data.get('scenario', {}).get('description', scenario)}")
    console.print(f"[dim]Evaluating {len(rule_list)} rules against {len(facts)} facts...[/dim]")

    report = reasoner.evaluate_scenario(facts, rule_list)
    print_report(report)


@main.command()
@click.option("--port", default=8501, type=int, help="Dashboard port (default: 8501)")
def dashboard(port):
    """Launch the Streamlit compliance dashboard."""
    try:
        from streamlit.web import cli as stcli
    except ImportError:
        console.print("[red]Streamlit is not installed. Install with: pip install streamlit[/red]")
        sys.exit(1)

    dashboard_path = Path(__file__).parent / "dashboard" / "app.py"
    if not dashboard_path.exists():
        console.print(f"[red]Dashboard not found at: {dashboard_path}[/red]")
        sys.exit(1)

    console.print(f"[green]Launching dashboard at http://localhost:{port}[/green]")
    sys.argv = ["streamlit", "run", str(dashboard_path), f"--server.port={port}"]
    stcli.main()
