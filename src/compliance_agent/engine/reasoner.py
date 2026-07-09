"""DDL rule reasoning engine — deontic compliance rules over policy text.

Implements rule schema v2 (explicit keywords/patterns, severities, citations,
applicability gates, and prohibition exceptions) with sentence-scoped negation
and a self-contained soft-logic (DDL) layer so DiffDDL stays optional.
Schema v1 prose conditions are still accepted with a deprecation warning.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from rich.console import Console
from rich.table import Table

console = Console()

VALID_RULE_TYPES = {"obligation", "permission", "prohibition"}
VALID_SEVERITIES = {"critical", "major", "minor"}
VALID_MATCH_MODES = {"any", "all"}
SEVERITY_WEIGHTS = {"critical": 3.0, "major": 2.0, "minor": 1.0}
DEFAULT_SEVERITY = "major"
SUPPORTED_SCHEMA_VERSIONS = {1, 2}

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_NA = "N/A"

# Results within this band above the threshold pass but are flagged for review.
WARN_BAND = 0.1

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Predicate:
    name: str
    condition: str = ""
    weight: float = 1.0
    keywords: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    match: str = "any"  # 'any': one keyword suffices; 'all': graded coverage


@dataclass
class ComplianceRule:
    id: str
    type: str            # obligation, permission, prohibition
    description: str
    predicates: list[Predicate] = field(default_factory=list)
    severity: str = DEFAULT_SEVERITY
    citation: str = ""
    applies_when: list[Predicate] = field(default_factory=list)
    unless: list[Predicate] = field(default_factory=list)  # prohibition exceptions


@dataclass
class RuleResult:
    rule_id: str
    rule_type: str
    description: str
    passed: bool
    strength: float
    status: str = STATUS_PASS
    severity: str = DEFAULT_SEVERITY
    citation: str = ""
    applicable: bool = True
    predicates_matched: list[dict] = field(default_factory=list)
    predicate_results: list[dict] = field(default_factory=list)
    explanation: str = ""


@dataclass
class ComplianceReport:
    results: list[RuleResult] = field(default_factory=list)
    overall_score: float = 0.0
    risk_level: str = "UNKNOWN"
    summary: str = ""
    decision: str = ""             # scenario mode: ALLOW / ALLOW_WITH_OBLIGATIONS / BLOCK
    decision_confidence: float = 0.0

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.status in (STATUS_PASS, STATUS_WARN))

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_FAIL)

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_WARN)

    @property
    def na_count(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_NA)

    @property
    def applicable_count(self) -> int:
        return sum(1 for r in self.results if r.applicable)

    @property
    def total_count(self) -> int:
        return len(self.results)

    def severity_breakdown(self) -> dict[str, int]:
        """Count of FAIL results per severity."""
        breakdown = {"critical": 0, "major": 0, "minor": 0}
        for r in self.results:
            if r.status == STATUS_FAIL and r.severity in breakdown:
                breakdown[r.severity] += 1
        return breakdown


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
        """Resolve deontic activations into a decision.

        Args:
            obligation: unmet-obligation pressure (0 = all obligations satisfied).
            permission: enabling-permission level (1 = fully permitted).
            prohibition: violation level (1 = prohibited conduct fully evidenced).

        Returns:
            (decision, confidence) where decision is one of
            ALLOW, ALLOW_WITH_OBLIGATIONS, BLOCK.
        """
        conflict = self.conflict_score(obligation, permission, prohibition)

        if prohibition > threshold and prohibition >= obligation:
            return "BLOCK", prohibition
        if obligation > threshold or conflict > 0.3:
            return "ALLOW_WITH_OBLIGATIONS", max(obligation, conflict)
        return "ALLOW", max(permission, 1.0 - prohibition)


# ---------------------------------------------------------------------------
# Sentence segmentation and negation
# ---------------------------------------------------------------------------

_WORD_START = re.compile(r"\w")
_SENTENCE_BREAK = re.compile(r"[.!?]+[\"')\]]*(?:\s+|$)|\n{2,}")

_PRE_NEGATION_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bdo\s+not\b",
        r"\bdoes\s+not\b",
        r"\bdid\s+not\b",
        r"\bwill\s+not\b",
        r"\bmust\s+not\b",
        r"\bshall\s+not\b",
        r"\bmay\s+not\b",
        r"\bcannot\b",
        r"\bcan\s+not\b",
        r"\bno\b",
        r"\bnot\b",
        r"\bnever\b",
        r"\bwithout\b",
        r"\bprohibit(?:s|ed)?\b",
        r"\bforbid(?:s|den)?\b",
    )
)

_POST_NEGATION = re.compile(
    r"^\s*(?:is|are|was|were|will\s+be|shall\s+be|remains?)\s+"
    r"(?:strictly\s+|expressly\s+)?"
    r"(?:not\b|never\b|prohibited\b|forbidden\b|banned\b|disallowed\b)",
    re.IGNORECASE,
)


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Split text into (start, end) sentence spans.

    Sentence boundaries are terminal punctuation or blank lines, so negation
    scope never leaks across sentences.
    """
    spans = []
    start = 0
    for match in _SENTENCE_BREAK.finditer(text):
        end = match.end()
        if text[start:end].strip():
            spans.append((start, end))
        start = end
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text)))
    return spans


