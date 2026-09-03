# DeepSeek Harness v87 fresh scaffold successor authorization

Date: 2026-09-03

Status: **credential-free fresh scaffold authorized after merge and green `main` only**. This
identity does not authorize a provider request, model process, formal collection, SFT export,
training, or production-readiness claim.

## Why v87 exists

V85 stopped before its provider boundary because one DinD readiness probe exceeded its
15-second subprocess timeout. V86 froze that invocation, found zero provider calls and complete
cleanup, and conservatively treated the physical v83 volume opening as consuming the only reopen.
The v83 and v85 identities and the v83 data volume therefore cannot be retried or reused.

V87 creates a new DinD data volume and new backing under `/data2`. It repeats the five-task
zero-provider qualification from the completed, digest-locked local archives and publishes a new
execution scaffold only if every task and image control passes atomically. It changes the shared
DinD readiness helper so an individual `docker info` timeout remains a bounded not-ready probe;
the total startup deadline still fails closed. A callback records physical volume opening
immediately after the outer container starts, before any readiness wait.

## Frozen boundaries

- identity: `deepseek-harness-hwe-v87-fresh-scaffold-successor-v1`;
- upstream v69 manifest hash:
  `a20be68167d37e1acf68e1a9623a8dd5dcfaab973c0f6832d1238658af8f1d8b`;
- v79 provider contract hash:
  `38d79fcf0a5418c4153827a13ada20f1b8764daa17259ea1abbc19d2ef67b9b7`;
- frozen v85 stop report hash:
  `68a5ee595cc474546451eb0561f008cab1886713688a7bc683986bbec534fa80`;
- v86 audit commit: `d9bee7e4a595eb0ddfbc7dbf8dbf213624e9566e`;
- v86 post-merge `main` run: `33753098955`, all eight classes passed;
- new data volume: `verigym-deepseek-harness-v87-dind-data`, bind-backed by exact
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v87/data`;
- new transient socket volume: `verigym-deepseek-harness-v87-dind-socket`, bind-backed by exact
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v87/socket`;
- v79, v81, v83, and v85 data roots are not opened, copied, or reused;
- scaffold sidecar network: `none`, with its inner bridge disabled;
- task and verifier network: `none`;
- controller transfer: exact canonical tag through the audited content-free read-only pipe;
- registry access and partial archives: forbidden; and
- possible provider successor: only `deepseek-harness-hwe-v89-official-matrix-v1`, with one
  reopen after an independent v88 audit, separate v89 authorization, and green post-merge main.

The fixed tasks remain Ibex PR-465, PR-1135, PR-1780 and CVA6 PR-2017, PR-2711. Each must again
prove compatible patch metadata, complete archive and OCI locks, base-FAIL without infrastructure
failure, reference-PASS, a task-specific credential-free command image, v2 security scan, and
distinct official verifier binding. No partial execution-scaffold contract may be published.

## Invocation gate

After this change is merged and its post-merge `main` run passes all eight required classes, the
single permitted invocation removes every recognized provider environment name and runs:

```bash
env -u VERIGYM_DEEPSEEK_API_KEY \
    -u VERIGYM_DEEPSEEK_API_BASE_URL \
    -u DOCKER_HOST -u DOCKER_CONTEXT \
    VERIGYM_RUN_DEEPSEEK_HARNESS_V87_FRESH_SCAFFOLD=1 \
    python scripts/materialize_hwe_deepseek_harness_v87_fresh_scaffold.py \
      --post-merge-main-run-id <green-main-run-id>
```

All other recognized provider variables must likewise be absent. The user-owned image downloader,
VPN/proxy configuration, host Docker daemon, `/data/docker`, all historical DinD roots, and all
historical evidence remain untouched. Success still requires an independent v88 audit before a
provider authorization can exist.

Terminal flags remain `formal_collection_allowed=false`,
`formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
