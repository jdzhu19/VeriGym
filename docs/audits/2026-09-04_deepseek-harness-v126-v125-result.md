# DeepSeek Harness v126 audit of the v125 bounded DinD readiness probe

Date: 2026-09-04

## Decision

The single authorized execution of
`deepseek-harness-hwe-v125-bounded-dind-readiness-probe-v1` is consumed and passed. The fresh
bind-backed DinD daemon became ready within the monotonic deadline and returned the exact frozen
identity: server version `23.0.6`, storage driver `vfs`, and default runtime `runc`. Outer controls,
image identity, absolute headroom, volume setup, and deterministic cleanup all passed.

This result establishes that a Docker data root backed by `/data2` can support the isolated DinD
transport needed by the successor scaffold. It also confirms that the v123 failure was a readiness
false positive rather than a ready-daemon identity mismatch. V125 itself did not read a task or
archive, materialize an image, run a verifier or Harness, start a model, access a registry, or cross
the provider boundary. Both migration conclusions remain false because no trajectory exists yet.

## Authorization and merge gates

- v124 result-audit commit: `00b4306acf48d1b14b54fa88a09c83e24c466c4d`
- v124 result-audit merge: `013154e899b4a0622dabf75f51d87a309d1b5b3b`
- v124 post-merge `main` run: `33826887799`, eight of eight jobs passed
- v125 implementation commit: `254644668f8b5f8d5e1597659b5227870d758f40`
- v125 authorization merge/source commit: `70cfa0393b3d2bfa06e26ca11fdccc09cde69d1f`
- v125 pull-request run: `33828737603`, eight of eight jobs passed
- v125 branch-push run: `33828717865`, eight of eight jobs passed
- v125 post-merge `main` run: `33829039148`, attempt 2 passed all eight jobs
- v125 manifest file SHA-256:
  `254f98645e8e30d8bed0a63909fb49ebc7d38744220b9dbdad251fb823d9d59e`
- v125 manifest canonical hash:
  `76de583642c6614d80a4b4bac1b95a4f2bd533e3be42a6b5caac3f9fd6ad07c0`
- v125 runner SHA-256:
  `25be8ceb93da732356034375972fa836c9d78373a45a553dd9166a7ccc2f613d`
- v125 authorization SHA-256:
  `78f58abc5e31567ada8500c47de4f22dfe129ddbe913a5229f2c02f0e2ab7634`
- merged campaign-model SHA-256:
  `a4141738bf94919f13055e5284b83e102489fe5e849e84f0602ad512f05dd297`
- v125 DeepSeek regression SHA-256:
  `db1d2890094758d2d244e3a33e848bf3ffd14db29f6b2e23028fae26b53e1e64`
- campaign-model regression SHA-256:
  `2d7587de302176445fac8dfb5e7ed0b5d432bdaf622fa7ae288de1965155f489`
- merged security policy SHA-256:
  `c079ab1a6149d42146cf856e7353b9c82122684b3143d06d32e58e258f7cbd08`