def _span_for(spans: list[tuple[int, int]], pos: int, text_len: int) -> tuple[int, int]:
    for start, end in spans:
        if start <= pos < end:
            return start, end
    return max(0, pos - 80), min(text_len, pos + 80)


def _is_negated(text: str, sentence: tuple[int, int], match_start: int, match_end: int) -> bool:
    """Detect negation of a keyword match within its own sentence only."""
    sent_start, sent_end = sentence
    before = text[sent_start:match_start]
    if any(p.search(before) for p in _PRE_NEGATION_PATTERNS):
        return True
    after = text[match_end:sent_end]
    return bool(_POST_NEGATION.search(after))


# ---------------------------------------------------------------------------
# Predicate extractor
# ---------------------------------------------------------------------------


def _term_pattern(term: str) -> "re.Pattern[str]":
    """Compile a keyword into a word-boundary-aware, case-insensitive pattern."""
    escaped = re.escape(term)
    prefix = r"\b" if term and _WORD_START.match(term[0]) else ""
    suffix = r"\b" if term and _WORD_START.match(term[-1]) else ""
    return re.compile(prefix + escaped + suffix, re.IGNORECASE)


def _predicate_terms(predicate: Predicate) -> tuple[list[tuple[str, "re.Pattern[str]"]], bool]:
    """Return (label, pattern) search terms and whether they were explicit.

    Explicit `keywords`/`patterns` (schema v2) are preferred; otherwise terms
    are inferred from the v1 prose `condition`.
    """
    explicit = bool(predicate.keywords or predicate.patterns)
    if explicit:
        terms = [(kw, _term_pattern(kw)) for kw in predicate.keywords]
        terms += [(p, re.compile(p, re.IGNORECASE)) for p in predicate.patterns]
    else:
        inferred = _parse_condition_keywords(predicate.condition)
        terms = [(kw, _term_pattern(kw)) for kw in inferred]
    return terms, explicit


def extract_predicate(predicate: Predicate, text: str, spans: Optional[list[tuple[int, int]]] = None) -> dict:
    """Evaluate a single predicate against policy text.

    Scoring:
    - Explicit keyword lists with ``match: any`` (default) treat keywords as
      alternative phrasings: any non-negated hit scores 1.0.
    - ``match: all`` and inferred v1 conditions use graded coverage
      (matched terms / total terms), so a single generic word no longer
      saturates the score.
    """
    if spans is None:
        spans = _sentence_spans(text)

    terms, explicit = _predicate_terms(predicate)
    if not terms:
        return {
            "name": predicate.name,
            "matched": False,
            "score": 0.0,
            "evidence": ["no searchable terms defined"],
            "snippets": [],
        }

    matched_terms = 0
    evidence = []
    negated_evidence = []
    snippets = []

    for label, pattern in terms:
        positive = 0
        negated = 0
        for match in pattern.finditer(text):
            sentence = _span_for(spans, match.start(), len(text))
            is_neg = _is_negated(text, sentence, match.start(), match.end())
            snippets.append(_build_snippet(text, sentence, match.start(), match.end(), label, negated=is_neg))
            if is_neg:
                negated += 1
            else:
                positive += 1
        if positive:
            matched_terms += 1
            evidence.append(f"'{label}' found {positive} time(s)")
        if negated:
            negated_evidence.append(f"'{label}' negated {negated} time(s)")

    if explicit and predicate.match == "any":
        score = 1.0 if matched_terms else 0.0
    else:
        score = matched_terms / len(terms)

    return {
        "name": predicate.name,
        "matched": matched_terms > 0,
        "score": score,
        "evidence": evidence + negated_evidence,
        "snippets": snippets,
    }


