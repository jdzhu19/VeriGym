# DeepSeek Harness v152 host-headroom scaffold authorization

Date: 2026-09-05

## Decision

This change authorizes exactly one zero-provider execution of
`deepseek-harness-hwe-v152-host-headroom-scaffold-v1`, and only after this implementation is
merged to `origin/main` and that merge commit passes all eight Actions classes. It implements the
narrow prerequisite required by the merged v151 audit after v150 stopped at the host containerd
shim with `no space left on device`.

V152 may measure host-root byte and inode headroom, inspect the already-local immutable DinD image,
create two fresh bind-backed volumes under its exact `/data2` identity, start one networkless DinD
sidecar, establish exact readiness, confirm empty mutable inner inventories, and remove all v152
Docker resources. It does not authorize a task image, HWE archive, verifier, Harness controller,
model process, registry request, provider request, collection, or training.

## Frozen predecessor and implementation

- v150 manifest file SHA-256:
  `5520fdac6b3ac583633aa987c534b319228b474581659519a00b116aa77c91c4`
- v150 manifest canonical hash:
  `f471c11b6371218c3d5bfab4380152eabec52b3637d466ef81658b36bcc47553`
- v150 result canonical hash:
  `6473b911af4183efdfb72e1d684ad7a663e960cb930459f7a10620077f21e414`
- v150 failed-attempt canonical hash:
  `5cfbd1ba8fd67d7310fcb79c5f3c72157582ed629e8566d5b6c2ffd44f7e6ab9`
- v150 recovery canonical hash:
  `9e006360d25fb973ec70c7f7985a0474e5c5244d597b482dc66259f93f831599`
- v151 audit commit: `da163b89ee6ffa7ce2e2326c00bc1c40e1d75686`
- v151 audit merge: `3ab451d645b9f0cdaa1f3d37de6be07d99ad0bba`
- v151 post-merge `main` run: `33943269412`, eight of eight jobs passed
- v151 audit SHA-256:
  `6b24d086468032b4acc0ce48a4154677e767526aed981106600ceb72605f0c10`
- v152 manifest file SHA-256:
  `ebd71e07ed6368cdbe76ab71c09e4cf4efcc9032ed2dea4ccc80868768c04ee5`
- v152 manifest canonical hash:
  `47281bc99187fb22d26606f3d7065462b60262a1678f84a1c694f72675ac1478`
- v152 runner SHA-256:
  `d2dfa9aa09713ff7361452bd6e41d58170362b645bc28f70729424f18569a529`

Execution requires the exact manifest and output paths, the one-use opt-in, a non-root host user,
a clean synchronized `main`, a positive post-merge `main` run ID, all twelve frozen provider
configuration names absent, and both `DOCKER_HOST` and `DOCKER_CONTEXT` absent. The runner validates
the immutable v150 evidence and v151 audit bytes without inspecting Docker predecessor resources.

## Host-root and DinD gates

Before any Docker operation, the runner measures `/` with `statvfs` and requires at least
4,294,967,296 available bytes and 100,000 available inodes. The same absolute gate is measured
again after cleanup. Percentages do not qualify the check. Both receipts contain only counts,
booleans, policy identifiers, and canonical hashes.

The local `docker:23.0.6-dind` identity remains locked to image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`
and repository digest
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`.
The only writable Docker roots are:

- data volume `verigym-deepseek-harness-v152-dind-data`, bind-backed by
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v152/data`;
- socket volume `verigym-deepseek-harness-v152-dind-socket`, bind-backed by
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v152/socket`.

The outer sidecar uses privileged mode only for nested Docker, `network=none`, VFS, no bridge,
iptables, or ip6tables, the fixed PID limit, an empty TLS-directory setting, and a read-only
sentinel. Readiness uses only the exact three-field command with a monotonic 120-second deadline,
five-second command bounds, empty stderr, and exact `23.0.6`, `vfs`, and `runc` equality.

After readiness, four bounded commands require empty inner container, image, volume, and custom
network inventories. Raw command output, output hashes, exception text, and container IDs are not
persisted. Any nonzero status, timeout, truncation, stderr, or nonempty inventory fails closed.

## Cleanup and successor boundary

Cleanup validates exact v152 owner, role, volume, and bind options before removal. Its minimized
helper uses `network=none`, a read-only root, bounded resources, only the exact v152 volumes, and
must return empty stdout and stderr. Publication requires the sidecar and both volumes absent and
both backing directories empty, mode `0700`, and restored to the invoking UID/GID. The host-root
postflight must also pass.

Only then may one atomic `host-runtime-scaffold-contract.json` be written. That contract explicitly
sets `provider_execution_authorized=false` and remains pending an independent v153 result audit.
V152 never inspects, mounts, mutates, removes, or reopens either v148 volume. In particular, it
cannot consume the retained v148 data-volume reopen budget.

The sole command, after merge and eight green post-merge checks, is:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V152_HOST_HEADROOM_SCAFFOLD=1 \
python scripts/run_hwe_deepseek_harness_v152_host_headroom_scaffold.py \
  --post-merge-main-run-id <green-main-run-id>
```

V152 is consumed by its first authorized invocation and must not be retried. Success or failure is
evidence only for v153. No replacement official matrix is authorized until v153 is merged and its
post-merge `main` run passes all eight check classes.

`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false` throughout.
