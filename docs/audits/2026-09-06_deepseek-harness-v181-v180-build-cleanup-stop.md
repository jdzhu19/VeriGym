# DeepSeek Harness v181 audit of the v180 build and cleanup stop

Date: 2026-09-06

## Decision

Freeze the sole v180 invocation as an infrastructure-invalid offline final-image build stop with a
second exception in failure cleanup. V180 consumed its one authorized invocation and must not be
retried, resumed, reconstructed, or relabeled. It produced no qualification contract and no
terminal zero-provider report.

PR-1816 remains task- and provider-unconsumed. V180 made zero provider calls and created no model
process, task source, workspace, HWE image import, candidate, trajectory, verifier decision, or
SFT-admission result. Formal collection, SFT mixing, training, GPU work, benchmark-score claims,
and production readiness remain false.

## Authorization and execution boundary

The v180 implementation commit is `3de16216b96b46d3b862737a418c7552797c069e`, merged by PR 206 as
`c4eb332d2d4b3332e187dce84941bd56bd4ea790`. Post-merge `main` run `33991118409` completed all
eight workflow classes successfully before invocation. The v180 manifest content hash is
`84944af9c15919cba6043e6d8eea76174e2bc0728487cc922768c8c1524c0115`; its file SHA-256 is
`785642eb66076892778ebb0481d286fc9ad49ec9de4626b04a2d63429be79d77`.

The launcher was invoked exactly once with that post-merge run ID. Its clean-main, seven-file
user-owned untracked inventory, predecessor, audit, archive, image, source, patch, and fresh-resource
gates passed. The headroom receipt records 12,601,004,032 available root bytes and
36,046,184,177,664 available `/data2` bytes, with `capacity_satisfied=true`. No registry access,
download, partial archive, VPN/proxy change, Docker daemon change, default-bridge repair, provider
configuration, or `LocalRuntime` use occurred.

## Passed mount and builder boundaries

V180 corrected the v178 Docker CLI incompatibility. The outer DinD container started and its
receipt proves image ID, repository digest, server 23.0.6, VFS driver, `runc`, privileged mode,
outer `network=none`, and absence of a host Docker socket and provider/proxy environment. It
inspected exactly two writable same-path output/scratch binds, one unchanged read-only host
sentinel bind, and the two intended writable named volumes. The receipt hash is
`dff0eb17c8d560b1a3f0ce907c90b91fc6db1612ff0dc759dbee8a692b9c0b50`.

The completed dependency-only builder archive again passed its eleven-member inventory,
config/image ID, two ordered rootfs layers, canonical history, owner/mode, sidecar, and SHA-256
checks. Inside DinD it also passed the mount-free, non-root, read-only, `network=none`, cap-drop
`ALL`, no-new-privileges probe. The probe bound the exact 189-package inventory and six required
build-tool hashes and versions, rejected HWE ancestry, and retained no raw output. Archive receipt
hash: `406f91b6fdb5a409e18dc980aa2782e35ecd3cc3f4c1c9060044a840266dfe57`;
runtime binding hash: `6c5711ae645b93e39682cee668e3d9e546010ff284e3f75ad43a903359a62276`.

These receipts establish that the v180 mount repair and `/data2` archive route worked. The stop is
not a recurrence of the v178 mount error, a builder-archive import failure, HWE archive corruption,
capacity exhaustion, provider failure, model failure, or verifier rejection.

## Build stop and cleanup finding

The inner offline `docker build` compiled Verilator for several minutes and then returned nonzero
from the inherited v172 `_run_quiet` helper. The build used the hash-bound v180 Dockerfile,
`--network none`, and `--pull=false`. That helper discards stdout and stderr, so this audit does not
assign a compiler, linker, install, storage, process, timeout, or other low-level cause. No OOM
event appeared in the accessible post-run kernel log, but that negative observation is insufficient
to identify the failure. The fixed audit category is `offline_final_image_build_nonzero`.

