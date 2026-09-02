# OpenHands v54 / v23 zero-provider materialization authorization

Date: 2026-09-02

Status: **new successor implementation and one zero-provider materialization authorization only**.
No provider canary, formal collection, SFT export, or training is started by this change.

## Frozen predecessor boundary

V53 is frozen by the stopped audit merged as
`3835aaedc3d38df5af62f385d1c5b5e249c77d2f`. Its post-merge `main` Actions run `33587409723`
passed all eight required job classes before this successor was created.

The exact v53 failure file has SHA-256
`e809bf3e843669ce67ae02a78ffcab18e21b10b3c6ddb2dbf8ced082dcb707b3` and canonical receipt
hash `aab9f0397db9383a5bab905079a5689ab3204bc7db308ea9441e0a694629f814`. It records a controlled
`layer_015` command failure during `pr2728_image_transfer`, no output contract, no provider call,
no model process, and no benchmark disposition. This remains a pre-provider infrastructure
failure; the cumulative OpenHands behavior-failure count is zero.

V54 is a new identity. It does not resume, rerun, relabel, or complete v53. The provisional v54
provider identity existed only inside an unmaterialized contract and was never consumed, so a
successful v54 contract shifts the future provider campaign to v55.

## Verified cache input

The v53 receipt contains 15 ordered layer entries totaling 774,127,158 bytes. Each was a v53 cache
miss that completed declared-size and SHA-256 validation before atomic publication. V54 preflight
requires all of the following before it performs any network action:

1. exact v53 failure-file bytes and canonical receipt hash;
2. exact status, stage, failure type, redacted error family, stderr byte count, and stderr hash;
3. exactly 15 bounded inventory entries with the frozen aggregate byte count; and
4. a live content-addressed cache hit whose size and content digest match every frozen entry.

The shared cache path remains
`/data/jzhu484/Agent/.verigym-tmp/openhands-hwe-pr2728-layer-cache-v2`. After resolving and
validating the current immutable Linux/amd64 manifest, v54 treats matching blobs only as verified
cache hits and invokes the pinned `crane blob` command once for each remaining miss. Complete
misses are size/digest validated and atomically published one at a time. Assembly still uses a
task-private cache containing exactly the current manifest's verified layers.

The v53 CLI transfer code was factored behind explicit identity, version, and cache parameters.
The frozen v53 entry point supplies its original defaults; v54 supplies only its new identity.
The manifest validation, per-layer integrity checks, single-download policy, private assembly,
tar identity validation, single archive cleanup, and redacted failure behavior are shared and
unchanged.

## Authorized sequence

The authorization file is
`configs/training/qwen35_hwe_openhands_v54_v23_canary_materialization_v1.json`, with hash
`ad9e981e55edffe046a05c70c1b946d06b57968e04902ea35301fcee4efe1e59`. It binds the exact v52
and v53 failure histories, public dataset and PR-2728 record, execution image, crane/ripgrep
artifacts, dedicated `verigym-hwe-net` transfer network, current v2 scanner, and sealed v33
PR-3204 inputs.

With only `VERIGYM_MATERIALIZE_OPENHANDS_HWE_V54_V23_CANARY=1` enabled and all provider
credential variables absent, the runner may execute exactly once and in this order:

1. re-resolve and validate the PR-2728 Linux/amd64 manifest, consume verified cache hits, download
   remaining misses once, assemble the image, and validate it before import;
2. run PR-2728 base-FAIL/reference-PASS public qualification with verifier network `none`;
3. build and run the v2 Codex, credential, hidden-asset, and network scanner;
4. generate the PR-2728 command-image lock;
5. revalidate the exact v33 PR-3204 locks and current offline v2 scan; and
6. atomically publish the v23 canary contract for future v55 provider authorization.

The executable entry point is
`scripts/materialize_cva6_openhands_v54_v23_canary.py`. Any failure freezes v54, removes partial
contract staging, preserves only independently verified persistent blobs, and requires another
identity. There is no runner retry and no partial canary authorization.

## Unchanged behavior and collection gates

OpenHands remains the primary route because neither v52 nor v53 reached provider behavior and the
behavior-failure count is still zero. The behavior protocol remains
`auto_public_thought_atomic_recovery_v23`: ordinary requests use provider-default auto tool choice,
the single content-only recovery alone uses required, sibling calls are fully prevalidated and
serially dispatched, and provider hidden thinking remains disabled.

The future happy-path provider order remains PR-2728 then PR-3204 with DeepSeek v4 Flash, seed 498,
and sample 14. V54 does not invoke that provider campaign. It also keeps
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

## Credential-free verification before authorization merge

The implementation was checked without registry access, benchmark execution, a provider
credential, a provider process, or materialization opt-in:

- Ruff lint passed and 761 repository files were already formatted; user-owned untracked scratch
  trees were explicitly excluded and left unchanged;
- core pytest: 1,086 passed, 1 skipped, 52 deselected;
- HWE Bench pytest: 52 passed;
- DeepSeek Harness pytest: 14 passed;
- OpenHands pytest: 575 passed, 66 skipped;
- mypy: core 209 source files, HWE Bench 9, DeepSeek Harness 7, and OpenHands 53 all passed;
- the standalone v54 CLI passed Python 3.12 strict mypy;
- core and OpenHands wheel/sdist policy audits passed; and
- the core wheel and sdist were each byte-identical across two builds with
  `SOURCE_DATE_EPOCH=1784712454`.

The v53 compatibility tests and v54 exact-failure/cache, identity-shift, redaction, stage-order,
and atomic-publication tests are included in the OpenHands count. The authorization hash was
independently recomputed after verification. After merge, all eight `main` Actions job classes
must pass before the sole v54 materialization opt-in is permitted.
