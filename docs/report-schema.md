# Report JSON Schema (v2)

`compliance-agent report -o report.json` and `check --format json` emit this structure.

```jsonc
{
  "metadata": {                 // caller-supplied context (paths, threshold, …)
    "policy": "policy.txt",
    "rules": "rules.yaml",
    "threshold": 0.5
  },
  "provenance": {               // audit trail: when, with what, over what
    "generated_at": "2026-07-07T12:00:00+00:00",   // ISO-8601 UTC
    "tool": "compliance-agent",
    "tool_version": "0.2.0",
    "report_schema_version": 2,
    "policy_path": "policy.txt",
    "policy_sha256": "…64 hex chars…",             // null if path unavailable
    "rules_path": "rules.yaml",
    "rule_pack_sha256": "…64 hex chars…",
    "threshold": 0.5
  },
  "summary": {
    "overall_score": 0.92,      // severity-weighted mean over applicable rules
    "risk_level": "LOW",        // LOW | MEDIUM | HIGH
    "passed": 5,                // PASS + WARN
    "failed": 0,
    "warnings": 1,              // WARN subset of passed
    "not_applicable": 4,
    "applicable": 5,
    "total": 9,
    "severity_breakdown": {     // FAIL counts per severity
      "critical": 0, "major": 0, "minor": 0
    },
    "text": "…human summary…",
    "decision": "ALLOW",        // scenario mode only
    "decision_confidence": 0.95 // scenario mode only
  },
  "results": [
    {
      "rule_id": "GDPR-SHARING-001",
      "rule_type": "prohibition",         // obligation | permission | prohibition
      "severity": "critical",             // critical | major | minor
      "citation": "GDPR Art. 28",
      "description": "…",
      "status": "PASS",                   // PASS | WARN | FAIL | N/A
      "passed": true,                     // false only for FAIL
      "applicable": true,                 // false when applies_when gate unmatched
      "strength": 1.0,                    // compliance strength in [0, 1]
      "explanation": "…full trace…",
      "predicates": [ /* raw per-predicate results incl. snippets */ ],
      "matched_predicates": [ /* subset that matched */ ],
      "evidence": [                       // flattened quoted evidence
        {
          "predicate": "has_dpa",
          "keyword": "data processing agreement",
          "sentence": "Personal data is shared … under strict data processing agreements.",
          "start": 1042,                  // character offsets in the source document
          "end": 1069,
          "negated": false
        }
      ],
      "recommended_action": "…"
    }
  ]
}
```

## Compatibility notes

- Keys present in schema v1 (`metadata`, `summary.overall_score/risk_level/passed/failed/total/text`, `results[].rule_id/rule_type/description/passed/strength/explanation/predicates/matched_predicates/recommended_action`) are unchanged; v2 adds fields without removing any.
- `status` supersedes the boolean `passed`: WARN results have `passed: true` but deserve human review; N/A results have `passed: true` and `applicable: false`.
- Markdown (`.md`) and HTML (`.html`) reports are rendered from this same dictionary.
