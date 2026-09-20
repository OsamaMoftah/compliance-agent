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

The repository keeps CodeQL's `py/path-injection` query enabled. A small local
CodeQL model pack marks only `RegulatoryRAG._validated_source_path` as a
path-injection barrier because it canonicalizes the explicitly selected corpus,
requires that it exists as a directory, and returns it solely for read-only
ingestion. Do not reuse that helper for writes or deletion; index deletion is a
separate operation with trusted-root, ownership-marker, and symlink checks.
