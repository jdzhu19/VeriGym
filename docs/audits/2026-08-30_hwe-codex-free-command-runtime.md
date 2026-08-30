# HWE Codex-free command runtime

Date: 2026-08-30

## Outcome

VeriGym now has a separately identified HWE `command_image` role that does not require Codex CLI,
Codex authentication, or a provider client. Historical v1/v2 agent-image locks and the frozen v19
campaign path are unchanged. A successor OpenHands configuration can choose either the compatible
short-lived-container backend or the new fail-closed episode-container backend.

This change does not start provider collection, admit a trajectory, train an adapter, run held-out
evaluation, or alter any existing campaign result.

## Why this design

The prior OpenHands shell path invoked `/bin/bash -lc` by overriding the image command, so the
bundled `codex exec-server` was not involved. The remaining Codex coupling was in the runtime
schema, image probe, image build, and lock format. The new role separates those concerns instead of
representing a command toolchain as an external coding-agent process.

The episode backend follows the common long-lived-container/exec shape used by
[SWE-bench's Docker harness](https://github.com/SWE-bench/SWE-bench/blob/main/swebench/harness/docker_utils.py)
and
[R2E-Gym's Docker runtime](https://github.com/R2E-Gym/R2E-Gym/blob/main/src/r2egym/agenthub/runtime/docker.py).
The separation between an agent control plane and a runtime action-execution service is also
consistent with the
[OpenHands runtime architecture](https://github.com/OpenHands/docs/blob/main/openhands/usage/architecture/runtime.mdx).
VeriGym adds stricter per-command process-inventory and poison-on-failure behavior because HWE
trajectory collection treats generated commands as untrusted.

## Image and supply-chain evidence

- Task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2330`.
- Verifier base: `sha256:bd04dfaa28bf30b408365e26b31bc829a2d3c729e3ea5321522289c583b1dcf9`.
- Command image: `sha256:3ba2d622fbec6891484c8529892be39db33e02127ec9aaec80381b7d87e64540`.
- ripgrep: official 15.2.0 x86-64 musl release, archive SHA-256
  `33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c`, binary SHA-256
  `e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849`.
- Command-image lock:
  `08afa638de63002bc9431905d264f879f1fd98753927b479b48db1e7ad9d6314`.
- Security scan:
  `a314c296bb25ca69b9d5c702b64ce7e976ee78c6d0738110b179bf3c80dfedb8`.

The official binary happens to match the binary bundled by the installed Codex package, but it was
downloaded independently from the signed upstream ripgrep release and is bound to the upstream
archive digest. Neither the npm package nor a Codex path is an input to the new image build. The
downloaded archive and image/run artifacts remain outside Git under the repository's dataset and
experiment roots.

## Zero-model runtime evidence

The real Docker smoke executed two commands successfully in one episode container. The second
command reported reuse, both commands used the same container identity, the external-process
backend was unavailable, and cleanup completed with no warning.

A fixed three-command local A/B on the same command image measured:

| Backend | Command wall time | Containers | Per-command durations |
| --- | ---: | ---: | --- |
| `ephemeral_container_v1` | 32.487234 s | 3 | 10.511522, 11.089385, 10.789982 s |
| `episode_container_exec_v1` | 7.571901 s | 1 | 7.347838, 0.111860, 0.111867 s |

The observed command-stage ratio was 4.2905× on the current Docker daemon. This is a local
engineering measurement, not a benchmark score and not a prediction of model-quality improvement.
Both backend preparations took about 21.45 seconds, so the benefit grows with shell-command count.

The real residual-process smoke launched a redirected background `sleep`. VeriGym detected an
inventory change from two to three processes, returned `residual_process_detected`, destroyed the
container, persisted no raw process data, rejected the next command as
`episode_container_poisoned`, and completed cleanup without warnings.

## Remaining gate

The new backend is implemented and zero-model validated, but no new collection identity is yet
authorized. A successor campaign must bind the new command-image locks and execution backend,
repeat the ordinary credential-free test and security gates, and pass its own provider canary
before collecting a new trajectory. Existing v19 records cannot be relabeled or migrated.
