# DockerRuntime

Milestone 7 adds an optional, production-oriented Docker execution profile for the existing RTL
flows. Docker is selected only with `--runtime docker`; installation of Docker never changes the
default `local` runtime.

## Installation and reference image

The implementation uses the Docker CLI with argument arrays and `shell=False`. There is no Docker
Python dependency and therefore no separate Python `docker` extra. The base package installs and
imports without a Docker CLI, socket, or daemon:

```bash
pip install -e .
```

Docker execution additionally requires a compatible Linux Docker CLI and reachable Engine daemon.
Build the reference image explicitly from the repository root:

```bash
docker build \
  -f docker/iverilog12/Dockerfile \
  -t verigym/rtl-iverilog:12.0 \
  docker/iverilog12
```

The multi-stage image builds the real upstream Icarus `v12_0` tag and runs as fixed numeric
UID/GID `10001:10001`. The image name is not trusted as version evidence: VeriGym executes
`iverilog -V` and `vvp -V` inside the resolved image and records their actual output and the
adapter-derived compatibility label. The image is not signoff-quality EDA infrastructure.

`verigym run` never builds an image. The default pull policy is `never`; a user may explicitly
select `--docker-pull-policy if_missing`. Image building or an explicit pull may use the network,
but every episode command runs with `network=none`.

## Run, inspect, and replay

The literal toy AgentEval command is:

```bash
verigym run \
  --suite toy-rtl \
  --task counter-basic \
  --mode agent \
  --agent scripted \
  --runtime docker \
  --docker-image verigym/rtl-iverilog:12.0 \
  --output runs/
```

Inspect daemon capabilities and a local image without pulling or building it:

```bash
verigym doctor --docker-image verigym/rtl-iverilog:12.0
```

Replay validates stored artifacts without a model call. Verification replay inspects the exact
stored image ID and creates only a new verifier session:

```bash
verigym replay runs/<run-id> --verify
```

If the exact image ID is unavailable, the daemon is unreachable, or a mandatory control cannot be
verified, replay fails instead of substituting a mutable tag or falling back to `LocalRuntime`.
The original manifest and trace are not modified; replay verifier artifacts and its runtime
descriptor are written under `artifacts/replay-verification/`.

## Immutable identity

During run preparation, before a model invocation or agent action, DockerRuntime inspects the
requested tag or reference exactly once. It records the requested reference, immutable
`sha256:...` image ID, creation time when reported, OS/architecture, configured user, observed
UID/GID, Docker client/server/API versions, and repository digests when Docker reports them.
Locally built images commonly have no repository digest; the manifest stores `null` in that case
and never invents one.

Every diagnostic, agent, and verifier command in that run is created from the immutable image ID.
Each child resolves both role tags to exact IDs. Within one campaign process, successful
tool/version observations may be reused only from an in-memory cache keyed by immutable image,
backend, user, and executable identities; the recorded source distinguishes `fresh_probe` from
`in_process_immutable_cache`. Every episode container still undergoes its own effective-control
inspection. Aggregate regeneration rejects mixed runtime/image fingerprints as non-homogeneous.

A fresh preparation runs one combined, fixed identity command per role image. The verifier command
checks UID, GID, Icarus, VVP, and optional Verilator; the external-agent command checks UID, GID,
executable version and hash, plus repository-agent tool and launcher identities when required.
Fixed section markers and
an exact section inventory prevent ambiguous parsing. Combining checks reduces a verifier plus
repository-agent preparation from eleven container lifecycles to two without weakening any
identity comparison. Cache hits still require the newly inspected immutable image IDs and complete
cached observations to match.

### Non-interactive execution protocol

Non-interactive containers use three separate Docker operations: detached `start`, runtime-bound
`wait`, then bounded `logs`. Startup has its own control-plane deadline, so daemon scheduling time
does not consume the candidate command budget. On runtime timeout VeriGym kills the container,
waits for a terminal state under a separate cleanup deadline, and then collects bounded partial
logs. Results retain the protocol ID and per-phase durations. `start --attach --interactive`
remains only for the separately bounded external-agent stdio broker.

