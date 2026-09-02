# DeepSeek Harness v70 audit of the v69 capacity stop

Date: 2026-09-03

Status: **frozen pre-provider capacity failure**. The v69 identity may not be retried, resumed,
reconstructed, or relabelled. No provider episode, formal collection, SFT export, training, or
production-readiness work started.

## Authorization and execution boundary

The v69 implementation and its final pre-execution hardening were merged through PRs #104-#106.
The one authorized execution used exact clean tracked `main` commit
`12c793a139636f81c963bc5df1320fcb312dc4f0`. Post-merge `main` Actions run `33662917793` passed
all eight required job classes before the runner was invoked.

The output root did not exist before invocation. Common DeepSeek, OpenAI, Anthropic, and VeriGym
provider variables were removed from the process environment without printing, persisting, or
hashing their values. The fixed manifest was
`configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json`, with content
hash `a20be68167d37e1acf68e1a9623a8dd5dcfaab973c0f6832d1238658af8f1d8b`.

The command ran exactly once. It did not change VPN or proxy state, start or stop the user-owned
image downloader, access a registry, or read a `.partial` image archive.

## Stop boundary

All five primary tasks passed the reference-patch metadata compatibility preflight. The runner
then applied its shared absolute headroom policy before any image-archive validation, Docker image
load or build, source preparation, base/reference verifier, security scan, command image, model
process, or provider request.

The headroom receipt recorded:

| Role | Minimum bytes | Observed bytes | Minimum inodes | Observed inodes | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| `control_root` | 4,294,967,296 | 65,888,256 | 100,000 | 128,830 | bytes failed |
| `docker_root` | 103,079,215,104 | 123,178,205,184 | 250,000 | 250,283,434 | passed |
| `scratch_root` | 8,589,934,592 | 42,090,982,453,248 | 50,000 | 717,418,166 | passed |
| `output_parent` | 2,147,483,648 | 42,090,982,453,248 | 10,000 | 717,418,166 | passed |

The control-root byte check failed, so the runner raised `MaterializationHeadroomError` and
atomically sealed `stopped_without_provider_contract` at `headroom_preflight`. The receipt records
zero provider calls, zero model processes, no completed task IDs, no task receipts, and
`provider_contract_published=false`. The provider contract file is absent.

Only the five patch-compatibility receipts contain files below a task-specific subdirectory. The
archive-receipt, image-receipt, image-lock, qualification, security-scan, source-image-lock, and
source directories are empty. This is a capacity/infrastructure result, not a verifier rejection,
model behavior result, HWE-Bench score, trajectory result, or SFT-admission result.

## Frozen evidence

The sanitized external evidence root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v69-multitask-zero-provider-v1`.
All evidence files have mode `0600`; no raw exception was persisted.

- `headroom-preflight.json`: file SHA-256
  `bc187ee2dc002f9a95581e0827623e74baf415a4ffbbc713f765300f6738df06`; embedded preflight hash
  `3c9414cd64f2dea4437de6baf0aeb8745ed01bacbb02cd804ffce40b90c0f389`.
- `materialization-progress.json`: file SHA-256
  `f594fd8bc593150a4fd13c420f6e657937c78939a94739887cb069617aa1746a`.
- `zero-provider-report.json`: file SHA-256
  `f594fd8bc593150a4fd13c420f6e657937c78939a94739887cb069617aa1746a`; embedded report hash
  `05c692d8bff1090d38cb33e76d71a7ff1662ff3ba98f84a4266d2f07d8da9e43`.
- PR-465 patch compatibility: file SHA-256
  `52f718976b97271e77c44cf12b9d5cfa5451b524b58f2e6c4cf59e8983542edc`.
- PR-1135 patch compatibility: file SHA-256
  `535d3f05b861d9bd0d0032a3388ef039bad1652ad046b0f3f830e7e197eee439`.
- PR-1780 patch compatibility: file SHA-256
  `e0d9e1d425431a59875b940242f1f59a5f44eaf2b4752c9ab339df5be9b98db1`.
- PR-2017 patch compatibility: file SHA-256
  `d5aa618bed2b175995a66568cd4c580766cd542f5f2ca28bfe24bd7bdf531dcb`.
- PR-2711 patch compatibility: file SHA-256
  `bcb8397740c6c27f1af1c517e0d0aab432dacd8ef70fa251216840e1f3fd21c8`.

## Disposition and remaining stages

V69 is frozen, but its five primary tasks were not provider-consumed: no provider marker was
crossed and no task attempt began. No partial authorization exists. A future materializer requires
a separately reviewed successor identity after the control root has at least 4 GiB free and all
other execution-time gates pass again; it may not rewrite v69 evidence or reuse the v69 identity.

The planned v71 official five-task matrix, v72 result audit, v73-v74 alternative-toolchain
materialization/audit, v75 PR-1816 research canary, and v76 VCS safety work remain unstarted and
unauthorized because v69 did not publish a provider contract. This audit does not authorize any of
those stages.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
