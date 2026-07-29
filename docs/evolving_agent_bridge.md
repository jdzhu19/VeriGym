# Observable Trajectories and Evolving Agents

Milestone 10B adds a benchmark-neutral bridge on top of ordinary replayable
`repo-rtl` runs. It exports bounded observations, derives offline rewards, and
compares immutable agent versions. It does not change hidden verification,
candidate freezing, Docker isolation, or any Milestones 0–9 contract.

## Export and reward boundary

`verigym trajectories export` reads a completed experiment without invoking a
model, Codex, runtime, verifier, public-test launcher, or network. Exportable
data is limited to public task properties; observable assistant messages and
tool events; bounded public-test feedback; workspace and patch metadata;
candidate identities; outcomes; usage; and decomposed rewards.

Private reasoning, hidden tests, reference patches, credentials, proxy values,
authentication files, raw host paths, and unbounded output are rejected rather
than redacted after export. Validate an existing dataset with:

```bash
verigym trajectories validate evidence/trajectory-dataset
```

The authoritative reward is `repo_rtl_reward_vector_v1`. Infrastructure-invalid
episodes keep unavailable correctness channels null. The optional
`repo_rtl_sparse_v1` scalar is a named training profile, not a universal
benchmark score, and is recomputed from frozen run artifacts.

## Splits, memory, and versions

Task split manifests bind source, task, license, and attribution identities.
The first-party split uses three Milestone 10A training tasks and three
independently authored held-out tasks. The normal suite cannot discover the
held-out assets until a frozen, executable context-memory v1 manifest grants
access. Contamination scans compare task identities, source hashes, files,
issue text, private assets, and memory tokens.

Version v0 is the frozen `codex-cli-agent` configuration with no memory. One
authorized memory-synthesis process may produce v1. Its output must contain
only generalized principles, public-test strategy, workspace-policy reminders,
debugging checklists, and patch discipline. Code, patches, task IDs, paths,
hashes, hidden/reference details, credentials, and held-out-only content fail
closed. The resulting memory is a distinct read-only prompt artifact; v0 and
v1 otherwise retain identical model, reasoning, authentication, runtime,
tool-policy, prompt-contract, package, image, and source identities.

`verigym evolve replay-context-update` validates the frozen training summary,
memory, update, and version hashes without invoking the memory builder.
Held-out v0/v1 runs use one sealed counterbalanced plan and are reported
separately. A three-task pilot is descriptive and cannot establish general
performance improvement.

## External trainer boundary

VeriGym exports trainer-ready observable trajectories and imports frozen
agent-version identities. Milestone 10B does not implement or validate an RL
optimization algorithm. External trainer, checkpoint, and adapter manifests
record hashes, provenance, license, compatibility, and secret-free loading
metadata; weight-bearing imports remain non-executable in M10B.
