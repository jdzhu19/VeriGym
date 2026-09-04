# DeepSeek Harness v124 audit of the v123 bounded DinD identity probe

Date: 2026-09-04

## Decision

The single authorized execution of
`deepseek-harness-hwe-v123-bounded-dind-identity-probe-v1` is consumed and must not be retried. It
completed deterministic cleanup with zero provider calls, but it did not qualify the inner Docker
daemon. The recorded `explicit_info_identity_failed` category is too broad: the combined evidence
shows that the runner accepted a false-positive readiness result before the daemon was connectable.
It does not establish that a ready daemon had the wrong version, storage driver, or default runtime.

The initial JSON-formatted `docker info` returned exit zero and a parseable object, but all three
selected values differed from the frozen identity. The explicit three-field `docker info` then
returned exit zero with three stdout bytes, 98 stderr bytes, one parsed value, and all three equality
checks false. The legacy version probe returned exit one with the independently classified
`daemon_connect_failure`. Together, those facts are consistent with Docker CLI formatting a
default/zero-value info structure while also reporting a daemon connection failure on stderr.
Consequently, an exit-zero parse alone was not a valid readiness predicate.

This is a zero-provider diagnostic design failure, not a benchmark-verifier or capacity failure. No
task, source archive, verifier image, Harness controller, or model was started. Both migration
conclusions remain false. There are no trajectories or SFT-admitted tasks.

## Authorization and merge gates

- v122 audit commit: `bbac3ccaa7bfa052d651f5cbf2f0e37ead453900`
- v122 authorization merge: `34a2854afcaa64a6de8a0fbca94ffd50dbb168db`
- v122 post-merge `main` run: `33823592366`, eight of eight jobs passed
- v123 implementation commit: `753a533fe21d8dfcb05a8b110bde4f1ffb084719`
- v123 authorization merge/source commit: `2489465550af18c994e449eecc2bdd8ae142c5e6`
- v123 post-merge `main` run: `33825382724`, eight of eight jobs passed
- v123 manifest file SHA-256:
  `bc9c80a1c33017a414b31ba1ad54ab631bde78f69d4e1515dbbde3934ff2044c`
- v123 manifest canonical hash:
  `8b921bdb5d24a65e69585a4e5c9e0c13a9e3bc32041ed5cb2fdb7c79fd98f45e`
- v123 runner SHA-256:
  `3d4490ef44a9a5c15aa5bd0e28b967e0c7d085711facff7271b961a202cf9442`
- v123 authorization SHA-256:
  `80a072e8fc5a1d5ef7f8ec052c39d3af9a94a32b191320c46f0e4e1f4545ce7d`
- merged campaign-model SHA-256:
  `85547440ba4fbabebe35b8b474cd30e571d6f1a8a4db4384d911d07ade273035`
- v123 DeepSeek regression SHA-256:
  `23ab2e2a24e2c4bdf8facc7aef9b06976d1387ab1454cb54150f4a067534ea70`
- campaign-model regression SHA-256:
  `b9ef69c0dcfeeceeaee8b8c013c9666e8f362d75d88a96efaa8676455f95e33a`
- merged security policy SHA-256:
  `b1176018ee02749d46d8b4de4c0a29c6ca7b7ad230939b7ab1d00eb8135751bc`

