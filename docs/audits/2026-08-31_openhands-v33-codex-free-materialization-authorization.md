# OpenHands v33 Codex-free materialization authorization

## Outcome and scope

This change authorizes exactly one zero-provider execution under the fresh identity
`openhands-hwe-v33-codex-free-canary-materialization-v1`, and only after its authorization commit
is merged to `origin/main` with all repository protection checks passing. The execution may repeat
the absolute filesystem headroom gate, build and security-scan six task-distinct Codex-free command
images in the new v33 namespace, and write a successor static canary contract.

It may not invoke a provider, execute the canary, collect a trajectory, start training, run
inference evaluation, load a held-out task, retry v32, reuse a v32 image, or rerun public-task
qualification. A later provider canary requires a separate authorization and result audit.

The immutable authorization is
`configs/training/qwen35_hwe_openhands_v33_codex_free_canary_materialization_v1.json`. The runner
requires `VERIGYM_MATERIALIZE_OPENHANDS_HWE_V33_CODEX_FREE_CANARY=1`, a clean tracked
`HEAD == origin/main` checkout, and the exact authorization hash
`79cca2864460c0b6ca4d4d8902e4f7be1cb6ae8296743b6b1409b2e3725deb17`.

## Frozen predecessor disposition

The sealed v29 evidence already contains five qualified public tasks and their frozen split:

- training reserve: PR-2330, PR-3226, PR-3231;
- validation reserve: PR-2989, PR-3059;
- canary validation: the separately frozen PR-3204 binding.

v33 consumes those exact task, source, verifier-image, and legacy-lock hashes. It does not rerun a
base-FAIL/reference-PASS verifier or transfer another task. This avoids spending Docker and
verifier capacity on qualification already sealed by v28/v29.

The v32 predecessor remains permanently stopped. v33 requires its external root to contain exactly
`materialization-progress.json` and `image-receipts/pr-2330.json`, with file SHA-256 values
`27c48e0ff1a2905ba4a3f6f7e2ed1defe17c1746c4a7d01de97fd2ff869d0583` and
`45fa97a18ed0c7b2e5e540f6d101e972ea928ec401a6ba8400effd0d7cdb5959`. It verifies the terminal
progress hash `4d713ed9faa05104a9fcee28a559158d1af03e19915986aedbeacb9672e1942b`,
zero provider/model counts, an empty lock map, and no canary, collection, training, or held-out
activity. The failed v32 image IDs are evidence only and are explicitly ineligible for reuse.

## Successor controls

Each task receives a distinct image under
`verigym/cva6-openhands-v33-command-pr-<number>:rg-15.2.0-v1`. Build and runtime network modes
remain `none`; the image contains no Codex binary or provider credentials. The runner requires the
frozen ripgrep 15.2.0 binary and release-archive hashes and retains the
`episode_container_exec_v1` runtime contract.

Before the first image build, the runner rediscovers Docker's data root and repeats the generic
absolute headroom policy: 4 GiB for the control root, 96 GiB for six-image Docker staging, 8 GiB
for scratch, 2 GiB for the output filesystem, plus the frozen inode minima. A preauthorization
snapshot passed with receipt hash
`ae63e24aca016abbabb8d988f66717bc53916cc01646a26b2d36b7e36b7f6960` and file SHA-256
`98f79f4e7ff324985d2fdcd53eb641ef6f4f0c28a320536fa8fe1a6e7c736fdf`; it is readiness evidence
only and cannot replace the execution-time gate.

Every image must produce `verigym_hwe_command_image_security_scan_v2` with scanner profile
`cva6-hwe-command-container-native-offline-v2`. A passed image requires zero diagnostic exit codes,
complete temporary-container and workspace cleanup, and no raw or hashed nonempty command output.
If a scan fails, terminal progress may import only the validated security/diagnostic hashes,
closed failure stage and category, stable assertion identifier, integer exit codes, and cleanup
booleans. It never imports stdout, stderr, daemon text, container IDs, or host paths.

Any headroom, build, scan, binding, distinctness, cleanup, inventory, or infrastructure failure
stops this single v33 identity without retry. No partial lock set or failed image may authorize the
provider canary.

## Authorized execution after merge

The one output root is fixed to:

`/data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1`

The post-merge command is:

```bash
PYTHONPATH=.:src:integrations/verigym-openhands/src \
VERIGYM_MATERIALIZE_OPENHANDS_HWE_V33_CODEX_FREE_CANARY=1 \
/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/bin/python \
  scripts/materialize_cva6_openhands_v33_codex_free_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v33_codex_free_canary_materialization_v1.json \
  --v29-root /data/jzhu484/Agent/experiments/openhands-hwe-v29-v19-canary-materialization-v1 \
  --v30-root /data/jzhu484/Agent/experiments/openhands-hwe-v30-v19-provider-canary-v1 \
  --v32-root /data/jzhu484/Agent/experiments/openhands-hwe-v32-codex-free-canary-materialization-v1 \
  --validation-image-lock /data/jzhu484/Agent/experiments/qwen35-hwe-openhands-bounded-sft-pilot-v1/image-locks/pr-3204.json \
  --rg-binary /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl/rg \
  --rg-release-archive /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz \
  --scratch-root /data/jzhu484/Agent/.verigym-tmp \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1
```

The command must be invoked once. Experiment files, image layers, full receipts, legacy locks, and
source trees remain outside Git. Only a later sanitized result audit may commit hashes, bindings,
statuses, and protection-check results.

## Verification required before execution

The authorization PR must pass the v33 zero-provider regressions; the v19, v30, v32,
command-runtime, scanner, and headroom regressions; the complete OpenHands Python 3.12 suite; the
ordinary credential-free repository tests; Ruff; strict mypy; package and artifact scans; Docker
external-agent zero-model security; reproducible builds; and all eight required Actions job
classes. Until that commit is merged and the main-branch run is green, image construction remains
unauthorized.

Pre-review results on the authorization branch are:

- v33 regressions: `10 passed`; combined v32/v33, scanner, headroom, and command-image regressions:
  `29 passed`;
- complete OpenHands Python 3.12 zero-model suite: `323 passed`;
- ordinary credential-free core suite: `1064 passed`, `1 skipped`, `52 deselected`; HWE plugin:
  `50 passed`;
- strict mypy: core `208` files, HWE `9` files, OpenHands `30` files, and the v33 runner
  `1` file;
- tracked-source Ruff and format: `687` files; Git diff hygiene, schema drift, and documentation
  contracts: passed;
- real pre-merge negative gate: rejected with zero v33 images before and after and no output root;
- preauthorization headroom snapshot: passed with zero provider calls and zero model processes;
- provider calls, canary episodes, verifier runs, trajectory collection, training, inference, and
  held-out loads: zero.

The first local core invocation inherited a stale `PYTHONPATH` pointing at a historical scratch
checkout and failed during collection against old APIs. Re-running with the current repository's
absolute source path produced the complete passing result above. The HWE plugin's Git 2.31 local
binary also filters `git apply --numstat` paths when invoked from a repository subdirectory; the
same 50 tests pass from the repository root, matching the Actions invocation. Neither environment
issue changed source or campaign policy.
