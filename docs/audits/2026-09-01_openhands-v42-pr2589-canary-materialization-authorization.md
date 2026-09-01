# OpenHands v42 PR-2589 canary-image authorization

Date: 2026-09-01

Status: authorized only after merge and green `main`; zero-provider materialization has not run.

## Why a successor image is required

V41 executed its one authorized PR-2549 provider episode and failed closed after exhausting the
fixed cumulative one-million-token budget. The immutable result is an ordinary model/trajectory
failure, not an infrastructure or security defect. PR-2549 may not be retried, reconstructed,
relabelled, or admitted. Its result audit merged as
`a2f756330a196da04c30788ce4381c6dffde6440`, and post-merge `main` run `33478968324` passed all
eight required job classes.

PR-2589 is the next public, source-qualified training profile that has no provider episode. V42
therefore authorizes only the construction and v2 scan of one task-distinct PR-2589 command image.
It does not change the v22 protocol, provider budget, prompt, model, or any frozen historical
attempt. A future provider canary requires a separately merged v43 authorization.

## Frozen inputs and output

The authorization file is
`configs/training/qwen35_hwe_openhands_v42_pr2589_canary_materialization_v1.json`, with hash
`e48fa6974a26ac32079649398b2d611d4cd2ff99e537a3b539f9e84d654086ac`.
It binds:

- the exact completed v33 materialization and its still-unstarted PR-3204 validation command
  binding;
- the complete sealed v41 evidence tree, report, PR-2549 attempt and security scan, failure-audit
  merge, and green post-merge main run;
- the merged v22 protocol repair;
- the public PR-2589 legacy task/source/verifier lock and its qualification audit;
- the official ripgrep 15.2.0 release archive and binary hashes; and
- a future static v43 order of PR-2589 training followed by PR-3204 validation, seed 494 and
  sample index 10.

The one permitted output root is:

`/data/jzhu484/Agent/experiments/openhands-hwe-v42-pr2589-canary-materialization-v1`

It must not exist before the unique invocation. The runner creates one PR-2589 command image,
requires a passed content-free v2 security receipt, writes one immutable command-image lock, and
seals a two-task v22 catalog/contract. The PR-3204 binding is read-only v33 evidence and no image
is rebuilt for it.

Although only one image is built, execution retains the conservative six-image absolute headroom
policy: 96 GiB on the Docker root plus independent control-root, scratch, output, and inode
thresholds. Build and runtime networking remain `none`. The command image contains neither Codex,
provider credentials, hidden assets, verifier payload, nor the reference patch.

## Authorized execution

Only after this authorization merges, `HEAD` equals `origin/main`, and the post-merge main run
passes all eight job classes may this command be invoked once:

```bash
VERIGYM_MATERIALIZE_OPENHANDS_HWE_V42_TRAINING_CANARY=1 \
python scripts/materialize_cva6_openhands_v42_pr2589_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v42_pr2589_canary_materialization_v1.json \
  --legacy-image-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/image-locks/pr-2589.json \
  --v33-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --v41-root /data/jzhu484/Agent/experiments/openhands-hwe-v41-provider-canary-v1 \
  --rg-binary /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl/rg \
  --rg-release-archive /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz \
  --scratch-root /data/jzhu484/Agent/.verigym-tmp \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v42-pr2589-canary-materialization-v1
```

At execution time the runner revalidates the clean merged source, ancestor commits, authorization
hash, exact v33 and full v41 evidence inventories, PR-2589 lock, ripgrep bytes, capacity, cleanup,
scan, and task/source/verifier/image bindings. Any failure freezes v42 without an in-place retry.

## Explicitly not authorized

V42 has no provider client or model-process surface. It authorizes no provider call, task episode,
canary execution, formal collection, SFT, GPU work, historical relabeling, task-role reassignment,
or held-out loading. Before and after successful materialization the terminal state remains:

- `formal_collection_allowed=false`;
- `formal_collection_started=false` and `collection_started=false`;
- `training_started=false` and `production_training_ready=false`;
- zero provider episodes, calls, retries, and model processes.

A successful v42 result must be independently audited, merged, and followed by green main checks
before any v43 provider authorization can be proposed.

## Pre-merge implementation verification

The first review found that two mechanically copied entries in `_REQUIRED_MERGED_PATHS` still
named the discarded generic v42 configuration and runner. That would have made the unique command
reject its own merged authorization before creating the output directory. The entries and all v42
format IDs now bind the PR-2589-specific identity, the authorization hash was recomputed, and a
regression test asserts both exact paths exist and no generic v42 path remains.

The host's default Python editable installation points at an older scratch checkout. Unqualified
`pytest` therefore failed during collection on interfaces absent from that old checkout. No
repository or environment mutation was needed: explicitly placing this checkout's `src` first on
`PYTHONPATH` restored the intended hermetic source binding. With that binding, the following
credential-free checks passed:

- tracked-source Ruff lint and format over 719 Python files, plus the new v42 runner and tests;
- strict core mypy over 208 source files and strict HWE plugin mypy over 9 source files;
- core pytest: 1,065 passed, 1 explicit real-Codex opt-in skipped;
- HWE plugin pytest: 51 passed;
- OpenHands Python 3.12 zero-model pytest: 435 passed, with only external-evidence tests skipped;
- v42 Python 3.12 tests with the exact local v41 evidence tree and PR-2589 legacy lock: 10 passed;
- core and OpenHands wheel/sdist builds plus the OpenHands distribution-content audit; and
- two normalized core builds with byte-identical wheels and sdists.

The GitHub authorization PR and its post-merge `main` commit must still pass the repository's eight
required job classes before the one zero-provider invocation is permitted.
