# DeepSeek Harness v118 explicit inner-inventory scaffold authorization

Date: 2026-09-04

## Decision

Authorize exactly one zero-provider execution of
`deepseek-harness-hwe-v118-explicit-inner-inventory-scaffold-v1`, and only after this
implementation is merged and the resulting `main` commit passes all eight required Actions jobs.
This is not an authorization for a provider request, formal collection, training, registry access,
partial archives, reuse of predecessor Docker data, or mutation of `/data/docker`.

V118 retains every v115 and v112 archive, OCI, source, task, verifier, security, headroom,
fresh-materialization, cleanup, and zero-provider gate. It narrowly repairs the v115 transport
direction error. Runtime preparation and both all-resource inventory queries now use a
`DockerCliEngine` explicitly bound to:

`unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v118/socket/docker.sock`

The inner inventory is obtained with `docker ps --all --quiet` and `docker volume ls --quiet`
through that endpoint. Host-side `docker exec <outer-sidecar> docker ...` is forbidden for this
check. The same centralized sanitized Docker environment is used for ordinary CLI calls and
streaming attach; inherited Docker endpoints, contexts, arbitrary environment values, remote
transports, and ambiguous sockets remain forbidden.

## Predecessor and merge gates

- v115 authorization merge: `48bc47f0dbb020e41f330bf5350bad621d01df1c`
- v115 post-merge `main` run: `33812788683`, eight of eight jobs passed
- v115 result-audit merge: `7faf47a4ba49139bf9e93200e104b8b9e9cbfea2`
- v116 post-merge `main` run: `33815411217`, eight of eight jobs passed
- v115 manifest canonical hash:
  `d851e4c0b2831865161f5ada6bf217d1df115dde03303925fece17e63fd4202c`
- v115 report canonical hash:
  `2116016b0b27d1ad4993a0694609194e2edc7ca7a39043e823e06c0d35b6e168`
- v118 manifest canonical hash:
  `c646f65d13b19096cf46ed4a9e3ab24a79c94382cd1d1ea9ab36c36c667bf72d`

The runner must execute from clean synchronized `main`. All required v118 implementation, test,
and authorization paths must already be tracked in that commit. `--post-merge-main-run-id` must
identify the successful post-merge workflow for that exact commit. Branch and pre-merge execution
are forbidden.

## Fresh storage and isolation

The only new writable roots are:

- evidence:
  `/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v118-explicit-inner-inventory-scaffold-v1`
- DinD data: `/data2/jiadongzhu/docker/deepseek-harness-hwe-v118/data`
- DinD socket: `/data2/jiadongzhu/docker/deepseek-harness-hwe-v118/socket`
- control scratch:
  `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v118-control`
- runtime scratch:
  `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v118-runtime`

All must start empty under `/data2`. The v115 data directory remains frozen and may only be
checked as a directory; it must not be traversed, opened, imported, reused, deleted, or modified.
The v115 socket, control, and runtime paths must remain empty. Frozen v115 evidence may only be
read to validate exact audit bindings.

The existing image downloader stays user-owned. V118 may not start a registry download, change
VPN or proxy state, consume `.partial` data, change
`/data/jzhu484/Agent/VeriGym`, or delete anything from `/data/docker`.

## Execution and successor boundary

The invocation must unset every provider-related name enforced by the runner and set only the
v118 opt-in variable. Harness initialization uses generated synthetic values and a closed loopback
port; these values must not cross the provider marker or persist in evidence. Task and verifier
containers remain `network=none`; the internal preflight network is removed before publication.

Any infrastructure, safety, endpoint, inventory, qualification, or cleanup failure consumes the
single v118 identity without retry and without a partial contract. Success requires five fresh
base-FAIL/non-infrastructure-failure and reference-PASS materializations, v2 command-image scans,
explicitly bound runtime preparation, empty all-resource inventory after every prepare, isolated
Harness initialization, final inventory, and cleanup.

Even on success, provider execution remains closed until an independent v119 result audit is
merged and its post-merge `main` workflow passes all eight jobs. V117 is retired unused. A future
provider matrix must use the distinct v120 identity and separately supplied ephemeral credentials.

The following remain false: `formal_collection_allowed`, `formal_collection_started`,
`collection_started`, `training_started`, and `production_training_ready`.