This design follows Docker's documented
[`start`](https://docs.docker.com/reference/cli/docker/container/start/),
[`wait`](https://docs.docker.com/reference/cli/docker/container/wait/), and
[`logs`](https://docs.docker.com/reference/cli/docker/container/logs/) primitives. The attached
Docker CLI implementation combines attach, start, stream teardown, and exit-status handling in one
control path, which is why it is not used for non-interactive timing. Related executable-gym
implementations informed the separation and timeout tests: the
[`SWE-bench` Docker harness](https://github.com/SWE-bench/SWE-bench/blob/main/swebench/harness/docker_utils.py)
uses an independently identified and timed exec process, while
[`R2E-Gym`](https://github.com/R2E-Gym/R2E-Gym/blob/main/src/r2egym/agenthub/runtime/docker.py)
separates detached container startup from bounded command execution.

## Isolation topology

DockerRuntime uses a private host-side session workspace and one short-lived constrained container
per command. It does not keep a mutable persistent container between commands.

The agent session contains only the materialized public workspace. File tools operate through the
same path policy, and compilation/simulation tools run in role-labeled Docker command containers.
On submission the session is frozen before the candidate hash and snapshot are created.

The verifier gets a second private workspace containing the frozen candidate plus only that task's
hidden inputs. It never receives the external benchmark checkout. Candidate and hidden files are
mode-read-only; only `.verigym_internal/` is writable for compiler output, simulator output such as
`wave.vcd`, and bounded build state. Hidden files are hashed before and after the verifier DAG.
Agent and verifier session IDs, writable storage, and command-container IDs are distinct, while all
ordinary RTL command sessions use the verifier image. Runtime-owned external agents use the
separate role image described below.

### Runtime-owned external agents

The optional Codex CLI Docker path uses separate agent and verifier image IDs. A host app-server
retains authentication and delegates all model-controlled shell, patch, and filesystem requests
to `codex exec-server` inside one episode container. The runtime, not the plugin, creates and owns
that process. Communication is a loopback-only WebSocket-to-container-stdio bridge; the container
itself remains `network=none`.

For the trusted host app-server only, the runtime preserves approved uppercase provider proxies
and synthesizes matching uppercase/lowercase bypass variables containing all loopback identities.
It rejects the launch if that bypass cannot be guaranteed. No proxy value is persisted or sent to
the agent container.

The agent image contains only the exact hash-bound Codex native executable and a minimal base
image. Runtime configuration overrides it to the current non-root host UID/GID so private
workspace cleanup remains verifiable. No `HOME`, Codex configuration, credential, proxy, source
checkout, hidden verifier, or Docker socket is mounted or copied. `/workspace` is the only bind
mount, and `/tmp` is the only other writable location. The inner execution label
`outer_runtime_delegated` is valid only inside this inspected outer boundary.

Replay removes the external-agent role configuration and can start only the exact stored verifier
image. It therefore cannot launch Codex or the stdio bridge.

## Configuration and defaults

Docker configuration is strict: unknown fields and unsafe values are rejected. The CLI exposes the
following run-level settings.

| Field / flag | Default | Semantics |
| --- | ---: | --- |
| `image` / `--docker-image` | required | Local tag, digest, or image ID resolved before execution |
| `pull_policy` / `--docker-pull-policy` | `never` | `if_missing` is the only explicit pull option |
| `network_mode` | `none` | No other network mode exists in Milestone 7 |
| `run_as_user` / `--docker-user` | image user | Must resolve to a non-root effective UID |
| `read_only_rootfs` | `true` | Cannot be disabled |
| `memory_bytes` / `--docker-memory-bytes` | 512 MiB | Real Docker memory limit |
| `cpus` / `--docker-cpus` | `1.0` | Docker CPU quota |
| `pids_limit` / `--docker-pids-limit` | `128` | Maximum container processes |
| `tmpfs_bytes` / `--docker-tmpfs-bytes` | 64 MiB | `/tmp` tmpfs size |
| `stop_timeout_s` / `--docker-stop-timeout-s` | `3` | Bounded container stop timeout |
| `max_command_time_s` / `--docker-max-command-time-s` | `60` | Site wall-time ceiling per command |
| `environment_allowlist` / `--docker-environment-allow` | empty | Repeatable, non-secret variable names |
| `max_artifact_file_bytes` | 16 MiB | Per-file declared-artifact ceiling |
| `max_artifact_bytes` | 64 MiB | Aggregate declared-artifact ceiling |

Task/command wall time and output limits may make execution stricter but cannot raise the runtime
ceiling. Memory swap is set equal to memory so swap cannot extend the memory budget; DockerRuntime
requires the daemon to report enforceable memory, swap, CPU, and PID controls. It verifies the
created container's memory, swap, NanoCPU, PID, tmpfs, stop-timeout, mount, environment, identity,
network, rootfs, capability, no-new-privileges, and init settings before start. A weaker effective
configuration fails closed.

The container environment is a fixed `PATH`, `HOME`, locale, and `TMPDIR` baseline plus explicitly
supplied allowlisted names. Host environment variables are not inherited. Secret-like variable
names are forbidden, and model credentials stay in the host-side model client.

## Results and failures

Host-side candidate wall time begins after detached startup succeeds, kills the short-lived command
container at its deadline, waits for terminal state, and preserves bounded partial output. A
timeout is recorded as `failure_reason=timeout` with `failure_origin=candidate_process` and the
effective limit. Startup, wait-cleanup, and log transport failures instead retain structured
control-plane subreasons. OOM is recorded only when Docker container state reports
`OOMKilled=true`; exit code 137 alone is not considered proof. The result includes the memory
limit, container role, exit code, phase timings, protocol ID, and Docker-state evidence.

Deterministic candidate compile, simulation, timeout, OOM, and output-limit outcomes remain
candidate failures when the tool marks them as candidate-controlled. Missing CLI/daemon/image,
permission denial, container create/start/inspect failure, parser/runtime faults, or a mandatory
control mismatch are infrastructure errors and retain `failure_origin=control_plane`. They are not
converted into ordinary wrong RTL or valid `pass@k` samples.

Wrong RTL keeps the established candidate-failure CLI exit behavior. Preparation and Docker
infrastructure failures use the existing runtime-infrastructure exit behavior. PPA and synthesis
remain explicitly `null`; Docker metadata is stored only in runtime/environment fields.

## Artifacts and cleanup

Only declared paths under `.verigym_internal/`, `build/`, or `artifacts/` can be collected from a
command workspace. VeriGym validates every path component with `lstat`, rejects traversal,
symlinks, unverified hard links, devices, sockets and FIFOs, enforces size limits, and hashes each
accepted regular file. The CLI backend uses a private bind mount and does not extract Docker tar
archives or copy container root filesystems.

Every container has exact VeriGym run/session/role ownership labels. Removal runs in `finally`
paths after success, candidate failure, timeout, OOM, policy or parser errors, replay, and
best-effort cancellation. Session and runtime close operations are idempotent. Cleanup warnings do
not hide a primary candidate failure. `verigym doctor` reports stale labeled containers/volumes but
Milestone 7 intentionally provides no destructive global janitor and never removes images.

## Tests

No-daemon unit tests run as part of the ordinary suite. Real Docker tests are opt-in:

```bash
VERIGYM_RUN_DOCKER_TESTS=1 \
VERIGYM_DOCKER_IMAGE=verigym/rtl-iverilog:12.0 \
pytest -m docker
```

Optional external VerilogEval V2 conformance uses the existing local checkout variable and never
downloads the benchmark:

```bash
VERIGYM_RUN_DOCKER_TESTS=1 \
VERIGYM_DOCKER_IMAGE=verigym/rtl-iverilog:12.0 \
VERIGYM_VERILOG_EVAL_ROOT=/path/to/verilog-eval \
pytest -m docker
```

DockerRuntime is Linux-first. Docker Desktop runs through a VM and may report different cgroup,
filesystem, UID/GID, networking, timing, and resource-accounting behavior; mandatory-control
verification still fails closed. Remote engines, Docker-in-Docker, automatic image builds,
automatic benchmark downloads, arbitrary mounts/devices, credential propagation, and commercial
tool licensing are outside Milestone 7. See [the security policy](../SECURITY.md) for trust
assumptions and residual risk.
