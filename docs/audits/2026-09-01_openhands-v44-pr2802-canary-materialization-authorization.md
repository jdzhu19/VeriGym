# OpenHands v44 PR-2802 canary-image authorization

Date: 2026-09-01

Status: authorized only after merge and green `main`; zero-provider materialization has not run.

## Why a successor image is required

V43 executed its one authorized PR-2589 provider episode and failed closed after exhausting the
fixed cumulative one-million-token budget. The immutable result is an ordinary model/trajectory
failure, not an infrastructure or security defect. PR-2589 may not be retried, reconstructed,
relabelled, or admitted. Its result audit merged as
`46435ca0dff824a3a65352fc65d270f2a8c21713`, and post-merge `main` run `33486581581` passed all
eight required job classes. The earlier PR-2549 failure remains equally immutable.

PR-2802 is the next public, source-qualified training profile that has no provider episode. V44
therefore authorizes only the construction and v2 scan of one task-distinct PR-2802 command image.
It does not change the v22 protocol, provider budget, prompt, model, or any frozen historical
attempt. A future provider canary requires a separately merged v45 authorization.

## Frozen inputs and output

The authorization file is
`configs/training/qwen35_hwe_openhands_v44_pr2802_canary_materialization_v1.json`, with hash
`0d696630052b212bd320d32b42222a7d644a77395b37a642ef64f8f292662958`.
It binds:

- the exact completed v33 materialization and its still-unstarted PR-3204 validation command
  binding;
- the complete sealed v43 evidence tree, report, PR-2589 attempt and security scan, failure-audit
  merge, and green post-merge main run;
- the merged v22 protocol repair;
- the public PR-2802 legacy task/source/verifier lock and its qualification audit;
- the official ripgrep 15.2.0 release archive and binary hashes; and
- a future static v45 order of PR-2802 training followed by PR-3204 validation, seed 495 and
  sample index 11.

The one permitted output root is:

`/data/jzhu484/Agent/experiments/openhands-hwe-v44-pr2802-canary-materialization-v1`

It must not exist before the unique invocation. The runner creates one PR-2802 command image,
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
VERIGYM_MATERIALIZE_OPENHANDS_HWE_V44_TRAINING_CANARY=1 \
python scripts/materialize_cva6_openhands_v44_pr2802_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v44_pr2802_canary_materialization_v1.json \
  --legacy-image-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/image-locks/pr-2802.json \
  --v33-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --v43-root /data/jzhu484/Agent/experiments/openhands-hwe-v43-provider-canary-v1 \
  --rg-binary /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl/rg \
  --rg-release-archive /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz \
  --scratch-root /data/jzhu484/Agent/.verigym-tmp \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v44-pr2802-canary-materialization-v1
```

At execution time the runner revalidates the clean merged source, ancestor commits, authorization
hash, exact v33 and full v43 evidence inventories, PR-2802 lock, ripgrep bytes, capacity, cleanup,
scan, and task/source/verifier/image bindings. Any failure freezes v44 without an in-place retry.

## Explicitly not authorized

V44 has no provider client or model-process surface. It authorizes no provider call, task episode,
canary execution, formal collection, SFT, GPU work, historical relabeling, task-role reassignment,
or held-out loading. Before and after successful materialization the terminal state remains:

- `formal_collection_allowed=false`;
- `formal_collection_started=false` and `collection_started=false`;
- `training_started=false` and `production_training_ready=false`;
- zero provider episodes, calls, retries, and model processes.

A successful v44 result must be independently audited, merged, and followed by green main checks
before any v45 provider authorization can be proposed.

## Pre-merge implementation verification

The mechanically copied successor skeleton was reviewed against the complete v43 tree rather than
accepted by version-string substitution. The review corrected the v43 attempt name, all v43 file
and content hashes, provider accounting, PR-2802 legacy bindings, the cumulative consumed-task
ledger, and the v45 seed/sample identity before the authorization hash was frozen. The generated
authorization base exactly equals the checked-in JSON after removing only its hash field.

Credential-free local verification passed:

- v44 focused tests with the exact local v43 evidence tree and PR-2802 legacy lock: 10 passed;
- core pytest: 1,065 passed and one explicit real-Codex opt-in skipped;
- HWE plugin pytest: 51 passed;
- OpenHands Python 3.12 zero-model pytest: 454 passed, with only external-evidence tests skipped;
- audit contracts: 12 passed and two unrelated selections deselected;
- Ruff lint and format over 724 tracked Python files plus both new Python files;
- strict mypy over 208 core, 9 HWE, and 44 OpenHands source files, plus the standalone runner;
- OpenHands wheel/sdist distribution-content audit; and
- normalized core builds with byte-identical wheel and sdist outputs.

The frozen OpenHands execution environment exposes a namespace package named `build` but not the
PyPA build frontend. No package was installed into or removed from that environment. The
distribution check instead used the repository development environment's PyPA build 1.6.0 with
`--no-isolation`; its setuptools 80.10.2 satisfies the plugin's declared `>=77,<81` build
requirement. This follows PyPA's documented no-isolation path for environments whose build
dependencies are already installed:
https://build.pypa.io/en/latest/how-to/basic-usage.html.

These checks created no provider episode or call, Docker image, model process, formal collection,
training run, GPU work, or held-out access. The GitHub authorization PR and its post-merge `main`
commit must still pass all eight required job classes before the one materialization command is
permitted.
