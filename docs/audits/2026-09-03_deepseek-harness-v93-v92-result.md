# DeepSeek Harness v93 audit of the v92 official matrix

Date: 2026-09-03

## Decision

The one authorized `deepseek-harness-hwe-v92-official-matrix-v1` execution is validly
closed as a pre-provider infrastructure stop. It produced no trajectory, consumed no
provider request, and establishes neither trajectory-collection migration nor SFT-path
migration. The v92 identity must not be retried.

The v90 data volume was reopened once, equal to its one-open successor budget. Any repair
must use a new campaign identity and a fresh purpose-bound `/data2` DinD data volume; it
must not reopen the v90 volume.

## Authorization and execution identity

- v92 authorization merge: `6e26453a013dddbc858b6f2619bd43daf1c892a5`
- v92 post-merge `main` run: `33764915249`, all eight required check classes passed
- manifest SHA-256: `aae696a498c08e7638d41c29c6129b177d7429c561a40d4e939e81efc7df7d03`
- manifest canonical hash: `ed4fdcaed0b104edef96c2809b382854a8b374fbbf317b02fe83f9f4a0c30b32`
- runner SHA-256: `861741382b3f91412ae252933678e5bca3da7fa88c44ff1622a3b7ee44511b75`
- authorization document SHA-256:
  `e9545744b1d06dfa46f460ac8274aebdc6be576629cb5d8870dec328b411a8c7`
- source commit recorded by the result:
  `6e26453a013dddbc858b6f2619bd43daf1c892a5`
- seed/sample: `502/18`
- scheduled order: Ibex PR-465, PR-1135, PR-1780, then CVA6 PR-2017, PR-2711

## Result integrity

The result root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v92-official-matrix-v1`.
All five files are regular files, no symlink exists, and every embedded canonical hash
recomputes exactly:

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| `matrix-report.json` | `09d73447edc525ac3c9e7bca0cdb5847fbc6e98632971ecc7f1440792ec70211` | `f392a5bc3534d6c6daaf953a63d9520ab95ef73ec4d7a904ce8fed1ab35b1c42` |
| `matrix-progress.json` | `09d73447edc525ac3c9e7bca0cdb5847fbc6e98632971ecc7f1440792ec70211` | `f392a5bc3534d6c6daaf953a63d9520ab95ef73ec4d7a904ce8fed1ab35b1c42` |
| `attempts/pr-465.json` | `c268dcb6f69ea0ecd7aa75755cdcd543025c38963bc583b9d4151113fa9c7df1` | `d431567af55e241e1b8c89198d753e7c369b4efe2e085871f43e1567cf460cb3` |
| `provider-dind-runtime-receipt.json` | `3b1cc1f8d5ef78222da7e9316d711a23c8c74995a5a667aa26117a18ad015a65` | `4d5da397a1c730b6da0280c86f0c65853c6352af63c7083328e136a888c08a6a` |
| `dind-cleanup-receipt.json` | `d7f9a0dc93e5b627033aea057398614eda05819e3bb72ff7c7dff3ac9e9f6a39` | `15a5291a1bbe40d01392615386fd3e87a955709582bccec2f1905a7f65ebb68e` |

The report and progress file are byte-identical. They record
`stopped_pending_independent_v93_audit`, matrix state `stopped`, reason
`pre_provider_infrastructure_failure`, one attempted disposition, zero provider episodes,
zero calls, and zero provider tokens. PR-465 has marker `not_started` and
`provider_consumed=false`; the other four tasks were not started. No decision row or
candidate dataset exists, and all six admission planes are false.

## Root cause

V92 stopped in `_validate_inner_inventory` after the DinD runtime receipt was sealed and
before the inner provider network was created. Host Docker events independently show the
bounded readiness probes, version/info/stat checks, empty container and volume checks,
image listing, controller inspection, and negative `verigym-hwe-net` inspection. No inner
network-create event or Harness initialization followed.

The deterministic contract gap is the HWE workspace runtime image. V92 requires the current
`HWE_WORKSPACE_RUNTIME_IMAGE_ID`:

`sha256:5b95472e7fbfa80eb0cf173099254ef5285fcd78f7c3c78b42678ae9181dd96e`

The sealed v90 inventory contains 16 observed image IDs and 11 required image IDs, but that
runtime image is in neither set. Its 11 required entries are the controller plus five
task-specific command images and five official verifier images. V90 therefore qualified a
provider successor without provisioning or locking an image that v92's Docker runtime
preflight requires. The fail-closed inventory check correctly prevented provider access.

A successor must explicitly lock, transfer, and scan the workspace runtime image, include it
in zero-provider inventory qualification, and complete the full zero-provider Docker runtime
and Harness initialization preflight before a separate provider authorization is considered.

## Cleanup, storage, and credential boundary

- The v90 data volume remains a local-driver bind volume with exact device
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v90/data`; the runtime receipt confirms the
  host and inner data root shared inode `64770:682230205` and that host `/data/docker` was not
  used for task layers.
- Physical reopen count is `1`, exactly the authorized budget.
- No campaign-owned container remains. The fixed socket volume is absent, its backing is
  empty, owner-only, and restored to UID/GID `1004:100`.
- The cleanup container ran with `network=none`, a read-only root, `no-new-privileges`, and
  only the three recorded cleanup capabilities; cleanup completed successfully.
- An independent in-memory scan compared both nonempty provider values against all five
  regular result files (14,382 bytes): zero hits. Values were not printed, persisted, or
  hashed.

## Closed policy

Both migration conclusions remain false. There are no candidate SFT tasks, research
trajectories, or authorized imports. Failed context is audit-only. The following remain
false: `formal_collection_allowed`, `formal_collection_started`, `collection_started`,
`training_started`, and `production_training_ready`.
