# DeepSeek Harness v71 isolated-DinD materialization authorization

Date: 2026-09-03

Status: **implementation authorization only**. After this change is merged and its post-merge
`main` run passes all eight required workflow classes, exactly one zero-provider execution may
materialize the inherited five-task schedule. This authorization does not permit a provider call,
formal collection, SFT export, training, production-readiness work, or any task substitution.

## Successor and predecessor boundary

V69 stopped before archive access, Docker image load, task qualification, or task consumption
because its control filesystem failed the absolute headroom gate. V70 independently sealed that
evidence. V71 is a new identity; it does not retry, resume, overwrite, reconstruct, or relabel v69.
It binds the v69 report file SHA-256
`f594fd8bc593150a4fd13c420f6e657937c78939a94739887cb069617aa1746a`, embedded report hash
`05c692d8bff1090d38cb33e76d71a7ff1662ff3ba98f84a4266d2f07d8da9e43`, v70 audit file SHA-256
`2db2114496251c46b2b51d06ec9ffeb5c9e83f53e408e6907ac9e9955761a73e`, and merged audit commit
`07141c1b8da2a8042ebee23653c830439730d63c`.

The inherited v69 task manifest retains content hash
`a20be68167d37e1acf68e1a9623a8dd5dcfaab973c0f6832d1238658af8f1d8b` and file SHA-256
`e5fb2dcf4578c27cbc121ccd00baa45d70a5c0cc0cba96999f83916721ce59be`. V71 reruns all five
patch checks and every subsequent qualification from their original completed local archives.
It neither reads `.partial` archives nor accesses a registry.

## Storage choice and isolation

The shared host daemon currently uses `/data/docker`; no ownership-safe attribution exists for its
large shared caches and images. Selective pruning would affect shared metadata and cannot guarantee
the required headroom. V71 therefore performs no prune or image deletion. It does not change the
host daemon configuration, restart Docker, alter VPN/proxy state, or start/stop the user-owned
downloader.

The already-local official `docker:23.0.6-dind` image is frozen as image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497` and repository digest
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`. Only this trusted
sidecar receives outer privilege. It has `network=none`, uses `vfs` and `runc`, has no host Docker
socket, and receives only a new v71 output root, an empty sentinel, a transient socket volume, and
the persistent data volume.

Both local-driver volumes have fixed names and exact owner/role labels. Their `type=none`,
`o=bind`, and `device` options are inspected. Inner Docker data is stored at
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v71/data`; the Unix socket is exposed through the
sibling `socket` directory. The host Docker root stores only the already-present sidecar image and
small volume/container metadata, not the five task images or derived command images.

No model-bearing controller is present in this stage. The trusted non-root host materializer
rejects all recognized provider configuration, `DOCKER_HOST`, and `DOCKER_CONTEXT` inputs. It
temporarily routes only the offline Docker operations to the new nested socket, then restores the
host connection before cleanup. Inner task and verifier containers remain networkless with their
normal capability, privilege, seccomp, PID, memory, and CPU controls.

## Atomic publication and stop policy

The runner first validates the stopped predecessor, frozen manifests/tools, clean merged main, and
all five patch shapes. It creates a new output and new bind backings, applies the existing absolute
headroom policy to `/`, the actual `/data2` Docker backing, scratch, and output filesystems, and
only then starts DinD. Each task must independently satisfy archive/config/repository/source locks,
base-FAIL without infrastructure error, reference-PASS, official verifier `network=none`, exact
tool inventory, and the command-image v2 security scan.

Progress remains non-authoritative. `provider-contract.json` is written last and only after all
five tasks finish in the inherited order, the inner container/volume inventory is empty, the
sidecar is removed, the socket volume is removed, the socket backing is empty, and the persistent
data volume still resolves to the frozen `/data2` directory. Any failure seals
`stopped_without_provider_contract`; partial task completion never grants partial authorization.

A completed v71 contract still sets `provider_execution_authorized=false` and requires the new v72
audit to merge and pass post-merge checks. The official DeepSeek model matrix therefore moves to a
new identity after v72, followed by separately versioned open-tool and VCS stages.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
