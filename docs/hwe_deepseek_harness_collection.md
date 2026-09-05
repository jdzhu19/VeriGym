# DeepSeek Harness HWE collection pilot

This path collects verifier-bound HWE-Bench trajectories through the official open-source
DeepSeek Harness while keeping VeriGym's task, runtime, and verifier contracts authoritative. It
is a three-task methodology and loader-conformance pilot, not a benchmark score and not a
production training dataset.

The frozen pilot uses DeepSeek Harness `0.1.1-rc.2` at revision
`b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`, DeepSeek V4 Flash, disabled thinking,
reasoning effort `off`, temperature zero, a 2,048-token response ceiling, and one parallel tool
call. Each of the following training-split CVA6 tasks receives exactly one attempt and one sample:

- `openhwgroup__cva6__pr-2032`
- `openhwgroup__cva6__pr-2549`
- `openhwgroup__cva6__pr-2944`

There is no whole-episode retry, model substitution, best-of-K selection, Harness compaction,
training, held-out evaluation, or HPC submission.

## Methodology boundary

The design borrows framework-level practices used by repository-agent work such as R2E-Gym,
SWE-Gym, and DeepSWE: immutable task/source bindings, machine-readable actions, isolated candidate
execution, ordinary verifier gating, append-only trajectory evidence, and explicit trainer-loader
validation. It does not copy their task prompts, episode limits, rollout counts, context lengths,
sampling settings, reward definitions, or optimizer hyperparameters. HWE values come from the
versioned `hwe_standard_v2` profile, qualified CVA6 sources, and digest-locked HWE images.

The controller receives the provider credential and network access but no task workspace. It can
invoke only six serial typed actions over an owner-only Unix socket:
`apply_patch`, `finish`, `inspect_diff`, `list_files`, `read_file`, and `shell`. VeriGym validates
arguments, runs file operations through core workspace tools, and runs shell commands in a
credential-free task-keyed image with `network=none`. The normal candidate freeze and separate
HWE verifier remain unchanged.

Harness session files and raw command observations remain private audit artifacts. The public
teacher transcript contains the exact compact observations shown to the model, exact tool-call
IDs and order, workspace epochs, hashes, usage counts, and verifier outcome. It contains no raw
provider events, thinking blocks, raw observations, credential values, hidden tests, reference
patches, or host paths.

## SFT compatibility

Only infrastructure-valid, verifier-passed trajectories produce SFT rows. One row is generated for
each assistant action using all exact prior model-visible messages as input and that action as the
sole target. Qwen3.5's frozen local chat template tokenizes the prefix and full example; the
loader proves that the full token stream begins with the prefix tokens and masks every token except
the final assistant action.

Rows use `max_length=32768` and `truncation=error`. An overlength row remains recorded as
ineligible and blocks `loader_ready`; it is never shortened, dropped, or silently truncated. NAP
is not needed on this path because no collected observation or context is transformed. NAP remains
necessary for separately derived compressed or masked contexts.

The disabled loader contract is
[`qwen35_hwe_deepseek_harness_action_sft_pilot_v1.json`](../configs/training/qwen35_hwe_deepseek_harness_action_sft_pilot_v1.json).
It records rLLM/veRL compatibility but intentionally leaves epochs, learning rate, update count,
and world size unset. Those HWE-specific choices require a separate preregistration after pilot
yield and token distributions are known.

### Native Harness v3 decision route

The v1/v2 action-only contract remains immutable. The independent v3 route follows the native
DeepSeek Harness/DeepSWE message shape observed in the frozen v2 pilot: an assistant decision may
contain concise public text followed by one or more sibling typed tool calls. Sibling calls are
executed serially in emitted order. This is a complete-assistant-decision target, not private
chain-of-thought export; Harness thinking remains disabled.

An `invalid_arguments` tool result is shown back to the model and the same episode may continue.
That failed assistant decision stays in exact context but receives no loss. A terminal text-only
or max-token interval receives at most one fixed `VERIGYM_HWE_FORMAT_RECOVERY_V1` prompt through
the same Harness session; no workspace reset, model substitution, whole-episode retry, or
best-of-K selection occurs. If the next interval still lacks an accepted `finish`, the trajectory
fails closed. All other broker rejection classes remain terminal.

