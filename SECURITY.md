# Security policy

## Scope

Compliance Agent is a local screening tool. Policy documents, regulatory documents, YAML rule packs, uploaded files, and vector-store contents may be sensitive.

The default workflow does not require an API key or send document text to a hosted Compliance Agent service. Optional dependencies may download models or use their own telemetry/configuration; review their policies before deployment.

## Reporting a vulnerability

Please do not disclose sensitive policy text or exploit details in a public issue. Contact the repository maintainer privately through the security contact configured on GitHub. Include the affected version, a minimal reproduction that contains synthetic data, impact, and a proposed mitigation if available.

## Operational guidance

- Keep `.chroma/`, uploaded documents, generated reports, and model caches out of public directories.
- Do not copy `.compliance-agent-index` into unrelated directories. It is an ownership marker used to authorize deletion during `monitor --reset`.
- Do not expose the Streamlit dashboard to an untrusted network without adding authentication and transport protection.
- Treat retrieved passages as untrusted input and review citations before relying on them.
- Run the CLI with explicit output paths and least-privilege filesystem permissions.

## CodeQL review notes

The CodeQL `py/path-injection` query is excluded for this repository because
`RegulatoryRAG.ingest_directory` intentionally accepts a local corpus path from
the CLI. That boundary canonicalizes the path, verifies that it exists and is a
directory, and only reads supported files below it. Index deletion is a separate
operation with its own trusted-root, ownership-marker, and symlink checks. The
CodeQL configuration keeps the remaining default security queries enabled; any
new filesystem write or deletion path must still receive an explicit security
review and tests.
