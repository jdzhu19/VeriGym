# CVA6 Codex HWE container-native collection

The current production path is versioned separately from both the strict repository-action
teacher path and the legacy HWE v1 path. It freezes these identities:

- collection profile: `hwe_standard_v2`;
- observation policy: `hwe_repository_observation_v2`;
- tool contract: `hwe_native_shell_v2` over the `repository_action.v2` envelope;
- prompt: `codex_cli_hwe_native_shell_context_v9`;
- exec lifecycle: `hwe_exec_process_lifecycle_v2`;
- transcript: `verigym_hwe_teacher_multiturn_transcript_v3`;
- SFT example: `verigym_hwe_verified_multiturn_sft_v3`;
- dataset: `verigym_hwe_verified_multiturn_sft_dataset_v3`;
- Codex/model: Codex CLI 0.147.0 and GPT-5.4 with `xhigh` reasoning;
- tokenizer: exactly `tiktoken==0.7.0` with `o200k_base`.

The older `hwe_standard_v1`, prompt v2, transcript/SFT v2, and image-lock v1 identities remain
readable and replayable. Their lexical shell restrictions and hashes are unchanged. A legacy
campaign cannot be resumed under v2, and its results are never relabeled or converted.

## Collection and observation contract

The public action vocabulary remains `list_files`, `read_file`, `apply_patch`, `shell`,
`inspect_diff`, and `finish`. Direct filesystem and patch methods remain workspace-relative and
workspace-bounded. In v2, `shell` uses the agent container as its read boundary: commands such as
`find ..`, absolute-path tool inspection, and ordinary compiler discovery are allowed. Only
changes under `/workspace/repository` become the candidate. The root filesystem is read-only;
`/tmp` is a bounded, ephemeral tmpfs; provider credentials and hidden/verifier/reference assets
are absent. Environment assignment, unapproved active expansion, interactive process control, a
model-chosen timeout, and noncanonical `cwd` values remain rejected. V2 permits only the frozen,
non-secret `PWD`, `RISCV`, and `VERILATOR_ROOT` reads needed for workspace and toolchain discovery.
`HOME`, `OLDPWD`, credential variables, and model-selected environment injection remain rejected.

Codex control-plane direct read-only filesystem probes outside the workspace are deterministically
mapped to one fixed nonexistent workspace path. They expose no container contents and are not
normalized as training actions. Direct mutations remain fail-closed; an agent that needs an
allowed container-native read must use the audited `shell` action.

