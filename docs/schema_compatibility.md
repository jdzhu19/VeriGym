# Schema compatibility

The current persistent schema is `1.0`.

- Missing or malformed versions produce a structured schema-compatibility error.
- Unknown major versions are rejected.
- A minor version is accepted only when a reader has an explicit compatibility branch.
- Strict Pydantic validation continues to reject undeclared fields; version handling does not
  become an “ignore unknown data” escape hatch.
- Writers emit only the canonical current version.
- Any future migration must create new output deterministically and must not modify the source
  artifact in place.

Compatibility failures are separate from normal candidate failures, missing tools, and runtime
or model transport failures. Legacy files that Milestones 0–9 actually wrote are handled by
targeted compatibility code, including artifacts predating integrity manifests and selected
additive `schema_version` fields. Integrity status is reported as `legacy_unverified` when no
manifest exists.

Sanitized fixtures under `tests/fixtures/golden/v1/` cover resolved and unresolved toy runs,
model failure, Docker replay identity, VerilogEval sampling, Yosys area, and an experiment report.
They contain no external corpus text, hidden tests, credentials, or host paths.
