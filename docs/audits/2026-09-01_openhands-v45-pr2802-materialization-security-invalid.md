# OpenHands v45 PR-2802 materialization rejected by result security audit

Date: 2026-09-01

Status: sealed security-invalid result; v45 cannot be retried or promoted.

## Result

The sole authorized execution of
`openhands-hwe-v45-pr2802-canary-materialization-v1` ran from clean merged `main` commit
`242464674ac1e8377fb6ebd9f93f80db861a8322`. Authorization PR
[#71](https://github.com/jdzhu19/VeriGym/pull/71) merged before execution, and post-merge main
Actions run [33492215788](https://github.com/jdzhu19/VeriGym/actions/runs/33492215788) passed all
eight required job classes.

The runner internally completed the PR-2802 command-image build, v2 image scan, lock, two-task
catalog, and static v22 canary contract. The mandatory independent artifact scan then rejected the
result because `materialization-progress.json` persisted raw absolute host paths in the
`repository_runtime` receipt. The affected fields identify the interpreter, virtual-environment
prefix, and loaded package root. They are not credentials, but they violate the repository's
export-safe host-path boundary and the result gate fails closed.

V45 is therefore security-invalid despite its internally completed status. The output tree and
produced images are immutable failure evidence. They must not be edited, re-scanned into a pass,
reused by a provider runner, or promoted into a formal catalog. The v45 command cannot run again.

## Frozen evidence

Full evidence remains outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v45-pr2802-canary-materialization-v1`. It contains
exactly seven regular single-link files and 18,372 bytes. All files have mode `0600`, the managed
directories have mode `0700`, and there are no symlinks. Its complete evidence-tree hash is
`46eb9dd97cda3071ebf3f77b5c481640dc44ff5f6bbb9bfc03d17a1f46943723`.

The exact file SHA-256 values are:

- `materialization-progress.json`:
  `851da5cf3fc32cc6fd3f563d901c1606da287fc2144a1d50d2a820ded647d032`;
- `headroom-preflight.json`:
  `0c3e2331ffc106e3611608b917be4aa51b563fbd4a08055acb7ace4a9f280b3c`;
- `canary-command-image-catalog.json`:
  `494ef1436bc604cc01b2a4aeaf5973f9915a815f4a486b9add849607b59d483d`;
- `canary-contract.json`:
  `911f312c3c29f2abe4e959aa2cf1bc3119da94d8e4ef386112f2965841cb530d`;
- `image-locks/pr-2802.json`:
  `3c8e50a45404a7c3700bf500091430ffe4b871335f25c93ef8431d777a6a25b0`;
- `image-receipts/pr-2802.json`:
  `4fd477e56e16f23c22de869463b4d69f387764e63c494e9575d2e34e9a5104bc`;
- `security-scans/pr-2802.json`:
  `2b447e28db8ba75ab556a1021f6c7c02e508e9a823374b60eba044eabd5822c3`.

Independent canonical recomputation matched the progress hash
`cf8148e7103f50d127d52e29181861e07ba7391e82f6fe33856a7c497cc9bdd0`, headroom hash
`7e29fdfe4ba888b89fd148481671e987e40333a621cee6c695770cce1a152c91`, catalog hash
`6b2adea79fce729395713a4f857b1a3f0081ef52f6e472dbd4203eaa64bdfe2e`, contract hash
`b8f045773e6aec2e50453a93a885cd413a59135609e59cc6e7e8de817fe97756`, lock hash
`172536120e30c91825c570b6c7e6f490f1aa05a59b37715f6323d6511cb44149`, and image-scan ID
`ab3749c7bf6df110e44dffb0591ea636f0c258f6aada9c8b2a4926718d0b5ef0`.

## Image result and independent rejection

The v2 scanner produced final command image
`sha256:ca8c2145eda9d5cd4292ab408880a9cf0be3543de197325ddfbc999b4e80a98c`
from intermediate image
`sha256:5b2b326fdfc9f1d9575475b90f2d915f928de69237569fa9409deeb4b54dd7d5`.
The image-local scan itself passed: non-root `1004:100`, read-only root, cap-drop `ALL`,
no-new-privileges, private PID/IPC, bounded resources, one visible workspace mount, inert default
command, exact five-variable environment, and runtime/build networking `none`. It found no Codex,
provider credential, hidden asset, verifier payload, reference patch, source residue, or undeclared
volume. Its temporary scan container and workspace were removed, and no container remains bound to
the final image.

That image-local pass cannot override the later evidence-root failure. The context-aware scan
covered all seven files and 18,372 bytes. It compared four active provider/proxy-sensitive values
and the known repository, result, predecessor, qualification, and tool host roots only in memory;
none of those values were printed, persisted in the audit, or hashed. It found zero scanner errors
and no exact provider or proxy value, but one hard `raw_host_path` finding in
`materialization-progress.json`. The failed scan report hash is
`18b65431b8d7c508aac8704a263cb909e50b04a5fd6feaca4e5229ed01e052e4`.

## Accounting and successor boundary

V45 made zero provider calls and episodes, started no benchmark task or verifier, and created no
trajectory or decision record. It did not start formal collection, SFT, inference evaluation, GPU
work, or held-out loading. `formal_collection_allowed=false`,
`formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false` remain fixed.

PR-2802 remains provider-unattempted, so a new identity may rebuild its command image. The only
permitted repair is a separately authorized v46 zero-provider materialization that binds this
complete failed tree and the merged audit. It must enforce the same absolute runtime paths in
memory but persist only stable booleans, versions, hashes, and role identifiers. The provider
canary formerly reserved as v46 moves to v47 and remains unauthorized until a successful v46
result audit merges and the post-merge main run passes all eight job classes.
