# DeepSeek Harness v122 audit of the v121 bounded DinD startup diagnostic

Date: 2026-09-04

## Decision

The single authorized execution of
`deepseek-harness-hwe-v121-bounded-dind-start-diagnostic-v1` is consumed. It completed its
diagnostic and deterministic cleanup with zero provider calls, but it did not establish the
frozen inner-daemon identity. The outer privileged DinD container started with the required
controls, and the first `docker info` readiness probe succeeded. The subsequent identity decision
reported all three version, storage-driver, and default-runtime comparisons false and therefore
closed as `dind_runtime_identity_failed`.

This is a zero-provider diagnostic failure, not a benchmark-verifier rejection. It does not
authorize a retry of v121 or the five-task execution scaffold. It also does not show that the
daemon failed to start: the daemon was ready, remained alive until controlled cleanup, and both
fresh v121 volumes were removed successfully. Both migration conclusions remain false. There are
no task results, candidate trajectories, or SFT-admitted tasks.

## Authorization and merge gates

- v119 audit commit: `c22066916ba51e8c74678be2b0af6ac8d438ac9a`
- v119 post-merge `main` run: `33820413201`, eight of eight jobs passed
- v121 implementation commit: `22e5e0339e500a2f76e0cd5e5b660321d07c6506`
- v121 authorization merge: `0cc0f14af875ade980a2f9914d63a8d51c8a9730`
- v121 post-merge `main` run: `33822511727`, eight of eight jobs passed
- v121 manifest file SHA-256:
  `900887d09c9784b790926bee036e618f9d2ca38d1bab88fe8b995a73b4417bcc`
- v121 manifest canonical hash:
  `15d13190598d9ce0edc433074e807165192395532e2cd398f7b4a850e905cb5b`
- v121 runner SHA-256:
  `f9335111f312f4c4609db8a348f285ac6dc9191c138942b4de92caf03e32386d`
- v121 authorization SHA-256:
  `bf603a2f661d6f9a856b42513e8e8980173ac5e0a3451c53763e66d53849e94f`
- merged campaign-model SHA-256:
  `2d753f7f7758a5082b3a959410b377f292b74da4b856f5ce4083df1a5b0f23bc`
- v121 DeepSeek regression SHA-256:
  `c13a8d82287d9f9d8a6de4c570982ae1ab322668d2c2865734af13afd8c1ab44`
- campaign-model regression SHA-256:
  `0730f26b111f3fe42cd4ae0f1feb7636e26392a8bbc13204fea37c31bd2f6b1a`
- merged security policy SHA-256:
  `f960d39a42da32e052818b906a2214d9da84aeaaca382e363ecf506815c695e1`

The exact post-merge run above passed quality, package, Docker external-agent zero-model security,
OpenHands, reproducible-build, and ordinary Python 3.11, 3.12, and 3.13 jobs before v121 was
invoked.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v121-bounded-dind-start-diagnostic-v1`

It contains exactly one directory including the root, eight regular JSON files, and zero
symlinks. Every receipt self-hash validates, as does the report self-hash. The report and atomic
progress file are byte-for-byte equal.

| Evidence file | File SHA-256 | Canonical hash |
| --- | --- | --- |
| `cleanup-receipt.json` | `7b578767fd92a48d0909fed938859f5e8d176b942d1dfa3ae7a54695d5aa3ee3` | `7e4f231c0ffcb5b7ca901c50e056567355920c6cdded72161e60a9b006ccf364` |
| `diagnostic-progress.json` | `7116954eaa1bc814cfa158b0ac27c8ec336e9af4622c7bbba66f96d5d5db7619` | `3f6a0aafbac59171a10de28729b1553deecf08a344b6bf420c81d62cacaa1d6d` |
| `diagnostic-report.json` | `7116954eaa1bc814cfa158b0ac27c8ec336e9af4622c7bbba66f96d5d5db7619` | `3f6a0aafbac59171a10de28729b1553deecf08a344b6bf420c81d62cacaa1d6d` |
| `headroom-preflight.json` | `f4ea7e58c17aa36382bca16bae4269049f6bee652f94cdb9d26c00eb5d81bd9f` | `7db81da16a8cfc14818e778db00380fae668271984a34a0b495e245a3ec51831` |
| `host-image-identity.json` | `18b1eb98f291ef69b9c801bd4c8adfbc02b4c5823e72e1b6454303f889e1d814` | `b4a0b7226e90bc4dcdcd6919febf7f0238a86ece438322eae34f7e8608969bc0` |
| `predecessor-preflight.json` | `5984612c32d1c3bd01b03cd58625dc88ddaa18b4fbf65791d90240210589e169` | `b289f94a3385231e50c1a8359bd45f86ee43998ba7c92e9330e1ab13f1534e93` |
| `startup-diagnostic-receipt.json` | `2d4bc1cb0dd94f6e0f5d8012d40aecccef2e41ea545ae28f763c9001d2ce783f` | `c8ece24364069ec04098adeda0bd3cf4f490eb04b383464099175376e3f2f260` |
| `volume-setup-receipt.json` | `55f0b894f225369c29544b6373022d524831e8a6b1ab9347023f5bf39679c9fc` | `9e48d339ad742f01db62eda09c6776d16897fa2bdd9f90de1f1999226d2243fb` |

The equal report/progress pair records:

- `status=completed_pending_independent_v122_audit`
- source commit `0cc0f14af875ade980a2f9914d63a8d51c8a9730`
- post-merge run `33822511727`
- `startup_attempt_count=1` and `startup_attempt_limit=1`
- `diagnostic_complete=true`
- `dind_ready=false`
- `startup_diagnostic_category=dind_runtime_identity_failed`
- `cleanup_confirmed=true`
- `provider_request_started=false` and `provider_calls=0`
- `model_process_count=0`
- all task, base/reference, Harness-controller, registry, collection, and training start flags false
- no raw Docker output, raw exception, host path, or container identity persisted or hashed

The headroom policy passed all four roles, observing 40,400,945,709,056 free bytes and
685,862,194 free inodes on the common `/data2` filesystem. The host image matched immutable image
ID `sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`,
repository digest
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`,
and the official `dockerd-entrypoint.sh`. The local image is tagged `docker:23.0.6-dind`.

