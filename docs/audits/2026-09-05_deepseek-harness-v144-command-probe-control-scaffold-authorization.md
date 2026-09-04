# DeepSeek Harness v144 command-probe control scaffold authorization

Date: 2026-09-05

Status: **one provider-free execution authorized only after merge and green post-merge `main`**.

## Decision

Authorize exactly one execution of
`deepseek-harness-hwe-v144-command-probe-control-scaffold-v1` after this implementation is merged
to `main` and that exact merge commit passes all eight ordinary Actions job classes. V144 must
materialize the five fixed HWE tasks into fresh bind-backed `/data2` resources and repeat the
complete atomic zero-provider scaffold. It may change only the command-image identity-probe
control: the probe has an explicit maximum 300-second timeout and a separate content-free
diagnostic.

This does not authorize DeepSeek provider access, candidate task execution, formal collection,
SFT, or production training. The former `deepseek-harness-hwe-v144-official-matrix-v1` identity is
retired without execution. A possible official successor is the distinct v146 identity, which is
unreachable unless v144 completes and a separate v145 result audit is merged with green
post-merge `main` checks.

## Frozen implementation

- Manifest:
  `configs/training/qwen35_hwe_deepseek_harness_v144_command_probe_control_scaffold_v1.json`
- Manifest file SHA-256:
  `6cb713dfd60e71bf565567259b4849e4b4a1de8754db269f8f5d6a4a12ea984f`
- Manifest canonical hash:
  `329ef1af435ecd1ce48a7d389b5f0b4d64bdd21bf6eca6a4cc0e1250d9ef322b`
- Runner:
  `scripts/materialize_hwe_deepseek_harness_v144_command_probe_control_scaffold.py`
- Runner SHA-256:
  `3f7552853685c13c24cdeed015d19e84d2d7392555b078cab0fde707f4f2306c`
- v143 audit merge: `0f2735e1720291a60debdadd18392626589775b0`
- v143 post-merge `main` run: `33907426320`, eight of eight jobs passed

The manifest binds the exact v142 manifest, runner, authorization, terminal report,
five-task materialization set, execution inventory, cleanup receipt, and v143 audit. V144 refuses
changed bytes, invalid canonical hashes, a changed five-task order, a missing audit ancestor, a
dirty or non-`main` source, or a mismatched post-merge run ID.

## Fresh resource and image boundary

V144 uses only these newly named resources:

- data volume: `verigym-deepseek-harness-v144-dind-data`
- socket volume: `verigym-deepseek-harness-v144-dind-socket`
- data backing: `/data2/jiadongzhu/docker/deepseek-harness-hwe-v144/data`
- socket backing: `/data2/jiadongzhu/docker/deepseek-harness-hwe-v144/socket`
- control root: `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v144-control`
- runtime scratch: `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v144-runtime`
- evidence root:
  `/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v144-command-probe-control-scaffold-v1`

The retained v142 data volume and evidence are immutable predecessor records. V144 must not open,
inspect, mount, mutate, retry, or promote that volume. It reads HWE task images only from the five
completed local archives under `/data2/jiadongzhu/Agent/hwe-bench-public-images`, validates every
archive and image lock, and imports through the exact fresh nested Unix socket. Registry access,
`.partial` archives, default-bridge recovery, daemon restart, VPN/proxy changes, and broad Docker
cleanup remain forbidden.

All five base/reference verifiers retain `network=none`, the separate 300-second Docker control
bound, and the unchanged 900-second official test timeout. Every task-specific command image is
rebuilt credential-free and Codex-free, then must pass the bounded v2 scan under its new v144
identity.

## Command-image probe control

Existing Docker command-image configurations keep the 60-second default. V144 alone explicitly
sets `identity_probe_timeout_s=300` for each of its five preparation probes. The probe script,
expected UID/GID, ripgrep version and SHA-256, immutable image ID and labels, command runtime
limits, `network=none`, read-only root, resource controls, and cleanup behavior are unchanged.

The diagnostic may persist only the fixed task ID, completed-task IDs, allowlisted subreason,
probe protocol, failure origin/reason, timeout/OOM/truncation booleans, exit code, and the fixed
control bound. Raw stdout, stderr, exception text, untrusted detail fields, and nonempty output or
exception hashes are forbidden. An unallowlisted image error is reduced to
`unallowlisted_docker_image_error`.

All five runtime probes and empty inner container/volume inventory checks must pass before the
synthetic network-isolated Harness initialization. A probe failure, ambiguous diagnostic,
materialization failure, security failure, cleanup failure, or partial result prevents atomic
scaffold publication.

## One-shot execution

After the implementation merge and green post-merge `main` run, invoke the runner once with all
provider and ambient Docker endpoint variables removed. Supply only the numeric ID of that green
post-merge run:

```text
VERIGYM_RUN_DEEPSEEK_HARNESS_V144_COMMAND_PROBE_CONTROL_SCAFFOLD=1 \
python scripts/materialize_hwe_deepseek_harness_v144_command_probe_control_scaffold.py \
  --post-merge-main-run-id <green-main-run-id>
```

The child environment must remove `DEEPSEEK_API_KEY`, `DEEPSEEK_API_TOKEN`, `OPENAI_API_KEY`,
`OPENAI_API_TOKEN`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENROUTER_API_KEY`,
`OPENROUTER_API_TOKEN`, `DOCKER_HOST`, and `DOCKER_CONTEXT`. Concrete values must never be printed,
persisted, or hashed.

The runner is consumed after its first start, whether it passes or fails. Success publishes only
the provider-free scaffold contract pending v145 audit. Failure freezes the exact v144 data volume
and sanitized evidence; it cannot be relabelled or retried. Cleanup may remove only exact
v144-owned socket resources and retains the v142-audited 300-second content-free cleanup policy.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

## Credential-free verification

Before authorization merge, run:

- core credential-free pytest;
- HWE Bench pytest and mypy;
- DeepSeek Harness pytest and mypy;
- Synopsys integration credential-free pytest and strict mypy;
- `ruff check . && ruff format --check . && mypy src`.

The focused regression set covers the default and bounded probe timeout, invalid bounds,
allowlisted content-free diagnostics, raw-detail rejection, immutable predecessor locks, fresh
resource identities, deterministic five-task order, bounded scanning, failure closure, progress
mapping, and the prohibition on v142 data-volume access.
