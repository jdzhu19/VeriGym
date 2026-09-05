# DeepSeek Harness v164 controller-initialize diagnostic authorization

Date: 2026-09-05

Status: **one synthetic zero-provider diagnostic authorized only after merge and green
post-merge `main`**.

## Decision and immutable inputs

Authorize exactly one execution of
`deepseek-harness-hwe-v164-controller-initialize-diagnostic-v1`. V164 is the bounded diagnostic
allowed by the v163 audit of the frozen v162 pre-provider failure. It is not a retry of v162 and
does not authorize a task, verifier, model request, trajectory, collection, or training run.

- Manifest SHA-256: `9f96a2f505b4d3f84b6ba1fc061320efd5cc2b69b43be5dc37dca52bb2c0f936`
- Manifest canonical hash: `570ebd074536732f3d7128741ec5a3cf0d359fed12ebce36a3145cd39a0b85ab`
- Runner SHA-256: `9255fa993170f04d8694a353c8aece50f10dfcba01a72fcfe6e8bf114181c46a`
- Launcher SHA-256: `df0c5c7493e61ef44ef8384fdcee7c79335c3fd0b7fdf48205875ce11a45e722`
- Structured-process module SHA-256:
  `710269e4c3be6cf084fbf7f744f14496ceffd2325f313380cde8e866ab6cfa24`
- v163 audit commit: `9ddfea81e62c816fecd574f3f2e373aea8068377`
- v163 audit merge: `f1e6c5421750f70df5b39a7ce5445d8fed2b04ca`
- v163 post-merge `main`: `33968340363`, eight of eight job classes passed

Execution additionally requires the exact merge commit containing this authorization to pass all
eight post-merge `main` job classes. The runner rejects a non-`main`, dirty, or non-up-to-date
checkout and records that run ID in atomic progress.

## Diagnostic boundary

V164 revalidates the exact seven-file v162 evidence tree, its canonical report, PR-465 attempt,
cleanup receipt, the v163 audit, and the pinned helper/process modules before output creation. The
v162 result must remain a pre-provider infrastructure failure with marker `not_started`, zero
episodes, zero calls, zero tokens, no task consumption, and complete cleanup.

The launcher selects blocked names before reading their values and removes the frozen twelve
provider names plus `DOCKER_HOST` and `DOCKER_CONTEXT`. Inside the child, the Harness initialize
probe receives only a freshly random synthetic key and `http://127.0.0.1:9/v1`. Initialize mode
must return zero events, no final response, no finish reason, no format repairs, and zero run
intervals. A provider marker is a hard infrastructure failure. All private Harness session and
broker artifacts are scanned for the two synthetic values and removed before a receipt is
published. The receipt may contain only an allowlisted structured category and bounded counts;
raw exceptions, stderr, output, and synthetic values are not persisted or hashed.

Before Harness initialization, a direct controller probe checks the exact nested Unix endpoint,
controller image ID, same-path source and runtime mounts, private writable session/broker mounts,
non-root identity, read-only root, dropped capabilities, no-new-privileges, private PID/IPC
namespaces, init, resource limits, bounded tmpfs, the dedicated controller bridge, and absence of
all provider environment names. It emits no task prompt and cannot invoke an HWE tool or official
verifier.

## Docker and cleanup boundary

V164 may reopen the exact retained `verigym-deepseek-harness-v158-dind-data` volume once, bringing
its immutable total reopen count from one to two. It uses a fresh v164 socket volume and fresh
`/data2` socket, control, runtime, output, and receipt paths. It does not pull, import, rebuild,
substitute, access `.partial` images, inspect unrelated Docker resources, change Docker daemon
configuration, or modify VPN/proxy state. The outer DinD and inner diagnostic controller alone may
use `verigym-hwe-net`; no task or verifier container is created.

Cleanup removes only v164-owned containers, the inner bridge, socket volume, and private
controller artifacts. The retained v158 data volume remains intact. Any infrastructure, evidence,
security, output-bound, marker, synthetic-value, or cleanup failure stops fail closed and cannot
authorize a replacement provider matrix.

Run exactly once after merge and the new green post-merge gate:

```text
VERIGYM_RUN_DEEPSEEK_HARNESS_V164_CONTROLLER_INITIALIZE_DIAGNOSTIC=1 \
python scripts/launch_hwe_deepseek_harness_v164_controller_initialize_diagnostic.py \
  --post-merge-main-run-id <green-main-run-id>
```

`formal_collection_allowed`, `formal_collection_started`, `collection_started`,
`training_started`, and `production_training_ready` remain false. The result is pending an
independent v165 audit. V164 cannot itself authorize a provider retry, formal collection, SFT, GPU
work, or production training.