def _build_snippet(
    text: str,
    sentence: tuple[int, int],
    start: int,
    end: int,
    keyword: str,
    negated: bool,
) -> dict:
    """Return the full matched sentence as local evidence."""
    sent_start, sent_end = sentence
    snippet = " ".join(text[sent_start:sent_end].split())
    return {
        "keyword": keyword,
        "negated": negated,
        "start": start,
        "end": end,
        "sentence": snippet,
        "text": snippet,
    }


def _parse_condition_keywords(condition: str) -> list[str]:
    """Infer search keywords from a v1 prose condition string (legacy mode)."""
    condition_lower = condition.lower()
    keywords = []

    # Extract quoted phrases
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", condition)
    keywords.extend(quoted)
    if keywords:
        return list(dict.fromkeys(keywords))

    stopwords = {
        "document", "text", "the", "and", "that", "must",
        "shall", "this", "with", "from", "their", "them",
    }

    # Extract key terms after verbs like "contains"/"mentions", splitting
    # comma- and or-separated alternatives so no term is silently dropped.
    terms = re.findall(
        r"(?:contains|mentions|references|specifies|guarantees|provides|allows)\s+([a-z0-9_,'\"/\s-]+)",
        condition_lower,
    )
    for term in terms:
        for segment in re.split(r",|\bor\b|\band\b", term):
            for word in segment.strip().split():
                if len(word) > 3 and word not in stopwords:
                    keywords.append(word)

    # If no keywords extracted, use the whole condition words
    if not keywords:
        words = condition_lower.replace('"', "").replace("'", "").split()
        keywords = [w for w in words if len(w) > 3 and w not in stopwords]

    return list(dict.fromkeys(keywords))  # deduplicate preserving order


# ---------------------------------------------------------------------------
# Scenario parsing
# ---------------------------------------------------------------------------


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def parse_scenario(data: Any) -> tuple[str, dict[str, float]]:
    """Parse a scenario YAML payload into (description, facts).

    Accepts either a top-level ``scenario:`` mapping or a bare mapping, and
    facts as either a list of ``{predicate, value}`` entries or a mapping.
    Raises ValueError with a human-readable message on malformed input.
    """
    if not isinstance(data, dict):
        raise ValueError("Scenario file must be a YAML mapping containing a 'facts' entry.")

    scenario = data.get("scenario", data)
    if not isinstance(scenario, dict):
        raise ValueError("'scenario' must be a mapping.")

    facts_raw = scenario.get("facts", data.get("facts"))
    if facts_raw is None:
        raise ValueError("Scenario is missing a 'facts' list or mapping.")

    facts: dict[str, float] = {}
    if isinstance(facts_raw, list):
        for index, entry in enumerate(facts_raw, 1):
            if not isinstance(entry, dict) or "predicate" not in entry:
                raise ValueError(f"facts[{index}] must be a mapping with a 'predicate' key.")
            value = entry.get("value", 1.0)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"facts[{index}].value must be a number between 0 and 1.")
            facts[str(entry["predicate"])] = _clamp(float(value))
    elif isinstance(facts_raw, dict):
        for name, value in facts_raw.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"Fact '{name}' must map to a number between 0 and 1.")
            facts[str(name)] = _clamp(float(value))
    else:
        raise ValueError("'facts' must be a list of {predicate, value} entries or a mapping.")

    description = str(scenario.get("description", ""))
    return description, facts


# ---------------------------------------------------------------------------
# Compliance Reasoner
# ---------------------------------------------------------------------------


def _aggregate(values: list[float], weights: list[float]) -> float:
    """Weighted mean shared by the text and facts evaluation paths."""
    total_weight = sum(weights)
    if not values or total_weight <= 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total_weight


