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

V174 subsequently passed the corrected preflight but its generic offline Icarus builder command
returned nonzero before DinD, task-image import, source preparation, either PR-1816 route, or any
model/provider boundary. The quiet frozen helper did not retain enough output to assign a unique
cause. V175 sealed its five-file result with zero task and provider consumption; do not retry
v174.

V176 is the fresh zero-provider successor. It binds the complete v174 result and v175 audit, uses
new `/data2` output, scratch, DinD backing, volume, builder, final-image, and scan identities, and
changes the generic builder Dockerfile only by removing its external frontend directive. The
builder still runs with `--network none --pull=false`; success therefore requires the complete
frozen closure to be local. Its controller retains no raw logs and emits only a one-MiB-bounded,
credential-scanned category, byte counts, and safe output hashes.

Run v176 exactly once from clean merged `main` after all eight post-merge workflow classes pass:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V176_OPEN_TOOLCHAIN_REPAIR=1 \
  python scripts/launch_hwe_deepseek_harness_v176_open_toolchain_repair.py \
  --post-merge-main-run-id <successful-v176-main-run-id>
```

Both PR-1816 routes must still independently reproduce base-FAIL/reference-PASS before the atomic
qualification contract is published. A successful result requires a v177 audit. The DeepSeek
research canary is v178 or later and remains unauthorized here; collection, candidate/SFT mixing,
training, and production readiness remain false.

V176 then stopped at its generic network-none builder with the bounded category
`offline_cache_miss`. V177 froze the six-file result: no DinD, HWE image import, task, verifier,
model, or provider boundary was reached, and PR-1816 remains unconsumed. Do not retry v176.

V178 binds a completed Docker archive under `/data2` instead of rerunning the generic builder. The
archive is a Debian base plus the Verilator build dependencies recovered from a completed
dependency-only stage; it contains no OpenSTA, CUDD, HWE, or Codex executable. The manifest locks
its archive and sidecar hashes, exact image ID, parent, two ordered rootfs layers, member inventory,
canonical history, 189-package inventory, and six required build-tool hashes and versions. The
runner validates the archive before creating campaign state, loads it only into the isolated
`/data2`-backed DinD daemon, and verifies it with a non-root, read-only, mount-free,
resource-bounded, `network=none` probe. The final Verilator/ripgrep build and both PR-1816 routes
remain offline; there is no host builder dependency, download, registry access, VPN/proxy change,
or HWE-tool inheritance.

Run v178 exactly once from clean merged `main` after all eight post-merge workflow classes pass:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V178_LOCAL_BUILDER=1 \
  python scripts/launch_hwe_deepseek_harness_v178_local_builder.py \
  --post-merge-main-run-id <successful-v178-main-run-id>
```

The qualification contract is atomic and requires both the agent-only open route and the official
authoritative verifier route to reproduce base-FAIL/reference-PASS, plus the builder binding,
image scan, and cleanup gates. A successful result remains pending v179. The research-only
DeepSeek canary is v180 or later and is not authorized by v178; collection, SFT mixing, training,
and production readiness remain false.

V178 passed its archive, image, patch, and capacity gates but stopped before outer DinD creation.
The inherited v172 Docker command appended a bare `rw` field to `--mount`; the installed CLI
rejects that syntax before container creation. V179 freezes the six-file, zero-provider,
fully-cleaned stop and authorizes only a fresh v180 qualification successor that omits the invalid
field while retaining the default writable bind behavior. Do not retry v178. V180 still authorizes
no model, provider, collection, SFT, training, or production operation.

V180 changes only the two writable output and scratch bind arguments: it omits their rejected bare
`rw` field and verifies that Docker materializes both as writable. The host-sentinel bind retains
its accepted `readonly` field, and both named DinD volumes retain `:rw`. The runner rejects any
extra mount, source/name/destination drift, wrong effective read/write mode, host Docker socket,
provider/proxy environment, changed network, or changed daemon identity. All v178 archive, image,
task, open-tool, official-verifier, scan, dual-route, and cleanup locks are inherited unchanged.

Run v180 exactly once from clean merged `main` after all eight post-merge workflow classes pass:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V180_DIND_MOUNT_REPAIR=1 \
  python scripts/launch_hwe_deepseek_harness_v180_dind_mount_repair.py \
  --post-merge-main-run-id <successful-v180-main-run-id>
