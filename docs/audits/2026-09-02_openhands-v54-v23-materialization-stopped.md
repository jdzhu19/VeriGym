# OpenHands v54 / v23 zero-provider materialization stopped audit

Date: 2026-09-02

Status: **v54 frozen after a repeated provider-free infrastructure failure**. No provider canary,
formal collection, SFT export, or training was authorized or started.

## Authorization and merged-main gate

PR [#89](https://github.com/jdzhu19/VeriGym/pull/89) merged the v54 authorization as
`c0493a0bc9a89a331064e606875124e24dda0a79`. Its post-merge `main` Actions run
[`33589102591`](https://github.com/jdzhu19/VeriGym/actions/runs/33589102591) passed all eight
required job classes before materialization began.

The one authorized invocation used authorization hash
`ad9e981e55edffe046a05c70c1b946d06b57968e04902ea35301fcee4efe1e59`, explicitly removed all
five allowlisted provider credential variables, and enabled only
`VERIGYM_MATERIALIZE_OPENHANDS_HWE_V54_V23_CANARY=1`. Preflight independently confirmed that the
v53 failure receipt and all 15 frozen layer-cache entries still matched their exact identities.
The v54 output and failure paths were absent before invocation. V54 was not retried.

## Failure disposition

V54 successfully resolved the candidate digest, manifest, and config in controlled containers.
It then consumed all 15 v53 entries as verified cache hits and stopped when the one controlled
`crane blob` invocation for `layer_015` exited with status 1. Docker daemon events independently
recorded exit code 0 for the digest, manifest, and config containers and exit code 1 for the
`layer_015` container.

The allowlisted transfer family is `unknown`. Temporary stderr was 192 bytes with SHA-256
`3b1989f565aa82c8afc920e54e89f22692e8bfb6cf59d62e5fcd52ad5f8e5409`. Raw stderr was not
printed by the runner, persisted, or copied into the repository.

This byte count and hash exactly match the frozen v53 `layer_015` failure fingerprint. V54 ran the
single download for several minutes before receiving that same result; there was no runner retry.
The repeated fingerprint is evidence of a reproducible transfer-infrastructure condition, not a
successful layer or an OpenHands behavior observation. Its concrete cause cannot be inferred from
the redacted evidence alone.

The failure receipt is
`/data/jzhu484/Agent/experiments/openhands-hwe-v54-v23-canary-materialization-v1.failure.json`.
Its file SHA-256 is
`0d43725b76d25386b90f380f787d929f77533cfdfa777bdb2fdce6a5d65066f9`, its canonical receipt
hash is `44ff66090d4559ccb66037b68d3b8742c2fe483fcde1dbef4e693b1f9f1f1013`, and independent
recalculation confirmed the receipt hash.

This remains a provider-before infrastructure failure. It assigns no benchmark disposition and
does not count as an OpenHands behavior failure. The cumulative behavior-failure count remains
zero.

## Atomicity and cleanup evidence

The bounded v54 failure inventory contains exactly the 15 inherited cache hits totaling
774,127,158 bytes. Post-failure read-only checks confirmed:

- the fixed content-addressed cache still contains exactly those 15 verified blobs and no
  incomplete `layer_015` publication;
- no v54 task-specific download or assembly staging directory remains;
- no v54 controlled container remains;
- neither the PR-2728 candidate tag nor the exact sentinel tag exists;
- the materialization output directory and canary contract do not exist; and
- the failure receipt has `provider_calls=0`, `model_process_count=0`, and
  `raw_output_persisted=false`.

PR-2728 public qualification, v2 security scanning, command-image locking, PR-3204 v33 lock
revalidation, and contract publication did not run because stage 1 failed.

## Route and next gate

OpenHands remains the primary route: neither v52, v53, nor v54 reached a provider, and none
consumed either allowed OpenHands behavior-failure slot. The Harness fallback conditions have not
been triggered.

V54 is permanently frozen and must not be rerun. The repeated identical `layer_015` failure means
a v55 zero-provider successor must not be authorized as a blind repetition. Any continuation must
first add a credential-free diagnostic or transfer-scaffold change that can distinguish the
allowlisted cause while preserving raw-stderr non-persistence, cache integrity, zero retries, and
the dedicated transfer network. That change needs its own tests, authorization identity, merge,
and post-merge eight-class gate. Because the v54 contract was never materialized, a future provider
campaign would shift again, from provisional v55 to v56.

The failure receipt keeps `formal_collection_allowed=false`,
`formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
