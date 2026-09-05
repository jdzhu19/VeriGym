# DeepSeek Harness v170 replacement official matrix authorization

Date: 2026-09-05

Status: **one provider-bearing execution authorized only after merge and green post-merge
`main`**.

## Decision and immutable inputs

Authorize exactly one execution of `deepseek-harness-hwe-v170-official-matrix-v1`. V170 is a
fresh replacement identity; it does not rerun or relabel the consumed v166 matrix or v168
diagnostic. The v169 audit accepted v168's zero-request initialization with the real provider
configuration and permits this separately reviewed successor. Provider execution remains closed
until this authorization is merged and the exact merge passes all eight `main` job classes.

- Manifest SHA-256: `59a7c188a1c5c1cf98dd0fc4959d907929781f91533806c08bf2264420aefbe4`
- Manifest canonical hash: `1e7c29b95ee380d5fb50df33a31d6a57f8cd2b1db329a2c6d3f527d02c152256`
- Runner SHA-256: `07753601460889a57acd4f5fedea55cef3401475dfccce562f296fb61c75d356`
- Launcher SHA-256: `2f8c9968444aecedb34fe415956a234d5b3f67d7f7fc29fa8a7251beacdb7213`
- v169 audit SHA-256: `1788543757777accc0e141d848e8a754db8a934c3f16d2ee1a36b1e53b80d68f`
- v169 audit commit: `e1b5f139074f5ef5c7ce66717fca80626cb30ef3`
- v169 audit merge: `c292325bad58d184537cc91a1673486df63eff95`
- v169 post-merge `main`: `33975720801`, eight of eight job classes passed

The runner rejects a non-`main`, dirty, or non-up-to-date checkout and verifies that the v169 audit
commit is an ancestor. Its required post-merge run ID is recorded in atomic progress. A failed
implementation, PR, or post-merge gate does not authorize execution.

## Frozen predecessor and task boundary

V170 revalidates every frozen implementation file and canonical receipt used by v158 through
v165, the complete v166 zero-consumption result tree, the v167 audit, the v168 implementation and
complete successful real-configuration diagnostic tree, and the v169 audit. It requires v166 to
remain a pre-provider infrastructure failure with marker `not_started`, zero calls and tokens, no
effective change, no admitted data, and confirmed cleanup. It requires v168 to remain a
zero-request successful initialization with real configuration, no task or verifier execution,
zero value hits, and confirmed cleanup.

The exact retained `verigym-deepseek-harness-v158-dind-data` volume has a cumulative reopen count
of four before v170. V170 may reopen it exactly once, making five the terminal budget. It creates
fresh v170 socket, control, runtime, output, episode, and receipt identities under `/data2`. It
does not pull, import, rebuild, substitute, or use `.partial` images; all five v158
task/source/image locks, 29-check command-image scans, toolchain profiles, and official verifier
identities remain exact.

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

Before the first provider request, the absolute host-root headroom gate, all five explicit runtime
probes, complete 12-image inventory, empty mutable inner inventory, and zero-call Harness
initialization must pass. The runtime registry creates a fresh Docker CLI engine bound to the
canonical v170 nested Unix socket for each task, and the Harness settings fingerprint and forward
that same endpoint. Agent command and official verifier sessions use `network=none`; only the
outer DinD and inner controller may use `verigym-hwe-net`.

The launcher selects blocked environment entries by name before reading values, removes the
frozen twelve-name provider set and both Docker endpoint variables, and restores only the two
DeepSeek names required inside the child. Concrete provider and proxy values are never printed,
persisted, or hashed. Cleanup is bounded and removes only v170-owned socket resources; the
retained v158 data volume and all unrelated Docker resources are preserved. Docker daemon,
downloader, proxy, and VPN configuration are not changed.

Run exactly once after merge and the new green post-merge gate:

```text
VERIGYM_RUN_DEEPSEEK_HARNESS_V170_OFFICIAL_MATRIX=1 \
python scripts/launch_hwe_deepseek_harness_v170_official_matrix.py \
  --post-merge-main-run-id <green-main-run-id>
```

The terminal result is pending an independent v171 audit. Candidate SFT import remains closed;
failed trajectories remain audit context only. `formal_collection_allowed`,
`formal_collection_started`, `collection_started`, `training_started`, and
`production_training_ready` remain false. This authorization does not start formal collection,
SFT, GPU work, benchmark scoring, or production training.
