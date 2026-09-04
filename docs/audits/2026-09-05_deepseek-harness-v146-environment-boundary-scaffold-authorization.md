# DeepSeek Harness v146 environment-boundary scaffold authorization

Date: 2026-09-05

Status: **one provider-free execution authorized only after merge and green post-merge `main`**.

## Decision

Authorize exactly one execution of
`deepseek-harness-hwe-v146-environment-boundary-scaffold-v1` after this implementation is merged
to `main` and that exact merge commit passes all eight ordinary Actions job classes. V146 repeats
the byte-locked v144 five-task provider-free scaffold in fresh `/data2` resources. Its only new
control is an exact sanitized child environment derived from the same provider-configuration name
set enforced by the runner.

This does not authorize DeepSeek provider access, candidate task execution, formal collection,
SFT, or production training. The failed planned `deepseek-harness-hwe-v146-official-matrix-v1`
identity is retired without execution. A possible official successor is the distinct v148
identity, which remains unreachable unless v146 completes and a separate v147 result audit is
merged with green post-merge `main` checks.

## Frozen implementation

- Manifest:
  `configs/training/qwen35_hwe_deepseek_harness_v146_environment_boundary_scaffold_v1.json`
- Manifest file SHA-256:
  `10876458660405dfe46e5402fd23ac2f1f837a05e868dda1c0c7d0e4b51ef3fd`
- Manifest canonical hash:
  `4c641ae0c6fb09c4918c0ef154081962da245f6460940df1a6d73abbcfde0335`
- Launcher:
  `scripts/launch_hwe_deepseek_harness_v146_environment_boundary_scaffold.py`
- Launcher SHA-256:
  `4dc728a6efce37236e7de472d497c6a6d73520a2ea445792c75e9824ae630b23`
- Runner:
  `scripts/materialize_hwe_deepseek_harness_v146_environment_boundary_scaffold.py`
- Runner SHA-256:
  `a1da105f851abc99ac313691f5923f4174de996171f7a445a88fa23e7c53a4a5`
- v145 audit SHA-256:
  `0cea87e223fb31a1d6be3306498f3fdf42c89e5e23f0abb509c7a37390d04bad`
- v145 audit merge: `3cf30dccdcd1df42d0f63536b648cf06edb31693`
- v145 post-merge `main` run: `33911340495`, eight of eight jobs passed

The manifest also locks the exact v142 terminal evidence and v143 audit used by v144, plus the
v144 manifest, runner, authorization, merge gate, and audited resource-free failure. It refuses a
changed byte, canonical hash, five-task order, environment-name set, audit ancestor, source
branch, post-merge run ID, or formal-state flag.

## Exact environment boundary

The launcher imports the exact provider-name set enforced by the inherited v69/v94 execution
boundary and compares it with the ordered manifest constant. The set contains the 12
`ANTHROPIC_*`, `DEEPSEEK_*`, `OPENAI_*`, and VeriGym-specific DeepSeek key/base-URL names accepted
by that boundary. `DOCKER_HOST` and `DOCKER_CONTEXT` are added as separate blocked endpoint names.

The launcher iterates environment names first. It copies a value only after proving that its name
is outside the blocked set, so blocked provider and Docker endpoint values are not read. It then
sets only the v146 opt-in and fixed child-boundary marker and starts the exact frozen runner. The
runner checks the same set, marker, and manifest before delegating to any code that can create an
output path or Docker resource. The inherited boundary independently repeats the absence check.

Provider configuration values must not be read, printed, persisted, or hashed. The launcher may
retain unrelated environment entries needed by Python and the local Docker CLI. It may not alter
VPN, proxy, Docker daemon, registry, or host configuration.

## Fresh resource and execution boundary

V146 uses only these newly named resources:

- data volume: `verigym-deepseek-harness-v146-dind-data`
- socket volume: `verigym-deepseek-harness-v146-dind-socket`
- data backing: `/data2/jiadongzhu/docker/deepseek-harness-hwe-v146/data`
- socket backing: `/data2/jiadongzhu/docker/deepseek-harness-hwe-v146/socket`
- control root: `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v146-control`
- runtime scratch: `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v146-runtime`
- evidence root:
  `/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v146-environment-boundary-scaffold-v1`

The v144 roots and Docker resources remain absent and must not be synthesized. The frozen v142
data volume is not mounted, inspected, or mutated. V146 reads task images only from the five
completed local archives, rejects `.partial` files, and never accesses a registry. It retains the
v144 official base-FAIL/reference-PASS behavior, `network=none` verifiers, 300-second Docker
control bound, unchanged 900-second official test bound, five credential-free and Codex-free
command-image builds, bounded v2 scans, and explicit 300-second content-free identity probes.

All five tasks, runtime probes, empty inner inventories, synthetic network-isolated Harness
initialization, and exact cleanup must pass before one atomic provider-free scaffold contract can
be published. Any failure prevents partial authorization and consumes the v146 campaign identity.

## One-shot execution

After the implementation merge and green post-merge `main` run, invoke the launcher exactly once:

```text
VERIGYM_RUN_DEEPSEEK_HARNESS_V146_ENVIRONMENT_BOUNDARY_SCAFFOLD=1 \
python scripts/launch_hwe_deepseek_harness_v146_environment_boundary_scaffold.py \
  --post-merge-main-run-id <green-main-run-id>
```

Do not wrap this command in a hand-maintained `env -u` list. The frozen launcher is the authorized
environment boundary. V146 is consumed after its first child start whether it passes or fails.
Success publishes only the provider-free scaffold pending v147 audit; failure retains only the
exact sanitized evidence and owner-scoped resource disposition allowed by the inherited cleanup
policy.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

## Credential-free verification

Before authorization merge, run core, HWE Bench, DeepSeek Harness, and Synopsys integration
credential-free suites, their required mypy checks, and
`ruff check . && ruff format --check . && mypy src`. Focused regressions must prove exact manifest
binding, equality with the inherited 12-name boundary, no reads of blocked values, Docker endpoint
removal, marker enforcement before materialization, the 300-second command probe, deterministic
task order, raw-detail exclusion, fresh resource identities, and v147 success mapping.