```

A successful result remains pending independent v181 audit. The separately versioned v182
research-only canary remains unauthorized; formal collection, SFT mixing, training, and production
readiness remain false.

V180 started its corrected outer DinD and passed the exact local-builder archive and runtime probe,
then the offline final command-image build returned nonzero. Its inherited quiet helper retained no
raw output, so v181 freezes category `offline_final_image_build_nonzero` without asserting a
compiler-level cause. The normal exception path removed the DinD container and volumes, but a
second `PermissionError` on the root-owned backing prevented a terminal report. A separately
bounded, exact-path, networkless cleanup removed only the v180 backing and scratch while preserving
the seven-file result tree and immutable input archives.

Do not retry or resume v180. PR-1816 remains task- and provider-unconsumed: the HWE image was never
imported, no source or verifier was run, and no model/provider boundary was reached. After v181 is
merged and its post-merge checks pass, v182 may be defined only as a task-free zero-provider build
diagnostic with bounded, credential-scanned output and root-owned-backing cleanup. It is not the
research canary and does not authorize collection, SFT, training, or production use.

V182 is that one-use diagnostic. It imports only the accepted open-tool image and completed local
dependency builder into a fresh `/data2`-backed, networkless DinD daemon. It uses the exact v180
Dockerfile with `--network none --pull=false`, captures at most 16 MiB for at most 3,600 seconds,
and persists only a fixed category, byte counts, and safe hashes after an in-memory credential
scan. Its inspected, least-capability cleanup helper owns only the exact v182 backing parent, and
the controller seals a terminal report even when cleanup fails.

Run v182 exactly once from clean merged `main` after all eight post-merge classes pass:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V182_BOUNDED_OPEN_BUILD=1 \
  python scripts/launch_hwe_deepseek_harness_v182_bounded_open_build.py \
  --post-merge-main-run-id <successful-v182-main-run-id>
```

V182 does not inspect/import an HWE image, load task metadata, prepare source, run a verifier, start
a model, or call a provider. Its result requires a v183 audit before any qualification repair can
be authorized. PR-1816 and the research canary remain unconsumed; collection and training remain
closed.

The sole v182 invocation completed its bounded measurement and cleanup. The final build returned
1 with fixed category `missing_executable`; capture was within its 16-MiB and 3,600-second bounds,
the sensitive-value scan passed, and no raw output was retained. All task/model/provider counters
remained zero, and the inspected helper removed both volumes, all owned containers, backing, and
scratch. V183 freezes this result and does not infer the missing program from the category alone.

After v183 is merged and a new `main` run passes all eight classes, v184 may be defined only as a
task-free, zero-provider disambiguation. It may report an exact missing command solely from a
manifest-bound allowlist, must fail closed on unknown/multiple matches, and must preserve all v182
output, secret-scan, terminal-report, and cleanup controls. It is not a qualification or canary;
PR-1816, collection, SFT, training, and production use remain closed.

V184 binds the frozen v182 result and v183 audit, then reuses the exact v182 archives, images,
Dockerfile, build limits, network policy, and cleanup policy under fresh one-use resource names. A
separate builder probe records only booleans for the fixed command allowlist and runs without
network, mounts, root privileges, or a writable root. The bounded build parser can retain one exact
allowlisted basename plus counts; it retains no matching line, unknown token, path, command argv,
or environment value. Unknown and multiple matches fail closed. A result that names a builder
prerequisite remains only diagnostic evidence and does not authorize installing it.

Because the output, transfer archives, DinD data, and socket backing are all exact `/data2` paths,
v184 binds separate capacity gates: 9 GiB for the controller-only root filesystem and 50 GiB for
`/data2`. Both observed values and both thresholds are sealed; failure happens before transfer or
daemon creation.

Run v184 exactly once from clean merged `main` after all eight post-merge classes pass:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V184_MISSING_COMMAND=1 \
  python scripts/launch_hwe_deepseek_harness_v184_missing_command.py \
  --post-merge-main-run-id <successful-v184-main-run-id>
