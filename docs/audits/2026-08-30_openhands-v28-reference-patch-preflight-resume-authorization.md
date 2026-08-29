# OpenHands v28 reference-patch preflight resume authorization

## Decision

This preregistration authorizes exactly one zero-model continuation under the new identity
`openhands-hwe-v28-reference-patch-preflight-resume-v1`, and only after this authorization merges
and all repository checks pass. It does not retry, rewrite or relabel v27 or any earlier identity.

The exact predecessor is the audited v27 stop at commit
`5df36778d7e5d5ba1fc5da77bb437addf0f82e90`. Its progress file SHA-256 is
`b673072cf3bc379b2e80994ff1b967c3c265daa96f343ca33433a8c5754428bb`, canonical progress hash is
`f21437bcd896e80f7d8d7cda509f7c07b363b19555fd2709f5d86ab65fbe5968`, and terminal diagnostic
hash is `d910ebe3f0934297801486973f9b3826c14380ec2ab182d0f2da7c9a8b8bab08`.

The authorization receipt is
`configs/training/qwen35_hwe_openhands_v28_reference_patch_preflight_resume_v1.json`; its canonical
authorization hash is `c66ec0393e20b89a7e5e410e527edcfbefeae080b37b21563e95e290cf1c2c2e`.
The reviewed runner SHA-256 is
`25a0c9a8a8bceeb9354bebc8e89205f2222f2afbb1d01669c13a390fce0a87ba`.

## Root cause and upstream-informed repair

The v27 run had four qualified public tasks when source preparation stopped on PR-1482. Its
official fix contains one ordinary text edit and one regular mode-100644 text-file creation. The
old local implementation required every reference path to exist both before and after applying
the patch, even though a VeriGym `Candidate` overlay can materialize a new regular text file.

The official HWE-Bench
[`adapter.py`](https://github.com/pku-liang/hwe-bench/blob/main/hwe_bench/harness/harbor/adapter.py)
passes the complete `fix_patch` to its solution script and does not impose that local in-place-only
restriction. The official
[`git apply` documentation](https://git-scm.com/docs/git-apply) defines the metadata-only
`--numstat`, NUL-terminated `-z`, and `--summary` interfaces used here. The HWE-Bench
[`repository`](https://github.com/pku-liang/hwe-bench) remains the source of the per-PR task and
patch semantics. These upstream references inform the compatibility boundary; they do not permit
reconstruction of v27 or prove a verifier outcome for PR-1482.

The HWE integration now runs a no-repository, no-network and no-Docker compatibility preflight
before output creation or image inspection. Raw Git output and patch paths stay in memory. A
receipt exposes only the classifier version, compatibility reason, bounded counts, three negative
access/persistence booleans and their content hash. Ordinary UTF-8 edits and regular mode-100644
text additions are supported. Deletions, renames, copies, mode changes, binary patches,
non-regular creations, unsafe or non-UTF-8 paths, manifest mismatches, malformed or over-bound
metadata and unknown summary records fail closed before Docker.

## Evidence import and one-candidate continuation

v28 validates the complete sealed v27 progress file before importing the four qualified bindings
for PR-2330, PR-3226, PR-3231 and PR-2989. Task, source, image, manifest and transfer identities
remain predecessor evidence. PR-2844 remains a terminal predecessor transfer failure.

PR-1482 is not rerun. Its current content-free compatibility receipt has hash
`c3eb126f6a6470703654a61ad6445300a620e79991be1d4753a5c14f13d66d75` and records two patch files
with one supported creation. v28 appends only an immutable predecessor adapter-version marker bound
to that receipt and the v27 failure evidence.

PR-3059 is the sole never-attempted continuation candidate. Its compatibility receipt has hash
`6d33e359635f9f3227455e7377334992b936487b215bbec8cdf69f14297cc751`
and records two in-place text edits. After merge, the runner may transfer and zero-model qualify
that task exactly once. A base-FAIL/reference-PASS result reaches the required five tasks; an
ordinary mismatch exhausts capacity; an infrastructure or security error stops immediately.
There is no automatic retry.

Candidate transfer alone uses `verigym-hwe-net`. Both verifier arms use `network=none`. Existing
daemonless digest, config, archive, image-ID, manifest, layer-cache, bounded diagnostic and
container isolation controls remain in force.

## Verification before authorization

- HWE patch-preflight regressions: `24 passed`; v28 continuation regressions: `6 passed`;
- v25, v26, v27 and v28 combined continuation regressions: `31 passed`;
- OpenHands Python 3.12 credential-free suite: `293 passed`; strict mypy: `28 source files`;
- HWE credential-free suite: `50 passed`; strict mypy: `9 source files`;
- ordinary credential-free repository suite: `1035 passed`, `1 skipped`, `52 deselected`;
- core strict mypy: `206 source files`; v28 strict Python 3.12 mypy: `1 source file`;
- tracked-source Ruff: passed; format: `667 files`; Git diff hygiene: passed;
- schema drift and documentation/audit contracts: `13 passed`, `2 deselected`;
- HWE and OpenHands wheel/sdist local builds and package-content audits: passed; both local builds
  reused the installed build backend, while Actions retain the authoritative isolated build;
- exact authorization hash recomputation: passed;
- real read-only authorization, dataset, seven-candidate inventory, two patch receipts, v27
  predecessor, five retained images, network, execution-image and tool-cache preflight: passed;
- real v28 `network=none` control container: zero exit/output, effective control hash
  `22988d5d14f8ef8fd3d8b8b6fa1659c4e712bf8c570abab17f739b0dcbca9aeb`, temporary container and
  scratch removed;
- changed implementation/config/security scan: `8 files`, `214,897 bytes`, zero hard leaks and
  zero scanner errors; proxy values were neither persisted nor hashed; report hash
  `d229378efedf96b473967d07d06a90f14ce7b4a00e4bf94361dc9022a3c436b5`;
- GitHub Actions quality, Python 3.11/3.12/3.13 ordinary, OpenHands 3.12, package, Docker security
  and reproducible-build checks remain the authoritative eight-check stage guard.

These are adapter, infrastructure and contract checks, not qualification or a benchmark result.

## Explicitly not authorized

This authorization permits only import of sealed public v27 evidence, content-free patch
compatibility classification, and one zero-model attempt for never-used public PR-3059. It does
not permit provider calls, agent-image construction, canary contract materialization, collection,
SFT, GPU work, adapter publication, or held-out access. The run must not start before this
authorization merges and may not be retried. Any result requires a separate sanitized audit.