class ComplianceReasoner:
    """Applies DDL rules to policy documents and scenarios."""

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self.ddl = DDL(fuzzy=True)

    # -- Loading and validation ---------------------------------------------

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
            rules.append(
                ComplianceRule(
                    id=r["id"],
                    type=r["type"],
                    description=r["description"],
                    predicates=[self._build_predicate(p) for p in r.get("predicates", [])],
                    severity=r.get("severity", DEFAULT_SEVERITY),
                    citation=r.get("citation", ""),
                    applies_when=[self._build_predicate(p) for p in r.get("applies_when", [])],
                    unless=[self._build_predicate(p) for p in r.get("unless", [])],
                )
            )
        return rules

    @staticmethod
    def _build_predicate(p: dict) -> Predicate:
        return Predicate(
            name=p["name"],
            condition=p.get("condition", ""),
            weight=p.get("weight", 1.0),
            keywords=list(p.get("keywords", [])),
            patterns=list(p.get("patterns", [])),
            match=p.get("match", "any"),
        )

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

    def validate_rules_dict(self, data: Any) -> list[str]:
        """Validate the community rule-pack schema used by the reasoner."""
        errors: list[str] = []
        if not isinstance(data, dict):
            return ["Rules file must be a YAML mapping with a top-level 'rules' list."]

        schema_version = data.get("schema_version", 1)
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            errors.append(f"schema_version must be one of: {sorted(SUPPORTED_SCHEMA_VERSIONS)}.")

        rules = data.get("rules")
        if not isinstance(rules, list) or not rules:
            return errors + ["Rules file must contain a non-empty top-level 'rules' list."]

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

            severity = rule.get("severity", DEFAULT_SEVERITY)
            if severity not in VALID_SEVERITIES:
                errors.append(f"{prefix}.severity must be one of: {', '.join(sorted(VALID_SEVERITIES))}.")

            citation = rule.get("citation", "")
            if not isinstance(citation, str):
                errors.append(f"{prefix}.citation must be a string.")

            if not isinstance(rule.get("description"), str) or not rule["description"].strip():
                errors.append(f"{prefix}.description is required and must be a non-empty string.")

            if rule.get("unless") and rule_type != "prohibition":
                errors.append(f"{prefix}.unless is only allowed on prohibition rules.")

            predicates = rule.get("predicates")
            if not isinstance(predicates, list) or not predicates:
                errors.append(f"{prefix}.predicates must be a non-empty list.")
            else:
                for pred_index, predicate in enumerate(predicates, 1):
                    errors.extend(self._validate_predicate(predicate, f"{prefix}.predicates[{pred_index}]"))

            for block in ("applies_when", "unless"):
                entries = rule.get(block)
                if entries is None:
                    continue
                if not isinstance(entries, list) or not entries:
                    errors.append(f"{prefix}.{block} must be a non-empty list when present.")
                    continue
                for entry_index, entry in enumerate(entries, 1):
                    errors.extend(self._validate_predicate(entry, f"{prefix}.{block}[{entry_index}]"))

        return errors

    @staticmethod
    def _validate_predicate(predicate: Any, prefix: str) -> list[str]:
        errors = []
        if not isinstance(predicate, dict):
            return [f"{prefix} must be a mapping."]

        if not isinstance(predicate.get("name"), str) or not predicate["name"].strip():
            errors.append(f"{prefix}.name is required and must be a non-empty string.")

        condition = predicate.get("condition", "")
        keywords = predicate.get("keywords", [])
        patterns = predicate.get("patterns", [])

        if not isinstance(condition, str):
            errors.append(f"{prefix}.condition must be a string.")
            condition = ""
        if not isinstance(keywords, list) or any(not isinstance(k, str) or not k.strip() for k in keywords):
            errors.append(f"{prefix}.keywords must be a list of non-empty strings.")
            keywords = []
        if not isinstance(patterns, list) or any(not isinstance(p, str) or not p.strip() for p in patterns):
            errors.append(f"{prefix}.patterns must be a list of non-empty strings.")
            patterns = []
        else:
            for p in patterns:
                try:
                    re.compile(p)
                except re.error as exc:
                    errors.append(f"{prefix}.patterns contains an invalid regex '{p}': {exc}")

        if not condition.strip() and not keywords and not patterns:
            errors.append(f"{prefix} must define 'keywords', 'patterns', or a legacy 'condition'.")

        match_mode = predicate.get("match", "any")
        if match_mode not in VALID_MATCH_MODES:
            errors.append(f"{prefix}.match must be one of: {', '.join(sorted(VALID_MATCH_MODES))}.")

        weight = predicate.get("weight", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0 or weight > 1:
            errors.append(f"{prefix}.weight must be a number greater than 0 and at most 1.")

        return errors

    @staticmethod
    def rule_pack_warnings(data: Any) -> list[str]:
        """Non-fatal advisories, e.g. legacy v1 prose conditions."""
        warnings: list[str] = []
        if not isinstance(data, dict):
            return warnings
        for index, rule in enumerate(data.get("rules") or [], 1):
            if not isinstance(rule, dict):
                continue
            for block in ("predicates", "applies_when", "unless"):
                for pred_index, predicate in enumerate(rule.get(block) or [], 1):
                    if not isinstance(predicate, dict):
                        continue
                    if predicate.get("condition") and not predicate.get("keywords") and not predicate.get("patterns"):
                        warnings.append(
                            f"rules[{index}].{block}[{pred_index}] uses a legacy prose 'condition'; "
                            "keyword inference is imprecise — migrate to explicit 'keywords' (schema v2)."
                        )
        return warnings

    # -- Evaluation -----------------------------------------------------------

    def evaluate_policy(self, policy_text: str, rules: list[ComplianceRule]) -> ComplianceReport:
        """Evaluate a policy document against a set of compliance rules."""
        spans = _sentence_spans(policy_text)
        results = [self._evaluate_rule(rule, policy_text, spans) for rule in rules]

        score = self._calculate_overall_score(results)
        risk = self._determine_risk_level(results)

        failing = [r for r in results if r.status == STATUS_FAIL]
        applicable = sum(1 for r in results if r.applicable)
        summary_parts = [
            f"{len(results)} rules evaluated ({applicable} applicable): "
            f"{sum(1 for r in results if r.status == STATUS_PASS)} passed, "
            f"{sum(1 for r in results if r.status == STATUS_WARN)} marginal, "
            f"{len(failing)} failed, "
            f"{len(results) - applicable} not applicable."
        ]
        if failing:
            summary_parts.append(f"Top failures: {', '.join(r.rule_id for r in failing[:3])}")

        return ComplianceReport(results=results, overall_score=score, risk_level=risk, summary=" ".join(summary_parts))

    def evaluate_scenario(self, facts: dict, rules: list[ComplianceRule]) -> ComplianceReport:
        """Evaluate a scenario (facts dict) against rules using DDL reasoning."""
        results = [self._evaluate_rule_with_facts(rule, facts) for rule in rules]

        score = self._calculate_overall_score(results)
        risk = self._determine_risk_level(results)
        decision, confidence = self._decide(results)

        return ComplianceReport(
            results=results,
            overall_score=score,
            risk_level=risk,
            summary=f"Scenario evaluated: {len(results)} rules, score={score:.2f}, decision={decision}",
            decision=decision,
            decision_confidence=confidence,
        )

    def _evaluate_rule(self, rule: ComplianceRule, text: str, spans: Optional[list[tuple[int, int]]] = None) -> RuleResult:
        """Evaluate a single rule against policy text."""
        if spans is None:
            spans = _sentence_spans(text)

        if rule.applies_when:
            gate_results = [extract_predicate(p, text, spans) for p in rule.applies_when]
            if not any(g["matched"] for g in gate_results):
                return self._na_result(rule, gate_results)

        predicate_results = [extract_predicate(p, text, spans) for p in rule.predicates]
        evidence_strength = _aggregate(
            [p["score"] for p in predicate_results],
            [p.weight for p in rule.predicates],
        )

        exception_strength = 0.0
        exception_results: list[dict] = []
        if rule.type == "prohibition" and rule.unless:
            exception_results = [extract_predicate(p, text, spans) for p in rule.unless]
            exception_strength = _aggregate(
                [p["score"] for p in exception_results],
                [p.weight for p in rule.unless],
            )

        strength = self._compliance_strength(rule.type, evidence_strength, exception_strength)
        status, passed = self._status_for(strength)

        evidence = []
        for p in predicate_results:
            state = "FOUND" if p["matched"] else "MISSING"
            evidence.append(f"[{state}] {p['name']}: {', '.join(p['evidence']) if p['evidence'] else 'no match'}")
        for p in exception_results:
            state = "EXCEPTION-FOUND" if p["matched"] else "EXCEPTION-MISSING"
            evidence.append(f"[{state}] {p['name']}: {', '.join(p['evidence']) if p['evidence'] else 'no match'}")

        explanation = f"{rule.type.upper()}: {rule.description}. " + " | ".join(evidence)
        explanation += (
            f" (evidence={evidence_strength:.2f}"
            + (f", exception={exception_strength:.2f}" if exception_results else "")
            + f", compliance_strength={strength:.2f}, threshold={self.threshold})"
        )

        return RuleResult(
            rule_id=rule.id,
            rule_type=rule.type,
            description=rule.description,
            passed=passed,
            strength=strength,
            status=status,
            severity=rule.severity,
            citation=rule.citation,
            applicable=True,
            predicates_matched=[p for p in predicate_results if p["matched"]],
            predicate_results=predicate_results + exception_results,
            explanation=explanation,
        )

    def _evaluate_rule_with_facts(self, rule: ComplianceRule, facts: dict) -> RuleResult:
        """Evaluate a rule against provided facts using DDL logic."""
        if rule.applies_when:
            gates = {p.name: float(facts.get(p.name, 0.0)) for p in rule.applies_when}
            if not any(v >= self.threshold for v in gates.values()):
                gate_info = [{"name": name, "matched": False, "score": value} for name, value in gates.items()]
                return self._na_result(rule, gate_info)

        values = [float(facts.get(p.name, 0.0)) for p in rule.predicates]
        weights = [p.weight for p in rule.predicates]
        predicate_values = [
            {"name": p.name, "value": v, "weight": p.weight}
            for p, v in zip(rule.predicates, values)
        ]
        aggregated = _aggregate(values, weights)

        exception_strength = 0.0
        exception_values: list[dict] = []
        if rule.type == "prohibition" and rule.unless:
            unless_values = [float(facts.get(p.name, 0.0)) for p in rule.unless]
            exception_values = [
                {"name": p.name, "value": v, "weight": p.weight}
                for p, v in zip(rule.unless, unless_values)
            ]
            exception_strength = _aggregate(unless_values, [p.weight for p in rule.unless])

        strength = self._compliance_strength(rule.type, aggregated, exception_strength)
        status, passed = self._status_for(strength)

        details = ", ".join(f"{pv['name']}={pv['value']:.2f}" for pv in predicate_values + exception_values)
        explanation = f"{rule.type.upper()}: {rule.description}. Predicates: {details}. Compliance strength={strength:.2f}"

        return RuleResult(
            rule_id=rule.id,
            rule_type=rule.type,
            description=rule.description,
            passed=passed,
            strength=strength,
            status=status,
            severity=rule.severity,
            citation=rule.citation,
            applicable=True,
            predicates_matched=[pv for pv, v in zip(predicate_values, values) if v >= self.threshold],
            predicate_results=predicate_values + exception_values,
            explanation=explanation,
        )

    def _na_result(self, rule: ComplianceRule, gate_results: list[dict]) -> RuleResult:
        gates = ", ".join(g["name"] for g in gate_results) or "applicability conditions"
        return RuleResult(
            rule_id=rule.id,
            rule_type=rule.type,
            description=rule.description,
            passed=True,
            strength=0.0,
            status=STATUS_NA,
            severity=rule.severity,
            citation=rule.citation,
            applicable=False,
            predicate_results=list(gate_results),
            explanation=(
                f"{rule.type.upper()}: {rule.description}. "
                f"Not applicable — no applicability condition matched ({gates})."
            ),
        )

    def _status_for(self, strength: float) -> tuple[str, bool]:
        if strength >= self.threshold + WARN_BAND:
            return STATUS_PASS, True
        if strength >= self.threshold:
            return STATUS_WARN, True
        return STATUS_FAIL, False

    def _compliance_strength(self, rule_type: str, evidence_strength: float, exception_strength: float = 0.0) -> float:
        if rule_type == "obligation":
            return self.ddl.obligation(evidence_strength)
        if rule_type == "permission":
            return self.ddl.permission(evidence_strength)
        if rule_type == "prohibition":
            # Prohibited unless excepted: violation = trigger AND NOT exception.
            violation = self.ddl.soft_and(evidence_strength, self.ddl.soft_not(exception_strength))
            return self.ddl.soft_not(violation)
        return evidence_strength

    def _calculate_overall_score(self, results: list[RuleResult]) -> float:
        """Severity-weighted mean strength over applicable rules only."""
        applicable = [r for r in results if r.applicable]
        if not applicable:
            return 1.0
        weights = [SEVERITY_WEIGHTS.get(r.severity, SEVERITY_WEIGHTS[DEFAULT_SEVERITY]) for r in applicable]
        return sum(r.strength * w for r, w in zip(applicable, weights)) / sum(weights)

    def _determine_risk_level(self, results: list[RuleResult]) -> str:
        applicable = [r for r in results if r.applicable]
        if not applicable:
            return "LOW"
        fails = [r for r in applicable if r.status == STATUS_FAIL]
        warns = [r for r in applicable if r.status == STATUS_WARN]
        if any(r.severity == "critical" for r in fails) or len(fails) > 0.3 * len(applicable):
            return "HIGH"
        if fails or warns:
            return "MEDIUM"
        return "LOW"

    def _decide(self, results: list[RuleResult]) -> tuple[str, float]:
        """Resolve applicable rule strengths into a deontic decision."""
        def mean(values: list[float], default: float) -> float:
            return sum(values) / len(values) if values else default

        obligations = [r.strength for r in results if r.applicable and r.rule_type == "obligation"]
        permissions = [r.strength for r in results if r.applicable and r.rule_type == "permission"]
        prohibitions = [r.strength for r in results if r.applicable and r.rule_type == "prohibition"]

        obligation_pressure = 1.0 - mean(obligations, 1.0)
        permission_level = mean(permissions, 1.0)
        violation_level = 1.0 - mean(prohibitions, 1.0)

        return self.ddl.resolve(obligation_pressure, permission_level, violation_level, self.threshold)


def print_report(report: ComplianceReport, verbose: bool = False) -> None:
    """Pretty-print a compliance report."""
    risk_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}
    color = risk_color.get(report.risk_level, "white")

    console.print(f"\n[bold]Compliance Score:[/bold] [{color}]{report.overall_score:.2f}[/{color}]")
    console.print(f"[bold]Risk Level:[/bold] [{color}]{report.risk_level}[/{color}]")
    if report.decision:
        decision_color = {"ALLOW": "green", "ALLOW_WITH_OBLIGATIONS": "yellow", "BLOCK": "red"}.get(report.decision, "white")
        console.print(
            f"[bold]Decision:[/bold] [{decision_color}]{report.decision}[/{decision_color}] "
            f"(confidence {report.decision_confidence:.2f})"
        )
    console.print(f"[bold]Summary:[/bold] {report.summary}")

    status_style = {
        STATUS_PASS: "[green]PASS[/green]",
        STATUS_WARN: "[yellow]WARN[/yellow]",
        STATUS_FAIL: "[red]FAIL[/red]",
        STATUS_NA: "[dim]N/A[/dim]",
    }

    table = Table(title="Rule Results", show_lines=True)
    table.add_column("Rule ID", style="cyan", width=22)
    table.add_column("Type", width=12)
    table.add_column("Severity", width=9)
    table.add_column("Status", width=8)
    table.add_column("Strength", width=9)
    table.add_column("Citation", width=18)
    table.add_column("Description")

    for r in report.results:
        table.add_row(
            r.rule_id,
            r.rule_type,
            r.severity,
            status_style.get(r.status, r.status),
            "—" if r.status == STATUS_NA else f"{r.strength:.2f}",
            r.citation or "—",
            r.description[:80],
        )

    console.print(table)

    if verbose:
        for r in report.results:
            console.print(f"\n[bold cyan]{r.rule_id}[/bold cyan] [{r.status}]")
            console.print(f"  {r.explanation}")