The pinned Harness `GenerateOptions` interface does not expose `tool_choice`, so v3 records this
limitation instead of claiming provider-side `required`. Safety continues to come from the exact
six-tool broker, argument validation, serial execution, network-none task runtime, ordinary
verifier, and target loss masking. The disabled v3 loader contract is
[`qwen35_hwe_deepseek_harness_decision_sft_pilot_v3.json`](../configs/training/qwen35_hwe_deepseek_harness_decision_sft_pilot_v3.json).

## Execution and gates

Install the integration and the exact CPU tokenizer dependency before the opt-in run:

```bash
python -m pip install --no-build-isolation -e integrations/verigym-deepseek-harness
python -m pip install 'transformers==4.57.6'
```

Set `VERIGYM_DEEPSEEK_API_KEY`, `VERIGYM_DEEPSEEK_API_BASE_URL`, and the explicit
`VERIGYM_RUN_DEEPSEEK_HWE_PILOT=1` opt-in, then run:

```bash
python scripts/collect_cva6_hwe_deepseek.py \
  --qualification-root /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1 \
  --image-lock-dir /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/image-locks \
  --tokenizer-root /data/jzhu484/Agent/datasets/Qwen3.5-9B \
  --base-model-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-dual-route-v5/base-model-lock.json \
  --output /data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/pilot-3task-v1 \
  --campaign-id cva6-hwe-deepseek-harness-pilot-3task-v1
```

The output directory must be new. Collection stops immediately on an infrastructure-invalid
attempt and never retries it. Normal verifier rejection is retained as a valid pilot outcome and
does not produce SFT labels. Finalization validates transcript causality, tokenizer and base-model
hashes, exact loss masks, secret/artifact policy, and dataset schema. Campaign and dataset receipts
always state `production_training_ready=false`, `training_started=false`,
`hpc_jobs_submitted=false`, and `gpu_hours=0`.

A failure before any model call is not a trajectory sample. After correcting such an
infrastructure preflight defect, a distinct campaign ID/output may use
`--supersedes-zero-call-preflight` to bind the prior sealed `campaign-report.json`. The runner
accepts that receipt only when every prior attempt has zero actions, no normalized transcript, and
zero or unavailable model-call accounting. It preserves the failed campaign and does not count the
new run as a retry of a model trajectory.

The v3 pilot uses a distinct output and requires the sealed v2 report as a predecessor receipt:

```bash
python scripts/collect_cva6_hwe_deepseek_v3.py \
  --qualification-root /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1 \
  --image-lock-dir /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/image-locks \
  --tokenizer-root /data/jzhu484/Agent/datasets/Qwen3.5-9B \
  --base-model-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-dual-route-v5/base-model-lock.json \
  --predecessor-report /data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/pilot-3task-v2/campaign-report.json \
  --output /data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/pilot-3task-v3 \
  --campaign-id cva6-hwe-deepseek-harness-pilot-3task-v3
```

## v69 multi-task zero-provider materialization

The later v69 path is manifest-driven and does not run a model. It freezes three Ibex tasks
(`PR-465`, `PR-1135`, and `PR-1780`) followed by two CVA6 tasks (`PR-2017` and `PR-2711`). It also
records the Ibex fallback order `PR-48`, `PR-293`, reserves `PR-1816` for the open-tool comparison,
and marks CVA6 `PR-3042` and `PR-3137` unavailable until completed archives and sidecars exist.
Historical, held-out, already authorized, and provider-consumed tasks cannot enter the schedule.

Run the materializer only from a clean, merged `main` after all eight required post-merge workflow
classes pass. The command accepts only the frozen local archive/tool paths, refuses provider
credential variables, hashes each completed archive in full, never contacts a registry, and runs
qualification and image inspection with `network=none`:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V69_ZERO_PROVIDER=1 \
  python scripts/materialize_hwe_deepseek_harness_v69.py \
  --post-merge-main-run-id <successful-main-run-id>
