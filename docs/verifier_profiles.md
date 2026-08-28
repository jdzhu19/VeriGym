# Verifier backend profiles

Verifier profiles replace one verifier-only DAG node with a hash-bound backend before any model
lookup. The first profile type is `synopsys.vcs.mcp`: it keeps VCS, its license setup, hidden
testbench, and raw reports on a fixed local or SSH-connected verifier worker.

This is separate from a synthesis `--toolchain-profile`. A run may select both: the verifier
profile controls hidden functional verification, while the toolchain profile controls final PPA.

## Run with a fixed verifier worker

Create one private server profile per task and start the service with only approved profiles:

```bash
verigym-synopsys-prepare-vcs-profile \
  --id rtllm-counter-vcs-v1 \
  --task-id rtllm/counter_12 \
  --source rtl/counter_12.v \
  --testbench /private/RTLLM/Control/Counter/counter_12/testbench.v \
  --top counter_12_tb \
  --pass-marker '===========Your Design Passed===========' \
  --fail-marker '===========Failed===========' \
  --vcs /opt/synopsys/vcs/bin/vcs \
  --output-profile /private/profiles/rtllm-counter-vcs-server.yaml

verigym-synopsys-vcs-mcp-server \
  --profile /private/profiles/rtllm-counter-vcs-server.yaml \
  --work-root /private/verigym-vcs-work
```

The client transport must be one executable regular file that accepts no arguments and connects
stdin/stdout to that exact service command. Export a sanitized client profile after recording the
server-declared and public-contract hashes returned by the service:

```bash
verigym-synopsys-export-vcs-mcp-profile \
  --id rtllm-counter-vcs-client-v1 \
  --server-profile-id rtllm-counter-vcs-v1 \
  --server-declared-profile-hash "$SERVER_DECLARED_SHA256" \
  --server-contract-hash "$SERVER_CONTRACT_SHA256" \
  --task-id rtllm/counter_12 \
  --transport-executable /usr/local/bin/verigym-vcs-mcp-transport \
  --output-profile /private/profiles/rtllm-counter-vcs-client.yaml
```

Use both the ID and document on a run:

```bash
verigym run --suite rtllm --task counter_12 --suite-source /datasets/RTLLM \
  --mode chat --agent single-turn --model YOUR_MODEL --runtime local \
  --verifier-profile rtllm-counter-vcs-client-v1 \
  --verifier-profile-file /private/profiles/rtllm-counter-vcs-client.yaml \
  --output runs/
```

`--runtime local` runs only the fixed transport in the trusted control plane. It does not make
VCS or commercial assets visible to a model. Replay re-resolves the transport, server, profile,
contract, and exact VCS version before re-executing the frozen candidate.

## Freeze it in an experiment

Experiment YAML uses equivalent fields at the top level:

```yaml
schema_version: "1.0"
name: rtllm-counter-vcs-mcp
suite:
  id: rtllm
  source: /datasets/RTLLM
  variant: counter_12
  tasks:
    include: [counter_12]
runs:
  mode: chat
  seeds: [0]
  samples_per_task: 1
  pass_k: [1]
verifier_profile: rtllm-counter-vcs-client-v1
verifier_profile_file: /private/profiles/rtllm-counter-vcs-client.yaml
systems:
  - id: candidate
    agent: {id: single-turn}
    model: {id: YOUR_MODEL}
runtime: {id: local}
output: {root: experiments/rtllm-counter-vcs-mcp}
```

Planning probes the transport and exact server/tool identity. Each plan item freezes the declared
and resolved profile objects; child runs must resolve the same identities before model-process
authorization.

## Version and benchmark boundaries

| Partition | Functional verifier | Compatibility rule |
| --- | --- | --- |
| RTLLM single-turn commercial | VCS through `synopsys.vcs.mcp` | Exact VCS version and task-bound server contract |
| RTLLM AgentEval v1 | Icarus and vvp 12 | Both resolved major versions must be 12 |
| VerilogEval V2, including AgentEval | Icarus and vvp | Major 12 is upstream-reference-compatible; major 13 is incompatible |
| RTL-Repo official completion, including AgentEval | Native Exact Match/Edit Similarity | No Icarus or VCS requirement |

Icarus 13 may remain installed side by side for development, but it must not be selected for a
reference-compatible RTLLM AgentEval or VerilogEval V2 result. Record `iverilog -V`, `vvp -V`, and
the immutable Docker image identity for published runs.

## Security and failure behavior

The VCS MCP service exposes only list, resolve, and simulate. Simulation accepts a task/profile
identity and bounded candidate RTL for the exact ordered source list. Top, testbench mount,
pass/fail markers, timeout, hidden testbench hash, and VCS executable are server-owned. The API has
no arbitrary command, shell, flags, environment, testbench bytes, report, or artifact-return field.

The client rejects transport-hash, protocol, server-version, profile, contract, task, VCS-version,
candidate, hidden-testbench, and replay-identity mismatches. Successful and candidate-failure
responses contain no stdout, stderr, diagnostics, artifacts, VCS log, hidden RTL, license value, or
server path. License absence remains `license_unavailable`; transport failure is infrastructure,
not a candidate rejection.

Direct `synopsys.vcs.simulate` and `synopsys.dc.synth` remain trusted verifier backends for legacy
or server-internal use. New commercial RTLLM campaigns should use `synopsys.vcs.mcp` for
functional verification and `synopsys.dc.mcp` for final PPA.

Agent-visible DC/MCP PPA is not implemented in phase one. It still requires a separately isolated,
disposable worker and a new threat-model claim; do not expose either commercial MCP backend in the
six-action agent tool registry.
