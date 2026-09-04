# DeepSeek Harness v123 bounded DinD identity-probe authorization

Date: 2026-09-04

## Decision

Authorize exactly one invocation of
`deepseek-harness-hwe-v123-bounded-dind-identity-probe-v1` after this implementation is merged to
`origin/main` and that merge commit passes all eight Actions classes. This is the narrow
zero-provider successor authorized by the v122 audit. It is not a v121 retry and cannot run a
task, verifier, Harness controller, model, collection, or training process.

V123 may validate the immutable v121 evidence and v122 audit, apply the absolute headroom policy
to fresh `/data2` paths, inspect the already-local immutable DinD image, create two fresh v123
bind-backed volumes, make one bounded DinD startup attempt, run the three authorized identity
probes, and clean only v123 resources. No network or registry access is authorized.

## Required predecessor gate

- v121 authorization merge: `0cc0f14af875ade980a2f9914d63a8d51c8a9730`
- v121 post-merge `main` run: `33822511727`, eight of eight jobs passed
- v121 manifest SHA-256:
  `900887d09c9784b790926bee036e618f9d2ca38d1bab88fe8b995a73b4417bcc`
- v121 manifest canonical hash:
  `15d13190598d9ce0edc433074e807165192395532e2cd398f7b4a850e905cb5b`
- v121 terminal report/progress SHA-256:
  `7116954eaa1bc814cfa158b0ac27c8ec336e9af4622c7bbba66f96d5d5db7619`
- v121 terminal report canonical hash:
  `3f6a0aafbac59171a10de28729b1553deecf08a344b6bf420c81d62cacaa1d6d`
- v121 startup receipt SHA-256:
  `2d4bc1cb0dd94f6e0f5d8012d40aecccef2e41ea545ae28f763c9001d2ce783f`
- v121 cleanup receipt SHA-256:
  `7b578767fd92a48d0909fed938859f5e8d176b942d1dfa3ae7a54695d5aa3ee3`
- v122 audit SHA-256:
  `1542c983392d914a65fa9f59680c5d8a3ddcfbaef670f7e75e51263ebfae1620`
- v122 audit merge: `34a2854afcaa64a6de8a0fbca94ffd50dbb168db`
- v122 post-merge `main` run: `33823592366`, eight of eight jobs passed
- v123 manifest canonical hash:
  `8b921bdb5d24a65e69585a4e5c9e0c13a9e3bc32041ed5cb2fdb7c79fd98f45e`

Execution requires clean synchronized `main`, an exact positive v123 post-merge main run ID, the
v123 opt-in set to `1`, all twelve provider environment names absent, and `DOCKER_HOST` and
`DOCKER_CONTEXT` absent. Docker CLI children inherit only the bounded transport's fixed locale and
executable search path.

## Probe boundary

V123 has one 60-second startup attempt, at most 120 seconds of readiness polling, 30 seconds per
identity command, and 65,536 bytes per Docker response. It first repeats JSON-formatted `docker
info` readiness and records only presence/equality booleans for `ServerVersion`, `Driver`, and
`DefaultRuntime`. It then runs one explicit tab-delimited `docker info` formatter for those three
fields. Only three exact values matching `23.0.6`, `vfs`, and `runc` qualify the identity.

The legacy `docker version --format {{.Server.Version}}` command runs once only to classify the
v121 observation. Its result cannot veto an exact explicit-info identity. Its outcome is reduced
to success, timeout, output-bound, formatter, daemon-connect, API-negotiation, or other-command
failure. Raw stdout, stderr, output hashes, exception text, container IDs/names, environment
values, and host paths are prohibited from receipts.

The daemon uses immutable image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`,
repository digest
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`,
the `vfs` driver, `network=none`, no bridge or iptables, a fixed PID limit, and only the two fresh
v123 volumes plus an empty read-only sentinel. It receives no task, repository, archive, verifier,
Harness, credential, proxy, Docker socket, or unrelated experiment mount.

## Cleanup and result boundary

Cleanup may remove a container or volume only after validating its exact v123 owner/role and bind
identity. The networkless, read-only cleanup helper has only `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`.
Data and socket volume removal is independent of helper success. A passed cleanup requires all
v123 containers and volumes absent and both backing directories empty, owned by the invoking
UID/GID, and mode `0700`. Ambiguity fails closed and freezes remaining v123 resources for audit.

The v123 identity is consumed by its first authorized invocation and cannot be retried. It may not
inspect, mount, reuse, or mutate a predecessor volume or backing directory. It also may not touch
the user-owned downloader, `.partial` files, VPN/proxy state, `/data/docker`, or the unrelated
`/data/jzhu484/Agent/VeriGym` checkout.

A separate v124 audit must validate the complete evidence, Docker event sequence, provider-value
scan, and cleanup state. Only v124 may decide whether an exact v123 result permits a new five-task
zero-provider scaffold. V123 itself publishes no provider contract.

## Closed policy

`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