```

The new output root is fixed under `/data2/jiadongzhu/Agent/experiments/`. The runner writes atomic
progress after each task, but `provider-contract.json` is the last publication and is never
created for a partial matrix. A completed contract still states
`provider_execution_authorized=false`; v70 must independently audit it before a successor can be
authorized. The v69 manifest and receipt models live in
`src/verigym/hwe/deepseek_harness_campaign.py`.

V69 later stopped at its filesystem headroom gate before archive or Docker access. The v70 audit
sealed that attempt with zero provider calls and no task consumption. The separately registered
v71 successor reruns the complete five-task zero-provider materialization on a Docker 23.0.6 DinD
daemon whose persistent local-driver volume is bind-backed by the exact campaign directory under
`/data2/jiadongzhu/docker/`. It revalidates the v69 manifest and stopped report, all five patches,
all archive/image/source locks, base-FAIL/reference-PASS, command-image scans, and cleanup; it does
not import v69's partial receipts as qualification evidence.

Run v71 only once from its clean merged `main` commit after all eight post-merge workflow classes
pass and after removing provider variables without exposing their values:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V71_DIND_ZERO_PROVIDER=1 \
  python scripts/materialize_hwe_deepseek_harness_v71_dind.py \
  --post-merge-main-run-id <successful-main-run-id>
```

V71 still publishes `provider_execution_authorized=false` and requires an independent v72 result
audit. Because the failure consumed the next unused version, the official model matrix and later
toolchain stages move to new identities after v72; no earlier planned version is silently reused.

V71 subsequently stopped after PR-465 qualification and command-image build but before its
security scan. V72 froze the attempt because the inherited bounded helper rejected nonempty build
output and the exception path incorrectly inferred socket cleanup from outer resource removal.
V73 is a new clean-room successor: it neither reuses nor opens the v71 data backing, reruns all five
tasks from the original completed archives, and uses new `verigym-deepseek-harness-v73-dind-*`
volumes backed under `/data2/jiadongzhu/docker/deepseek-harness-hwe-v73/`.

Run v73 only once from its clean merged `main` commit after all eight post-merge workflow classes
pass, again with provider and Docker routing variables removed without exposing their values:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V73_DIND_ZERO_PROVIDER=1 \
  python scripts/materialize_hwe_deepseek_harness_v73_dind.py \
  --post-merge-main-run-id <successful-main-run-id>
```

Every command-image build gets a content-free bounded diagnostic, and provider-contract publication
requires the separately hashed socket-cleanup receipt. A successful result remains
`provider_execution_authorized=false` until the independent v74 audit is merged and its post-merge
`main` run passes all eight classes.

V73 subsequently stopped before its first command-image runtime scan could create a container.
V74 froze the zero-provider result and traced the failure to a scanner bind source outside the
single same-path output mount visible to the nested daemon; it also identified the transient
`runc/` socket-volume path missing from the cleanup allowlist. V75 is the next fresh identity. It
retires and never reopens the v73 data volume, uses new `/data2`-backed data/socket volumes, places
every scanner workspace below `output/scan-workspaces`, and verifies that directory is empty after
each task. Its cleanup allowlist includes `runc/`.

Run v75 exactly once only after its authorization is merged and all eight post-merge `main` job
classes pass, with provider and Docker routing variables removed without exposing their values:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V75_DIND_ZERO_PROVIDER=1 \
  python scripts/materialize_hwe_deepseek_harness_v75_dind.py \
  --post-merge-main-run-id <successful-main-run-id>
```

Any failure remains pre-provider and publishes no partial contract. A complete v75 result still
sets `provider_execution_authorized=false` until an independent v76 audit is merged and its own
post-merge `main` checks pass.

V75 subsequently completed all three Ibex tasks, then stopped during PR-2017 source preparation.
V76 froze the result and identified the exact CVA6 task-image bridge
`.hwe_tools/verilator -> /tools/verilator-v5.008`; the generic source sanitizer correctly rejected
that escaping link. V77 uses a new identity and new `/data2` storage. It adds only `.hwe_tools` to
the CVA6 profile exclusions and keeps the generic rejection of every unlisted escaping symlink.

