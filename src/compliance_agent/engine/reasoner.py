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

VALID_RULE_TYPES = {"obligation", "permission", "prohibition"}

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
    predicate_results: list[dict] = field(default_factory=list)
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


class RuleValidationError(ValueError):
    """Raised when a rules file cannot be safely evaluated."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


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
    negated_matches = []
    snippets = []
    for kw in keywords:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        found = list(pattern.finditer(text))
        positive_count = 0
        negated_count = 0
        for match in found:
            if _is_negated(text, match.start()):
                negated_count += 1
                snippets.append(_build_snippet(text, match.start(), match.end(), kw, negated=True))
            else:
                positive_count += 1
                snippets.append(_build_snippet(text, match.start(), match.end(), kw, negated=False))
        if positive_count:
            matches.append({"keyword": kw, "count": positive_count})
        if negated_count:
            negated_matches.append({"keyword": kw, "count": negated_count})

    if not matches:
        evidence = [f"'{m['keyword']}' negated {m['count']} time(s)" for m in negated_matches]
        return {"name": predicate.name, "matched": False, "score": 0.0, "evidence": evidence, "snippets": snippets}

    score = min(1.0, sum(m["count"] for m in matches))
    weighted_score = score * predicate.weight

    return {
        "name": predicate.name,
        "matched": True,
        "score": weighted_score,
        "evidence": [f"'{m['keyword']}' found {m['count']} time(s)" for m in matches]
        + [f"'{m['keyword']}' negated {m['count']} time(s)" for m in negated_matches],
        "snippets": snippets,
    }


def _build_snippet(text: str, start: int, end: int, keyword: str, negated: bool) -> dict:
    """Return compact local evidence around a predicate match."""
    snippet_start = max(0, start - 80)
    snippet_end = min(len(text), end + 80)
    snippet = " ".join(text[snippet_start:snippet_end].split())
    return {
        "keyword": keyword,
        "negated": negated,
        "start": start,
        "end": end,
        "text": snippet,
    }


def _is_negated(text: str, match_start: int) -> bool:
    """Detect simple local negation before a keyword match."""
    window = text[max(0, match_start - 30):match_start].lower()
    negation_patterns = (
        r"\bdo\s+not\b",
        r"\bdoes\s+not\b",
        r"\bwill\s+not\b",
        r"\bmust\s+not\b",
        r"\bshall\s+not\b",
        r"\bno\b",
        r"\bnot\b",
        r"\bnever\b",
        r"\bwithout\b",
    )
    return any(re.search(pattern, window) for pattern in negation_patterns)


def _parse_condition_keywords(condition: str) -> list[str]:
    """Extract search keywords from a rule condition string."""
    condition_lower = condition.lower()
    keywords = []

    # Extract quoted phrases
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", condition)
    keywords.extend(quoted)
    if keywords:
        return list(dict.fromkeys(keywords))

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
        errors = self.validate_rules_dict(data)
        if errors:
            raise RuleValidationError(errors)

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

    def validate_rules_file(self, rules_path: str) -> list[str]:
        """Return validation errors for a YAML rules file."""
        path = Path(rules_path)
        if not path.exists():
            return [f"Rules file not found: {rules_path}"]

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            return [f"Invalid YAML: {e}"]

        return self.validate_rules_dict(data)

    def validate_rules_dict(self, data: dict) -> list[str]:
        """Validate the community rule-pack schema used by the reasoner."""
        errors = []
        if not isinstance(data, dict):
            return ["Rules file must be a YAML mapping with a top-level 'rules' list."]

        rules = data.get("rules")
        if not isinstance(rules, list) or not rules:
            return ["Rules file must contain a non-empty top-level 'rules' list."]

        seen_ids = set()
        for index, rule in enumerate(rules, 1):
            prefix = f"rules[{index}]"
            if not isinstance(rule, dict):
                errors.append(f"{prefix} must be a mapping.")
                continue

            rule_id = rule.get("id")
            if not isinstance(rule_id, str) or not rule_id.strip():
                errors.append(f"{prefix}.id is required and must be a non-empty string.")
            elif rule_id in seen_ids:
                errors.append(f"{prefix}.id duplicates '{rule_id}'.")
            else:
                seen_ids.add(rule_id)

            rule_type = rule.get("type")
            if rule_type not in VALID_RULE_TYPES:
                errors.append(f"{prefix}.type must be one of: {', '.join(sorted(VALID_RULE_TYPES))}.")

            if not isinstance(rule.get("description"), str) or not rule["description"].strip():
                errors.append(f"{prefix}.description is required and must be a non-empty string.")

            predicates = rule.get("predicates")
            if not isinstance(predicates, list) or not predicates:
                errors.append(f"{prefix}.predicates must be a non-empty list.")
                continue

            for pred_index, predicate in enumerate(predicates, 1):
                pred_prefix = f"{prefix}.predicates[{pred_index}]"
                if not isinstance(predicate, dict):
                    errors.append(f"{pred_prefix} must be a mapping.")
                    continue
                if not isinstance(predicate.get("name"), str) or not predicate["name"].strip():
                    errors.append(f"{pred_prefix}.name is required and must be a non-empty string.")
                if not isinstance(predicate.get("condition"), str) or not predicate["condition"].strip():
                    errors.append(f"{pred_prefix}.condition is required and must be a non-empty string.")
                weight = predicate.get("weight", 1.0)
                if not isinstance(weight, (int, float)) or weight <= 0 or weight > 1:
                    errors.append(f"{pred_prefix}.weight must be a number greater than 0 and at most 1.")

        return errors

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
        evidence_strength = self._aggregate_scores([p["score"] for p in predicate_results])
        strength = self._compliance_strength(rule.type, evidence_strength)
        passed = strength >= self.threshold

        evidence = []
        for p in predicate_results:
            status = "FOUND" if p["matched"] else "MISSING"
            evidence.append(f"[{status}] {p['name']}: {', '.join(p['evidence']) if p['evidence'] else 'no match'}")

        explanation = f"{rule.type.upper()}: {rule.description}. " + " | ".join(evidence)
        explanation += f" (evidence={evidence_strength:.2f}, compliance_strength={strength:.2f}, threshold={self.threshold})"

        return RuleResult(
            rule_id=rule.id,
            rule_type=rule.type,
            description=rule.description,
            passed=passed,
            strength=strength,
            predicates_matched=[p for p in predicate_results if p["matched"]],
            predicate_results=predicate_results,
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

        strength = self._compliance_strength(rule.type, aggregated)

        passed = strength >= self.threshold

        details = ", ".join(f"{pv['name']}={pv['value']:.2f}" for pv in predicate_values)
        explanation = f"{rule.type.upper()}: {rule.description}. Predicates: {details}. Compliance strength={strength:.2f}"

        return RuleResult(
            rule_id=rule.id,
            rule_type=rule.type,
            description=rule.description,
            passed=passed,
            strength=strength,
            predicates_matched=[pv for pv in predicate_values if pv["value"] >= self.threshold],
            predicate_results=predicate_values,
            explanation=explanation,
        )

    def _aggregate_scores(self, scores: list[float]) -> float:
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def _compliance_strength(self, rule_type: str, evidence_strength: float) -> float:
        if rule_type == "obligation":
            return self.ddl.obligation(evidence_strength)
        if rule_type == "permission":
            return self.ddl.permission(evidence_strength)
        if rule_type == "prohibition":
            return self.ddl.prohibition(evidence_strength)
        return evidence_strength

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