This policy takes the trajectory/observation lessons from R2E-Gym—retain complete action order,
bound each returned observation deterministically, and preserve useful head/tail/diagnostic
evidence—without adopting R2E-Gym's agent tools, security boundary, or numerical limits. The
reference is pinned to R2E-Gym commit
[`0d94c4e`](https://github.com/R2E-Gym/R2E-Gym/tree/0d94c4eb9431cd195c55a7ea3abd54006c9a1735),
including its
[`Observation`](https://github.com/R2E-Gym/R2E-Gym/blob/0d94c4eb9431cd195c55a7ea3abd54006c9a1735/src/r2egym/agenthub/observation/observation.py)
implementation. HWE-specific structural views additionally recognize SystemVerilog and
Chisel/Scala, while generated/vendor/third-party trees are omitted from the initial shallow view
but remain available to scoped inspection.

The Codex 0.147 exec-server broker correlates JSON-RPC request/response pairs and the
`process/start` -> streamed `process/output` -> `process/exited` -> `process/closed` lifecycle.
Lifecycle v2 also accepts the observed early-close delivery order only by buffering a known
active `process/closed` event until its causally earlier `process/exited` event arrives; a missing,
unknown, duplicate, or inconsistent event still fails closed. A single correlated interrupt of a
known active process is recorded as part of that shell action. Concurrent process starts are
forbidden so workspace epochs and shell-based mutations remain causally ordered.
It freezes argv/cwd, disables interactive stdin, stores bounded raw output privately, and returns
one deterministic compact observation. Unknown output-bearing command, process, filesystem, or
patch methods fail closed. Bash `-c` and `-lc` wrappers are reduced to the exact inner command;
v2 does not rewrite container-native paths in either the command or its output.

Every compact command result records command identity, cwd, exit code, duration, raw stdout and
stderr sizes/hashes, compact token count, rule ID, and explicit omission markers. List/search/read,
generic shell, compile/simulation diagnostics, and diff each use their own deterministic
compactor. Raw limits are 32 MiB per command and 256 MiB per episode. Model-visible preferred/hard
limits are 4K/8K tokens for reads and shell output and 8K/16K for diffs; list and search have the
smaller frozen limits in the profile. Exact token counting is mandatory—collection fails closed if
the frozen tokenizer is unavailable.

Decision steps have soft/hard limits of 80/200 and mutation actions 16/32. Soft overflow is marked
long-horizon; hard overflow terminates the episode. Collector-owned timeouts are 60 seconds for
ordinary commands, 600 for compilation, and 900 for simulation/regression, within a 3600-second
episode wall limit.

## Agent images and isolation

Build one agent image for every task-keyed official verifier image. The offline build uses the
already-local immutable image ID, whiteouts `/home/cva6`, and injects the hash-checked native Codex
exec-server plus its bundled static `rg`:

```console
scripts/build_cva6_hwe_agent_image.sh \
  /absolute/path/to/vendor/x86_64-unknown-linux-musl/bin/codex \
  sha256:VERIFIER_IMAGE_ID \
  hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032 \
  verigym/cva6-hwe-pr-2032:0.147.0-v2-sanitized-v1 \
  /data/jzhu484/Agent/experiments/hwe-image-receipts-v2/pr-2032.json
```

Complete the receipt with task/source hashes, distinct host-launcher and agent-native Codex hashes,
the public toolchain artifact allowlist, and a passed security scan, then seal it as
`verigym_hwe_agent_image_lock_v2`. Collection accepts no version or hash substitution. Runtime
controls remain non-root, `network=none`, read-only rootfs, cap-drop, no-new-privileges, private
PID/IPC, one visible persistent workspace mount, and bounded ephemeral `/tmp`. The host app-server
alone retains provider credentials.

## Campaign and artifacts

Install the opt-in exact tokenizer and integration packages, then run the guarded campaign:

```console
python -m pip install -e '.[dev,openai-compatible,hwe-collection]'
VERIGYM_RUN_CVA6_HWE_COLLECTION=1 \
  scripts/collect_cva6_hwe_codex.py \
  --qualification-root /data/jzhu484/Agent/experiments/CVA6_QUALIFICATION \
  --image-lock-dir /data/jzhu484/Agent/experiments/HWE_IMAGE_LOCKS_V2 \
  --output /data/jzhu484/Agent/experiments/CVA6_HWE_COLLECTION_V2 \
  --campaign-id cva6-codex-hwe-native-shell-v2
```

The campaign first runs PR 2032, PR 2549, and PR 2944. It proceeds only when all three are
infrastructure-valid, at least two pass the benchmark verifier, and at least one is primary
eligible. It then samples the frozen 11-task pool at most once per task and stops at eight primary
successes or a terminal condition. There is no post-model retry, best-of-K, automatic resampling,
or model replacement. A clean startup failure is automatically relaunched at most twice only when
external model calls are exactly zero, no candidate path changed, runtime cleanup completed, and
the failure has no security/credential/identity/hash marker. Those launches do not consume the
task's one sample and are recorded in a hashed restart ledger. Pilot counts are not a benchmark
score.

Raw provider/exec events live only under each run's `private-audit/`. They are written mode 0600,
bounded, secret-scanned, hash checked, and frozen mode 0400. They never enter reports, held-out
artifacts, transcripts, or datasets. The second SFT pass permits only ANSI/progress cleanup,
exact-repeat folding, and same-workspace-epoch exact observation references; failed causal
validation rejects the example.

Reports separately count benchmark verifier pass, normalized success, primary eligibility,
long-context candidates, and rejection reasons. Compact records at or below 32K tokens are primary
eligible. The 32K-64K bucket is recorded but disabled for training; larger records remain
audit-only. The handoff uses
[qwen35_hwe_sft_v3.json](../configs/training/qwen35_hwe_sft_v3.json) with `truncation=error` and
assistant-only supervision. It never submits an HPC or GPU job.

Collection is incomplete until the report contains eight new verifier-resolved,
infrastructure-valid primary examples. Historical strict/48K/host-direct runs and the immutable
v1 infrastructure-invalid campaign remain audit evidence only.

## Rollout length versus training length

The full causally ordered transcript remains the unit used by the current primary-eligibility
gate. A verifier-passed transcript of 32K--64K tokens is retained as a long-context candidate but
is not silently truncated, windowed, or relabeled as a primary SFT example.

This distinction is consistent with DeepSWE's published separation between training and
evaluation. Its
[training script](https://github.com/agentica-project/rllm/blob/main/examples/swe/train_deepswe_32b.sh)
uses a 4K prompt, 32K response, and 32K PPO token bound, while the official
[R2E-Gym evaluation recipe](https://github.com/R2E-Gym/R2E-Gym/blob/main/reproduction/DEEPSWE_REPRODUCTION.MD)
uses a 64K context and up to 100 environment steps. The
[DeepSWE recipe](https://www.together.ai/blog/deepswe) also masks trajectories that terminate at
the context, step, or timeout limit during RL. These results support retaining longer HWE
rollouts for evaluation or a future RL path; they do not establish that an 80K teacher transcript
can be converted losslessly into a 32K SFT example.

Any future step-window training view must therefore receive a new format and policy identity,
carry an explicit causal-state contract, and be evaluated separately. It cannot change the
meaning of `primary_eligible` in an already frozen campaign.

## Experimental action-conditioned observation masking

The separately versioned `hwe_action_preserving_observation_masking_v1` policy implements that
training view without changing the frozen transcript or primary formats. For each recorded tool
action it constructs one record containing the exact history before that action and the unchanged
target assistant tool call. It retains all prior assistant actions, the most recent `M`
observations, and at most four current-workspace-epoch observations selected from mutation, diff,
failure, compile, and simulation evidence. Every older observation becomes a deterministic marker
containing its public compact-content hash, byte/token counts, normalized sequence, action, and
workspace epoch.

The record format is `verigym_hwe_action_conditioned_sft_v1`; its dataset manifest is
`verigym_hwe_action_conditioned_sft_dataset_v1`. Only the final assistant message in each record
is supervised, including when prior assistant messages remain in the input. The schemas are
[record](schemas/hwe-action-conditioned-sft.schema.json),
[dataset](schemas/hwe-action-conditioned-sft-dataset.schema.json), and
[analysis](schemas/hwe-observation-masking-analysis.schema.json). The experimental trainer
configuration is
[qwen35_hwe_action_conditioned_sft_v1.json](../configs/training/qwen35_hwe_action_conditioned_sft_v1.json)
and remains disabled pending a separate quality gate.

This is structural action preservation, not a counterfactual model guarantee. The target action
and every preceding action are byte-identical, but the collector does not spend additional model
calls to prove that GPT-5.4 would regenerate the same action under each masked view. Records
therefore state `counterfactual_next_action_validation=not_run`, are always
`primary_eligible=false`, and cannot enter the existing eight-example primary binding. A future
CoACT-like learned compressor requires another identity, HWE-specific training data, and its own
action-equivalence gate.

The current Codex app-server owns the provider conversation. Its remote exec-server boundary can
compact each new observation before it enters the conversation, but cannot retroactively replace
older provider-history messages. Consequently `live_rollout_masking_applied=false`: this policy is
an exact derivation for action-conditioned training/evaluation, not a claim about the historical
context used during the original Codex rollout.

Use the bounded analyzer on sealed transcripts as follows:

```console
python scripts/analyze_hwe_observation_masking.py \
  --transcript /absolute/path/to/hwe_teacher_transcript.json \
  --windows 8 10 16 \
  --output /absolute/path/to/hwe-observation-masking-analysis-v1.json
```

The analysis selection rule chooses the largest tested window for which every target-action record
remains at or below 32K. The initial two-trajectory analysis selected `M=16`. The completed fresh
production campaign below deliberately froze the more aggressive `M=1`, `P=1` view (one recent
observation and at most one pinned current-epoch diagnostic) under a different policy hash. An
unseen trajectory still fails closed if any derived record exceeds 32K.

### Fresh action-conditioned campaign

The collector has a separate `--campaign-mode action-conditioned` path. It freezes GPT-5.4
`xhigh`, seed 484, prompt v9, the v2 collection/observation/tool identities, exec lifecycle v2,
all eleven task-keyed image-lock hashes, the exact tokenizer identity, and the selected history
policy parameters in `verigym_hwe_cva6_codex_action_conditioned_campaign_report_v3`. It performs
fresh model rollouts; it does not import successful trajectories from an earlier campaign or
relabel their primary status.

The three pilots remain PR 2032, PR 2549, and PR 2944. The gate requires all three runs to be
infrastructure-valid, at least two benchmark verifier passes, and successful deterministic
materialization of every verifier-passed trajectory into records no longer than 32K. Passing the
gate continues through the frozen pool with one sample per task until eight
`action_conditioned_eligible_success` trajectories are collected or the pool is exhausted.

```console
VERIGYM_RUN_CVA6_HWE_COLLECTION=1 python scripts/collect_cva6_hwe_codex.py \
  --campaign-mode action-conditioned \
  --qualification-root /absolute/path/to/cva6-multiturn-sft-qualification-v1 \
  --image-lock-dir /absolute/path/to/cva6-hwe-codex-native-shell-v2/image-locks-baseline-v2 \
  --output /absolute/path/to/new-action-conditioned-campaign \
  --campaign-id unique-frozen-campaign-id \
  --history-recent-observations 1 \
  --history-max-pinned-observations 1
```

Each accepted trajectory stores a sealed per-trajectory JSONL plus a manifest of record hashes,
source transcript hash, maximum record length, and public-file hash. If eight trajectories are
obtained, the collector writes a distinct experimental dataset, bindings, and disabled handoff.
It never writes the historical primary dataset format and never submits an HPC or GPU job.

### Completed M1/P1 campaign

The frozen campaign
`cva6-codex-hwe-action-conditioned-v1-m1p1-v9-lifecycle2-1` completed on 2026-08-21.
Its three-task pilot passed 3/3, then five production tasks supplied the remaining accepted
trajectories. All eight attempts were first samples, infrastructure-valid, verifier-passed, and
normalized successes; there were no model-policy rejections, zero-call restarts, retries,
best-of-K choices, or model substitutions. This gate result is not reported as a benchmark score.

The eight source transcripts comprise two legacy primary-bucket lengths, five long-context
candidates, and one audit-length transcript. The separately versioned M1/P1 derivation produced
419 action-conditioned records, with a maximum record length of 26,486 tokens and no truncation.
The dataset hash is
`3a0905c578ca70b9af0ac5a17d0bf100d21e4357445882321616bf26f55fe841`.
Every preceding assistant action and the target action remain exact; old observations are replaced
only by typed hash markers. Counterfactual next-action validation remains `not_run`, so the data is
`experimental_action_conditioned`, not historical `primary_eligible` data.

The generated handoff binds
[qwen35_hwe_action_conditioned_sft_v2.json](../configs/training/qwen35_hwe_action_conditioned_sft_v2.json),
uses `max_length=32768`, `truncation=error`, and final-assistant-action-only supervision. It records
`requires_separate_quality_gate=true`, `training_config_enabled=false`, and
`hpc_jobs_submitted=false`; completing collection did not launch training.
