# DeepSeek Harness v162 official matrix authorization

Date: 2026-09-05

Status: **one provider-bearing execution authorized only after merge and green post-merge
`main`**.

## Decision and immutable inputs

Authorize exactly one execution of `deepseek-harness-hwe-v162-official-matrix-v1`. V162 is the
sole provider successor named by the repaired v160 contract and independently accepted by v161.
It is a new identity; v154 and all provider-free v156/v158/v160 identities remain frozen.

- Manifest SHA-256: `fa394fcde9fda0de8f43e80981a14d591c93d379ae066a0381b7e92110111531`
- Manifest canonical hash: `a8fe31eff7419815272356fb2e12715b09833aaf8b79fbe747082f9a640495e3`
- Runner SHA-256: `90dcbc8dd88a7377ea7151c57dd9a2917e41b1ea9943a35631078d1a16f48ee1`
- Launcher SHA-256: `c3aaf66b4006e5a10c751c4c0ecbe97f927ab1fa21e1331dbf2404d93506bdee`
- v161 audit commit: `0bbf5d448fcf843afb9143c87e0380c856c425a4`
- v161 audit merge: `779a0964bf62ec7b816c70d1cf83f13c7aa1c5ae`
- v161 post-merge `main`: `33965500946`, eight of eight job classes passed

Execution additionally requires the exact merge commit containing this authorization to pass all
eight post-merge `main` job classes. The runner rejects a non-`main`, dirty, or non-up-to-date
checkout and records that run ID in its atomic progress.

## Matrix and protocol

Execute strictly and serially with seed/sample `502/18`: Ibex PR-465, PR-1135, PR-1780, then CVA6
PR-2017 and PR-2711. Each task is bound to its v158 source tree, task/source hashes, freshly
materialized command image, 29-check v2 security scan, toolchain profile, and official verifier
image. V162 revalidates the complete v158 and v160 evidence trees plus all canonical receipts
before output creation.

The fixed model is DeepSeek v4 Flash through Harness `0.1.1-rc.2`, integration `0.5.0`, and
revision `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`. Per task: at most 64 calls, 1,000,000 provider
tokens, 65,536 context tokens, 2,048 output tokens, temperature zero, and zero request or episode
retries. Tool choice is `auto`; public rationale and sibling calls are preserved. Hidden reasoning,
foreign tools, illegal paths, and unpaired observations fail closed.

Every candidate decision uses the exact Qwen tokenizer, is strictly below 65,536 tokens, is never
truncated, and applies the decision-only loss mask. Candidate admission requires the verifier,
protocol, trajectory, infrastructure, security, and SFT planes together. Candidate import remains
closed pending v163; no result is a benchmark score.

## Docker, provider, and cleanup boundary

V162 may reopen the exact retained `verigym-deepseek-harness-v158-dind-data` volume once. It uses a
fresh v162 socket volume and fresh `/data2` socket, control, runtime, output, and receipt paths. It
does not import, pull, rebuild, substitute, or access `.partial` images. It does not inspect or
delete unrelated Docker resources and does not change Docker or VPN configuration.

The actual runtime registry creates a fresh `DockerCliEngine` explicitly bound to the canonical
v162 Unix socket for every task. Harness settings fingerprint that same endpoint and pass it
explicitly to the controller helper. Ambient Docker routing is not authoritative. Before the first
provider request, all five runtime probes, the complete 12-image inventory, empty mutable inner
inventory, and zero-call Harness initialization must pass. Command and official verifier sessions
use `network=none`; only the outer DinD and inner controller may use `verigym-hwe-net`.

The launcher selects blocked provider entries by name before reading values, strips the frozen
twelve-name set plus Docker endpoint variables, and restores only the two required DeepSeek names
inside the child. Concrete values are never printed, persisted, or hashed. A pre-marker
infrastructure/security failure stops without consuming the task; after a valid or unreadable
marker it consumes the task and stops. Ordinary model/verifier failure consumes and continues;
two consecutive no-progress or structurally invalid trajectories stop the remainder. Cleanup is
bounded and removes only v162-owned socket resources; the retained v158 data volume is preserved.

Run exactly once after merge and the new green post-merge gate:

```text
VERIGYM_RUN_DEEPSEEK_HARNESS_V162_OFFICIAL_MATRIX=1 \
python scripts/launch_hwe_deepseek_harness_v162_official_matrix.py \
  --post-merge-main-run-id <green-main-run-id>
```

`formal_collection_allowed`, `formal_collection_started`, `collection_started`,
`training_started`, and `production_training_ready` remain false. The result is pending an
independent v163 audit; this authorization does not start formal collection, SFT, GPU work, or
production training.
