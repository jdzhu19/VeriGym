# OpenHands v53 / v23 zero-provider materialization authorization

Date: 2026-09-02

Status: **successor implementation and one zero-provider materialization authorization only**.
No provider canary, formal collection, SFT export, or training is started by this change.

## Predecessor boundary

V52 is frozen by the stopped audit merged as
`37bc52b9c062fcfc2bb8e400cff447dcbf2b7ccc`. Its post-merge `main` Actions run `33583105272`
passed all eight required job classes. The v52 failure receipt has file SHA-256
`92bc1d36da3a4619acb0703c10f9df4215a5457d475ae46cf0c5b4ea9af33afa` and canonical receipt
hash `7ab138d0e144c23f7a9809f0d4573f1c9da336ad23b57f868186b6930d80e171`.

V52 stopped during `pr2728_image_transfer` / `candidate_pull`. It published no output contract,
created no source workspace, ran no verifier, called no provider, and assigned no benchmark
disposition. The OpenHands behavior-failure count remains zero. V53 is a new identity; it does not
resume, retry, reconstruct, or relabel v52.

## Transfer repair

V53 replaces the single multi-layer download with a failure-resilient sequence bound to crane
v0.22.0 and platform `linux/amd64`:

1. resolve the platform manifest digest, fetch the exact manifest, reject indexes, and cap it at
   512 unique layers;
2. validate the manifest bytes against the resolved digest and bind every ordered layer digest and
   declared size;
3. for each cache miss, invoke the pinned
   [`crane blob`](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/doc/crane_blob.md)
   command exactly once into task-specific staging;
4. validate the complete blob's declared size and SHA-256, then atomically rename it into the
   fixed content-addressed cache before starting the next layer; and
5. seed a private assembly cache with exactly the current manifest's verified layers, invoke
   `crane pull` to assemble the Docker tar, and independently verify the tar/config/image identity
   before loading and tagging it.

The official crane
[`recipes`](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/recipes.md)
document platform-specific manifests and their config/layer sizes. V53 uses that public metadata
only for image transfer integrity; it does not inspect benchmark source or hidden assets.

There is no runner-level retry. A failed v53 identity freezes and publishes no partial contract,
but layers already size/digest validated and atomically committed remain safe cache inputs for a
separately authorized successor. A failure receipt contains only bounded verified-layer
digest/size/hit facts and the existing allowlisted error family, stderr byte count, and SHA-256.
Raw stderr remains temporary.

## Authorized sequence

The authorization file is
`configs/training/qwen35_hwe_openhands_v53_v23_canary_materialization_v1.json`, with hash
`34da3a84553de8c878db07bec7f5319cf73446ebfadb43b49be7dc5659cdf564`. It binds the exact v52
failure, official dataset and PR-2728 record, execution image, crane/ripgrep artifacts, dedicated
download network, Linux/amd64 per-layer protocol, current v2 scanner, and all sealed v33 PR-3204
inputs.

With its explicit opt-in, the runner performs exactly:

1. PR-2728 platform-manifest resolution, per-layer transfer, cached assembly, and image import;
2. PR-2728 base-FAIL/reference-PASS public qualification with verifier network `none`;
3. v2 Codex, credential, hidden-asset, and network scanning;
4. PR-2728 command-image locking;
5. exact v33 PR-3204 source/command/scan lock revalidation plus a current offline v2 rescan; and
6. atomic v23 canary-contract publication.

The executable entry point is
`scripts/materialize_cva6_openhands_v53_v23_canary.py`. Any failed stage removes the contract
staging tree and freezes v53. It never deletes a verified persistent layer blob.

## Unchanged OpenHands and collection gates

The behavior protocol remains `auto_public_thought_atomic_recovery_v23`. Ordinary requests omit
`tool_choice`; only the one content-only recovery uses `required`. Sibling calls remain fully
prevalidated and serially dispatched in decision order. Provider hidden thinking remains disabled.
The provider limits, stuck/no-progress gates, bounded observations, six result planes, decision
masking, and exact-64K/no-truncation admission are unchanged.

The materialized happy-path schedule remains training PR-2728 then validation PR-3204, DeepSeek
v4 Flash, seed 498, sample 14. Because v52 never reached provider access, those provider sample
identities remain unconsumed. The future provider campaign shifts to v54 and requires a separate
authorization after a successful v53 result audit and another green post-merge `main` run.

This authorization keeps `formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and `production_training_ready=false`.

## Credential-free verification before authorization merge

The successor implementation was checked without Docker registry access, benchmark execution, a
provider credential, a provider process, or materialization opt-in:

- `ruff check .` and `ruff format --check .`: passed; 757 files were already formatted;
- core pytest: 1,086 passed, 1 skipped, 52 deselected;
- HWE Bench pytest: 52 passed;
- DeepSeek Harness pytest: 14 passed;
- OpenHands pytest: 568 passed, 66 skipped;
- mypy: core 209 source files, HWE Bench 9, DeepSeek Harness 7, and OpenHands 51 all passed;
- the standalone v53 materializer passed Python 3.12 mypy and direct CLI import/help checks;
- core and OpenHands wheel/sdist policy audits passed from no-isolation local builds; and
- the core wheel and sdist were each byte-identical across two builds with the same
  `SOURCE_DATE_EPOCH`.

The authorization hash was independently recomputed after these checks. No canary contract or
failure receipt was produced during credential-free verification; the sole authorized v53
zero-provider run remains pending the merged-`main` eight-class gate.
