# DeepSeek Harness v81 provider execution scaffold authorization

Date: 2026-09-03

Status: **credential-free scaffold authorized after merge and green `main` only**. This identity
does not authorize a provider request, a model process, formal collection, SFT export, training,
or a production-readiness claim.

## Why v81 exists

V79 successfully qualified the fixed PR-465, PR-1135, PR-1780, PR-2017, and PR-2711 schedule,
and v80 independently audited that result. The v79 DinD data backing is frozen evidence and may
not be reopened or reused. The official Harness route nevertheless needs the five official
verifier images, five task-specific command images, the frozen controller image, and prepared
task sources on the same isolated Docker daemon that will later run the matrix.

V81 therefore creates a separate, purpose-bound execution scaffold under
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v81`. It repeats the offline base-FAIL and
reference-PASS qualification from the completed local archives, rebuilds and scans the command
images, and copies the already digest-locked controller image through a content-free pipe from the
outer daemon. The transfer does not persist an export archive and does not use a registry.

## Fixed boundaries

- identity: `deepseek-harness-hwe-v81-provider-execution-scaffold-v1`;
- upstream provider contract hash:
  `38d79fcf0a5418c4153827a13ada20f1b8764daa17259ea1abbc19d2ef67b9b7`;
- v80 audit commit: `d522b1d451bace29e80b2af60ad31a4ba74774ec`;
- v80 post-merge `main` run: `33735930859`, all eight classes passed;
- new data volume: `verigym-deepseek-harness-v81-dind-data`, bind-backed by the exact `/data2`
  directory above;
- scaffold sidecar network: `none`, with the inner bridge disabled;
- controller image:
  `sha256:daa74c183f7d8c1ba55ed79c76e912f50be8782ca9d2da640645f906dce474b8`;
- provider successor: only `deepseek-harness-hwe-v83-official-matrix-v1`, with an exact reopen
  budget of one after a separate v82 audit and green post-merge `main`;
- future outer and inner provider network name: the pre-existing user-defined bridge
  `verigym-hwe-net`; v81 does not attach to or create that provider path.

The v81 invocation rejects root execution, provider variables, `DOCKER_HOST`, `DOCKER_CONTEXT`,
existing output/backing paths, registry access, partial archives, and any change to the v69/v79/
v80 evidence locks. It neither changes the host Docker data root nor deletes or prunes shared
Docker content. Task and verifier execution stays on `network=none`. The transient socket volume
is removed through a fixed, capability-minimized cleanup container before publication.

If any scaffold, capacity, archive, source, image, security, or cleanup check fails, v81 publishes
no execution-scaffold contract. The identity is then frozen and cannot be retried; a new version
is required. A successful scaffold is also not provider authorization: v82 must independently
audit the files, image inventory, `/data2` inode binding, cleanup, and zero provider/model counts.

## Invocation gate

After this change is merged and its post-merge `main` run passes all eight required classes, the
single permitted invocation is:

```bash
env -u VERIGYM_DEEPSEEK_API_KEY \
    -u VERIGYM_DEEPSEEK_API_BASE_URL \
    -u DOCKER_HOST -u DOCKER_CONTEXT \
    VERIGYM_RUN_DEEPSEEK_HARNESS_V81_EXECUTION_SCAFFOLD=1 \
    python scripts/materialize_hwe_deepseek_harness_v81_execution_scaffold.py \
      --post-merge-main-run-id <green-main-run-id>
```

No concrete credential or proxy value may be printed, persisted, or hashed. The user-owned image
downloader, VPN/proxy configuration, `/data/docker`, and every historical DinD data backing remain
untouched.

Terminal flags remain `formal_collection_allowed=false`,
`formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
