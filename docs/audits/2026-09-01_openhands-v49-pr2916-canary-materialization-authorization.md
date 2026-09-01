# OpenHands v49 PR-2916 canary materialization authorization

Date: 2026-09-01

Status: authorization proposed; zero-provider materialization only.

## Scope and predecessor

The sole v48 provider canary consumed PR-2802 as an ordinary failed training attempt. It made 43
provider calls and exhausted the fixed one-million-token budget without producing a candidate
write or patch. PR-3204 did not start. V48 and PR-2802 are frozen and may not be retried,
reconstructed, relabelled, or promoted.

V49 is an append-only replacement materialization identity. It binds the exact v48 evidence tree
`c0f72852b070f8a2ca2046b3fa3d4a32ba342de4d2edaa92327f9184113053c6`, report hash
`4ba2cbeaa8c79464dd63a68749e7f4b313251b596ff4a799193ab8cc348a4b2d`, report-file SHA-256
`a49f69fc59d86f480abf162d93810abde5898535fd90996e5934fe562a549d0f`, merged audit commit
`8b186bec056ae6c10c3785620ac64ef68d60932a`, audit-file SHA-256
`b20f7e4cf11315d7113f81d47d11b028ff6ee86071e02b3776feed9513e2919d`, and green post-merge
main run `33504770097`. The authorization explicitly records PR-2802 as `consumed_v48` with
`failed_task_retry_authorized=false`.

The replacement training task is the already frozen public PR-2916 training-role binding. Its
legacy lock file SHA-256 is
`5175e93059e2d6c9de802b5314ff8dbbb687c6fe025de3c29c18b987023fc394`, with task hash
`cf633dddaea257f8932e60323275e272a1988e27284309326f21894ece5b029f`, source hash
`b3728d76776306d83e530fa90f6e70cfa4f15a5089ec76d0369c069e47bacbe2`, and verifier image
`sha256:5f3327d0d9edb261177c9610b03a5328d66dba202719d081cda3970d8106ce71`.
The official upstream pull request changes one line in one file; this was used only as a bounded
task-selection heuristic, not as evidence that the task will pass:
<https://github.com/openhwgroup/cva6/pull/2916>.

The checked-in authorization is
`configs/training/qwen35_hwe_openhands_v49_pr2916_canary_materialization_v1.json`, with canonical
authorization hash
`7a04e2dc24a4f380bc85223589a63ccf7619a2d76c9a8eb76b993985f5fb3010`.

## Materialization and security boundary

V49 constructs one fresh PR-2916 command image in its own tag namespace. It does not reuse any
v44, v45, or v46 PR-2802 image. It reuses only the sealed v33 PR-3204 validation image in a static
future contract. Build and runtime networks are `none`; the new command image must pass the v2
content-free scanner and contain no Codex binary or path, provider credential, hidden verifier
asset, reference patch, public verifier payload, or legacy source residue.

The runner preserves the v46 export-safe runtime repair. Absolute repository, interpreter,
virtual-environment, and package paths are validated in memory but are never persisted or hashed.
The authorization binds the repository-local isolated Python 3.12.13 runtime, `src`-first imports,
the exact `pyvenv.cfg` hash, and the stale-editable-path regressions. Every progress update is
atomic. A headroom, source, image, scan, cleanup, receipt, evidence, or binding failure permanently
freezes v49.

## Authorized execution

The sole permitted output root is:

`/data/jzhu484/Agent/experiments/openhands-hwe-v49-pr2916-canary-materialization-v1`

It must not exist before execution. The conservative six-image absolute headroom gate remains in
force even though v49 builds one image. Only after this authorization merges, `HEAD` equals
`origin/main`, and all eight post-merge main job classes pass may the following command run exactly
once:

```bash
VERIGYM_MATERIALIZE_OPENHANDS_HWE_V49_TRAINING_CANARY=1 \
.venv/bin/python scripts/materialize_cva6_openhands_v49_pr2916_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v49_pr2916_canary_materialization_v1.json \
  --legacy-image-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/image-locks/pr-2916.json \
  --v33-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --v43-root /data/jzhu484/Agent/experiments/openhands-hwe-v43-provider-canary-v1 \
  --v44-stop-root /data/jzhu484/Agent/experiments/openhands-hwe-v44-pr2802-canary-materialization-pre-output-stop-v1 \
  --v45-root /data/jzhu484/Agent/experiments/openhands-hwe-v45-pr2802-canary-materialization-v1 \
  --v48-root /data/jzhu484/Agent/experiments/openhands-hwe-v48-provider-canary-v1 \
  --rg-binary /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl/rg \
  --rg-release-archive /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz \
  --scratch-root /data/jzhu484/Agent/.verigym-tmp \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v49-pr2916-canary-materialization-v1
```

The execution must revalidate the clean merged source, all predecessor hashes, the PR-2916 legacy
lock, v33 PR-3204 binding, ripgrep bytes, runtime isolation, space and inode thresholds, Docker
cleanup, image scan, and final catalog/contract bindings. This command has no provider client or
episode surface and must account for zero provider calls, episodes, model processes, and task
attempts.

## Future identity and explicit non-authorization

A successful and independently audited v49 result may support only a separately reviewed v50
provider canary: PR-2916 training followed by PR-3204 validation, protocol v22, seed 497, and
sample 13. V50 remains unauthorized until the v49 result audit merges and its post-merge main run
passes all eight required job classes.

V49 authorizes no provider call, benchmark task execution, canary, formal collection, SFT, GPU
work, retry, historical relabeling, validation-role reassignment, or held-out loading. Throughout
v49:

- `formal_collection_allowed=false`;
- `formal_collection_started=false` and `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.

## Verification

Credential-free pre-merge verification passed:

- focused v49 tests with the exact v43, v44, v45, v48, and PR-2916 external evidence: 17 passed;
- core pytest: 1,065 passed, one explicit real-Codex opt-in skipped, and 52 marked selections
  excluded;
- HWE plugin pytest: 51 passed;
- OpenHands Python 3.12 zero-model pytest: 513 passed and 58 external-evidence opt-ins skipped;
- audit, release, and context-aware security-scanner contracts: 80 passed and three unrelated
  selections deselected;
- Ruff lint and format checks over 736 tracked Python files plus the two new v49 Python files;
- strict mypy over 208 core source files plus the standalone v49 runner, nine HWE source files,
  and 46 OpenHands source files;
- persistent-schema drift and Git patch-hygiene checks;
- an offline OpenHands wheel/sdist content audit with no issues; and
- normalized core builds with byte-identical wheel and sdist outputs.

The first repository-wide Ruff command also inspected the user's untracked `.verigym-tmp` tree
and reported three pre-existing import-order findings there. Those files are outside the tracked
source and were left untouched; the tracked-file and explicit-v49 rerun passed. Initial local
OpenHands test and mypy invocations omitted integration-specific source paths. Rerunning with the
same repository/plugin roots and Python 3.12 configuration used by CI passed without code changes.

These checks created no v49 authorized output, Docker image, provider episode, task attempt, formal
collection, training run, GPU work, or held-out access. The authorization PR and its post-merge
main commit must still pass all eight required Actions job classes before the sole materialization
command may execute.
