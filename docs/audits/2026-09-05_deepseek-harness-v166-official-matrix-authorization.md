# DeepSeek Harness v166 replacement official matrix authorization

Date: 2026-09-05

Status: **one provider-bearing execution authorized only after merge and green post-merge
`main`**.

## Decision and immutable inputs

Authorize exactly one execution of `deepseek-harness-hwe-v166-official-matrix-v1`. V166 is a
fresh replacement identity; it does not rerun or relabel the consumed v162 matrix or the consumed
v164 diagnostic. The v165 audit accepted v164's successful direct and Harness initialization
probes and permits this separately reviewed successor. Provider execution remains closed until
this authorization is merged and the exact merge passes all eight `main` job classes.

- Manifest SHA-256: `e1efc66fa18b3a809533b1dfc40c446687058a6891bbdecf61774d261e44b64d`
- Manifest canonical hash: `18b9c5fa89bd81b2cfad4ed9f573d239088c7fbb243b938e82ab44d8156e722b`
- Runner SHA-256: `1b2e421905abf7e41047a98ef05d5a9ba4137b54f62c3530b1515943edcea6f2`
- Launcher SHA-256: `f0aac83b2dbe2c9c2efb1037483d7796855c02b3f703f434715821963861f948`
- v165 audit commit: `238178400e7d3c8126cc899d9bb8f1c325f88a6e`
- v165 audit merge: `8dfee24e6fb90c7fb21e9a58902d638ce4d52095`
- v165 post-merge `main`: `33971109229`, eight of eight job classes passed

The runner rejects a non-`main`, dirty, or non-up-to-date checkout and verifies that the v165
audit commit is an ancestor. Its required post-merge run ID is recorded in atomic progress. A
failed implementation, PR, or post-merge gate does not authorize execution.

## Frozen predecessor and task boundary

V166 revalidates every frozen implementation file and canonical receipt used by v158 and v160,
the complete v158 and v160 evidence trees, the v162 manifest/runner/launcher/authorization and
complete zero-consumption result tree, the v163 audit, the v164 implementation and complete
successful diagnostic tree, and the v165 audit. It requires v162 to remain a pre-provider
infrastructure failure with marker `not_started`, zero calls and tokens, no effective change, no
admitted data, and confirmed cleanup. It requires v164 to remain a provider-free successful
controller diagnosis with no task or verifier execution and confirmed cleanup.

The exact retained `verigym-deepseek-harness-v158-dind-data` volume has a cumulative reopen count
of two before v166. V166 may reopen it exactly once, making three the terminal budget. It creates
fresh v166 socket, control, runtime, output, and receipt identities under `/data2`. It does not
pull, import, rebuild, substitute, or use `.partial` images; all five v158 task/source/image locks,
29-check command-image scans, toolchain profiles, and official verifier identities remain exact.

## Matrix and protocol

Execute strictly and serially with seed/sample `502/18`: Ibex PR-465, PR-1135, PR-1780, then CVA6
PR-2017 and PR-2711. The fixed model is DeepSeek v4 Flash through Harness `0.1.1-rc.2`, integration
`0.5.0`, and revision `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`. Per task: at most 64
calls, 1,000,000 provider tokens, 65,536 context tokens, 2,048 output tokens, temperature zero,
and zero request or episode retries. Tool choice is `auto`; public rationale and sibling calls are
preserved. Hidden reasoning, foreign tools, illegal paths, and unpaired observations fail closed.

A pre-marker infrastructure or security failure stops without consuming that task. The same
failure after a valid or conservatively unreadable marker consumes it and stops. Ordinary model
or verifier rejection consumes the task and continues. Two consecutive no-progress,
no-effective-modification, or trajectory-structure outcomes stop the remainder. Every admitted
decision uses the exact Qwen tokenizer, is strictly shorter than 65,536 tokens, is never
truncated, and applies the decision-only loss mask. Candidate admission requires all verifier,
protocol, trajectory, infrastructure, security, and SFT planes together.

## Docker, provider, and publication boundary

Before the first provider request, the absolute host-root headroom gate, all five explicit
runtime probes, complete 12-image inventory, empty mutable inner inventory, and zero-call Harness
initialization must pass. The runtime registry creates a fresh Docker CLI engine bound to the
canonical v166 nested Unix socket for each task, and the Harness settings fingerprint and forward
that same endpoint. Agent command and official verifier sessions use `network=none`; only the
outer DinD and inner controller may use `verigym-hwe-net`.

The launcher selects blocked environment entries by name before reading values, removes the
frozen twelve-name provider set and both Docker endpoint variables, and restores only the two
DeepSeek names required inside the child. Concrete provider and proxy values are never printed,
persisted, or hashed. Cleanup is bounded and removes only v166-owned socket resources; the
retained v158 data volume and all unrelated Docker resources are preserved. Docker daemon and VPN
configuration are not changed.

Run exactly once after merge and the new green post-merge gate:

```text
VERIGYM_RUN_DEEPSEEK_HARNESS_V166_OFFICIAL_MATRIX=1 \
python scripts/launch_hwe_deepseek_harness_v166_official_matrix.py \
  --post-merge-main-run-id <green-main-run-id>
```

The terminal result is pending an independent v167 audit. Candidate SFT import remains closed;
failed trajectories remain audit context only. `formal_collection_allowed`,
`formal_collection_started`, `collection_started`, `training_started`, and
`production_training_ready` remain false. This authorization does not start formal collection,
SFT, GPU work, benchmark scoring, or production training.
