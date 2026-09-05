# DeepSeek Harness v178 local complete-builder qualification authorization

Date: 2026-09-06

## Decision

Authorize one zero-provider invocation of
`deepseek-harness-hwe-v178-local-builder-qualification-v1` only after this implementation is
merged to `main` and all eight post-merge workflow classes pass. V178 may qualify the reserved
Ibex PR-1816 open-toolchain comparison. It does not authorize a model, provider request, research
canary, trajectory, collection, SFT import or mixing, training, GPU work, benchmark-score claim,
or production readiness.

V176 is frozen and is not retried. Its bounded `offline_cache_miss` result, complete six-file
evidence tree, v177 audit, audit merge, and successful post-merge `main` run `33986069560` are
immutable predecessors. PR-1816 and provider consumption both remain zero.

The v178 manifest hash is
`2107ab1537df8d1d70ffa9513b2bd055bd06f521709d4f571ae7e71ffa60ac84`; its file SHA-256 is
`3168826c0234c6cfc171f33f47e8e82791ab6f9e44252ce8e47c438e5d7fedb8`. The final Dockerfile
SHA-256 is `272f2bdf5def15042b290a8b84b8ee4526b1e34386eaa18aa1f9579aba85f082`.

## Completed local builder archive

After the v177 merge and green gate, a read-only inventory found a completed dependency-only image
from an unfinished OpenSTA builder. Its exact identity is
`sha256:427a3ced88ef7857f74020c7d36bfb2a772dd67e22ee3dc20b24dce06e667ba3`.
The image contains a Debian base plus the packages needed to compile Verilator 5.008. It does not
contain a built OpenSTA or CUDD tree and does not inherit or copy an HWE task image. It was exported
as a completed Docker archive at
`/data2/jiadongzhu/Agent/datasets/tools/open-builder/v178/verilator-build-deps.tar`; the runner does
not depend on the shared host Docker store retaining the original image or provenance tag.

The manifest binds:

- archive SHA-256 `3045ab0f51baadec4c6b9d17039ee3a17e1cb652ec71b67be20c2cd477799b7d`,
  size 519838720 bytes, owner-only mode, and a separately hash-bound sidecar;
- the exact eleven-member Docker archive inventory, config filename, repository tag, and two
  ordered layer-tar names;
- creation identity `2026-08-28T08:16:23.797798019Z`;
- parent configuration identity
  `sha256:b284c9506fab13ae9bd94af562184978810b692f089901bdea8f21b074681576`;
- the two ordered rootfs diff IDs;
- canonical five-line, 848-byte `docker history` output with SHA-256
  `e4f62b732efce4f14a0e581250dba749314f84f255b7808e7f1c5f1981598949`;
- the exact 189-line, 4803-byte `dpkg-query -W` inventory with SHA-256
  `f835bc84ba9de9f29c9c52d8108762c1b2c933ca60cb3fea61e5c581ac359738`;
- exact hashes and versions for autoconf 2.72, Bison 3.8.2, Flex 2.6.4, g++ 14.2.0,
  Make 4.4.1, and Perl v5.40.1.

The canonical history contains the fixed Debian base and one package-install layer. Although its
build arguments name OpenSTA and CUDD inputs, no OpenSTA/CUDD build layer is present. The history
contains no HWE or Codex marker. Archive structure, image ID, platform, configuration, layers,
history bytes, package inventory, binary hashes, and tool versions must all agree.

## Authorized operation

The runner validates the completed archive before creating an output directory. It may save the
accepted open-tools image into bounded scratch, create one fresh `/data2`-backed DinD daemon with
outer `network=none`, load both archives, and apply tag `verigym/open-rtl-tools:v178-builder` only
inside that isolated daemon. It then creates one bounded builder probe with:

- `network=none`, read-only root, no mounts, non-root UID/GID;
- cap-drop `ALL`, no-new-privileges, private IPC, init/reaping;
- fixed CPU, memory, PID, tmpfs, output, and wall-time bounds;
- no provider/proxy forwarding, host home, Docker socket mount, HWE task mount, or workspace mount.

The probe output is scanned against active sensitive values and markers in memory. Only its byte
count and SHA-256 may be retained. Raw history, raw probe output, arguments, environment values,
and container identity are not persisted. Probe cleanup is mandatory.

It may build the final command image only with `--network none --pull=false` from completed local
Verilator 5.008 and ripgrep 15.2.0 archives. The final Dockerfile differs from v176 only by the
fresh inner builder tag. It cannot execute the original generic builder Dockerfile, download a
package, contact a registry, change VPN/proxy state, repair the default bridge, use a partial
archive, copy tools from an HWE task image, or use host EDA tools.

The completed local HWE archive under
`/data2/jiadongzhu/Agent/hwe-bench-public-images` is the only permitted official image source. The
open agent-only command image and official verifier remain distinct. Both use `network=none` and
must independently produce base-FAIL/reference-PASS for the same public PR-1816 test. The open
receipt is non-authoritative; only the official HWE verifier receipt is benchmark-authoritative.

## Atomicity, cleanup, and successor boundary

Any missing or changed predecessor, local builder archive, source archive, Dockerfile, task archive,
digest, image, platform, tool, route result, security control, or cleanup result stops without a
partial contract. No campaign builder tag is created on the host. Failure removes all v178 scratch,
backing, volume, and owned-container resources; success retains the immutable `/data2` builder
archive and may retain only the purpose-bound v178 DinD data volume with reopen budget one.

The qualification contract is written only after the builder binding, final-image scan, open and
official base-FAIL/reference-PASS results, role binding, empty inner inventory, outer cleanup, and
socket cleanup pass. A successful v178 result requires an independent v179 audit and eight green
post-merge `main` workflow classes before a distinct v180 research-only canary can be considered.
That later canary must use seed/sample `503/19`; it is not authorized here. Research-only output
must never be automatically mixed with official-route candidate SFT data.

All formal and training flags remain false:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`;
- `production_training_ready=false`.

## Invocation

After merge and the green post-merge gate, invoke exactly once:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V178_LOCAL_BUILDER=1 \
  python scripts/launch_hwe_deepseek_harness_v178_local_builder.py \
  --post-merge-main-run-id <successful-v178-main-run-id>
```

The launcher removes the complete provider configuration set plus `DOCKER_HOST` and
`DOCKER_CONTEXT` before the runner starts. Any different output, archive, manifest, Docker
endpoint, provider-bearing environment, branch, source commit, untracked inventory, or preexisting
v178 resource fails closed.
