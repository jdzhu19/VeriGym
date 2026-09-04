# DeepSeek Harness v125 bounded DinD readiness-probe authorization

Date: 2026-09-04

## Decision

This change authorizes exactly one zero-provider execution of
`deepseek-harness-hwe-v125-bounded-dind-readiness-probe-v1` after the implementation is merged to
`origin/main` and that merge commit passes all eight Actions classes. It consumes the v124 audit's
narrow successor authorization and does not authorize a task, verifier, Harness controller, model,
registry request, or provider request.

V125 exists only to correct the v123 readiness false positive. It may create fresh bind-backed
Docker volumes whose data lives under its exact `/data2` identity, start one outer DinD container
with `network=none`, and wait for a clean explicit three-field identity response. It cannot inspect
or mutate any predecessor volume.

The runner imports the frozen v123 Docker primitives rather than changing the consumed v123 file.
It temporarily rebinds only the v125 owner and path constants around each primitive call and always
restores the original module values; tests cover both v125-only resource names and restoration.

## Frozen predecessor and gate

- v123 implementation commit: `753a533fe21d8dfcb05a8b110bde4f1ffb084719`
- v123 authorization merge: `2489465550af18c994e449eecc2bdd8ae142c5e6`
- v123 post-merge `main` run: `33825382724`, eight of eight jobs passed
- v123 manifest canonical hash:
  `8b921bdb5d24a65e69585a4e5c9e0c13a9e3bc32041ed5cb2fdb7c79fd98f45e`
- v123 report canonical hash:
  `35de7d238a423904aed7ac99da56c64190631a8966da3cd397db018bfd9cd8a0`
- v123 readiness-probe canonical hash:
  `56873a4bc385a167e9b909a45d239fab340e88bcdad5ed13583541e3ab1bf8ec`
- v123 cleanup canonical hash:
  `17d8bd3a1bb294e572d1cc790144770b2b8039cf5862b8793bf13fc1ce49b5e2`
- v124 audit commit: `00b4306acf48d1b14b54fa88a09c83e24c466c4d`
- v124 audit merge: `013154e899b4a0622dabf75f51d87a309d1b5b3b`
- v124 post-merge `main` run: `33826887799`, eight of eight jobs passed
- v124 audit SHA-256:
  `0a3a1afb47ad72b94f9d1acffd195a695a4e3036603599c20b670dde64450d46`
- v125 manifest canonical hash:
  `76de583642c6614d80a4b4bac1b95a4f2bd533e3be42a6b5caac3f9fd6ad07c0`

Execution requires clean synchronized `main`, the exact positive v125 post-merge main run ID, the
v125 opt-in set to `1`, all twelve provider environment names absent, and `DOCKER_HOST` and
`DOCKER_CONTEXT` absent. The manifest, runner, this authorization, campaign model, tests, and
security policy must already be tracked in the merged source commit. The identity is consumed by
its first authorized invocation and cannot be retried.

## Readiness predicate

The runner may start the immutable local `docker:23.0.6-dind` image once with privileged mode,
`network=none`, no bridge or iptables, the frozen PID limit, empty TLS directory setting, two fresh
v125 volumes, and a read-only sentinel. The host-image ID, repository digest, official entrypoint,
outer controls, bind options, ownership labels, and absolute `/data2` headroom must match before the
inner probe can qualify.

Each readiness iteration invokes only:

`docker info --format '{{.ServerVersion}}\t{{.Driver}}\t{{.DefaultRuntime}}'`

One iteration qualifies only if it exits zero without timeout or truncation, stderr is empty,
stdout parses to exactly three tab-separated values, and those values exactly equal `23.0.6`,
`vfs`, and `runc`. A clean complete three-value response that differs from the frozen identity
fails immediately. All other responses are transient until a monotonic 120-second deadline. Each
command is capped at five seconds and the loop waits at most one second between attempts. No
smaller fixed poll-count cap is permitted, and JSON-formatted `docker info` cannot establish
readiness.

The receipt keeps only bounded byte counts, exit/timeout/truncation facts, poll count, equality
booleans, and allowlisted categories. Raw stdout, stderr, exception text, output hashes, container
identities, host paths, and environment values are neither persisted nor hashed.

## Cleanup and closed boundary

Cleanup independently validates the exact v125 owner, role, and bind options before removing a
container or volume. It removes only fresh v125 resources and requires both backing directories to
be empty, owned by the invoking UID/GID, and mode `0700`. Ambiguous cleanup fails closed. The v118
frozen volumes and every v121/v123 predecessor resource remain outside the inspection and mutation
boundary.

No task archive, source tree, HWE image, base/reference verification, inner Docker network, Harness
controller, model process, registry, or provider is allowed. A successful v125 probe still cannot
publish a task contract; only a later independent v126 audit may decide whether to authorize a new
five-task zero-provider scaffold.

`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
