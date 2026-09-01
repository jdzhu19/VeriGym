# OpenHands v46 PR-2802 result-path redaction repair authorization

Date: 2026-09-01

Status: authorization proposed; zero-provider materialization only.

## Scope and predecessor

The sole v45 materialization completed its image-local build and v2 scan, but the independent
result-artifact gate rejected it because `materialization-progress.json` stored the absolute
interpreter, virtual-environment prefix, and package-root paths. V45 is frozen as security-invalid
evidence and cannot be edited, retried, promoted, or used by a provider runner.

V46 is an append-only replacement identity. It binds the exact seven-file v45 tree
`46eb9dd97cda3071ebf3f77b5c481640dc44ff5f6bbb9bfc03d17a1f46943723`, failed progress hash
`cf8148e7103f50d127d52e29181861e07ba7391e82f6fe33856a7c497cc9bdd0`, independent failed
security-report hash
`18b65431b8d7c508aac8704a263cb909e50b04a5fd6feaca4e5229ed01e052e4`, merged audit commit
`ecff5a9ded206b280571f67b6040f09af9fb5d2c`, audit-file SHA-256
`6bd4fd8753ec579c882b74b91c458aa4aa59c3443b591a583fe47f8fbbb65ca7`, and green main run
`33493809497`.

The authorization file is
`configs/training/qwen35_hwe_openhands_v46_pr2802_canary_materialization_v1.json`, with canonical
authorization hash
`54aa422171fa6f2a2dcf0753c1f47307a632ac57ab01b4a70bf6f6f3c99e687f`.

## Repair and security boundary

The runner continues to enforce the exact approved repository, interpreter, prefix, Python
3.12.13 runtime, isolated `pyvenv.cfg` hash, current-repository import origin, and `src`-first
bootstrap in memory. The persisted runtime receipt now contains only the Python version,
`pyvenv.cfg` hash, stable booleans proving each equality, and
`absolute_host_paths_persisted=false`. Neither the checked-in authorization nor the generated
progress receipt contains an actual repository, interpreter, prefix, or package-root path, or a
hash derived solely from any such path.

Regression coverage constructs the runtime receipt under a dynamic checkout, compares its
serialized bytes against all known runtime roots, and sends the result through VeriGym's
context-aware artifact scanner. It also preserves the stale-editable-path and already-loaded
foreign-package subprocess tests. This repair follows Python's documented `.pth` processing and
pip's documented editable-install behavior:

- <https://docs.python.org/3/library/site.html>
- <https://pip.pypa.io/en/stable/topics/local-project-installs/>

V46 does not reuse either v45 image. It creates a fresh tag namespace, rebuilds PR-2802 from the
qualified legacy task/source/verifier binding, performs the same offline v2 image scan, and reuses
only the sealed v33 PR-3204 validation image. Build and runtime networks remain `none`; the command
container must contain no Codex, provider credentials, hidden assets, verifier payload, reference
patch, or source residue.

## Authorized execution

The sole permitted output root is:

`/data/jzhu484/Agent/experiments/openhands-hwe-v46-pr2802-canary-materialization-v1`

It must not exist before execution. The conservative six-image absolute headroom gate remains in
force even though this identity builds one image. Only after this authorization merges, `HEAD`
equals `origin/main`, and all eight post-merge main job classes pass may the following command run
exactly once:

```bash
VERIGYM_MATERIALIZE_OPENHANDS_HWE_V46_TRAINING_CANARY=1 \
.venv/bin/python scripts/materialize_cva6_openhands_v46_pr2802_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v46_pr2802_canary_materialization_v1.json \
  --legacy-image-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/image-locks/pr-2802.json \
  --v33-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --v43-root /data/jzhu484/Agent/experiments/openhands-hwe-v43-provider-canary-v1 \
  --v44-stop-root /data/jzhu484/Agent/experiments/openhands-hwe-v44-pr2802-canary-materialization-pre-output-stop-v1 \
  --v45-root /data/jzhu484/Agent/experiments/openhands-hwe-v45-pr2802-canary-materialization-v1 \
  --rg-binary /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl/rg \
  --rg-release-archive /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz \
  --scratch-root /data/jzhu484/Agent/.verigym-tmp \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v46-pr2802-canary-materialization-v1
```

At execution time the runner revalidates the clean merged source, immutable predecessors,
authorization, repository runtime, legacy lock, ripgrep bytes, headroom, cleanup, v2 scan, and all
task/source/verifier/image bindings. Any failure permanently freezes v46.

## Future identity and explicit non-authorization

A successful v46 result may only support a separately reviewed v47 provider canary, fixed as
PR-2802 training followed by PR-3204 validation, seed 496, sample 12, and protocol v22. V47 remains
unauthorized until the v46 result audit merges and its post-merge main run passes all eight job
classes.

V46 has no provider client or episode surface. It authorizes no provider call, benchmark task
execution, canary, formal collection, SFT, GPU work, historical relabeling, retry, role reassignment,
or held-out loading. Throughout v46, provider episodes/calls/model processes remain zero and:

- `formal_collection_allowed=false`;
- `formal_collection_started=false` and `collection_started=false`;
- `training_started=false` and `production_training_ready=false`.

## Verification

Credential-free pre-merge verification passed:

- focused v46 tests with exact v43, v44, v45, and PR-2802 evidence: 16 passed;
- authorization and generated-runtime-receipt context scans: pass, with zero hard findings and
  zero scanner errors;
- core pytest: 1,065 passed, ten explicit real-tool opt-ins skipped, and 43 marked selections
  excluded;
- HWE plugin pytest: 51 passed;
- OpenHands Python 3.12 zero-model pytest: 477 passed and 38 external-evidence opt-ins skipped;
- audit/security-scanner contracts: 62 passed and two unrelated selections deselected;
- Ruff format/lint over all 728 tracked Python files plus both new v46 files;
- strict mypy over 208 core, 9 HWE, and 44 OpenHands source files plus the standalone v46 runner;
- schema drift and Git patch hygiene checks;
- OpenHands wheel/sdist content audit with no issues; and
- normalized core builds with byte-identical wheel and sdist outputs.

The first full OpenHands run exposed that an earlier test can mutate process-global `sys.path`
after module import. The repair now makes `src`-first order a repeated hard runtime gate rather than
merely exporting a false observation, and the full suite passed after adding the isolated-bootstrap
regression setup. A first isolated package build also stopped while its temporary environment
encountered the site's package-index proxy returning HTTP 502. No proxy or VPN setting was changed;
the local package audit used the already frozen `.venv` dependencies with build isolation disabled
and passed. GitHub Actions retains its clean isolated build.

No dependency or environment was installed, removed, or changed. These checks created no v46
authorized output, provider episode or call, Docker image, model process, formal collection,
training run, GPU work, or held-out access. The authorization PR and its post-merge main commit must
still pass all eight required Actions job classes before execution.
