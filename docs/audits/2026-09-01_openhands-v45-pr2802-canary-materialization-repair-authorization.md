# OpenHands v45 PR-2802 materialization repair authorization

Date: 2026-09-01

Status: authorized only after merge and green `main`; zero-provider materialization has not run.

## Why v45 is required

The one authorized v44 command stopped before runner `main`, output creation, scratch allocation,
Docker, or a task loop. The ambient `python` resolved `verigym` through a stale Conda editable
install that pointed at an older temporary checkout. V44 is infrastructure-invalid and permanently
sealed; changing the interpreter and invoking it again would be an unauthorized retry.

The v44 stop audit merged as `ad52c2148e6ad6be006b4cf5a174fba0f21235c3`, and post-merge main
run `33489756991` passed all eight required job classes. Its external receipt proves zero Docker
builds, provider calls, task attempts, collection, training, GPU work, and held-out loading.

PR-2802 and PR-3204 therefore remain fresh. V45 is a new zero-provider identity that repairs only
launcher and import isolation. It preserves v44's task/source/verifier inputs, v2 scan, headroom,
network-none runtime, atomic output, future seed/sample, and no-retry rules. A future provider
canary requires a separately merged v46 authorization.

## Frozen inputs and launcher isolation

The authorization file is
`configs/training/qwen35_hwe_openhands_v45_pr2802_canary_materialization_v1.json`, with hash
`933e4a43c4d67c74c1a891db0420ca550c2c6c3707576d69f4a2ff601fa82bbb`.
It binds:

- the exact completed v33 materialization and still-unstarted PR-3204 validation binding;
- the sealed v43 PR-2589 ordinary failure and its green post-merge main run;
- the v44 pre-output stop tree, receipt, audit merge, and green post-merge main run;
- the merged v22 protocol repair;
- the public PR-2802 legacy task/source/verifier lock and qualification audit;
- the official ripgrep 15.2.0 archive and binary hashes; and
- a future v46 order of PR-2802 training followed by PR-3204 validation, seed 495 and sample 11.

V45 must run under `/data/jzhu484/Agent/VeriGym/.venv/bin/python`. The virtual environment is
Python 3.12.13, has `include-system-site-packages=false`, and its `pyvenv.cfg` SHA-256 is
`784bdfbe2c09a7a284dd3a39b1ab5d1e9a6bd5324a345fd5539e7a223a33b4df`. Before importing any
repository package, the runner puts the exact current `src` first on `sys.path`; it refuses an
already loaded foreign `verigym`, validates the resulting package root, and checks the interpreter,
prefix, version, and venv configuration again before output.

This follows Python's documented `.pth` processing behavior and pip's documented editable-install
behavior, under which a development directory is added to the import path:

- <https://docs.python.org/3/library/site.html>
- <https://pip.pypa.io/en/stable/topics/local-project-installs/>

## Authorized output and execution

The sole permitted output root is:

`/data/jzhu484/Agent/experiments/openhands-hwe-v45-pr2802-canary-materialization-v1`

It must not exist before the unique invocation. The runner may build and v2-scan exactly one
PR-2802 command image, write one immutable lock, and seal the two-task v22 catalog/contract. The
PR-3204 command image is immutable v33 evidence and is not rebuilt.

Although only one image is built, execution retains the conservative six-image absolute headroom
policy: 96 GiB on the Docker root plus independent control-root, scratch, output, and inode
thresholds. Build and runtime networking remain `none`. The command image must contain no Codex,
credentials, hidden assets, verifier payload, or reference patch.

Only after this authorization merges, `HEAD` equals `origin/main`, and the post-merge main run
passes all eight job classes may this command be invoked once:

```bash
VERIGYM_MATERIALIZE_OPENHANDS_HWE_V45_TRAINING_CANARY=1 \
.venv/bin/python scripts/materialize_cva6_openhands_v45_pr2802_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v45_pr2802_canary_materialization_v1.json \
  --legacy-image-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/image-locks/pr-2802.json \
  --v33-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --v43-root /data/jzhu484/Agent/experiments/openhands-hwe-v43-provider-canary-v1 \
  --v44-stop-root /data/jzhu484/Agent/experiments/openhands-hwe-v44-pr2802-canary-materialization-pre-output-stop-v1 \
  --rg-binary /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl/rg \
  --rg-release-archive /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz \
  --scratch-root /data/jzhu484/Agent/.verigym-tmp \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v45-pr2802-canary-materialization-v1
```

At execution time the runner revalidates the clean merged source and ancestors, all three evidence
inventories, authorization hash, repository runtime, PR-2802 lock, ripgrep bytes, capacity,
cleanup, scan, and task/source/verifier/image bindings. Any failure permanently freezes v45.

## Explicitly not authorized

V45 has no provider client or episode surface. It authorizes no provider call, task execution,
canary, formal collection, SFT, GPU work, historical relabeling, task-role reassignment, or
held-out loading. Before and after successful materialization the state remains:

- `formal_collection_allowed=false`;
- `formal_collection_started=false` and `collection_started=false`;
- `training_started=false` and `production_training_ready=false`;
- zero provider episodes, calls, retries, and model processes.

A successful v45 result must be independently audited, merged, and followed by green main checks
before any v46 provider authorization can be proposed.

## Pre-merge verification

Credential-free local verification passed:

- focused v45 tests with exact v43, v44-stop, and PR-2802 evidence: 14 passed, including separate
  subprocesses for a competing stale path and an already-loaded foreign `verigym`;
- core pytest: 1,065 passed and one explicit real-Codex opt-in skipped;
- HWE plugin pytest: 51 passed;
- frozen OpenHands Python 3.12 zero-model pytest: 465 passed, with 34 external-evidence opt-ins
  skipped;
- audit/schema contracts: 13 passed and two unrelated selections deselected;
- Ruff lint and format over 728 tracked and new Python files;
- strict mypy over 208 core, 9 HWE, and 44 OpenHands source files plus the standalone v45 runner;
- OpenHands wheel/sdist distribution-content audit with no issues; and
- normalized core builds with byte-identical wheel and sdist outputs.

The generated authorization base exactly equals the checked-in JSON after removing only its hash
field. The isolated runtime gate passed under `.venv/bin/python` and rejected the ambient Conda
interpreter. The initial HWE test command omitted the plugin's local `src` from `PYTHONPATH` and
therefore stopped during test discovery; the exact repository plugin path was then supplied and
all 51 tests passed. No dependency or environment was installed, removed, or changed.

The first GitHub PR run exposed one additional deterministic test defect: the authorization
generator derived the frozen execution path from the current checkout, so its policy differed on
GitHub's `/home/runner/...` checkout even though the checked-in authorization correctly named the
approved `/data/...` runtime. The repair separates immutable authorized-path constants from the
dynamic source path used by bootstrap tests and adds an explicit checkout-independence regression.
The authorization bytes and hash did not change because the approved local values were already
correct. The failed CI jobs stopped in zero-model pytest; lint, mypy, and all earlier steps passed,
and no execution surface was enabled.

These checks created no authorized output, provider episode or call, Docker image, model process,
formal collection, training run, GPU work, or held-out access. The GitHub authorization PR and its
post-merge `main` commit must still pass all eight required job classes before the one
materialization command is permitted.
