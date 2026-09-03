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
