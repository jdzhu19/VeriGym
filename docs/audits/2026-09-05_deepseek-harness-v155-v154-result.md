# DeepSeek Harness v155 audit of the v154 official matrix

Date: 2026-09-05

## Decision

The single authorized execution of
`deepseek-harness-hwe-v154-official-matrix-v1` stopped before the provider boundary while
preparing the zero-provider Docker runtime for the first scheduled task, Ibex PR-465. The
structured exception class is `DockerImageError`. Its provider marker is `not_started`, with zero
provider calls, zero provider tokens, no effective modification, and `provider_consumed=false`.
The remaining four tasks never started.

This is a pre-provider infrastructure failure, not a model or official-verifier result. It does
not establish trajectory-collection or SFT-path migration. V154 is frozen and must never be
rerun. Because the v154 evidence deliberately excludes raw exception text and does not retain the
Docker error subreason, a successor may authorize only a fresh, zero-provider command-runtime
diagnostic before any replacement official matrix is considered.

Formal collection, candidate import, SFT, and production training remain disabled.

## Authorization and merge gates

- v154 implementation commit: `786a9b87c667fdcb918b6e591e47333d0005e310`
- v154 authorization merge/source commit: `dcfb9d5117d7fa2881d8694c7f86aed10857abc0`
- v154 pull request: [#180](https://github.com/jdzhu19/VeriGym/pull/180)
- v154 branch-push run: `33956662207`, eight of eight jobs passed
- v154 pull-request run: `33956666206`, eight of eight jobs passed
- v154 post-merge `main` run: `33956912403`, eight of eight jobs passed
- v154 manifest file SHA-256:
  `08cb90e0ae7f22f9e7d281185999c95f78f78b15bc2086387528ad485ffb3191`
- v154 manifest canonical hash:
  `95be7665adbc220c1350b23743aa56f9062e03b5fe7c1b1b0ae19293fdc657ec`
- v154 launcher SHA-256:
  `2d14334226d684fcbaa59d4e8ad4921c2efe8f4d7825f13b06347ba25d685d54`
- v154 runner SHA-256:
  `05021b235fa22f7673cd567824b95b4d1d8123c00ffaec6a0eb4729314e7d8d5`
- v154 authorization SHA-256:
  `fbdaa71db009f1c946d74371c57a3a335de8ed672b77287ce9ae5acfc250e584`

The launcher was invoked exactly once from the clean merged `main` commit with post-merge run ID
`33956912403`. Its child environment retained only the two required DeepSeek configuration names
from the twelve-name blocked set. No provider or proxy value was printed, persisted, or hashed.

## Immutable execution evidence

The frozen evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v154-official-matrix-v1`

It contains seven directories including the root, seven regular files, zero symlinks, and no
other filesystem objects. Every directory is mode `0700`; every file is mode `0600`. All seven
JSON canonical self-hashes validate. The terminal progress and report are byte-identical. An
in-memory scan compared both distinct nonempty provider values with all seven evidence files and
found zero matches without printing, persisting, or hashing either value.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| PR-465 infrastructure attempt | `328a7ed5f0430cead308c36d8484b3c07aa7e9cd55fd2859f085b248279e077c` | `6c7e60969b194d5c1b969dff9c79513411570f872f5b58b46d01885c4c72b682` |
| socket cleanup receipt | `e9f0fb5e9ae314dfc731244a7a4847566f6360475e64516bcd8065824d5d4bc3` | `4d5ed5b20e02c8d0e0a8c99dcca3553c0e5ca9c24a19763b3000e0486d088cfe` |
| host-root headroom | `81d48106b1ce450ee134b860f2e8208505c08d4b8ad9ba143ba32cb163128b1f` | `57a4ff9b5d46def2bdc1758f99ced9dceacceccc66b37bea210672e1c00feef0` |
| report/progress | `a52d0084a4a4edcb38ac4f6efcbbd773fcb226a3212bc73c23347847b8de07d4` | `7b58f36501fb19e22daa5c42746cfce6de2bc04d86771d0a28450b208d1c6aca` |
| provider DinD runtime | `0d15a272d0ca00d9393b11c41a56e28901fe7227423506949cd7c1862652f4de` | `ffd2d65615f813687424465d2c398775f12842724c8da23aa464349a136a5523` |
| provider network | `3735966acdad770669555885a218927a4bdea43a935689c07e8371744bf4eb3e` | `6894b464d5899d8809727cdba179898995db9852f7c36c1f8d2ada9b1f9c59a9` |

The final report records `stopped_pending_independent_v155_audit`, matrix status `stopped`, stop
reason `pre_provider_infrastructure_failure`, attempt count one, provider episode count zero,
provider call count zero, provider token count zero, and v148 data-volume reopen count one. The
only attempt has all six admission planes false. No task workspace, transcript, decision record,
candidate dataset, official-verifier result, or model output was created.

## Failure localization

The absolute host-root gate passed before any Docker access with 9,323,581,440 free bytes and
18,226,148 free inodes, above the required 4 GiB and 100,000 inodes. A later read-only check found
approximately 34 TiB free on `/data2`, so the v154 failure is not the host-root exhaustion that
stopped v150 and is not a `/data2` capacity failure.

The exact local DinD image started successfully with Docker server 23.0.6, storage driver `vfs`,
default runtime `runc`, and its retained data backing on `/data2`. The campaign then validated the
required immutable inner image inventory, including workspace, controller, five command, and five
official-verifier image identities. It also created and validated the provider-only inner
`verigym-hwe-net` bridge. The failure occurred only after switching to the nested Docker socket,
inside `DockerRuntime.prepare` for PR-465 during the five-task zero-provider preflight. No
zero-provider-preflight receipt was published because the first runtime did not complete.

The immutable v154 attempt intentionally retains only `exception_type=DockerImageError` and
`raw_exception_persisted=false`; it does not retain the exception's structured `subreason` or
probe details. It would therefore be unsound to claim a more specific cause from this evidence.

No VPN, proxy, registry, image downloader, Docker daemon, or shared Docker network configuration
was changed. No partial archive was used.

## Cleanup and retained resources

Best-effort cleanup removed the inner provider network, all campaign-owned inner mutable
resources, the exact v154 DinD sidecar, and the exact v154 socket volume. The cleanup receipt
returned exit zero and records `cleanup_confirmed=true`. A fresh read-only residual check found no
v154-owned container and no v154 socket volume. The socket, control, and runtime scratch
directories are empty, mode `0700`, and owned by UID 1004/GID 100.

The retained `verigym-deepseek-harness-v148-dind-data` volume remains bound to
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v148/data` with its exact v148 owner and `data`
role. Its single authorized reopen was consumed by v154. It must not be reopened again under v154
or silently granted another reopen under a successor.

## Successor boundary

V154 must never be rerun or relabelled. This v155 audit authorizes no provider execution. A fresh
successor diagnostic must remain credential-free and zero-provider, use a new identity and fresh
`/data2` data/socket backings, and import only immutable, completed, SHA-verified local image
archives required to reproduce PR-465 command-runtime preparation. It must not mount or reopen the
retained v148 data volume, access a registry, use a partial archive, or modify the downloader,
VPN, proxy, host Docker daemon, or shared network.

The diagnostic must preserve the runtime security controls and record a bounded, sanitized
structured Docker error subreason and non-secret probe metadata. If it passes, it must prove the
exact workspace, PR-465 command, and official-verifier identities and complete deterministic
cleanup. Its result requires another independent merged audit and eight green post-merge `main`
check classes before a new provider identity can be authorized. The unconsumed task order and
seed/sample `502/18` may be preserved only after that gate.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
