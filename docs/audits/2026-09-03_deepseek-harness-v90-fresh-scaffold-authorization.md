# DeepSeek Harness v90 fresh scaffold timeout successor authorization

Date: 2026-09-03

Status: **credential-free fresh scaffold authorized after merge and green `main` only**. This
identity does not authorize a provider request, model process, formal collection, SFT export,
training, or production-readiness claim.

## Why v90 exists

V87 successfully created and opened its new bind-backed DinD volume under `/data2`, passed
readiness, and loaded the locked PR-465 image. Its first cold-VFS runtime baseline read exceeded
the HWE source-preparation layer's fixed 60-second Docker control timeout. V88 froze that run and
its data volume with zero provider calls, zero model processes, no completed task, and no published
scaffold. The conditional v89 provider successor was never eligible and is retired.

V90 is a new one-use zero-provider identity with a new exact data volume and backing. It changes
only the source-preparation Docker control timeout from its default 60 seconds to the reviewed,
manifest-locked 300-second maximum. The default for every other caller remains 60 seconds, values
outside 1--300 are rejected before Docker access, and the existing repository-copy limit remains
300 seconds. This does not weaken the network, archive, verifier, provider, or cleanup boundary.

## Frozen boundaries

- identity: `deepseek-harness-hwe-v90-fresh-scaffold-timeout-successor-v1`;
- v87 stop report SHA-256:
  `f9acd67b51561ff5c3fbf1d17569ea04d281fd3e4545370742a95f75ad3886bf`;
- v87 canonical report hash:
  `ea4a69158765b05cb5d18d52b87ec292986be3a21e8a1169c8c28b9ab92efdcd`;
- v88 audit commit: `2738832520c079c0ec4bf2a990ac19c9b84d8f15`;
- v88 post-merge `main` run: `33757519337`, all eight classes passed;
- source-preparation Docker control timeout: exactly 300 seconds;
- new data volume: `verigym-deepseek-harness-v90-dind-data`, bind-backed by exact
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v90/data`;
- new transient socket volume: `verigym-deepseek-harness-v90-dind-socket`, bind-backed by exact
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v90/socket`;
- v79, v81, v83, v85, and v87 data roots are not opened, read, copied, or reused;
- outer scaffold network and all task/verifier networks: `none`;
- registry access and partial archives: forbidden; and
- possible provider successor: only `deepseek-harness-hwe-v92-official-matrix-v1`, with one reopen
  after an independent v91 audit, separate v92 authorization, and green post-merge `main`.

The fixed tasks remain Ibex PR-465, PR-1135, PR-1780 and CVA6 PR-2017, PR-2711. Every task must
again prove compatible patch metadata, complete archive and OCI locks, base-FAIL without
infrastructure failure, reference-PASS, a task-specific credential-free command image, v2
security scan, and distinct official verifier binding. The 300-second timeout is written into
every task receipt and the atomic scaffold contract. No partial contract may be published.

## Invocation gate

After this change is merged and its post-merge `main` run passes all eight required classes, the
single permitted invocation removes every recognized provider environment name and Docker client
override, without printing their values, then runs:

```bash
env -u VERIGYM_DEEPSEEK_API_KEY \
    -u VERIGYM_DEEPSEEK_API_BASE_URL \
    -u DOCKER_HOST -u DOCKER_CONTEXT \
    VERIGYM_RUN_DEEPSEEK_HARNESS_V90_FRESH_SCAFFOLD=1 \
    python scripts/materialize_hwe_deepseek_harness_v90_fresh_scaffold.py \
      --post-merge-main-run-id <green-main-run-id>
```

All other recognized provider variables must likewise be absent. The user-owned image downloader,
VPN/proxy configuration, host Docker daemon, `/data/docker`, all historical DinD roots, and all
historical evidence remain untouched. Success requires an independent v91 audit before any
provider authorization can exist.

Terminal flags remain `formal_collection_allowed=false`,
`formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