The first post-merge Docker job failed in an unrelated repository-agent fake-provider test. The
identical step had passed for the same source commit in both the pull-request and branch-push runs.
The failed job was rerun without source changes, and attempt 2 completed all eight job classes
successfully before v125 was invoked. The v125 identity was not consumed during the failed CI gate.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v125-bounded-dind-readiness-probe-v1`

It contains exactly one directory including the root, eight regular JSON files, and zero symlinks.
The root is mode `0700`; all files are mode `0600`. Every receipt self-hash validates, as does the
report self-hash. The report and atomic progress file are byte-for-byte equal.

| Evidence file | File SHA-256 | Canonical hash |
| --- | --- | --- |
| `cleanup-receipt.json` | `0006e7c1d66404aa48dd0b36a0a5bd446cfbd27a8995e15081047adc5fbe71af` | `3c6d805971c794b1c30c04c61f7a26b0a422e2f43c4d077c9e7d9532e2c3b1c8` |
| `headroom-preflight.json` | `6b4975525dd44695355f0cd07ef0061ef800b5e8a5911636537106c44f673b04` | `20aa1801f60fe36698dcb1f2e0a8517e969c2b76d1e189ecfe3f11163092e3b6` |
| `host-image-identity.json` | `8ebd2a52e7c0b907fddbb2a8dbff375910d1fcc212b33f2309f2d98f59097a99` | `99dbb43543c20b702213b5fe700eb942695146be6bc103479775d37c70e64678` |
| `predecessor-preflight.json` | `5cfc3ba33881b599c068a02d29a903ba4ab40c2c81fba8611f1a0d61dfd27d18` | `dbf54ae4d2a7d536ed2b52b35957e3e04dffbe26d8b1dd1f2b46094addc7bfc6` |
| `readiness-probe-progress.json` | `a168356b7289d1e306ef915835f6cf2c42d164b8317aa0d758fc98ee1f6a9976` | `6da2ba5dcff5aa424aea2bc1af02157c703fedd12fa6ae11897b3fad0ba9b7de` |
| `readiness-probe-receipt.json` | `b5102f595d1353ad12111cdf026c1c0d10434ba240d6d2204c688fd398820afc` | `23fc06716d775e4f132e30b8cc0fdf79e3c246f39f632b78f77703cd414160fc` |
| `readiness-probe-report.json` | `a168356b7289d1e306ef915835f6cf2c42d164b8317aa0d758fc98ee1f6a9976` | `6da2ba5dcff5aa424aea2bc1af02157c703fedd12fa6ae11897b3fad0ba9b7de` |
| `volume-setup-receipt.json` | `a0b52260aa6409229d3997bcd58301ee3d015c5756872fd5378264cbc21838eb` | `43c08c8d86321a45b92cec31a5d02b5108bab9323c210770158b587eb08b3250` |

The equal report/progress pair records:

- `status=completed_pending_independent_v126_audit`
- source commit `70cfa0393b3d2bfa06e26ca11fdccc09cde69d1f`
- post-merge run `33829039148`
- `startup_attempt_count=1` and `startup_attempt_limit=1`
- `diagnostic_complete=true`
- `diagnostic_category=dind_identity_qualified`
- `dind_identity_qualified=true`
- `cleanup_confirmed=true`
- `provider_request_started=false` and `provider_calls=0`
- `model_process_count=0`
- all task, base/reference, Harness-controller, registry, collection, and training start flags false
- no JSON-info readiness shortcut or fixed poll-count cap
- no raw Docker output, raw exception, host path, or container identity persisted or hashed

The headroom policy passed all four roles, observing 40,191,334,789,120 free bytes and 684,689,227
free inodes on `/data2`. The host image matched immutable image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`,
repository digest
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`,
and the official entrypoint.

## Readiness result

The bounded `docker run --detach` returned one immutable-ID-shaped result, exit zero, no stderr,
no timeout, and no truncation. The outer control inspection passed privileged mode, network
`none`, the frozen PID limit, empty TLS-directory setting, the two fresh v125 volumes, and the
read-only sentinel bind.

The explicit readiness loop made 16 calls before qualification. The successful call exited zero
without timeout, truncation, or stderr; stdout contained exactly three tab-separated values, and
all three equality checks passed for `23.0.6`, `vfs`, and `runc`. The receipt retains only the final
bounded byte counts, value count, equality booleans, and allowlisted category. It does not retain
the raw values or the transient responses.

Content-restricted host Docker events independently show one daemon create/start lifecycle, 16
matching explicit `docker info` exec lifecycles, controlled kill/die/destroy, and one cleanup-helper
create/start/die/destroy lifecycle. The daemon exited 137 because cleanup killed it; the cleanup
helper exited zero. No JSON-formatted info command occurred.

## Cleanup and isolation

The cleanup receipt passed. It records removal of the main container, cleanup helper, data volume,
and socket volume, followed by restoration of both backing directories. A post-run check found no
v125-labeled container and no registered v125 volume. The data, socket, control, and scratch
directories are empty, owned by UID 1004/GID 100, and mode `0700`.

The invocation removed all 12 forbidden provider environment names plus `DOCKER_HOST` and
`DOCKER_CONTEXT` for the child process. A post-run scan compared the four nonempty provider values
present in the parent process without printing, persisting, or hashing them: all eight evidence
files produced zero matches. Separate literal scans found zero evidence files containing `/data2`,
`/data/docker`, or `docker.sock`.

The frozen v118 volumes and every predecessor Docker volume were not inspected or mutated. The
user-owned downloader, VPN/proxy state, `.partial` files, shared `/data/docker`, and the unrelated
checkout were not changed. No registry or provider access occurred.

## Successor boundary

After this v126 audit is merged and the resulting `main` commit passes all eight Actions classes,
one new zero-provider five-task scaffold may be implemented under the fresh identity
`deepseek-harness-hwe-v127-readiness-gated-scaffold-v1`. Implementation alone does not authorize
its execution; its manifest, runner, tests, security policy, and authorization must first be merged
and pass another post-merge eight-class gate.

V127 must bind the exact v125 manifest, report, readiness, cleanup, source commit, and post-merge
run above. It must use entirely fresh v127 output, control, runtime, DinD data, DinD socket,
container, volume, and network identities under `/data2`. It may reuse audited code and immutable
locks, but may not reuse, inspect, repair, remove, or import any predecessor Docker volume or data.
The v125 explicit three-field readiness predicate, 120-second monotonic deadline, five-second
command limit, and no-smaller-poll-cap rule must gate every inner-Docker operation.

The atomic task order remains Ibex PR-465, PR-1135, PR-1780, then CVA6 PR-2017 and PR-2711. V127
may read only completed local archives and must verify every archive, OCI manifest/config,
repository base, source commit, image ID, task/source/image lock, and reference-patch compatibility
without registry access. Every task must independently demonstrate base-FAIL without an
infrastructure failure and reference-PASS. Task-specific credential-free command images must pass
the v2 scan, and all task and verifier containers must use `network=none`.

Runtime preparation and complete container/volume inventories must use the explicitly bound v127
inner socket, never host-side `docker exec ... docker`. Empty inner inventories are required after
each prepare and at final cleanup. Harness initialization may use only generated synthetic values
and a closed loopback port; no provider marker may be crossed. Any infrastructure, safety,
readiness, endpoint, inventory, task, verifier, or cleanup failure consumes v127 and publishes no
partial contract. A provider execution contract may be published atomically only after all five
tasks pass every zero-provider gate, and it still requires an independent v128 result audit before
any provider execution.

V125 must never be retried. No task or provider execution is authorized by this v126 audit itself.

## Closed policy

`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
