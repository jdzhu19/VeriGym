# VeriGym trusted rollout controller

This image contains only the audited VeriGym controller, the HWE-Bench adapter, the training
broker protocol, and a pinned Docker 19.03.14 client. It is the trusted parent of per-episode
benchmark sandboxes. The controller uses the node's Docker daemon to create sibling containers;
it does not run a nested privileged Docker daemon.

Only the controller receives `/var/run/docker.sock`. Model servers, trainers, OpenHands, provider
CLIs, and benchmark sandboxes must not receive that socket. The controller itself runs with no
network, a read-only root filesystem, dropped capabilities, no provider credentials, and no
general shell endpoint. Its Docker socket access is nevertheless host-equivalent authority, so
only the immutable audited image ID is accepted by the launcher.

Build with `scripts/build_rollout_controller_image.sh` using immutable RepoDigests for Python and
the Docker CLI stages. Run with `scripts/run_repository_rollout_controller.py`. The source and
scratch named volumes must be created and populated by the trusted control plane with these
labels:

```text
verigym.owner=rollout-controller
verigym.role=source|scratch
```

The scratch-volume root must be writable by the scheduler user's UID/GID. It is mounted at its
daemon-side absolute mountpoint inside the controller, so every temporary bind path passed to the
host daemon denotes the same object on both sides of the controller boundary.

Each HWE-Bench episode then selects its own digest-locked verifier image. Those child containers
retain `--network none`, resource limits, dropped capabilities, and deterministic cleanup. CPU-only
controllers and sandboxes can run on `bmcpu07`; a rollout needing a colocated GPU model can use
`gpu01` without changing this trust boundary.
