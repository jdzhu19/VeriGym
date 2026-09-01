# OpenHands v46 PR-2802 materialization result audit

Date: 2026-09-01

Status: sealed zero-provider materialization accepted; v47 provider canary remains unauthorized
until this audit merges and the post-merge main run passes all eight required job classes.

## Execution and authorization

The sole authorized execution of
`openhands-hwe-v46-pr2802-canary-materialization-v1` ran from clean merged `main` commit
`e56d4eed4e403985f6f1134a35acbd79a6bec5c9`. Authorization PR
[#73](https://github.com/jdzhu19/VeriGym/pull/73) and post-merge main Actions run
[33495927696](https://github.com/jdzhu19/VeriGym/actions/runs/33495927696) passed all eight required
job classes before execution.

The checked-in authorization file SHA-256 is
`675d5f021e8a6a85c6d508d9bcd183f918ca1167cec4a4ba0bc7f3fe5101c482`; its canonical
authorization hash is
`54aa422171fa6f2a2dcf0753c1f47307a632ac57ab01b4a70bf6f6f3c99e687f`. The authorization audit
file SHA-256 is
`351e396ed306f52c6127cd35abc04935679636e796584c5f1edb994018e940a6`.

Execution-time preflight revalidated the main commit and workflow, clean tracked state, exact
authorization, repository Python 3.12.13 runtime, v33/v43/v44/v45 evidence, PR-2802 legacy lock,
ripgrep binary/archive hashes, required Docker images, empty v46 image namespace and output, and
absolute byte/inode headroom. The preflight passed before the runner repeated the same gates.

## Frozen result inventory

Full evidence remains outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v46-pr2802-canary-materialization-v1`. It contains
exactly seven regular single-link files and 18,566 bytes. All files have mode `0600`, all managed
directories have mode `0700`, and there are no symlinks or special files. Its complete tree hash is
`80e224648c35fb8e40155a0428e57d29cf867a42be7438e3b04e67c9960d2a40`.

The exact file SHA-256 values are:

- `materialization-progress.json`:
  `e7833ea4495aae1ee2f5665bb713e8fb4d36e3d84656ed32d7174722f36750bf`;
- `headroom-preflight.json`:
  `d4c24884d71a602e28337d657655b577bcd842e79657386d58329d9804c2cfc8`;
- `canary-command-image-catalog.json`:
  `97ae068650536b9654e0dc8a0c795759225bd7dbcc6a6982b46dd3c83fb7f003`;
- `canary-contract.json`:
  `daa26401d58796ceae54b671dd679402bd7348b424c0c4c670349090357bfa17`;
- `image-locks/pr-2802.json`:
  `c544ad2fe377f06ce1df30263ade79631ccf0242e0ceb6a15cf7efebc9ad3e9d`;
- `image-receipts/pr-2802.json`:
  `5c0a8cef3bbb5e998f462c573be8c80fb4958330c90868a308c597daf48e1a18`;
- `security-scans/pr-2802.json`:
  `63478f7ad8438c576beaab9085d72898843cf4b9caa68e5afc88378928e13227`.

Independent canonical recomputation matched progress hash
`dbf9b49e385b7b59819dd85748ed0990a0492cbc92d438a4c3aab448474f15ea`, headroom hash
`caac9247fe23d5a62ad0317efb8d70dcd99fb716b48d889c3c44524b928af9ae`, catalog hash
`94002a251b6a4036199c344d718c2668bbc2a3db64b0bffbac8367cf714590c9`, contract hash
`2423735c54cac89a9798afb353dfd700663586c031ba2af8366e875c68d1b8dc`, lock hash
`56eb714597459b0f6462d78049fc85fef3cd68d52de90931fec7ed2bc9757bde`, and image-scan ID
`523853d2ac78c030cc5ae47e8fea21ad1f526f8afa5d841e07ab1f833856c59c`.

## Image and result security

The v2 scanner produced final command image
`sha256:f370d7c34c8ea2c7d7a2fdde6a5bc47bf5cf887f5f35ab4bd759bb18b173a4db`
from intermediate image
`sha256:cb7b45b8efcc8dc90b71699361437a8609a371383592ed5172d865bb61da76ba`.
The image scan passed all declared controls: non-root `1004:100`, read-only root, cap-drop `ALL`,
no-new-privileges, private PID/IPC, bounded resources, one visible workspace mount, no declared
volumes, inert default command, exact five-variable credential-free environment, and build/runtime
networking `none`. It found no Codex, provider credential, hidden/reference/verifier asset, source
residue, or undeclared tool. Temporary scan resources were removed and no container remains bound
to the final image.

The independent context-aware result scan covered all seven files. It compared the one active
provider/proxy-sensitive value and the repository, result, predecessor, qualification, tool,
scratch, and Docker host roots only in memory; no compared value was printed, persisted, or hashed.
The gate passed with zero hard-secret findings and zero scanner errors. The deterministic report
hash is `7a1a62cba34811fb25cdb5b8360206c74059c300d8e6165277e71835e9f728e5`.

The persisted `repository_runtime` receipt contains only the Python version, approved
`pyvenv.cfg` content hash, equality booleans, and `absolute_host_paths_persisted=false`. It contains
no interpreter, prefix, repository, or package-root value. This closes the v45 result-path defect.

The first audit aggregation command completed the security gate and then stopped while attempting
to read a nonexistent `receipt_hash` from the unhashed v1 image-build receipt schema. It did not
write or change evidence. The corrected schema-aware audit validated the receipt by exact bindings
and file SHA-256 and reproduced the same passing security gate.

## Accounting and successor boundary

V46 made zero provider calls and episodes, started no benchmark task or verifier, and created no
trajectory or decision record. It did not start formal collection, SFT, inference evaluation, GPU
work, or held-out loading. `formal_collection_allowed=false`,
`formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false` remain fixed.

The sealed contract reserves a separately versioned v47 provider canary: PR-2802 training followed
by PR-3204 validation, protocol v22, seed 496, and sample 12. That provider canary may be proposed
only after this result audit merges and its post-merge main run passes all eight job classes. V46
does not authorize provider access or any downstream collection.