```

V184 is task-free and zero-provider. It cannot import an HWE image, prepare PR-1816, run either
verifier route, create a model process, call DeepSeek, publish a qualification contract, or begin
collection/training. Only a separately merged v185 audit may authorize a new repair identity.

The sole v184 invocation completed within its time/output bounds and cleaned every owned resource,
but both `: not found` matches were outside its fixed 35-command allowlist. Its frozen category is
`unknown_missing_executable`, with `missing_command=null`; no raw line or unknown token was
retained. The builder probe's unavailable-command booleans are not sufficient to identify the
failure, so v185 authorizes no dependency repair, PR-1816 qualification, or DeepSeek canary.

After v185 is merged and a new post-merge `main` run passes all eight classes, v186 may be defined
only as one task-free, zero-provider diagnostic-context refinement over the exact v184 build. It
may classify manifest-fixed shell/build contexts and at most one member of a closed command
dictionary, without retaining arbitrary tokens or hashes, raw lines, paths, argv, environment
data, or raw output. It cannot change dependencies or the Dockerfile. Collection, SFT mixing,
training, and production readiness remain closed.

V186 freezes the v184 evidence tree and v185 audit, then reruns only the exact bounded final-image
build under fresh `/data2` DinD, output, scratch, volume, and image identities. It does not alter
the Dockerfile or dependencies. A mount-free, read-only-root, non-root probe records booleans for
the fixed 119-command dictionary. The in-memory classifier accepts only fixed POSIX-sh, bash,
Make, and unscoped `: not found` contexts and can retain at most one dictionary command enum.
Unknown text and token hashes are never persisted; mixed, unscoped, unknown, and multiple matches
remain fail closed.

Run v186 exactly once from clean merged `main` after all eight post-merge classes pass:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V186_DIAGNOSTIC_CONTEXT=1 \
  python scripts/launch_hwe_deepseek_harness_v186_diagnostic_context.py \
  --post-merge-main-run-id <successful-v186-main-run-id>
```

V186 loads no HWE image or task, prepares no PR-1816 source, runs no verifier or model, and exposes
no provider client. It cannot authorize a dependency repair, qualification, canary, collection,
SFT mixing, training, or production use. Only an independent v187 audit may interpret its fixed
result.

The sole v186 invocation completed within its build and output bounds and cleaned all owned
resources. Its fixed classifier found two POSIX-sh `command not found` markers, both resolving to
the single closed-dictionary enum `git`; the separate isolated builder probe also recorded
`git=false`. No raw line, arbitrary token or token hash, path, argv, environment data, or raw output
was retained. V187 freezes that result and authorizes no HWE or provider action.

After v187 is merged and a new post-merge `main` run passes all eight classes, v188 may implement
one task-free, zero-provider minimal builder repair. It may add only a fully locked git package
closure to a fresh dependency-only builder, then rerun the otherwise exact v186 final-image build
offline. Any missing input acquisition must be a separately bounded, checksum-verified command
whose route is first verified not to use the VPN and whose container uses `verigym-hwe-net`, not
the broken default bridge. Partial archives and implicit registry downloads remain forbidden.

V188 requires fresh `/data2` resource identities and new absolute 4-GiB control-root and 50-GiB
`/data2` capacity observations. The control process keeps only bounded controller state on `/`,
while Docker backing, scratch, output, and the exported image remain on `/data2`; 4 GiB therefore
matches the ordinary campaign control-root floor without budgeting bulk image data twice. The
final build and probes remain `network=none`, with the same time/output bounds, sensitive-value
scan, fixed receipts, v2 image security scan, terminal report, and complete cleanup. V188 may not
load an HWE image or task, prepare PR-1816, run either verifier route, start a model, call DeepSeek,
publish a qualification contract, or begin collection/training. A later independent audit is
required before the PR-1816 dual-route qualification can be authorized.

The v188 implementation binds the completed git closure to one deterministic 11,653,120-byte tar
archive and six exact Debian package members. Acquisition is already complete; the execution
runner has no download path. It first derives a dependency-only builder from the immutable v178
builder, with `--network none --pull=false`, then proves that the closed 119-command probe differs
from v186 only at `git=false -> git=true`. It retags that derived image only inside the isolated
DinD daemon as the exact v180 builder input and rebuilds the unchanged v180 final Dockerfile.

A successful final build must pass the v2 agent-toolchain scan with nine executable hashes,
including `/usr/bin/git`, while the official HWE verifier image is absent from DinD. The resulting
non-authoritative image is exported atomically to its fresh `/data2` directory with a checked
Docker-save manifest and sidecar. The output report still publishes no qualification contract.
Invoke v188 only once from clean merged `main`, after a new eight-class post-merge run and a fresh
capacity check:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V188_GIT_BUILDER_REPAIR=1 \
  python scripts/launch_hwe_deepseek_harness_v188_git_builder_repair.py \
  --post-merge-main-run-id <successful-v188-main-run-id>
```

Whether the repair succeeds or fails, its sealed result requires independent v189 audit. No HWE
qualification or DeepSeek canary is implied by building or exporting the image.
