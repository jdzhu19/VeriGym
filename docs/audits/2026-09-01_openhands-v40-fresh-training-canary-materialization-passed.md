# OpenHands v40 fresh-training canary materialization passed

Date: 2026-09-01

Status: sealed zero-provider materialization result; provider execution remains unauthorized.

## Result

The single authorized execution of
`openhands-hwe-v40-fresh-training-canary-materialization-v1` completed successfully from clean
merged `main` commit `9b9241c6bceed58dfd1b3475cad8cf5627361403`. It built, independently
scanned, and locked one Codex-free PR-2549 command image, then sealed the static v22 successor
canary contract in the fixed order PR-2549 training followed by PR-3204 validation. It made zero
provider calls and did not execute either canary task.

Authorization PR [#61](https://github.com/jdzhu19/VeriGym/pull/61) merged before execution. Its
post-merge main Actions run
[33473770645](https://github.com/jdzhu19/VeriGym/actions/runs/33473770645) passed all eight required
job classes: ordinary Python 3.11, 3.12, and 3.13; quality; package; reproducible build; OpenHands
Python 3.12; and Docker external-agent zero-model security.

Full evidence remains outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v40-fresh-training-canary-materialization-v1`.
It contains exactly 7 regular files and 17,839 bytes, with no symlinks. The complete evidence-tree
hash is `49cfed8ee15733519db036e64e4e26962dc91d5775ac90d2bcf11c6f6177a8ee`.

## Execution-time gate and terminal state

The execution-time absolute headroom gate passed before the image build. Its canonical preflight
hash is `afd15263506bb1e3801017cc1ca5eab96d3aa51ab12dab29283dab6a79d930a2` and its
file SHA-256 is `c72440f4f7d16e867816d221d00345bbb393d7ca2a2dd77a2adb29305497e3e3`.
All byte and inode observations satisfied the frozen conservative six-image thresholds for the
control root, Docker root, scratch root, and output parent. The receipt persisted neither resolved
host paths nor raw command output.

The final `materialization-progress.json` has canonical progress hash
`46881145bc00c56b769a3e7b378ad4bf4a8d63ac1d5a5107455a5f73623f8511` and file
SHA-256 `cacc15eec94f317ccbca34334e97a2c8be82b184b3772148731a1a4c73ca6655`.
Independent recomputation matched both. Its status is
`completed_v22_canary_contract_materialized`; its provider episode, provider call, and model
process counts are all zero.

## PR-2549 command-image lock

The materializer produced command image
`sha256:1d6e8dabb17c45cb4bec8ef0a7d8c5e3800a5fb22892d803335bcda1bb4c03e6`, lock
`f099358ae9858d2b894525d999c13b45a790abed549f9b480c0117f6dad22985`, and v2 security
scan `86deb3062ba5554be39960ccb5180fda13d1b21cae215617e8bc5ec8853b52b7`.
The lock file SHA-256 is
`5be6879347142b945ee54ae1f078cad20884201624ecf4b9afaf7885eaa0305b`, the image receipt
file SHA-256 is `d11a9fc0cb326100dd749ac80ef304e06c21b75c05d36338fe5e2346c81ec8a3`,
and the security-scan file SHA-256 is
`f9ad9e559bf8993c4520b60ea9199133f4639eeabb4201180202d0a0ecad45aa`.

The lock preserves the frozen PR-2549 task, source, and verifier identities from the qualified
legacy lock. Dockerfile `RUN` networking and runtime networking are both `none`. The v2 scanner
confirmed a read-only root, non-root UID/GID, cap-drop `ALL`, no-new-privileges, bounded resources,
a private IPC/PID boundary, and a single visible workspace mount. It found no Codex executable or
dependency, provider credential, hidden asset, verifier payload, reference patch, or undeclared
volume. The exact image environment is the frozen five-variable command environment. Temporary
scan containers and workspaces were removed, and no container remains bound to the derived image.

PR-2549 has older historical experiment evidence. This result does not relabel or reconstruct any
historical trajectory. The command image is new only to the v22 successor-canary identity. A future
successful v41 PR-2549 canary trajectory may be imported without formal re-execution; an ordinary
v41 failure instead permanently consumes PR-2549 for this purpose and requires a new formal task.

## Catalog, contract, and independent artifact scan

The two-task command-image catalog has canonical hash
`622b1cbbbb06d84dc8190344ab90c0f45493c754a3623b50c175d0b426cd7ed7` and file SHA-256
`2fc607e59bd581e0c4819b9f1829cf656281c05ae116da8b468d26ad9af3c914`. It binds the new
PR-2549 training image and the sealed, previously unstarted v33 PR-3204 validation image. The two
command-image IDs are distinct. Both use `episode_container_exec_v1`, network `none`, and
credential-free command containers.

The v41 canary contract has canonical hash
`5689104dc6d011724e68fab197748cd099be0067442f7ca98ccd35f8ef8a7b37` and file SHA-256
`989defbb855b372ffba86d12f48036b5870650e85094bae8ac1a628aa64d382e`. It fixes PR-2549
training before PR-3204 validation, seed 493, sample index 9, DeepSeek v4 Flash, OpenHands SDK
1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0, temperature zero, 64 provider calls, 1,000,000 provider
tokens, a 65,536-token context, 2,048 output tokens, zero provider retries, zero whole-episode
retries, no truncation, first-failure stop, all six result planes, and
`required_tool_atomic_shape_recovery_v22`.

An independent in-memory context-aware scan covered all 7 files and 17,839 bytes. It checked the
active provider endpoint, provider credential, active proxy values, and known repository/result/
predecessor host roots without printing, persisting, or hashing those values. It found zero hard
secret leaks and zero scanner errors under report hash
`1ef02f340275c87f07eb6e550c62f4a6e6692e6008016b9d6dd0b49c97093876`.

## Negative claims and next gate

No provider request, canary episode, command execution against a task, verifier run, trajectory,
decision record, formal collection, SFT, inference evaluation, GPU job, or held-out load occurred.
`formal_collection_allowed=false`, `formal_collection_started=false`, `collection_started=false`,
`training_started=false`, `production_training_ready=false`, `canary_executed=false`, and
`benchmark_score_claimed=false` remain fixed.

This result audit authorizes no provider call by itself. A separate append-only v41 runner and
authorization must bind this exact evidence tree, progress, catalog, contract, both command-image
locks, the frozen tokenizer, runtime identity, and all six result planes. Only after that
authorization merges and its post-merge main run passes all eight required job classes may the two
zero-retry canary episodes execute.
