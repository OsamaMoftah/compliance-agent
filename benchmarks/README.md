# Synthetic benchmark

This directory contains small, versioned synthetic cases for regression testing of the deterministic rule engine. The cases exercise positive evidence, missing evidence, negation, prohibition exceptions, applicability gates, ambiguous language, mixed-clause adversarial input, and evidence extraction. Ambiguous cases intentionally measure conservative screening behavior; they are not legal interpretations.

Run the benchmark with:

```bash
compliance-agent benchmark --dataset benchmarks/synthetic_cases.yaml --output table
compliance-agent benchmark --dataset benchmarks/synthetic_cases.yaml --output json
```

The reported precision, recall, F1, false-positive rate, and false-negative rate describe agreement with these synthetic labels only. They do not establish legal correctness or validate a rule pack against a regulator's interpretation.
