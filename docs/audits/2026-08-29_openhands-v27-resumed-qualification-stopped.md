# OpenHands v27 resumed public qualification stopped

## Result

The one authorized run of `openhands-hwe-v27-resumed-public-qualification-v1` stopped fail closed
during source preparation for PR-1482. It is not eligible for retry, provider canary, collection,
training, or a benchmark claim. The authorization merged as PR #30 at commit
`04171b87d8409b5cd5b90096fabf362fe5e77d16` after all 16 push/PR checks passed.

The result is frozen outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v27-resumed-public-qualification-v1`. Its sealed
`qualification-progress.json` is 30,466 bytes with SHA-256
`b673072cf3bc379b2e80994ff1b967c3c265daa96f343ca33433a8c5754428bb`. The canonical progress
hash is `f21437bcd896e80f7d8d7cda509f7c07b363b19555fd2709f5d86ab65fbe5968` and recomputes exactly.

## Qualified evidence preserved

v27 verified and imported the two exact v26 qualified bindings for PR-2330 and PR-3226 without
rerunning either task. It did not retry the failed v26 PR-2844 transfer. The resumed path then
produced two new infrastructure-valid base-FAIL/reference-PASS outcomes:

- PR-3231: task hash
  `6597b3856b61cca5608ca1591a1df9ef911f930578a87fe1f57fbcba1745f913`, source hash
  `400347869b2873f624202d475d9fd677dda3789ba2751f7d77c226bce5057cb6`, transfer receipt
  `61fafb4b2c1d8650bc8b43f2271ad6e4a62be5456f1ae61fe85660903cbf7d16`;
- PR-2989: task hash
  `1c4dcc4c8ba5bed7b8b5342a1752350ae0447fe2101adb7e3f77c85151e368c0`, source hash
  `8c8c4c95bd12348a232e9d85c9da430ad3378bb3e9f65e87c4825154a91bbe24`, transfer receipt
  `9b12844032c6096862eba0b597da95042c6ef65cb8f3025b5b452878417b516c`.

The PR-3231 pull exited zero with empty stdout and 2,224 bounded stderr bytes. PR-2989 exited zero
with empty stdout and 2,042 bounded stderr bytes. Both were correctly accepted because integrity
came from the independently checked archive inventory, remote config digest, loaded image ID,
manifest digest, source lock, and verifier results rather than an empty-stderr assumption. The
shared layer cache reduced later candidate transfers to only their non-shared layers.

The result contains four qualified bindings in total. It did not reach the required five-task
split and therefore did not assign training or validation reserves.

## Exact stop boundary

PR-1482 completed config, digest, pull, and Docker-load stages successfully. Its pull exited zero
with empty stdout and 2,042 bounded stderr bytes, and its transfer receipt is
`4d0b332bbdf42261946d959a27d4b9830d051129903fcaa4db311f2a1c27fbc9`. Source preparation then
raised a `ConfigurationError` because the official reference patch was not an in-place-only text
edit. No base or reference verifier outcome was created for PR-1482. PR-3059 remained unattempted.

A content-free offline inspection of the frozen official record found two patch entries, including
one file creation. The local HWE profile requires every listed reference path to be a regular file
both before and after patch application, so this shape is deterministically incompatible before an
image is downloaded. This is an adapter-compatibility rejection, not evidence that the official
task or verifier is invalid.

The upstream HWE-Bench
[`adapter.py`](https://github.com/pku-liang/hwe-bench/blob/main/hwe_bench/harness/harbor/adapter.py)
passes the complete official `fix_patch` to its solve script and does not impose VeriGym's
in-place-only Candidate representation. Git's
[`git apply` documentation](https://git-scm.com/docs/git-apply) defines metadata-only summary and
machine-readable numstat modes that expose creations, deletions, renames, mode changes, and binary
patches without applying them.

A later identity should therefore perform a content-free reference-patch compatibility
classification before any image config, digest, pull, load, or source extraction. Known
incompatible shapes should be recorded as static adapter rejections and skipped without consuming
network, Docker, verifier, or model capacity. Infrastructure and security failures must remain
immediate fail-closed stops. That successor may import the four sealed qualified bindings only
after checking the complete v27 file and canonical hashes, must not retry PR-1482, and may continue
only with never-attempted candidates. This audit does not authorize that successor or another run.

## Cleanup and security scan

After the stop, transfer scratch and all v27 temporary containers were absent. Five successfully
imported candidate images remained as external evidence, including PR-1482's transferred image;
the temporary tarball sentinel tag was absent.

The export-eligible progress file passed the context-aware artifact scan over 30,466 bytes with
zero hard secret leaks and zero scanner errors. Proxy values were neither persisted nor hashed. The
scan report hash is `08226353009d4d9454b87340d6d1a3c40ee799f92d0da9ef4b081710dcefa352`.

No dataset, candidate source, image, cache, tarball, verifier workspace, credential, proxy value,
raw diagnostic, or full experiment artifact is committed by this audit. Provider calls and model
processes remained zero, no held-out task ID was loaded, and no historical attempt was retried.