The exact post-merge run passed quality, package, Docker external-agent zero-model security,
OpenHands, reproducible-build, and ordinary Python 3.11, 3.12, and 3.13 jobs before v123 was
invoked.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v123-bounded-dind-identity-probe-v1`

It contains exactly one directory including the root, eight regular JSON files, and zero symlinks.
Every receipt self-hash validates, as does the report self-hash. The report and atomic progress file
are byte-for-byte equal.

| Evidence file | File SHA-256 | Canonical hash |
| --- | --- | --- |
| `cleanup-receipt.json` | `bc6eff71feedc3a2216682bc8f3cef52411d12d37eebcdce56516fa728e12e55` | `17d8bd3a1bb294e572d1cc790144770b2b8039cf5862b8793bf13fc1ce49b5e2` |
| `headroom-preflight.json` | `378b68b6920a86f6c1ac183f78de764fbdb343bfc6c151ba3b02dab9006ad548` | `ee903976f240412544a5b55470e93a88e83d9a6bb504ef7ee6d33b7f6de9907a` |
| `host-image-identity.json` | `c0277f43daaceef1773df30477a7d9048f4dde879a434402a580b1e5dc28de66` | `887b247835199e00583f0803818ed5c314b666be4a961bf35cd291cfefab338d` |
| `identity-probe-progress.json` | `1fc545ef33958baba13b56c134b600d9825805fa3091f9c7d726f870e9f16bbe` | `35de7d238a423904aed7ac99da56c64190631a8966da3cd397db018bfd9cd8a0` |
| `identity-probe-receipt.json` | `13c60c169d7f775e83b5749f2c39cd4a4c526e0b8d338354cf46a93cc64ad41b` | `56873a4bc385a167e9b909a45d239fab340e88bcdad5ed13583541e3ab1bf8ec` |
| `identity-probe-report.json` | `1fc545ef33958baba13b56c134b600d9825805fa3091f9c7d726f870e9f16bbe` | `35de7d238a423904aed7ac99da56c64190631a8966da3cd397db018bfd9cd8a0` |
| `predecessor-preflight.json` | `c45b5f7075c825b2a7623b4f0aaf48d743eaa169c2ec5ccf05b024a6e7907978` | `01191c009ff3f9423796ace06bc29932a81778de6d77fc66c43fc4b3267d0fc6` |
| `volume-setup-receipt.json` | `80780ae45b86380efdb505889b40db2040963ad15bb6c192681c7d6150b4c3c1` | `74be8007959fe2fb100c59dbc73ac71413900b80d96c873618ecac50e1174043` |

The equal report/progress pair records:

- `status=completed_pending_independent_v124_audit`
- source commit `2489465550af18c994e449eecc2bdd8ae142c5e6`
- post-merge run `33825382724`
- `startup_attempt_count=1` and `startup_attempt_limit=1`
- `diagnostic_complete=true`
- `diagnostic_category=explicit_info_identity_failed`
- `dind_identity_qualified=false`
- `cleanup_confirmed=true`
- `provider_request_started=false` and `provider_calls=0`
- `model_process_count=0`
- all task, base/reference, Harness-controller, registry, collection, and training start flags false
- no raw Docker output, raw exception, host path, or container identity persisted or hashed

The headroom policy passed all four roles, observing 40,322,683,310,080 free bytes and 685,017,368
free inodes on the common `/data2` filesystem. The host image matched immutable image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`,
repository digest
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`,
and the official `dockerd-entrypoint.sh`. The local image is tagged `docker:23.0.6-dind`.

## Readiness classification

The startup receipt records a successful, non-timeout, non-truncated `docker run --detach` with an
immutable-ID-shaped 65-byte stdout and no stderr. The outer control inspection passed privileged
mode, network `none`, the PID limit, empty TLS directory setting, two fresh named volumes, and the
read-only sentinel bind.

The first and only JSON readiness poll returned exit zero, which v123 treated as daemon readiness.
Its parsed `ServerVersion`, `Driver`, and `DefaultRuntime` keys were present, but every equality check
was false. The immediately following explicit formatter returned exit zero, three stdout bytes, 98
stderr bytes, one value rather than three, and every equality check false. The legacy formatter
then returned exit one, one stdout byte, 98 stderr bytes, and `daemon_connect_failure`. Docker events
for the bounded execution window show the one daemon create/start lifecycle, those three exec
lifecycles, controlled kill/die/destroy, and the successful cleanup-helper lifecycle. The daemon
container exited 137 because cleanup killed it; the cleanup helper exited zero.

The three-byte explicit stdout is not retained and must not be reconstructed as evidence. Its byte
count, nonempty stderr, deficient value count, and the separate connection-failure classification
are sufficient to reject the readiness decision. V123 therefore demonstrated a faulty readiness
predicate, not a ready daemon with an identity mismatch.

## Cleanup and isolation

The cleanup receipt passed. It records independent removal of the main container, cleanup helper,
data volume, and socket volume. No v123-labeled container or registered v123 volume remains. The
four v123 data, socket, control, and scratch directories remain as empty audit-visible directories;
each is owned by UID 1004/GID 100 at mode `0700`.

The invocation explicitly removed all 12 forbidden provider environment names plus `DOCKER_HOST`
and `DOCKER_CONTEXT`, then set only the v123 opt-in. A post-run scan used the three distinct provider
values present in the parent process without printing, persisting, or hashing them: all eight
evidence files were scanned and zero matches were found. Separate literal scans found zero evidence
files containing `/data2`, `/data/docker`, or `docker.sock`.

The v118 frozen volumes were not inspected or mutated. The user-owned downloader, VPN/proxy state,
`.partial` files, `/data/docker`, and the unrelated `/data/jzhu484/Agent/VeriGym` checkout were not
changed. No registry or provider access occurred.

## Successor boundary

After this audit is merged and its resulting `main` commit passes all eight Actions classes, one
new zero-provider readiness probe may be implemented as
`deepseek-harness-hwe-v125-bounded-dind-readiness-probe-v1`. It must use entirely fresh v125 output,
control, scratch, data-backing, socket-backing, container, and volume identities under `/data2`. It
may not reuse or inspect any frozen predecessor volume.

V125 may perform only predecessor/evidence checks, absolute headroom checks, the same immutable
host-image check, fresh bind-backed volume setup, one bounded DinD start, outer-control inspection,
one bounded readiness loop, optional post-readiness diagnostic classification, and deterministic
cleanup. No JSON-info exit code may independently establish readiness. Instead, each readiness
iteration must call an explicit formatter for `ServerVersion`, `Driver`, and `DefaultRuntime` and
qualify readiness only when all of the following are simultaneously true:

1. the command exits zero without timeout or truncation;
2. stderr is empty;
3. stdout parses to exactly three values; and
4. those values exactly equal `23.0.6`, `vfs`, and `runc`.

An exit failure, timeout, truncation, nonempty stderr, parse failure, or deficient values is a
transient not-ready result until a monotonic 120-second deadline. The loop may sleep one second
between attempts; the deadline, not a smaller fixed poll-count cap, must remain authoritative, and
each command must have a five-second timeout. If a clean, complete three-value response differs
from the frozen identity, v125 must fail immediately as an actual identity mismatch. If the
deadline expires first, it must record only an allowlisted content-free readiness category.

V125 must retain only bounded counts, timing/timeout/truncation facts, selected-field equality
booleans, and allowlisted categories. It must not persist or hash raw stdout, stderr, exception
text, container identities, host paths, or environment values. It gets one startup attempt with no
retry, no Docker network, no task/archive/source/image materialization, no base/reference
verification, no Harness controller or model process, no registry, and no provider credentials or
request. Cleanup must independently validate ownership and remove only fresh v125 resources; any
cleanup failure remains fail-closed.

Only a later independent v126 audit may decide whether a successful v125 result authorizes a new
five-task zero-provider scaffold. V123 itself must never be retried.

## Closed policy

`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
