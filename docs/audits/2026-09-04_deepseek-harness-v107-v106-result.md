# DeepSeek Harness v107 audit of the v106 fresh-inventory-binding scaffold

Date: 2026-09-04

## Decision

The one authorized `deepseek-harness-hwe-v106-fresh-inventory-binding-scaffold-v1`
execution is validly closed as an immediate pre-Docker, pre-provider implementation failure. It
created no Docker backing directory, volume, container, task image, model process, provider
request, or provider call. It published no progress, report, inventory, task receipt, or
execution-scaffold contract.

V106 and its empty evidence root are frozen and must not be retried, reopened, edited, imported,
removed, or promoted. The conditionally reserved v108 provider identity is retired unused. A
repair requires a new zero-provider identity, fresh `/data2` paths, a new one-use authorization,
and a later provider identity.

## Authorization identity

- v106 authorization merge: `24556739daf27990cec2b17a1f89a92371251375`
- v106 post-merge `main` run: `33799073649`, all eight required check classes passed
- manifest file SHA-256:
  `f518e2fa16eda17d25b3ccaa58de8787fa9405c07f73c357b40cd54e026379be`
- manifest canonical hash:
  `1ec4b4b9724519e593dc1b7621f8b1584595abebde1417fbed932a328aa4a98b`
- runner SHA-256:
  `0b2f1b8aee07d1448f26835e2cb7dcafd688ec325a4f24fddfdb3824bd3fd5b6`
- authorization document SHA-256:
  `0bf4fee73ed444bbbe0b1c7581b8326955a959feff1b3e579072bab01c44c8ec`
- source commit at execution:
  `24556739daf27990cec2b17a1f89a92371251375`
- audited predecessor: v104 merge
  `95b9a11dbb3833fd57fc5b0a43bcd8708bc25865`, post-merge run `33795946043`

The authorization PR's pull-request run `33798186022` passed all eight jobs. Its push run
`33798167207` initially saw an unrelated existing Docker fake-provider test return an error; the
identical pull-request job passed, and the failed push job passed on its one CI rerun. This did
not execute or consume the v106 scaffold identity.

## Failure point

The v106 command was invoked exactly once with all 12 provider-related environment variables
explicitly unset and the required opt-in enabled. It exited with status 1 during the first
progress write in `v94.materialize`, before the headroom preflight or any Docker operation.

The v106 `_write_progress` wrapper called
`v103.v100.v97.v94._V94_WRITE_PROGRESS`. The frozen v94 module does not expose that attribute;
the captured base writer is exposed on the v97 wrapper module as
`v103.v100.v97._V94_WRITE_PROGRESS`. Python therefore raised `AttributeError` before it could
write the initial progress object.

This is a v106 wrapper composition defect. It is not the v103 final-inventory defect, a task or
patch rejection, a verifier result, a security scan result, a Docker-root limitation, or a
capacity failure. No exception text was written into the evidence root.

## Evidence and absence checks

The frozen result root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v106-fresh-inventory-binding-scaffold-v1`.
It has inode identity `64770:686131122`, mode `0700`, and contains exactly 14 directories created
by the initial layout setup. It contains zero regular files and zero symbolic links. In
particular, none of the following exists:

- `execution-scaffold-progress.json`
- `execution-scaffold-report.json`
- `execution-scaffold-contract.json`
- `execution-inventory.json`
- `final-execution-inventory.json`
- `task-materialization-set.json`

Post-failure inspection also confirmed:

- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v106` does not exist;
- Docker volumes `verigym-deepseek-harness-v106-dind-data` and
  `verigym-deepseek-harness-v106-dind-socket` do not exist;
- no `verigym-dind-v106-*` container exists; and
- the v106 control and runtime scratch directories do not exist.

Because failure preceded headroom inspection, archive access, image transfer, task
materialization, and Harness initialization, v106 made no registry request, used no partial
archive, accessed no task image, and had no opportunity to persist or hash a provider value.
The host Docker root and the user-owned downloader, VPN, and proxy configuration were untouched.

## Repair boundary

After this audit is merged and the resulting `main` commit passes all eight Actions classes, a
new zero-provider successor may be implemented as
`deepseek-harness-hwe-v109-progress-writer-scaffold-v1`, using fresh bind-backed Docker paths
rooted at `/data2/jiadongzhu/docker/deepseek-harness-hwe-v109`.

The successor must preserve the v106 fresh lock-and-receipt inventory design, but bind its
progress writer to the actual frozen base-writer capture. Regression coverage must invoke the
real scoped progress wrapper against a temporary output root, verify the written progress hash
and v109 format/status identity, and verify restoration after the context exits. All five tasks
must still be freshly rematerialized from completed local archives; no v103 or v106 task layer or
receipt may enter a successor contract.

V109 must remain one-use and zero-provider. A successful result requires an independent v110
audit before any provider execution. Any later provider matrix must use a new identity; v108 is
retired.

## Closed policy

Both migration conclusions remain false. There are no candidate SFT tasks, research
trajectories, or authorized imports. The following remain false:
`formal_collection_allowed`, `formal_collection_started`, `collection_started`,
`training_started`, and `production_training_ready`.
