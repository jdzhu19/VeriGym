# DeepSeek Harness v121 bounded DinD startup diagnostic authorization

Date: 2026-09-04

## Decision

Authorize exactly one invocation of
`deepseek-harness-hwe-v121-bounded-dind-start-diagnostic-v1` after this implementation is merged
to `origin/main` and that merge commit passes all eight Actions classes. This is a zero-provider,
diagnostic-only successor to the consumed v118 scaffold. It is not a v118 retry and does not
authorize a task, Harness controller, trajectory, collection, or training run.

The v121 invocation may validate the exact v118 terminal evidence and v119 audit, apply the
existing absolute headroom policy to new `/data2` roots, inspect the already-local immutable DinD
image, create the two exact fresh v121 bind-backed volumes, make one bounded outer-DinD startup
attempt, retain a content-free diagnostic classification, and clean only v121 resources. No
registry access is authorized.

## Required predecessor gate

- v118 authorization merge: `928b117882ae8be4c60520f8d4a49d82edc548b8`
- v118 post-merge `main` run: `33819300080`, eight of eight jobs passed
- v118 manifest SHA-256:
  `71489c93e226c2f9b74d9e972f788e251b6c5604665c115debc1b7f69fd8f16c`
- v118 manifest canonical hash:
  `c646f65d13b19096cf46ed4a9e3ab24a79c94382cd1d1ea9ab36c36c667bf72d`
- v118 terminal report/progress SHA-256:
  `353874efff13292fd075e339dd05eec35d45747d0f9eac5057a7ac7fb0ec7565`
- v118 terminal report canonical hash:
  `6e40aa486c9949883cdfe5a253fb99eff5bb671de67d6ab687a2ba72d422fd0f`
- v119 audit SHA-256:
  `9b161db96c25c78cded25ceaf3ff3dd35fa191a6d25d38fbea873777bffdb9a1`
- v119 audit merge: `c22066916ba51e8c74678be2b0af6ac8d438ac9a`
- v119 post-merge `main` run: `33820413201`, eight of eight jobs passed
- v121 manifest canonical hash:
  `15d13190598d9ce0edc433074e807165192395532e2cd398f7b4a850e905cb5b`

Execution requires a clean, synchronized `main`, an exact positive v121 post-merge main run ID,
the checked-in opt-in environment name set to `1`, all twelve provider environment names absent,
and both `DOCKER_HOST` and `DOCKER_CONTEXT` absent. The Docker CLI child environment is restricted
to the fixed locale and executable search path by the shared bounded engine transport.

## Diagnostic boundary

The single startup call is bounded to 60 seconds and the readiness phase to 120 seconds. Each
Docker control response is capped at 65,536 bytes. Receipts may contain only exit status, timeout
and truncation flags, byte counts, validated booleans, and an allowlisted category. Raw stdout,
raw stderr, their hashes, container IDs, generated container names, environment values, and host
paths are prohibited from diagnostic receipts.

The startup sidecar uses the already-local immutable DinD image, `network=none`, the `vfs` storage
driver, no bridge or iptables, a fixed PID limit, an empty TLS-certificate setting, the two fresh
v121 volumes, and one empty read-only sentinel directory. It receives no repository, task,
archive, verifier, Harness, credential, Docker socket, proxy, or unrelated experiment mount.

No task archive may be opened. No command image may be built or imported. No base/reference
verification, inner network, Harness process, model process, or provider request may start.

## Cleanup boundary

Cleanup first resolves and force-removes the generated v121 main container if it exists. A
separately bounded, network-none, read-only-root helper may empty and restore ownership of only
the two v121 backing directories. If its `docker run --rm` fails after container creation, the
helper is independently inspected and force-removed. Data- and socket-volume removal and absence
checks occur independently of the helper result.

Success requires the main and helper containers absent, both Docker volumes absent, both backing
directories empty and restored to the invoking non-root UID/GID at mode `0700`, and a passed
cleanup receipt. Any unconfirmed cleanup remains an explicit failure and freezes the remaining
v121 resources for audit; it does not authorize sudo repair or a retry.

The v118 data and socket volumes are immutable evidence. V121 may not inspect, mount, remove,
repair, reopen, or otherwise mutate them or their backing directories. It also may not touch the
user-owned downloader, `.partial` archives, VPN/proxy configuration, `/data/docker`, or the
unrelated `/data/jzhu484/Agent/VeriGym` checkout.

## Result boundary

The v121 identity is consumed by its first authorized invocation whether startup succeeds or
fails. A sanitized, bounded receipt plus confirmed cleanup counts as a completed diagnostic even
when the DinD startup category is a failure. A separate v122 audit must validate the complete
evidence tree, the absence of provider and raw diagnostic values, Docker events, and cleanup
state. Only that audit may propose a new five-task scaffold identity.

V121 cannot authorize or publish a provider contract. Both migration conclusions remain false,
and all candidate-SFT lists remain unchanged.

## Closed policy

`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
