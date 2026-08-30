# OpenHands v30 provider canary stopped during zero-call Docker preflight

## Result

The one authorized execution of `openhands-hwe-v30-v19-provider-canary-v1` stopped fail closed
during the PR-2330 Docker image preflight. No provider episode started, no provider request was
sent, and neither scheduled task was attempted. The PR-3204 validation episode was therefore not
reached.

The authorization merged as PR #36 at commit
`abbcf2e2192d6cbb806a0be1bfc210984c1ab7ff` after all 16 push/PR results for the eight required
Actions classes passed. The run used that exact merged commit and wrote its immutable evidence to
`/data/jzhu484/Agent/experiments/openhands-hwe-v30-v19-provider-canary-v1`.

The final report records:

- `status=stopped_infrastructure_invalid` and
  `failure_reason=zero_call_preflight:DockerImageError`;
- zero provider episodes, provider calls, retries, and task attempts;
- an empty held-out task list and no remaining reserve consumption;
- `canary_passed=false`, `formal_collection_allowed=false`,
  `production_training_ready=false`, and `benchmark_score_claimed=false`; and
- collection and training never started.

This is an infrastructure-invalid canary result, not a benchmark rejection and not a trajectory
result. The v30 identity is sealed and is not eligible for an automatic retry.

## Artifact chain

The report and progress copies are byte-identical. Their file SHA-256 is
`68df4079a1a12e278f596b481282c9d6128ac7f1a5b125acafcf5dbfd175e017`; their embedded canonical
report hash is `da246599e8f2a0553d54771fa0f8f6e15a7167f9290c07bac23533f81144bb76` and recomputes exactly.

The remaining artifact identities are:

- `agent-version.json`: file SHA-256
  `2929dc9186287a9f0df6862dc30b15c616e933e77c34cc5e3849e623f0c688b9`, validated version hash
  `266dd78365925344d4c8efc92f531bab5ad6ab02fd95f5a1d5e3fa7c8c28db1a`;
- `contract-receipt.json`: file SHA-256
  `f827cd89a1adfea92110f5b24b4ca1d88c6ac83ede040059260bfdd97fcdb8f8`, canonical receipt hash
  `0a4eadb954b4394a5981911f90c8cb96fd27783e99bb20d4f509afa0e531f1b6`; and
- complete four-file evidence directory hash
  `4d7a609a887666ded3b77bebd2bd5d9342959f0c70a07cc58e84297dd66a39a1`.

An independent in-memory post-run scan checked all four files and 8,981 bytes, including the
active provider endpoint, provider credential, and proxy values without persisting or hashing
those private values. It found zero hard secret leaks and zero scanner errors. The scan report
hash is `6a938a54ff3f4594fa642d20db2669ddc6e8738d89e721dbc6c508d7c3851296`.

No v30-managed preflight container remains.

## Failure reconstruction

The sealed report intentionally retained only the exception class. The more precise classification
below is an offline reconstruction from the deterministic preflight command order, immutable image
identity, Docker's label-filtered event stream, and the runtime implementation; it is not a field
retrofitted into the v30 artifact.

All four workspace-image health containers exited zero. For the PR-2330 agent image, the `id -u`,
`id -g`, and `codex --version` containers also exited zero. The fourth and final command in the
fixed agent-image sequence was the Codex executable SHA-256 check. Docker recorded its attach at
11:45:15.056 +08:00, start at 11:45:20.492, and exit zero at 11:46:16.510. The engine applies a
60-second timeout to `docker start --attach`, measured before the daemon's start event; crossing
that boundary marks the command timed out even when the subsequent container inspection reports
exit zero. The health gate then raises `DockerImageError` with the reconstructed structured class
`agent_image_health_failed`, command `external-agent executable SHA-256`, and failure reason
`timeout`.

A separate post-stop diagnostic used the same content-addressed agent image with `network=none`,
a read-only root, non-root UID/GID, cap-drop `ALL`, no-new-privileges, bounded resources, no task
source, and no provider environment. `codex --version` returned the locked `codex-cli 0.147.0` in
19.13 seconds, and SHA-256 returned the locked
`cb0a15567e9a60a5820d54b0f6ae86d504dc3805c1eab21a47f70e3eb7b73a40` in 21.82 seconds. This
supports transient Docker control/attach or host-I/O latency rather than an image-version or
binary-identity mismatch. It does not turn the stopped preflight into a pass.

Docker documents the label/time filtering used for this reconstruction in
[`docker system events`](https://docs.docker.com/reference/cli/docker/system/events/), notes that
an attached client can appear hung and that the attach path has its own buffering behavior in
[`docker container attach`](https://docs.docker.com/reference/cli/docker/container/attach/), and
recommends daemon logs for deeper diagnosis in
[`Read the daemon logs`](https://docs.docker.com/engine/daemon/logs/). The upstream Moby report
[#41827](https://github.com/moby/moby/issues/41827) is relevant evidence that attach-stream state
can block Docker operations, but it does not establish that its high-output reproduction caused
this low-output v30 event.

## Diagnostic limitation and next gate

The runner's broad zero-call preflight handler reduced every exception to its Python type. That
made the stop safe but needlessly slowed diagnosis. A separately reviewed successor should:

1. persist only sanitized, allowlisted `DockerRuntimeError` fields (`origin`, `subreason`, command,
   timeout, OOM, truncation, and exit code) plus a preflight stage identifier;
2. distinguish Docker CLI/attach elapsed time from actual container execution time, preferably via
   bounded start, wait, inspect, and log operations or equivalent event-aware accounting;
3. reduce repeated container lifecycle work for immutable image probes while preserving the
   image-ID, executable-hash, label, non-root, toolchain, and isolation gates; and
4. add regressions for an attach timeout followed by exit zero and for artifact redaction.

Increasing the timeout alone would blur control-plane delay with candidate-process execution and
is not a sufficient repair. This audit authorizes no successor identity, provider retry, formal
collection, SFT, GPU work, or held-out access. A new repair/authorization PR and all eight checks
are required before any further provider canary can be considered.
