"""Command-line interface for Compliance Agent.

Exit codes: 0 = success / all rules passed, 1 = findings (failed rules or
invalid rule pack), 2 = usage or input error.
"""

import json
import sys
from pathlib import Path
from typing import cast

import click
import yaml
from rich.console import Console

from compliance_agent.engine.checker import ComplianceChecker
from compliance_agent.engine.reasoner import (
    ComplianceReasoner,
    RuleValidationError,
    parse_scenario,
    print_report,
)
from compliance_agent.engine.reporting import build_provenance, report_to_dict, write_report

console = Console()

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


def _get_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("compliance-agent")
    except PackageNotFoundError:
        from compliance_agent import __version__

        return __version__


def _fail(message: str, code: int = EXIT_ERROR) -> None:
    console.print(f"[red]{message}[/red]")
    sys.exit(code)


def _read_text(path: str, label: str) -> str:
    p = Path(path)
    if not p.exists():
        _fail(f"{label} not found: {path}")
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        _fail(f"Could not read {label.lower()} '{path}': {e}")
    raise AssertionError("unreachable")


def _load_yaml(path: str, label: str) -> object:
    text = _read_text(path, label)
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        _fail(f"{label} is not valid YAML ({path}): {e}")
    raise AssertionError("unreachable")


def _load_rules(reasoner: ComplianceReasoner, rules_path: str):
    try:
        return reasoner.load_rules(rules_path)
    except FileNotFoundError as e:
        _fail(str(e))
    except yaml.YAMLError as e:
        _fail(f"Rules file is not valid YAML ({rules_path}): {e}")
    except RuleValidationError as e:
        console.print("[red]Rules validation failed:[/red]")
        for error in e.errors:
            console.print(f"  - {error}")
        sys.exit(EXIT_ERROR)
    raise AssertionError("unreachable")


@click.group()
@click.version_option(version=_get_version(), prog_name="compliance-agent")
def main():
    """Compliance Agent — regulatory intelligence, drift detection, and rule reasoning."""
    pass


@main.command()
@click.option("--source", "-s", required=True, help="Directory containing regulatory documents")
@click.option("--query", "-q", default=None, help="Query the index instead of ingesting")
@click.option("--reset", is_flag=True, help="Clear existing index before ingesting")
def monitor(source, query, reset):
    """Ingest and query regulatory documents using RAG."""
    try:
        from compliance_agent.engine.rag import RegulatoryRAG
    except ImportError:
        _fail("RAG dependencies are not installed. Install with: pip install 'compliance-agent[rag]'")

    rag = RegulatoryRAG()

    if query:
        if rag.vectorstore is None:
            _fail("No index found. Run 'compliance-agent monitor --source <dir>' first.")

        console.print(f"[bold]Query:[/bold] {query}")
        results = rag.query(query)
        rag.print_results(results)
    else:
        try:
            rag.ingest_directory(source, reset=reset)
        except FileNotFoundError as e:
            _fail(str(e))
        console.print(f"\n[green]Ready. Try:[/green] compliance-agent monitor --source {source} --query \"Your question\"")
        if sources := rag.list_sources():
            console.print(f"\n[dim]Indexed sources: {', '.join(sources)}[/dim]")


@main.command()
@click.option("--policy", "-p", required=True, help="Policy document to check")
@click.option("--rules", "-r", required=True, help="YAML rules file")
@click.option("--regulations", default=None, help="Directory of regulatory docs for RAG context")
@click.option("--baseline", default=None, help="Previous policy version for drift comparison")
@click.option("--threshold", default=0.5, type=float, help="Decision threshold (default: 0.5)")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
@click.option("--verbose", "-v", is_flag=True, help="Show full per-rule explanations")
def check(policy, rules, regulations, baseline, threshold, output_format, verbose):
    """Run a full compliance check on a policy document.

    Exits 0 when all applicable rules pass, 1 when any rule fails.
    """
    if not Path(policy).exists():
        _fail(f"Policy file not found: {policy}")

    if output_format == "json":
        reasoner = ComplianceReasoner(threshold=threshold)
        rule_list = _load_rules(reasoner, rules)
        policy_text = _read_text(policy, "Policy file")
        report = reasoner.evaluate_policy(policy_text, rule_list)
        data = report_to_dict(
            report,
            metadata={"policy": policy, "rules": rules, "threshold": threshold},
            provenance=build_provenance(policy, rules, threshold),
        )
        click.echo(json.dumps(data, indent=2))
        sys.exit(EXIT_FINDINGS if report.failed_count else EXIT_OK)

    checker = ComplianceChecker()
    try:
        result = checker.full_check(
            policy_path=policy,
            rules_path=rules,
            regulations_dir=regulations,
            baseline_path=baseline,
            threshold=threshold,
            verbose=verbose,
        )
    except FileNotFoundError as e:
        _fail(str(e))
    except yaml.YAMLError as e:
        _fail(f"Rules file is not valid YAML: {e}")
    except RuleValidationError as e:
        console.print("[red]Rules validation failed:[/red]")
        for error in e.errors:
            console.print(f"  - {error}")
        sys.exit(EXIT_ERROR)

    sys.exit(EXIT_FINDINGS if result["report"].failed_count else EXIT_OK)


