# DeepSeek Harness v110 audit of the v109 progress-writer scaffold

Date: 2026-09-04

## Decision

The one authorized `deepseek-harness-hwe-v109-progress-writer-scaffold-v1` execution is
validly closed as a pre-Docker headroom rejection. The v109 progress writer repaired the v106
defect and produced a canonically valid progress/report pair. The run then failed closed because
the inherited headroom call measured the host system root as `control_root`; `/` had less than
the fixed 4-GiB minimum even though every `/data2` campaign filesystem passed by a wide margin.

V109 and all of its evidence and empty runtime directories are frozen and must not be retried,
reopened, edited, imported, removed, or promoted. The conditionally reserved v111 provider
identity is retired unused. A repair requires a new zero-provider identity, fresh `/data2` paths,
and a later provider identity.

## Authorization identity

- v109 authorization merge: `4d1456a34128d4c6f61fd2e7bbdd551c08f701dd`
- v109 post-merge `main` run: `33802355801`, all eight required check classes passed
- manifest file SHA-256:
  `ac147c5ef7c395353caf13bb15ba01b517df7be2392a6bb8cfef956735d6904a`
- manifest canonical hash:
  `363d2be159244606259325cc62a3421d3caf8b07dca0253f78e5fce56b80385e`
- runner SHA-256:
  `a666fb6cff83bf6634125aa91058000e951448b761a31d123793c91538258208`
- authorization document SHA-256:
  `2bd690b71727b3f24da546a08757e1b8d772b93bc8a469037ad1b2dd8cf6b144`
- source commit recorded by the result:
  `4d1456a34128d4c6f61fd2e7bbdd551c08f701dd`
- audited predecessor: v107 merge
  `96111d6073e4fe0944035a1a9a4b480e3f08d811`, post-merge run `33800282289`
- frozen v106 runner SHA-256:
  `0b2f1b8aee07d1448f26835e2cb7dcafd688ec325a4f24fddfdb3824bd3fd5b6`
- frozen v107 audit SHA-256:
  `d030a2be5d64fbb7df3214545c3e9940ef44c63427acea0646b9b6306eb4ecaf`

The v109 authorization PR's push and pull-request workflows each passed all eight jobs before
merge. The post-merge `main` workflow also passed all eight jobs before the one v109 invocation.

## Result integrity

