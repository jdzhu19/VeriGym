# DeepSeek Harness v151 audit of the v150 official matrix

Date: 2026-09-05

## Decision

The single authorized execution of
`deepseek-harness-hwe-v150-official-matrix-v1` stopped before the provider boundary because the
host Docker runtime could not create the outer DinD container shim. The Docker state reported
`no space left on device` under `/var/lib/containerd/io.containerd.runtime.v2.task`. The first
task, Ibex PR-465, has marker `not_started`, zero provider calls, zero provider tokens, and
`provider_consumed=false`. The other four tasks never started.

This is a host infrastructure failure, not an HWE image-import failure, Harness/model failure, or
official-verifier rejection. It produces no trajectory-collection or SFT-path migration
conclusion. V150 is frozen and must never be rerun, even though no task crossed the provider
boundary. A new identity may be authorized only after a separate zero-provider check proves that
the host container runtime has sufficient root-filesystem headroom and can start and remove its
bounded sidecar cleanly.

Formal collection, candidate import, SFT, and production training remain disabled.

## Authorization and merge gates

- v150 implementation commit: `ceee145372c0888155a21a4b5900727585f775fb`
- v150 authorization merge/source commit: `d73901307d745e0af760f6c732741f12135ce348`
- v150 pull request: [#176](https://github.com/jdzhu19/VeriGym/pull/176)
- v150 branch-push run: `33942364629`, eight of eight jobs passed
- v150 pull-request run: `33942381359`, eight of eight jobs passed
- v150 post-merge `main` run: `33942594502`, eight of eight jobs passed
- v150 manifest file SHA-256:
  `5520fdac6b3ac583633aa987c534b319228b474581659519a00b116aa77c91c4`
- v150 manifest canonical hash:
  `f471c11b6371218c3d5bfab4380152eabec52b3637d466ef81658b36bcc47553`
- v150 launcher SHA-256:
  `a3503e8879604b19384b9e1b94c732b10d600ecc610aea0356a66fb350384ade`
- v150 runner SHA-256:
  `8228a86d7ca38a9f3db09be156ce8c51bec349352b22e14c59bace1286a496b4`
- v150 authorization SHA-256:
  `fe211fca93bfd9d99427ab81a4d519e4f19f0ca52607f28ee3ea897f5fcb90f0`

The launcher was invoked exactly once from the clean merged `main` commit with post-merge run ID
`33942594502`. Its exact-two-name child boundary retained only the required DeepSeek provider
configuration names. No provider or proxy value was printed, persisted, or hashed.

## Immutable execution evidence

The frozen evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v150-official-matrix-v1`

It contains seven directories including the root, four regular files, zero symlinks, and no other
filesystem objects. All directories are mode `0700`; all files are mode `0600`. Every JSON
canonical self-hash validates. The terminal progress and report files are byte-identical. An
in-memory scan compared both distinct nonempty provider values with all four evidence files and
found zero matches without printing, persisting, or hashing either value.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `e4b9d5a43c4d0f93dececb1bf336ca3d321e3c59414bf637a2fc2a9533945440` | `6473b911af4183efdfb72e1d684ad7a663e960cb930459f7a10620077f21e414` |
| PR-465 infrastructure attempt | `7ef2d084e51edbc850b0f3ff7fc11efb6bbb8c8a55adc9aa45444b057ca1fe3a` | `5cfbd1ba8fd67d7310fcb79c5f3c72157582ed629e8566d5b6c2ffd44f7e6ab9` |
| cleanup-recovery receipt | `52fe07c5bbb66ec52ecb81383455bfa058d0b709280a47b13124e6db5b3e1982` | `9e006360d25fb973ec70c7f7985a0474e5c5244d597b482dc66259f93f831599` |

The final report records `stopped_pending_independent_v151_audit`, matrix status `stopped`, stop
reason `pre_provider_infrastructure_failure`, attempt count one, provider episode count zero,
provider call count zero, provider token count zero, and v148 data-volume reopen count zero. The
only attempt has all six admission planes false. No task workspace, transcript, decision record,
candidate dataset, official-verifier result, or model output was created.

## Failure classification

The exact v150-owned outer container was created but never started. Its Docker state was
`created`, exit code `128`, and error:

`failed to start shim: mkdir /var/lib/containerd/io.containerd.runtime.v2.task/...: no space left on device`

At that point the host root filesystem had approximately 20 KiB available. The Docker data root
was already `/data/docker`, and the retained nested Docker data volume was already bind-backed on
`/data2`; neither setting removes containerd's small host-root runtime-state requirement. The
failure therefore occurred before the nested daemon became ready, before inner inventory or
network creation, before zero-provider task-runtime preparation, and before any Harness request.

No VPN, proxy, registry, image downloader, Docker daemon, or Docker network configuration was
changed. No partial archive was used. The existing image downloader was not stopped or restarted.

## Cleanup recovery and retained resources

The normal v150 best-effort cleanup could not enter the never-started container and therefore
correctly left `dind_cleanup_confirmed=false` in the immutable report. After verifying the exact
container ID, owner label `deepseek-harness-hwe-v150-official-matrix-v1`, role
`provider-daemon`, and non-running state, the failed container was removed. A first attempt to run
the bounded cleanup helper was blocked by the same root-filesystem exhaustion.

The remaining socket backing was empty. After verifying the exact socket-volume labels, bind
path, and absence of any v150 container, the exact socket volume was removed directly. The empty
root-owned backing directory was removed and recreated by the host user at mode `0700`. The
separate cleanup-recovery receipt records these actions and the original report hashes; the v150
report itself was not rewritten.

Final resource state:

- no v150-owned container remains;
- `verigym-deepseek-harness-v148-dind-socket` is absent;
- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v148/socket` is empty, mode `0700`, and owned by
  UID 1004/GID 100;
- `verigym-deepseek-harness-v148-dind-data` remains labelled with the v148 owner and role `data`,
  bind-backed by `/data2/jiadongzhu/docker/deepseek-harness-hwe-v148/data`;
- the retained v148 data volume was not mutated by cleanup and remains frozen.

## Successor boundary

V150 must never be rerun or relabelled. This v151 audit authorizes no provider execution. Before a
replacement official-matrix identity is proposed, a new zero-provider scaffold must fail closed
unless it can prove adequate host-root byte and inode headroom, start the exact bounded DinD
sidecar, complete readiness and inventory checks, remove the sidecar, and restore the socket
backing. That scaffold must not reopen the v148 data volume or expose provider configuration.

Only after the scaffold result receives its own independent merged audit and eight green
post-merge `main` check classes may a distinct one-use official matrix preserve the unconsumed
task order and seed/sample `502/18`. The new provider identity must retain all v150 protocol,
source, image, toolchain, verifier, credential-boundary, stopping, exact-tokenizer, and cleanup
controls.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