Run v77 exactly once only after its authorization is merged and all eight post-merge `main` job
classes pass, with provider and Docker routing variables removed without exposing their values:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V77_DIND_ZERO_PROVIDER=1 \
  python scripts/materialize_hwe_deepseek_harness_v77_dind.py \
  --post-merge-main-run-id <successful-main-run-id>
```

Any failure remains pre-provider and publishes no partial contract. A complete v77 result still
sets `provider_execution_authorized=false` until an independent v78 audit is merged and its own
post-merge `main` checks pass.

V77 subsequently completed all three Ibex tasks and the CVA6 source-profile repair, then stopped
at the PR-2017 source-binding gate. V78 froze the result and found that the historic v69 helper
conflated the public dataset base with the official image's digest-locked runtime marker. V79 uses
one exact PR-2017 override, requires equality for every other task, and records both identities in
canonical task receipts. It uses a new identity and new `/data2` storage and never reopens v77.

Run v79 exactly once only after its authorization is merged and all eight post-merge `main` job
classes pass, with provider and Docker routing variables removed without exposing their values:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V79_DIND_ZERO_PROVIDER=1 \
  python scripts/materialize_hwe_deepseek_harness_v79_dind.py \
  --post-merge-main-run-id <successful-main-run-id>
```

Any failure remains pre-provider and publishes no partial contract. A complete v79 result still
sets `provider_execution_authorized=false` until an independent v80 audit is merged and its own
post-merge `main` checks pass.

## PR-1816 open-toolchain comparison

The v171 audit froze v170 with a clear provider marker and zero calls. The separate v172 campaign
does not retry that official matrix. It performs a zero-provider comparison for the PR-1816 task
reserved by v69, using only completed local archives and a fresh DinD data root bind-backed under
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v172/`.

The agent-side image contains the pinned VeriGym open stack (Verilator 5.008, Icarus 12, Yosys
0.67, and ripgrep 15.2.0) and contains no HWE task-image tools, provider credential, or Codex
installation. Its public test result is diagnostic only. The same base and official reference are
then verified separately by the digest-locked PR-1816 HWE image. Both routes must reproduce
base-FAIL/reference-PASS, remain `network=none`, and bind different receipt hashes before a
qualification contract can exist.

Run v172 once only from its clean merged `main` commit after all eight post-merge workflow classes
pass. The launcher removes provider and ambient Docker endpoint names without reading or emitting
their values:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V172_OPEN_TOOLCHAIN=1 \
  python scripts/launch_hwe_deepseek_harness_v172_open_toolchain.py \
  --post-merge-main-run-id <successful-v172-main-run-id>
```

A successful result remains pending the independent v173 audit. The one-call PR-1816 research
canary (seed/sample 503/19) is not authorized here. Formal collection, SFT, training, candidate
mixing, and production readiness remain false.

V172 stopped in its read-only preflight because Docker returned the expected DinD lock as
`docker@sha256:...` while the runner tested direct membership of the bare `sha256:...` component.
V173 sealed the attempt with no output, Docker mutation, task execution, verifier run, model, or
provider consumption. Do not retry v172.

V174 is the fresh zero-provider qualification repair. It binds the v172 stop receipt and v173
audit, preserves the frozen PR-1816 and open-toolchain inputs, and uses new output, scratch,
`/data2`-backed DinD, volume, and tag identities. Its repaired preflight accepts only one exact
`docker@sha256:...` value and separately verifies the frozen image ID and `linux/amd64` platform.
The hash-bound v174 final Dockerfile changes only its internal builder stage reference from the
retired `v172-builder` tag to the fresh `v174-builder` tag.
Run it exactly once from clean merged `main` after all eight post-merge workflow classes pass:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V174_OPEN_TOOLCHAIN_REPAIR=1 \
  python scripts/launch_hwe_deepseek_harness_v174_open_toolchain_repair.py \
  --post-merge-main-run-id <successful-v174-main-run-id>
```

A successful result remains pending an independent v175 audit. The PR-1816 DeepSeek research
canary moves to v176 or later and remains unauthorized. Formal collection, SFT, training,
candidate mixing, and production readiness remain false.
