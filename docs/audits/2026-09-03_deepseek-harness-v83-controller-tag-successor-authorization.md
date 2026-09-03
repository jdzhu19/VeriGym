# DeepSeek Harness v83 controller-tag scaffold successor authorization

Date: 2026-09-03

Status: **credential-free successor scaffold authorized after merge and green `main` only**. This
identity does not authorize a provider request, a model process, formal collection, SFT export,
training, or a production-readiness claim.

## Why v83 exists

V81 completed all five offline task qualifications but stopped before publishing an execution
scaffold. Its content-addressed controller transfer used `docker save` with an image ID, so the
archive preserved the correct image config while emitting no repository tag. The fresh inner
daemon correctly failed the strict tag check. V82 froze and audited that safe zero-provider stop.

V83 is a new single-use identity with new storage. It repeats the five offline qualifications and
changes only the controller transfer boundary: the host canonical tag is first required to resolve
to the exact frozen image ID and repository digest; that tag, rather than the ID, is passed to the
content-free Docker save/load pipe. The inner daemon must then expose the exact image ID and the
one canonical tag. Because an offline load need not restore `RepoDigests`, the receipt binds the
inner result to the independently verified host repository digest instead of inventing inner
registry provenance.

## Fixed boundaries

- identity: `deepseek-harness-hwe-v83-controller-tag-successor-v1`;
- upstream v79 provider contract hash:
  `38d79fcf0a5418c4153827a13ada20f1b8764daa17259ea1abbc19d2ef67b9b7`;
- frozen v81 stop report hash:
  `d1910a8446d4a5aab16a6903d216b5056af5ba0ae234db514e2b3764b691dc2f`;
- v82 audit commit: `fec373ff16687eb0d17c4434831c77ee8f8f980d`;
- v82 post-merge `main` run: `33742071653`, all eight classes passed;
- v83 manifest file SHA-256:
  `ebb58a8917444b8d96d37f4fc27ec037313f7f7e9a1d0b5d93ba2136418bc30b`, with canonical hash
  `24bdcfa839d0b4aedde41a11c404c134d777a6c7220225c86e6588136b6ac3a8`;
- v83 materializer file SHA-256:
  `535224ae711475a0ab93233a19742fea36452b6168507eac40698725c036dd75`;
- new data volume: `verigym-deepseek-harness-v83-dind-data`, bind-backed by exact
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v83/data`;
- v79 and v81 data volumes and backing directories are frozen and are not reopened or reused;
- scaffold sidecar network: `none`, with the inner bridge disabled;
- controller tag: `node:22.19.0-bookworm-slim`;
- controller image ID:
  `sha256:daa74c183f7d8c1ba55ed79c76e912f50be8782ca9d2da640645f906dce474b8`;
- controller source repository digest:
  `sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90`;
- provider successor: only `deepseek-harness-hwe-v85-official-matrix-v1`, with an exact reopen
  budget of one after a separate v84 audit and green post-merge `main`;
- future outer and inner provider network name: pre-existing user-defined bridge
  `verigym-hwe-net`; v83 neither attaches to nor creates that provider path.

The v83 invocation rejects root execution, provider variables, `DOCKER_HOST`, `DOCKER_CONTEXT`,
existing output/backing paths, registry access, partial archives, and any change to the locked
predecessor evidence. It neither changes the host Docker data root nor deletes or prunes shared
Docker content. Task and verifier execution remains on `network=none`. The transient socket volume
is removed through the fixed, capability-minimized cleanup container before publication.

If any scaffold, capacity, archive, source, image, security, transfer, or cleanup check fails, v83
publishes no execution-scaffold contract. The identity is then frozen and cannot be retried; a new
version is required. A successful scaffold is also not provider authorization: v84 must
independently audit the artifacts, image inventory, `/data2` inode binding, cleanup, canonical-tag
receipt, and zero provider/model counts.

## Invocation gate

After this change is merged and its post-merge `main` run passes all eight required classes, the
single permitted invocation is:

```bash
env -u VERIGYM_DEEPSEEK_API_KEY \
    -u VERIGYM_DEEPSEEK_API_BASE_URL \
    -u DOCKER_HOST -u DOCKER_CONTEXT \
    VERIGYM_RUN_DEEPSEEK_HARNESS_V83_CONTROLLER_TAG_SUCCESSOR=1 \
    python scripts/materialize_hwe_deepseek_harness_v83_controller_tag_successor.py \
      --post-merge-main-run-id <green-main-run-id>
```

All other recognized provider variables must likewise be absent. No concrete credential or proxy
value may be printed, persisted, or hashed. The user-owned image downloader, VPN/proxy
configuration, `/data/docker`, and every historical DinD backing remain untouched.

Terminal flags remain `formal_collection_allowed=false`,
`formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