The exception path removed the outer DinD container and both labeled volumes before attempting to
delete their bind backing. DinD had created the backing `data` and `socket` directories as root.
The non-root Python cleanup then raised `PermissionError` while traversing `data`. Because that
second exception interrupted the exception handler, v180 did not replace its valid sealed
intermediate progress row or write `zero-provider-report.json`. The progress row therefore remains
at `status=open_toolchain_build`; it must not be interpreted as a running campaign or terminal
success. Its embedded report hash is
`5b780505be63ddb4acadb53588d7e1ff969d9024b8a7cc330211bb734b83bc24`.

After freezing the initial filesystem observation, a separate Docker cleanup container mounted
only the exact v180 backing parent. It used the same immutable DinD image, `network=none`, a
read-only root, no-new-privileges, cap-drop `ALL`, and only `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`.
It removed the failed inner Docker cache and socket backing, restored the empty parent to
UID/GID `1004:100` and mode `0700`, and removed itself. The empty parent and the owner-controlled
v180 scratch tree were then removed. Those transient build/cache files are not recoverable, but
both source image inputs remain reproducible from their immutable `/data2` archives. This
remediation does not rewrite or validate the v180 result.

Post-cleanup inspection finds zero v180-labeled container or volume, no v180 builder/final host
tag, and no v180 backing or scratch path. The frozen persistent builder archive and the seven
unrelated user-owned untracked files are unchanged.

## Frozen v180 evidence

The result root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v180-dind-mount-repair-qualification-v1`

It has tree hash
`04360c914501fa238e187af8e355e52981c0a1b87e3df9b2f59771efaf81b1a3`, mode `0700`, owner
UID/GID `1004:100`, and exactly seven ordinary mode-`0600` files:

- `archive-receipt.json`:
  `a74732ebd3a3751b4463fad864fbb0fb0903f5c93f789313856de554146d508c`;
- `dind-runtime.json`:
  `3ac01022af95b5367902bb60f6a15be3a772b1652cfc88689089e8ea21411df2`;
- `headroom.json`:
  `767c111c2b59665b422796601f0e2ebe288daf65674b87b9fa6a8466c431499e`;
- `local-builder-archive.json`:
  `e370259a2c0494041b2fdb62a77a3055093e73c5e1d381cdd125632ca7e46ae6`;
- `local-builder-binding.json`:
  `c28ad081a97b4a7e0fc29de9cb0b3798cbb3d61cedcc41a7a0dc10520c8f7e10`;
- `materialization-progress.json`:
  `f33371f75d0b5b5bd66d6b4408d9500f9ab30b0df0b0c6eb68b1ad2e85b78dbe`;
- `reference-patch-compatibility.json`:
  `e5e8aa3a47f0716b019dac51882db009573ba98ed1941fdbaca703c4e81696b7`.

There is no zero-provider report, qualification contract, security scan, image lock, source tree,
official-qualification directory, open comparison, role-binding receipt, inner-cleanup receipt,
candidate, trajectory, or verifier decision. The HWE archive was inspected but never imported.

## Narrow successor boundary

V181 authorizes no rerun of v180 and no qualification or canary. After this audit is merged and a
new post-merge `main` run passes all eight classes, a separate v182 identity may run one
zero-provider, task-free final-image build diagnostic using the exact v180 Dockerfile, local
builder archive, accepted open-tool image, Verilator archive, and ripgrep archive. It must not load
the HWE image, prepare PR-1816 source, run a verifier, create a model process, or expose a provider
client.

The diagnostic controller must bound combined build output and time, scan captured bytes against
active credential/proxy values and secret-like markers before retaining only a fixed category,
byte counts, and SHA-256 values, and never persist raw output, command arguments, or environment
values. It must distinguish nonzero exit, timeout, output overflow, sensitive output, and success.
Its exception path must guarantee a terminal report even when cleanup fails. Root-owned DinD
backing must be emptied and ownership normalized by an exact-path, networkless, least-capability
cleanup helper before volume/backing removal; cleanup evidence must reflect observed filesystem,
container, and volume state.

Only an independently audited diagnostic may authorize a later repaired qualification. The
PR-1816 DeepSeek research canary moves beyond v182 and remains unauthorized. All formal and
training flags remain false:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`;
- `production_training_ready=false`.
