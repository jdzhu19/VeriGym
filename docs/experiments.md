# Experiment configuration and deterministic planning

A VeriGym experiment freezes one evaluation configuration into an ordered list of ordinary child
runs. Planning completes before the first child starts. It validates the suite, source, tasks,
systems, runtime, mandatory verifier tools, sampling settings, and optional synthesis profile.
It never downloads a benchmark or invokes a model.

`execution.max_plan_items` defaults to 10,000 and may not exceed 100,000. The planner computes the
Cartesian-product size first and rejects an over-limit configuration before creating output or
looking up a model. Explicit non-default bounds participate in normalized experiment identity;
the omitted default preserves existing Milestone 9 plan hashes.

New frozen manifests and plans carry package build provenance. Runtime identity normalization
binds Docker plans to the resolved immutable image ID rather than mutable request tags or
session-lifecycle fields.

Start from [`examples/experiments/toy-milestone9-baseline.yaml`](../examples/experiments/toy-milestone9-baseline.yaml):

```yaml
schema_version: "1.0"
name: "toy-milestone9-baseline"
suite:
  id: "toy-rtl"
  source: null
  variant: null
  tasks:
    include: ["and-gate-basic", "counter-basic"]
    exclude: []
runs:
  mode: "agent"
  seeds: [0, 1]
  samples_per_task: 1
  pass_k: [1]
systems:
  - id: "scripted-good"
    agent: {id: "scripted"}
    model: null
  - id: "scripted-bad"
    agent: {id: "scripted-bad"}
    model: null
runtime: {id: "local"}
profile: null
execution:
  max_workers: 1
  continue_on_infrastructure_error: true
output:
  root: "runs/experiments/toy-milestone9-baseline"
```

AgentEval uses the same frozen experiment surface as an ordinary run. Enable iterative RTLLM
feedback in `runs` and select exactly one Yosys/OpenSTA ATP v2 or isolated DC/MCP profile at
experiment scope:

```yaml
runs:
  mode: "agent"
  seeds: [0]
  samples_per_task: 1
  pass_k: [1]
  agent_ppa_feedback: true
  agent_ppa_max_calls: 3  # 1..8; repeated cache hits do not consume executions
profile: profiles/nangate45-opensta.yaml
```

The resolved feedback contract and profile hash are frozen into every plan item. VerilogEval and
RTL-Repo AgentEval variants reject `agent_ppa_feedback`. RTLLM accepts a commercial profile only
when its remote resolution proves the hash-bound disposable-worker contract; a final-PPA-only DC
profile is rejected instead of silently changing execution modes.

The schema is strict and versioned. Unknown fields, duplicate YAML/JSON keys, recursive aliases,
oversized/deep documents, duplicate systems or seeds, invalid paths, nonpositive sample counts,
and `k` values outside `1..samples_per_task` are rejected. A model-free agent cannot carry an
irrelevant model, and a model-backed agent requires an explicit model. Configuration stores only
the name of a credential environment variable; raw credentials are not accepted or persisted.

## Task selection and order

`include` accepts full task IDs, native slugs, and shell-style globs. `exclude` accepts the same
matching forms. Explicit unknown IDs, overlapping includes that select a task twice, and an empty
final selection are errors. The plan order is always:

1. normalized task ID;
2. system ID;
3. numeric base seed;
4. sample index.

Filesystem enumeration and worker completion order cannot affect it. The one-MVP-runtime and
one-optional-profile choices are explicit experiment-wide dimensions; no implicit model × agent
cross product is created.

## Seeds, samples, and identities

Every base seed is a separate replicate. For each task/system/base-seed tuple, sample indices are
`0..samples_per_task-1`. The child seed is the signed-63-bit reduction of SHA-256 over canonical
JSON containing the evaluation-config hash, task hash, full system identity, base seed, and sample
index. It is assigned during planning, never from completion order.

Each `plan_item_id` hashes every evaluation-relevant field: task/source/release, descriptors and
model options, prompt/tool policy, budget/generation, base and child seeds, runtime and immutable
image, verifier/correctness definition, and declared/resolved profile identities. Plan index,
timestamps, and output paths are excluded. The ordered plan, normalized config, selected task
set, and source identity receive separate SHA-256 hashes.

For external VerilogEval, set `suite.source` to a user-supplied checkout and set `variant` to
`v2-spec-to-rtl`. The source snapshot records its dataset hash and available Git provenance.
VeriGym never clones or modifies it. Docker image tags and profiles are resolved before model
lookup; children receive the frozen exact image/profile identity. A task or source mismatch is
checked inside the ordinary orchestrator before runtime setup or model lookup.

## Commands and overrides

```bash
verigym batch --config experiment.yaml --dry-run
verigym batch --config experiment.yaml
verigym batch --config experiment.yaml --max-workers 2
verigym batch --config experiment.yaml --fail-fast-infrastructure
verigym batch --config experiment.yaml --output /new/empty/root
```

Dry-run performs source/tool/runtime/profile diagnostics and prints the complete immutable plan
and exact child count. It does not execute a candidate or call a model, and it does not create the
configured output root. Overrides are normalized into the persisted config identity. Resume does
not accept plan-changing overrides.
