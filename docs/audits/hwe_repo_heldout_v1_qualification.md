# HWE repository held-out v1 qualification gate

- Date: 2026-08-11
- Status: qualified
- Tasks: Ibex PR222, CVA6 PR2945, Rocket Chip PR3065
- Model calls: 0
- Final verifier runs: 6
- Campaign samples in this record: 0

This is a zero-model base-FAIL/reference-PASS qualification record, not a benchmark score. All
three selected tasks passed the infrastructure gate before the agent version or held-out split was
frozen. No task result in this record measures model quality.

## Locked inputs

The three records came from Hugging Face revision
`1403afb57ce056c659c82b35e39c38c6a21ee635`. The Rocket Chip JSONL was 833,567 bytes with SHA-256
`2a7a26ef2f69eaacd4046de4a5ab40c04b8e7f0c0b990feb754683ad8e4b9388`. The selected records each
modify one file, with patch deltas +7/-3, +1/-1, and +10/-2 in Ibex, CVA6, and Rocket Chip order.

The digest-locked images and local image identities were:

| Task | Manifest digest | Local image ID |
| --- | --- | --- |
| Ibex PR222 | `sha256:7c8b3368a6bb5f12b19f52e2e34271233c70bccffb6c734c2bb8a9a54e95a572` | `sha256:cde141cb0f4c8458dc1f0339c2834090126e70101adfca7b4910d23b54046c58` |
| CVA6 PR2945 | `sha256:242b87a27a74c1e71b8e0386a19b8748e389418ae90f0d165cde6e505a687e9f` | `sha256:eb4cefa443b17491593bbdbae5ea2fb2086f5b7401160baf90c314104636306f` |
| Rocket PR3065 | `sha256:3ea7f5e34b0ee20f626c461e6c89e05cc3502a265996220d2b18e0f644a4adab` | `sha256:62c6c017b76e139053a9c3c0c45a7ecaa4b4ac23bab12f6d32ba95edfaa79573` |

The final source-lock v2 SHA-256 values were
`0dbd276c0387dd84695e7258c5f06f9f682653fbbad57c78bc53ecfcf9c0beaa`,
`ee1a34900c702cf3af613e7269362872995be3d8053808268452d34f60f77274`, and
`7163668d68e65ca72ab95dcf3553fe0c3deafebce57e2d37f1e118a8d7998304`. The corresponding
prepared sources occupied approximately 2.5 MB, 162 MB, and 17 MB. CVA6's profile-bound exclusion
removed only the image's untracked, rebuildable
`verif/core-v-verif/vendor/riscv/riscv-isa-sim/build` directory from the agent workspace.

## Rocket offline dependency correction

The initial Rocket attempt used the official image and reached its SBT build, but the verifier's
stricter `--network none` policy exposed an incomplete image cache. SBT could not retrieve
`compiler-bridge_2.12:1.3.5` sources or its `util-interface:1.3.0` closure. This was an
infrastructure-invalid offline dependency failure, not evidence that the upstream reference patch
was incorrect.

A controlled prewarm ran a one-line public Scala project in the same official image. It did not
mount the Rocket repository, reference patch, or hidden verifier. The final repository profile
locks only these three public files:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `compiler-bridge_2.12-1.3.5-sources.jar` | 48,862 | `9e689ec3266a5c1a37404b84dcc680f0540c4ab35d59cdf6a81ddefe1851c8f5` |
| `util-interface-1.3.0.jar` | 2,571 | `89028234b4621ac92761676a00e2e47598fcf5232a9bb994a7ed6dee94eb5aa2` |
| `util-interface-1.3.0.pom` | 2,775 | `984601d455b24a730455bd093dbd81aca7a829fcf003de3ab50309373ec3301e` |

Preparation requires an explicit local verifier cache and copies no other additions. Each Rocket
verifier execution creates a unique Docker volume, lets Docker initialize it from the official
image cache, injects and rechecks the three frozen files, generates Coursier sidecars, and removes
the volume after the container exits. Base and reference executions never share a writable cache.
Cache-seed failure is classified as `sandbox_error`; the hidden test cannot spoof seed success
because the trusted runner emits the ready marker before invoking the test script.

## Qualification outcome

| Task | Base | Reference | Infrastructure error | Model processes | Smoke-report SHA-256 |
| --- | --- | --- | --- | ---: | --- |
| Ibex PR222 | FAIL | PASS | no | 0 | `3c52c413dee7bda88693c5251b9e6f9ca66d82e3100b1af526e9c52a697d00fc` |
| CVA6 PR2945 | FAIL | PASS | no | 0 | `a2d24a34d92912e1383480c2c3a95efc27009538947c48fd9a8158ed9224ad9a` |
| Rocket PR3065 | FAIL | PASS | no | 0 | `955919e753e9ba4fc522a3fa19e893c7a87fba9b0c897a23dc4f9a1cc5417c34` |

All six final verifier containers used `--network none`, dropped all Linux capabilities, enabled
`no-new-privileges`, and enforced repository-profile CPU, memory, PID, timeout, and output bounds.
Both Rocket results recorded three dependencies and successful cache-volume cleanup; no labeled
verifier volume remained after qualification. Raw hidden-test output, test scripts, candidate
repositories, and golden patches were not exported.

## Implementation validation

The final offline checks passed:

- Ruff lint and format checks over 387 Python files
- strict mypy for 176 core, 8 HWE-Bench, and 17 training-reference source files
- 760 ordinary core tests passed, with 1 real-Codex test skipped and 51 opt-in tests deselected
- 23 HWE-Bench and 36 training-reference tests passed
- persistent-schema drift check reported 0 changed schema files
- core, HWE-Bench, and training-reference wheel/sdist policy audits passed with no issues
- existing source-lock v1 prepared sources remained loadable through the compatibility path
- missing, extra, symlinked, and content-tampered verifier dependency states fail closed
- the nine exported qualification report/result files passed the artifact security scan with zero
  hard-secret findings and zero scanner errors

The complete suite used the repository-prescribed short `/data/jzhu484/Agent/.vgpt/` pytest base
paths. The security scan covered only the nine structured qualification files eligible for export,
not candidate repository copies or raw verifier output.

## Gate consequence and host state

The complete three-task set is eligible for the separately recorded
`codex-luna-max-hwe-heldout-v1` agent-version and `hwe-repo-heldout-v1` split freeze. This audit does
not include Luna sampling, trajectories, training export, or a benchmark-quality claim.

The host's built-in Docker `bridge` object referenced a missing `docker0` interface. Controlled
prewarming therefore used the dedicated `verigym-hwe-net` user-defined bridge; formal verification
remained network-disabled. Docker was not restarted, existing containers were not disturbed, and
the temporary prewarm container was removed. The host VPN configuration was not changed. Docker
root stayed under `/data/docker`, and datasets, scratch files, package builds, and experiment
evidence stayed under the repository-prescribed `/data/jzhu484/Agent/` paths. No credential or
concrete proxy value is included here.
