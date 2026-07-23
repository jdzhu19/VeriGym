# Persistent artifact contract

VeriGym writes strict, versioned JSON or JSONL. Current writers emit schema version `1.0`;
readers dispatch explicitly by major/minor version. Generated JSON Schemas live in
[`docs/schemas/`](schemas/).

Persistent top-level objects include tasks; run configuration and manifests; plugin, prompt,
tool-policy, runtime, and profile descriptors; model requests/responses and observed remote
identity; observations, actions, episode/batch events, tool/verifier results; scorecards and
synthesis metrics; sampling manifests and pass@k reports; experiment config, frozen plan, state,
index, manifest, and aggregate reports; replay evidence; build provenance; and artifact-integrity
manifests.

New completed runs contain `artifact_manifest.json`. It hashes bounded, normalized relative
paths with role, visibility, size, and SHA-256 metadata. Experiment manifests bind parent files
and child artifact-manifest identities. Readers reject traversal, duplicate paths, links, special
files, missing required files, size violations, and hash mismatches before trusting content.
Pre-integrity Milestones 0–9 artifacts remain readable as `legacy_unverified`; they are never
silently described as verified.

Atomic same-directory replacement is used for mutable parent state. Replay consumes the frozen
candidate and exact stored runtime/profile identities. Report generation reads validated
artifacts only and performs no model, simulator, synthesis, Docker, or network call.

Regenerate or check schemas with:

```bash
python scripts/export_schemas.py
python scripts/export_schemas.py --check
```
