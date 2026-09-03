# DeepSeek Harness v72 audit of the v71 DinD materialization stop

Date: 2026-09-03

Status: **frozen pre-provider infrastructure failure**. V71 may not be retried, resumed,
reconstructed, or relabelled. No provider episode, formal collection, SFT export, training, or
production-readiness work started.

## Authorization and execution boundary

The v71 implementation was merged through PR #108. Its only authorized execution used exact clean
tracked `main` commit `6d91f0b45290ef604859d35740eb44e622498649`. Post-merge `main` Actions run
`33714732606` passed all eight required job classes before invocation.

The output root, DinD backing root, and both fixed outer volumes did not exist before invocation.
Recognized DeepSeek, OpenAI, Anthropic, and VeriGym provider variables plus `DOCKER_HOST` and
`DOCKER_CONTEXT` were removed from the child environment without printing, persisting, or hashing
their values. The command ran exactly once. It did not change Docker daemon configuration, restart
Docker, alter VPN/proxy state, start or stop the user-owned image downloader, access a registry,
read a `.partial` archive, prune a cache, or delete a shared `/data/docker` image.

## Passed boundaries

All five inherited tasks again passed the reference-patch metadata compatibility preflight. The
content-free headroom gate passed all four roles:

| Role | Minimum bytes | Observed bytes | Minimum inodes | Observed inodes |
| --- | ---: | ---: | ---: | ---: |
| `control_root` | 4,294,967,296 | 9,400,119,296 | 100,000 | 18,377,617 |
| `docker_root` | 103,079,215,104 | 41,945,153,744,896 | 250,000 | 717,255,113 |
| `scratch_root` | 8,589,934,592 | 41,945,153,744,896 | 50,000 | 717,255,113 |
| `output_parent` | 2,147,483,648 | 41,945,153,744,896 | 10,000 | 717,255,113 |

The `docker_root` observation was the exact new backing directory
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v71/data`, not the host daemon root. Its preflight
hash is `563fee678c28b9079789e2adce22f600bd839674bd071b9bcf00d31ffdfccbf2`.

The frozen Docker sidecar matched image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`, repository digest
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`, server 23.0.6,
`vfs`, and `runc`. It had `network=none`, no host Docker socket, and only the fixed data/socket,
output, and sentinel mounts. Docker volume inspection confirmed local-driver `device` equals the
exact `/data2` data backing. Runtime receipt hash:
`d6e821e087f1cbf85023d1383e04588d3c792e77a8d986b0f5862becbe418bc9`.

PR-465 then passed its full completed-archive binding and official zero-model qualification:
base failed without infrastructure error and the reference passed. The archive receipt file
SHA-256 is `21d5ae1c122d933237f3d5d1e27b18a5656509eeb6873f820dba60845d5d4516`; the smoke report file
SHA-256 is `f31aef682ef74774205da019fefa70327f13af028e00b4a88038432c49b70f0e`.

Its task-specific command-image build also reached its final sanitized receipt. The receipt records
`build_network=none`, `codex_present=false`, official toolchain profile
`ibex-verilator-system-container-native-v1`, derived image ID
`sha256:2b287e33adf103f2c0bc20c1727d783a1a59118df418c15d0995f83c497cfe1a`, and file SHA-256
`6139769eaa812158ea76f1858897b427b980f5d2413f7015bbdffd3a9a3cda6f`.

## Stop and cleanup findings

Immediately after the build receipt was written, the inherited v69 bounded-command helper raised
`ConfigurationError`. Because the shell writes that receipt only after the build and sanitizer
finish, the evidence establishes successful artifact publication followed by a rejection in the
helper's exit/output boundary or its final shell cleanup. Raw stdout/stderr was not persisted, so
v72 does not narrow the cause beyond that evidence. The command-image security scan, image lock,
task receipt, and all later tasks were never reached.

The exception path removed the privileged sidecar and the transient socket volume, but it did not
empty the bind backing first. Dockerd socket, PID, and runtime-directory entries remained. The v71
report nevertheless recorded `dind_cleanup_confirmed=true`; that field is contradicted by the
post-run filesystem inspection and is not trusted. This independent mismatch alone makes v71
infrastructure/security invalid.

After freezing the evidence, a separate networkless, read-only-root cleanup container mounted only
the exact v71 socket directory. The first least-capability cleanup lacked directory traversal
permission and failed closed. A second invocation added only `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`,
removed the known v71 socket/PID/runtime entries, restored the directory to mode `0700` and
UID:GID `1004:100`, and removed itself. The socket directory is now empty; no v71 sidecar or socket
volume remains. This remediation does not rewrite or validate the stopped v71 result.

The persistent v71 data volume remains labeled and bound to its `/data2` path. It was not deleted,
pruned, reopened, or reused. Because its post-failure inner runtime inventory was not independently
revalidated, a successor must use a new data volume and new backing directory.

## Frozen evidence and disposition

The external evidence root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v71-dind-zero-provider-successor-v1`.

- `zero-provider-report.json` and `materialization-progress.json`: file SHA-256
  `486f486fc730e6b58767c9b8bcfa460afead5f0834ce1750895b0bb7b83b50ab`; embedded report hash
  `4f12e20da48abc2ffce048194519c8afb3c973796ed60e661c245815b0dc47c8`.
- `headroom-preflight.json`: file SHA-256
  `3c876c94a4304a95b141baf5adc4caab6a222f40eeff45b0a8c424b8e25e837c`.
- `dind-runtime-receipt.json`: file SHA-256
  `3c8dc5c9ca1329955ed1fc65b24239d0ba8be9ccfe2e34da1e83aa6016364574`.
- PR-465 source-image lock: file SHA-256
  `9f2b2f43e3577f418f0e5bcf24cdaac0960e40d324a0330611c92fbfda66d87a`.

The report is sealed as `stopped_without_provider_contract`, with zero completed task IDs, zero
provider calls, zero model processes, and `provider_contract_published=false`. The provider
contract file is absent. This is not a verifier rejection, model behavior result, trajectory,
HWE-Bench score, or SFT-admission result.

A future materializer requires a separately reviewed successor identity. It must use new `/data2`
data/socket backings, persist content-free bounded-command byte/digest/exit diagnostics before
classifying successful nonempty output, clear and inspect the socket backing before removing its
volume, and never claim cleanup from outer resource removal alone. The five tasks remain
provider-unconsumed because no provider boundary was crossed.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