## Startup classification

The startup receipt records a successful, non-timeout, non-truncated `docker run --detach` with
an immutable-ID-shaped 65-byte stdout and no stderr. The outer control inspection passed:
privileged mode, network `none`, the PID limit, empty TLS directory setting, two fresh named
volumes, and the read-only sentinel bind were all present.

The daemon readiness probe passed on poll one. Host Docker events independently show exactly one
diagnostic-daemon create/start lifecycle, followed by one successful `docker info --format
{{json .}}` exec and one failed `docker version --format {{.Server.Version}}` exec. The main
container was then killed, exited, and destroyed. The evidence intentionally discarded the raw
outputs, so the existing record cannot distinguish a missing formatter field, a formatter
evaluation failure, or a genuine identity mismatch. It would be incorrect to infer the raw value
or to declare the DinD identity qualified from this evidence.

## Cleanup and isolation

The cleanup receipt passed. It records independent removal of the main container, cleanup helper,
data volume, and socket volume. No v121-labeled container or registered v121 volume remains. The
four v121 data, socket, control, and scratch directories remain as empty audit-visible directories;
each is owned by UID 1004/GID 100 at mode `0700`.

The invocation explicitly removed all 12 forbidden provider environment names plus `DOCKER_HOST`
and `DOCKER_CONTEXT`, then set only the v121 opt-in. A post-run scan used the three distinct
provider values present in the parent process without printing, persisting, or hashing them: all
eight evidence files were scanned and zero matches were found. Separate literal scans found zero
evidence files containing `/data2`, `/data/docker`, or `docker.sock`.

The v118 frozen volumes were not inspected or mutated. The user-owned downloader, VPN/proxy
state, `.partial` files, `/data/docker`, and the unrelated `/data/jzhu484/Agent/VeriGym` checkout
were not changed. No registry or provider access occurred.

## Successor boundary

After this audit is merged and its resulting `main` commit passes all eight Actions classes, one
new zero-provider identity may be implemented as
`deepseek-harness-hwe-v123-bounded-dind-identity-probe-v1`. It must use entirely fresh v123 output,
control, scratch, data-backing, socket-backing, container, and volume identities under `/data2`.
It may not reuse or inspect any frozen predecessor volume.

V123 may perform only predecessor/evidence checks, absolute headroom checks, the same immutable
host-image check, fresh bind-backed volume setup, one bounded DinD start, outer-control
inspection, bounded inner identity probes, and deterministic cleanup. Its inner probes may:

1. repeat the JSON-formatted `docker info` readiness check while recording only allowlisted field
   presence and equality booleans;
2. run one explicit `docker info` formatter for `ServerVersion`, `Driver`, and `DefaultRuntime`,
   accepting the identity only if all three exact expected values are returned; and
3. repeat the old `docker version` formatter only to classify its exit as success, formatter
   failure, daemon-connect failure, or other allowlisted content-free failure.

V123 must not persist or hash raw stdout, stderr, exception text, container identities, host paths,
or environment values. It must retain only bounded byte counts, exit/timing/truncation facts,
selected-field presence/equality booleans, and an allowlisted error category. It must use one
startup attempt with no retry, no Docker network, no task/archive/source/image materialization, no
base/reference verification, no Harness controller or model process, no registry, and no provider
credentials or request. Cleanup must independently validate ownership and remove only fresh v123
resources; any cleanup failure remains fail-closed.

Only a later independent audit may decide whether a successful v123 result authorizes a new
five-task zero-provider scaffold. V121 itself must never be retried.

## Closed policy

`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
