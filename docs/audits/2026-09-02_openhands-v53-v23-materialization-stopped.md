# OpenHands v53 / v23 zero-provider materialization stopped audit

Date: 2026-09-02

Status: **v53 frozen after a provider-free infrastructure failure**. No provider canary,
formal collection, SFT export, or training was authorized or started.

## Authorization and merged-main gate

PR [#87](https://github.com/jdzhu19/VeriGym/pull/87) merged the v53 authorization as
`87b83a8b0951a6c31d4ee6da73a49a3254b33e8d`. Its post-merge `main` Actions run
[`33585325753`](https://github.com/jdzhu19/VeriGym/actions/runs/33585325753) passed all eight
required job classes before materialization began.

The one authorized invocation used authorization hash
`34da3a84553de8c878db07bec7f5319cf73446ebfadb43b49be7dc5659cdf564`, explicitly removed every
allowlisted provider credential variable, and enabled only
`VERIGYM_MATERIALIZE_OPENHANDS_HWE_V53_V23_CANARY=1`. The output and failure paths were absent
before invocation. V53 was not retried.

## Failure disposition

V53 stopped in the first stage, `pr2728_image_transfer`, when the single controlled
`crane blob` invocation for `layer_015` exited with status 1. The redacted transfer family is
`unknown`; temporary stderr was 192 bytes with SHA-256
`3b1989f565aa82c8afc920e54e89f22692e8bfb6cf59d62e5fcd52ad5f8e5409`. Raw stderr was not
printed by the runner, persisted, hashed into any credential identity, or copied into the
repository. A Docker daemon event independently recorded the final v53 container exit code as 1.

The failure receipt is
`/data/jzhu484/Agent/experiments/openhands-hwe-v53-v23-canary-materialization-v1.failure.json`.
Its file SHA-256 is
`e809bf3e843669ce67ae02a78ffcab18e21b10b3c6ddb2dbf8ced082dcb707b3`, its canonical receipt
hash is `aab9f0397db9383a5bab905079a5689ab3204bc7db308ea9441e0a694629f814`, and independent
recalculation confirmed the receipt hash.

This is a provider-before infrastructure failure. It assigns no benchmark disposition and does
not count as an OpenHands behavior failure. The cumulative behavior-failure count remains zero.

## Atomic-progress evidence

Before the failed layer, 15 cache misses completed their declared-size and SHA-256 validation and
were atomically committed to the fixed v53 content-addressed cache. The bounded inventory covers
774,127,158 bytes. A post-failure read-only audit confirmed:

- all 15 receipt entries exist in the persistent cache with matching sizes and content digests;
- all 15 were v53 cache misses, rather than inherited or relabeled successes;
- no v53 task-specific download or assembly staging directory remains;
- no v53 controlled container remains;
- neither the PR-2728 candidate tag nor the exact sentinel tag exists; and
- the materialization output directory and canary contract do not exist.

This proves the v53 repair fixed the deterministic v52 loss-of-progress defect: a later transfer
failure no longer erases previously verified layers. It does not convert the partial transfer into
a successful materialization or authorize reuse under the frozen v53 identity.

## Downstream gates

Because stage 1 failed, PR-2728 public qualification, the v2 security scan, command-image locking,
PR-3204 v33 lock revalidation, and atomic v23 contract publication did not run. Provider calls and
model-process count remain zero.

The failure receipt keeps `formal_collection_allowed=false`,
`formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

Any continuation requires a new v54 zero-provider materialization identity bound to this exact
failure evidence. It may consume the 15 verified content-addressed cache entries as cache hits, but
it must not resume or rerun v53. Since the v53 contract was never produced, the provisional v54
provider identity in that unmaterialized contract is unconsumed; a future provider campaign must
shift to v55. The v54 authorization must be merged and its own post-merge `main` eight-class run
must pass before another materialization invocation.
