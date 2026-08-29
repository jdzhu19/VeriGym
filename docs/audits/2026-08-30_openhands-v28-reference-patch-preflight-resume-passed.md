# OpenHands v28 reference-patch preflight resume passed

## Result

The one authorized run of `openhands-hwe-v28-reference-patch-preflight-resume-v1` completed its
zero-model public qualification and reached the required five-task reserve. It authorizes no
provider canary, collection, training, held-out access or benchmark claim by itself.

The authorization merged as PR #32 at commit
`1cab2ead8df3f93f2a5b914ff08b16a0820083cd` after all 16 push/PR results for the eight required
Actions classes passed. The result is frozen outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v28-reference-patch-preflight-resume-v1`.

Its sealed `qualification-progress.json` is 39,991 bytes with SHA-256
`f44e11ae449d9c6836c3a86b112492a65b03446039a5d8a38c2b9403231abc70`. The canonical progress
hash is `c631e93fd7c002dc47aff45894d24701baabbad599da405b57d5516f8d6ce119` and recomputes exactly.

## Frozen reserve split

v28 verified and imported the four exact v27 qualified bindings without rerunning or relabelling
them. It then qualified the sole never-attempted continuation task, PR-3059. The resulting frozen
split is:

- training reserve: PR-2330, PR-3226 and PR-3231;
- validation reserve: PR-2989 and PR-3059.

The task order, role assignment and five distinct bindings are complete. This is task
qualification, not an agent trajectory dataset and not a benchmark score.

## PR-3059 evidence

PR-3059 produced an infrastructure-valid base-FAIL/reference-PASS result with zero model
processes. Its public bindings are:

- task hash: `c1549938585e9152fa30898df196e312a45836062e03f2a35bb28d4896fba7e0`;
- source hash: `e5c320e0beaaba4e4c473da9c695db5ffdabb537c29e89d8d48bb8be9e8422b5`;
- source image-lock SHA-256:
  `305ac58f497c097ec47e08c617151c09fc10772fd8dc4abfd83cba2b76a3f193`;
- image ID: `sha256:c4c9b688bec8e6a8f730bc7b1e5aad6766cbd22c74b5d1cbdcfdd8ba59565479`;
- manifest digest:
  `sha256:acb1d693e42d73dcb67b8c1d058abd2bf886cae547991def09befb84de994a09`;
- transfer receipt hash:
  `ab3ed32792bd0f18078aae199e8665cf44f5025e4d68d5639275c708ad7d01a3`.

The independently sealed smoke report is 721 bytes with SHA-256
`98d7bc86f32704008a1983247243f33f52d246e19718d1a039b7529f3ca3960c`. Its base verifier node is
`failed`, its reference verifier node is `passed`, `base_infrastructure_error` is false, and the
two arms used `network=none`.

The digest-qualified `crane pull` exited zero with empty stdout and 2,224 bounded stderr bytes. As
preregistered, integrity came from the manifest, config, archive inventory, loaded image ID and
source-lock bindings rather than an empty-stderr assumption. Raw command output was not persisted.

## Patch preflight and immutable history

Before any v28 image or network access, the content-free Git metadata preflight revalidated
PR-1482 and PR-3059. Both two-file patches are representable by the repaired adapter; PR-1482 has
one regular text-file creation and PR-3059 has none. Their receipt hashes remain respectively
`c3eb126f6a6470703654a61ad6445300a620e79991be1d4753a5c14f13d66d75` and
`6d33e359635f9f3227455e7377334992b936487b215bbec8cdf69f14297cc751`.

PR-1482 was not rerun or retroactively qualified. v28 records only a predecessor
adapter-version-incompatible marker bound to the sealed v27 failure and current content-free
compatibility receipt. PR-2844 also remains the sealed predecessor transfer failure and its image
is absent. Historical attempts retried is false.

## Cleanup and security

The v28 transfer scratch, digest sentinel and all `verigym-hwe-v28-*` temporary containers were
removed. The host now contains six expected candidate images: the five retained predecessor
images plus PR-3059. No verifier-owned cache volume remains. One unrelated generic
`verigym-hwe-*` container was observed, but its Docker creation timestamp is 2026-08-28, before
this run; it was left untouched and is not v28 evidence.

The export-eligible progress file passed the context-aware artifact scan over 39,991 bytes with
zero hard secret leaks and zero scanner errors. Proxy values were neither persisted nor hashed.
The scan report hash is `fbffc2e473ffcbb404e0c9c4fe709e47d4e126a81d5fe2e77b73bc3aed058bbc`.

Provider calls and model processes remained zero, no held-out task ID was loaded, no agent image
was built, and failure diagnostic is null. No dataset, source tree, image, cache, tarball, verifier
workspace, credential, proxy value, raw diagnostic or full experiment artifact is committed by
this audit.

## Next gate

A separately reviewed and merged authorization must bind this exact five-task result before any
agent image construction or provider canary. The frozen canary remains one training-reserve task
followed by PR-3204 validation, with the preregistered model, versions, seed, sample index, limits,
security scan and fail-closed protocol. This audit does not authorize or start that stage.
