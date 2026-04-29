"""DDL rule reasoning engine — differentiable deontic logic for compliance rules.

Includes a self-contained DDL implementation so DiffDDL is an optional dependency.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

console = Console()

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Predicate:
    name: str
    condition: str
    weight: float = 1.0


@dataclass
class ComplianceRule:
    id: str
    type: str            # obligation, permission, prohibition
    description: str
    predicates: list[Predicate] = field(default_factory=list)


@dataclass
class RuleResult:
    rule_id: str
    rule_type: str
    description: str
    passed: bool
    strength: float
    predicates_matched: list[dict] = field(default_factory=list)
    explanation: str = ""


@dataclass
class ComplianceReport:
    results: list[RuleResult] = field(default_factory=list)
    overall_score: float = 0.0
    risk_level: str = "UNKNOWN"
    summary: str = ""

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total_count(self) -> int:
        return len(self.results)


# ---------------------------------------------------------------------------
# Self-contained DDL implementation
# ---------------------------------------------------------------------------


class DDL:
    """Lightweight differentiable deontic logic operations.

    Mirrors the interface of DiffDDL for basic compliance reasoning
    without requiring the full PyTorch-based library.
    """

    def __init__(self, fuzzy: bool = True, temperature: float = 2.0):
        self.fuzzy = fuzzy
        self.temperature = temperature

    def soft_and(self, x: float, y: float) -> float:
        return x * y

    def soft_or(self, x: float, y: float) -> float:
        return x + y - x * y

    def soft_not(self, x: float) -> float:
        return 1.0 - x

    def soft_implies(self, x: float, y: float) -> float:
        return self.soft_or(self.soft_not(x), y)

    def obligation(self, x: float) -> float:
        return x

    def permission(self, x: float) -> float:
        return x

    def prohibition(self, x: float) -> float:
        return self.soft_not(x)

    def conflict_score(self, obligation: float, permission: float, prohibition: float) -> float:
        """Higher score = more conflict."""
        return (obligation * prohibition) + (obligation * (1 - permission)) * 0.5

    def resolve(
        self,
        obligation: float,
        permission: float,
        prohibition: float,
        threshold: float = 0.5,
    ) -> tuple[str, float]:
        """Resolve deontic conflict into a decision.

        Returns:
            (decision: str, confidence: float)
            Decisions: ALLOW, ALLOW_WITH_OBLIGATIONS, BLOCK
        """
        conflict = self.conflict_score(obligation, permission, prohibition)

        if prohibition > obligation and prohibition > threshold:
            return "BLOCK", prohibition
        elif conflict > 0.3:
            return "ALLOW_WITH_OBLIGATIONS", max(obligation, permission)
        else:
            return "ALLOW", max(permission, 1 - prohibition)


# ---------------------------------------------------------------------------
# Predicate extractor
# ---------------------------------------------------------------------------


def extract_predicate(predicate: Predicate, text: str) -> dict:
    """Evaluate a single predicate against policy text.

    Uses keyword matching from the condition string.
    """
    keywords = _parse_condition_keywords(predicate.condition)
    matches = []
    for kw in keywords:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        found = len(pattern.findall(text))
        if found:
            matches.append({"keyword": kw, "count": found})

    if not matches:
        return {"name": predicate.name, "matched": False, "score": 0.0, "evidence": []}

    score = min(1.0, sum(m["count"] for m in matches) * 0.5)
    weighted_score = score * predicate.weight

    return {
        "name": predicate.name,
        "matched": True,
        "score": weighted_score,
        "evidence": [f"'{m['keyword']}' found {m['count']} time(s)" for m in matches],
    }


def _parse_condition_keywords(condition: str) -> list[str]:
    """Extract search keywords from a rule condition string."""
    condition_lower = condition.lower()
    keywords = []

    # Extract quoted phrases
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", condition)
    keywords.extend(quoted)

    # Also extract key terms after "contains" or "mentions"
    terms = re.findall(r'(?:contains|mentions|references)\s+["\']?([a-z_\s]+)["\']?', condition_lower)
    for term in terms:
        for word in term.strip().split():
            if len(word) > 3 and word not in ("document", "text", "the", "and", "that"):
                keywords.append(word)

    # If no keywords extracted, use the whole condition words
    if not keywords:
        words = condition_lower.replace('"', "").replace("'", "").split()
        stopwords = {
            "document", "text", "the", "and", "that", "must",
            "shall", "this", "with",
        }
        keywords = [w for w in words if len(w) > 3 and w not in stopwords]

    return list(dict.fromkeys(keywords))  # deduplicate preserving order


# ---------------------------------------------------------------------------
# Compliance Reasoner
# ---------------------------------------------------------------------------


class ComplianceReasoner:
    """Applies DDL rules to policy documents and scenarios."""

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self.ddl = DDL(fuzzy=True)

    def load_rules(self, rules_path: str) -> list[ComplianceRule]:
        """Load compliance rules from a YAML file."""
        path = Path(rules_path)
        if not path.exists():
            raise FileNotFoundError(f"Rules file not found: {rules_path}")

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return self.parse_rules_dict(data)

    def parse_rules_dict(self, data: dict) -> list[ComplianceRule]:
        """Parse rules from an already-loaded YAML dict (for dashboard/API use)."""
        rules = []
        for r in data.get("rules", []):
            predicates = [
                Predicate(
                    name=p["name"],
                    condition=p["condition"],
                    weight=p.get("weight", 1.0),
                )
                for p in r.get("predicates", [])
            ]
            rules.append(
                ComplianceRule(
                    id=r["id"],
                    type=r["type"],
                    description=r["description"],
                    predicates=predicates,
                )
            )
        return rules

    def evaluate_policy(self, policy_text: str, rules: list[ComplianceRule]) -> ComplianceReport:
        """Evaluate a policy document against a set of compliance rules."""
        results = []
        for rule in rules:
            result = self._evaluate_rule(rule, policy_text)
            results.append(result)

        score = self._calculate_overall_score(results)
        risk = self._determine_risk_level(score, results)

        failing = [r for r in results if not r.passed]
        summary_parts = [
            f"{len(results)} rules evaluated: "
            f"{sum(1 for r in results if r.passed)} passed, "
            f"{len(failing)} failed."
        ]
        if failing:
            summary_parts.append(f"Top failures: {', '.join(r.rule_id for r in failing[:3])}")

        return ComplianceReport(results=results, overall_score=score, risk_level=risk, summary=" ".join(summary_parts))

    def evaluate_scenario(self, facts: dict, rules: list[ComplianceRule]) -> ComplianceReport:
        """Evaluate a scenario (facts dict) against rules using DDL reasoning."""
        results = []
        for rule in rules:
            result = self._evaluate_rule_with_facts(rule, facts)
            results.append(result)

        score = self._calculate_overall_score(results)
        risk = self._determine_risk_level(score, results)

        return ComplianceReport(
            results=results,
            overall_score=score,
            risk_level=risk,
            summary=f"Scenario evaluated: {len(results)} rules, score={score:.2f}",
        )

    def _evaluate_rule(self, rule: ComplianceRule, text: str) -> RuleResult:
        """Evaluate a single rule against policy text."""
        predicate_results = [extract_predicate(p, text) for p in rule.predicates]

        scores = [p["score"] for p in predicate_results]

        if not scores:
            strength = 0.0
        else:
            strength = sum(scores) / len(scores)

        passed = strength >= self.threshold

        evidence = []
        for p in predicate_results:
            status = "PASS" if p["matched"] else "MISS"
            evidence.append(f"[{status}] {p['name']}: {', '.join(p['evidence']) if p['evidence'] else 'no match'}")

        explanation = f"{rule.type.upper()}: {rule.description}. " + " | ".join(evidence)
        explanation += f" (strength={strength:.2f}, threshold={self.threshold})"

        return RuleResult(
            rule_id=rule.id,
            rule_type=rule.type,
            description=rule.description,
            passed=passed,
            strength=strength,
            predicates_matched=[p for p in predicate_results if p["matched"]],
            explanation=explanation,
        )

    def _evaluate_rule_with_facts(self, rule: ComplianceRule, facts: dict) -> RuleResult:
        """Evaluate a rule against provided facts using DDL logic."""
        predicate_values = []
        for pred in rule.predicates:
            value = facts.get(pred.name, 0.0)
            predicate_values.append({"name": pred.name, "value": value, "weight": pred.weight})

        # Aggregate predicate values
        if predicate_values:
            weighted_values = [pv["value"] * pv["weight"] for pv in predicate_values]
            aggregated = sum(weighted_values) / sum(pv["weight"] for pv in predicate_values)
        else:
            aggregated = 0.0

        # Apply deontic operator
        if rule.type == "obligation":
            strength = self.ddl.obligation(aggregated)
        elif rule.type == "permission":
            strength = self.ddl.permission(aggregated)
        elif rule.type == "prohibition":
            strength = self.ddl.prohibition(aggregated)
        else:
            strength = aggregated

        passed = strength >= self.threshold

        details = ", ".join(f"{pv['name']}={pv['value']:.2f}" for pv in predicate_values)
        explanation = f"{rule.type.upper()}: {rule.description}. Predicates: {details}. Strength={strength:.2f}"

        return RuleResult(
            rule_id=rule.id,
            rule_type=rule.type,
            description=rule.description,
            passed=passed,
            strength=strength,
            predicates_matched=[pv for pv in predicate_values if pv["value"] >= self.threshold],
            explanation=explanation,
        )

    def _calculate_overall_score(self, results: list[RuleResult]) -> float:
        if not results:
            return 1.0
        return sum(r.strength for r in results) / len(results)

    def _determine_risk_level(self, score: float, results: list[RuleResult]) -> str:
        failed = sum(1 for r in results if not r.passed)
        if failed == 0:
            return "LOW"
        elif failed <= len(results) * 0.3:
            return "MEDIUM"
        else:
            return "HIGH"


def print_report(report: ComplianceReport) -> None:
    """Pretty-print a compliance report."""
    risk_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}
    color = risk_color.get(report.risk_level, "white")

    console.print(f"\n[bold]Compliance Score:[/bold] [{color}]{report.overall_score:.2f}[/{color}]")
    console.print(f"[bold]Risk Level:[/bold] [{color}]{report.risk_level}[/{color}]")
    console.print(f"[bold]Summary:[/bold] {report.summary}")

    table = Table(title="Rule Results", show_lines=True)
    table.add_column("Rule ID", style="cyan", width=20)
    table.add_column("Type", width=12)
    table.add_column("Result", width=10)
    table.add_column("Strength", width=10)
    table.add_column("Explanation")

    for r in report.results:
        result_style = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        table.add_row(r.rule_id, r.rule_type, result_style, f"{r.strength:.2f}", r.explanation[:120])

    console.print(table)