The frozen result root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v109-progress-writer-scaffold-v1`.
It contains exactly 14 directories, eight regular files, and no symbolic links. The report and
progress file are byte-identical, and their embedded canonical hash recomputes exactly.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| `execution-scaffold-report.json` | `a2a1ee54a69d7542ce1ed078074e22265040e01e0ef7a96402fa40c3c94dd3e2` | `d70eba8db5a28eb24e8582f1bafddeb9bcbf71e5778e7374e305e60791f2f4f9` |
| `execution-scaffold-progress.json` | `a2a1ee54a69d7542ce1ed078074e22265040e01e0ef7a96402fa40c3c94dd3e2` | `d70eba8db5a28eb24e8582f1bafddeb9bcbf71e5778e7374e305e60791f2f4f9` |
| `headroom-preflight.json` | `dfe8359c637f5eb21e9ebde66ea8d2258ea1743681eb2caa0acc1a76d2988824` | `b982611f2d349e3abb6c6a02248fc02528e071d41a6f3348de9aa71960963cc9` |

The report records status `stopped_without_execution_scaffold`, stop reason
`MaterializationHeadroomError`, zero completed stages, `provider_execution_authorized=false`,
`provider_execution_scaffold_published=false`, `provider_request_started=false`, zero provider
calls, zero model processes, cleanup confirmed, no persisted raw exception, and all formal and
training flags false. No task materialization set, execution inventory, final inventory, runtime
receipt, image-transfer receipt, or contract exists.

Five patch-compatibility receipts are the only other files. All record `compatible=true`,
`docker_accessed=false`, `network_accessed=false`, and
`completed_before_archive_or_docker_access=true`:

| Task | Receipt SHA-256 |
| --- | --- |
| PR-465 | `52f718976b97271e77c44cf12b9d5cfa5451b524b58f2e6c4cf59e8983542edc` |
| PR-1135 | `535d3f05b861d9bd0d0032a3388ef039bad1652ad046b0f3f830e7e197eee439` |
| PR-1780 | `e0d9e1d425431a59875b940242f1f59a5f44eaf2b4752c9ab339df5be9b98db1` |
| PR-2017 | `d5aa618bed2b175995a66568cd4c580766cd542f5f2ca28bfe24bd7bdf531dcb` |
| PR-2711 | `bcb8397740c6c27f1af1c517e0d0aab432dacd8ef70fa251216840e1f3fd21c8` |

## Headroom finding

The absolute headroom policy itself was unchanged. It rejected only this observation:

- role: `control_root`
- supplied path: `/`
- minimum free bytes: `4,294,967,296`
- observed free bytes: `3,344,760,832`
- shortfall: `950,206,464` bytes
- inode threshold: passed

The three actual `/data2` campaign filesystem roles all passed:

| Role | Minimum free bytes | Observed free bytes | Inodes |
| --- | ---: | ---: | --- |
| bind-backed Docker root | 103,079,215,104 | 40,739,554,017,280 | passed |
| runtime scratch root | 8,589,934,592 | 40,739,554,017,280 | passed |
| output parent | 2,147,483,648 | 40,739,554,017,280 | passed |

The inherited v94 call hard-codes `control_root=Path("/")`, even though its campaign control
directory is a purpose-bound path under `/data2`. The failure therefore confirms that large task
layers are already directed to `/data2`; it does not indicate pressure in `/data/docker`, which
had approximately 714 GB free, or in `/data2`, which had approximately 38 TB free.

## Docker, credential, and cleanup boundary

The v109 data and socket backing directories were created under `/data2` before the headroom
call, but both remain empty. The v109 control and runtime scratch directories also exist and are
empty. No Docker volume or `verigym-dind-v109-*` container exists. The campaign transferred,
built, and imported no image and inspected no task or DinD image; no registry or partial archive
was used.

The command explicitly unset all 12 provider-related environment variables. A post-run in-memory
comparison of the four live nonempty parent-process provider values against all eight evidence
files found zero matches; values were not printed, persisted, or hashed.

After the failure, 1,705 files totaling approximately 1.09 GB were removed with `pip cache
purge`. The target was the user-owned, regenerable cache `/home/jzhu484/.cache/pip`. `/home` is a
separate filesystem, so this did not change system-root headroom. No Docker data, VPN/proxy
configuration, downloader state, or other user's file was removed or modified.

## Repair boundary

After this audit is merged and the resulting `main` commit passes all eight Actions classes, a
new zero-provider successor may be implemented as
`deepseek-harness-hwe-v112-data2-control-headroom-scaffold-v1` with fresh paths rooted at
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v112`.

V112 must retain every absolute byte and inode threshold. It may replace only the inherited
`control_root=Path("/")` argument with its real, empty, purpose-bound v112 control directory on
`/data2`. The wrapper must reject any unexpected inherited path or threshold call, record the
control-headroom binding explicitly, and test both argument substitution and propagation to the
v94 execution layer. Docker root, runtime scratch, output, task, verifier, inventory, credential,
and cleanup gates remain unchanged.

V112 must be one-use and zero-provider, and must rematerialize all five tasks from completed
local archives. A successful result requires an independent v113 audit before any provider
execution. Any later provider matrix must use a new identity; v108 and v111 remain retired.

## Closed policy

Both migration conclusions remain false. There are no candidate SFT tasks or trajectories. The
following remain false: `formal_collection_allowed`, `formal_collection_started`,
`collection_started`, `training_started`, and `production_training_ready`.