@main.command()
@click.option("--policy", "-p", required=True, help="Policy document to check")
@click.option("--rules", "-r", required=True, help="YAML rules file")
@click.option("--output", "-o", required=True, help="Report output path (.json, .md, or .html)")
@click.option("--threshold", default=0.5, type=float, help="Decision threshold (default: 0.5)")
def report(policy, rules, output, threshold):
    """Generate a shareable compliance review report."""
    reasoner = ComplianceReasoner(threshold=threshold)
    rule_list = _load_rules(reasoner, rules)
    policy_text = _read_text(policy, "Policy file")

    compliance_report = reasoner.evaluate_policy(policy_text, rule_list)
    try:
        output_path = write_report(
            compliance_report,
            output,
            metadata={"policy": policy, "rules": rules, "threshold": threshold},
            provenance=build_provenance(policy, rules, threshold),
        )
    except (ValueError, OSError) as e:
        _fail(str(e))
    console.print(f"[green]Report written:[/green] {output_path}")


@main.command("validate-rules")
@click.option("--rules", "-r", required=True, help="YAML rules file")
def validate_rules(rules):
    """Validate a YAML rules file before using it in checks.

    Exits 0 when valid, 1 when validation errors are found.
    """
    reasoner = ComplianceReasoner()
    errors = reasoner.validate_rules_file(rules)
    if errors:
        console.print("[red]Rules validation failed:[/red]")
        for error in errors:
            console.print(f"  - {error}")
        sys.exit(EXIT_FINDINGS)

    data = cast(dict, _load_yaml(rules, "Rules file"))
    for warning in reasoner.rule_pack_warnings(data):
        console.print(f"[yellow]Warning:[/yellow] {warning}")

    rule_list = reasoner.parse_rules_dict(data)
    console.print(f"[green]Rules are valid.[/green] Loaded {len(rule_list)} rule(s).")


@main.command()
@click.argument("baseline")
@click.argument("current")
@click.option("--chunk", "-c", is_flag=True, help="Section-by-section detection")
@click.option("--threshold", default=0.05, type=float, help="Drift detection p-value threshold (default: 0.05)")
@click.option("--output", "-o", type=click.Choice(["table", "json"]), default="table", help="Output format")
def drift(baseline, current, chunk, threshold, output):
    """Detect semantic drift between two policy versions."""
    from compliance_agent.engine.drift import DriftBridge

    for path, label in ((baseline, "Baseline"), (current, "Current")):
        if not Path(path).exists():
            _fail(f"{label} policy file not found: {path}")

    bridge = DriftBridge()
    try:
        bridge.detect(baseline, current, chunked=chunk, output_format=output, threshold=threshold)
    except RuntimeError as e:
        _fail(str(e))


@main.command()
@click.option("--scenario", "-s", "scenario_path", required=True, help="YAML scenario file with facts")
@click.option("--rules", "-r", required=True, help="YAML rules file")
@click.option("--threshold", default=0.5, type=float, help="Decision threshold")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
@click.option("--verbose", "-v", is_flag=True, help="Show full per-rule explanations")
def reason(scenario_path, rules, threshold, output_format, verbose):
    """Evaluate a compliance scenario against DDL rules."""
    data = _load_yaml(scenario_path, "Scenario file")
    try:
        description, facts = parse_scenario(data)
    except ValueError as e:
        _fail(f"Invalid scenario file ({scenario_path}): {e}")
        return

    reasoner = ComplianceReasoner(threshold=threshold)
    rule_list = _load_rules(reasoner, rules)

    scenario_report = reasoner.evaluate_scenario(facts, rule_list)

    if output_format == "json":
        payload = report_to_dict(
            scenario_report,
            metadata={"scenario": scenario_path, "rules": rules, "threshold": threshold},
            provenance=build_provenance(scenario_path, rules, threshold),
        )
        click.echo(json.dumps(payload, indent=2))
    else:
        console.print(f"[bold]Scenario:[/bold] {description or scenario_path}")
        console.print(f"[dim]Evaluating {len(rule_list)} rules against {len(facts)} facts...[/dim]")
        print_report(scenario_report, verbose=verbose)

    sys.exit(EXIT_FINDINGS if scenario_report.failed_count else EXIT_OK)


@main.command()
@click.option("--port", default=8501, type=int, help="Dashboard port (default: 8501)")
def dashboard(port):
    """Launch the Streamlit compliance dashboard."""
    try:
        from streamlit.web import cli as stcli
    except ImportError:
        _fail("Streamlit is not installed. Install with: pip install 'compliance-agent[dashboard]'")

    dashboard_path = Path(__file__).parent / "dashboard" / "app.py"
    if not dashboard_path.exists():
        _fail(f"Dashboard not found at: {dashboard_path}")

    console.print(f"[green]Launching dashboard at http://localhost:{port}[/green]")
    sys.argv = ["streamlit", "run", str(dashboard_path), f"--server.port={port}"]
    stcli.main()


if __name__ == "__main__":
    main()
