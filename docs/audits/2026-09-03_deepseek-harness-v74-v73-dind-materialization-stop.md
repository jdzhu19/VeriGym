# DeepSeek Harness v74 audit of the v73 DinD materialization stop

Date: 2026-09-03

Status: **frozen pre-provider infrastructure failure**. V73 may not be retried, resumed,
reconstructed, or relabelled. No provider episode, formal collection, SFT export, training, or
production-readiness work started.

## Authorization and execution boundary

The v73 implementation was merged through PR #110. Its only authorized execution used exact clean
tracked `main` commit `85e5b18147417debef1395e495c6b1ec7a916e22`. Post-merge `main` Actions run
`33717399403` passed all eight required job classes before invocation.

The output root, DinD backing root, and both fixed v73 outer volumes did not exist before the
invocation. Recognized DeepSeek, OpenAI, Anthropic, and VeriGym provider variables plus
`DOCKER_HOST` and `DOCKER_CONTEXT` were removed from the child environment without printing,
persisting, or hashing their values. The command ran exactly once. It did not change the host
Docker daemon configuration, restart Docker, alter VPN/proxy state, start or stop the user-owned
image downloader, access a registry, read a `.partial` archive, prune a cache, delete a shared
`/data/docker` image, or reopen the retired v71 data backing.

## Passed boundaries

All five inherited tasks passed the reference-patch metadata compatibility preflight. The
content-free headroom gate passed all four roles:

| Role | Minimum bytes | Observed bytes | Minimum inodes | Observed inodes |
| --- | ---: | ---: | ---: | ---: |
| `control_root` | 4,294,967,296 | 9,395,421,184 | 100,000 | 18,368,441 |
| `docker_root` | 103,079,215,104 | 41,915,728,486,400 | 250,000 | 716,856,177 |
| `scratch_root` | 8,589,934,592 | 41,915,728,486,400 | 50,000 | 716,856,177 |
| `output_parent` | 2,147,483,648 | 41,915,728,486,400 | 10,000 | 716,856,177 |

The `docker_root` observation was the exact new backing directory
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v73/data`. Its preflight hash is
`64dd53a974fb6eccf6762230232dc393b18bd7927dbafe0203066ae38ed6cba9`.

The frozen Docker sidecar matched image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`, repository digest
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`, server 23.0.6,
`vfs`, and `runc`. It had `network=none`, no host Docker socket, and only the fixed data/socket,
output, and sentinel mounts. Runtime receipt hash:
`436f6f8cca9ff88d91a2013bcbc8e5d6f0192062df726bda08bfea51db0a43ee`.

PR-465 passed completed-archive identity and official zero-model qualification: base failed
without infrastructure error and the reference passed. The archive receipt file SHA-256 is
`21d5ae1c122d933237f3d5d1e27b18a5656509eeb6873f820dba60845d5d4516`; the smoke report file
SHA-256 is `f31aef682ef74774205da019fefa70327f13af028e00b4a88038432c49b70f0e`;
and the source-image lock file SHA-256 is
`9f2b2f43e3577f418f0e5bcf24cdaac0960e40d324a0330611c92fbfda66d87a`.

The task-specific command-image build completed and published derived image
`sha256:1cd291fa22ceb58ca3c22c8cc200fedf6472d966c3b655952916c211ed1a5836`.
Its content-free diagnostic recorded exit code 0, zero stdout bytes, 1,722 stderr bytes, no raw
output, and diagnostic hash
`a2661b11af4728fa881e58e5a5615bf097f609ffddff7bc2b822da7bd3dd710b`. This confirms that the
v73 command boundary corrected the v71 false rejection without weakening output bounds.

## Stop finding

The command-image v2 runtime scan failed at `docker_create`. Its frozen security scan classified
`docker_create_failed`, recorded create exit code 1 and 168 stderr bytes, created no temporary
container, removed its temporary workspace, detected no secret, and set `scan_passed=false`.
Security-scan file SHA-256:
`7e80cf5e3705044439412b417508ce3b1377fe78a402496d1825a5b6dfb6b429`.

The scan intentionally did not persist or hash nonempty failure stderr, so this audit does not
claim its text. Deterministic path reconstruction identifies the infrastructure mismatch: the
Ibex scanner creates its bind source below `/data2/jiadongzhu/Agent/.verigym-tmp`, while the v73
sidecar mounted only the v73 output root as a same-path host directory. The inner Docker daemon
therefore could not resolve the scanner's bind source in its own mount namespace. A successor must
place each scanner workspace below the already mounted successor output root (or explicitly mount
an equally narrow fresh scan root); it must not broaden the sidecar to the shared scratch tree.

No command-image lock or task receipt was published, and no later task started. This is not a task
verifier rejection or model result.

## Cleanup finding and remediation

The exception path removed the v73 sidecar. Its dedicated networkless cleanup container then
removed the listed Docker socket/PID/runtime paths, restored the socket directory identity, and
removed the socket volume. Host verification still found an unlisted root-owned `runc/` entry.
The cleanup-attempt receipt therefore correctly set `cleanup_confirmed=false`; its file SHA-256 is
`23fc27cc17c277aad4abdf7d8d5cd6b8c90b96c05db010472fe487f46ea11ad0` and embedded receipt hash
is `af8b185b44941c8a4f04809c0b4ff649b582ba2b68539c53384321e5b2f7e10c`.

After freezing the result, a separate `network=none`, read-only-root cleanup container mounted only
the exact v73 socket backing and added only `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`. It removed the
known transient `runc/` directory, restored mode `0700` and UID:GID `1004:100`, and removed itself.
The backing is now empty. This remediation does not rewrite or validate the v73 result.

The persistent v73 data volume remains labeled and bound to its exact `/data2` path. It is not
deleted, pruned, reopened, or reused. Because the post-failure inner inventory was not independently
revalidated, a successor must use a new data volume and new backing directory. Its fixed cleanup
inventory must include `/verigym-socket/runc` before host-side empty/owner/mode validation.

## Frozen evidence and disposition

The external evidence root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v73-dind-zero-provider-successor-v1`.

- `zero-provider-report.json` and `materialization-progress.json`: file SHA-256
  `659b5a0de53facc49cdd9ab8ce68de05f39e0257548010b5a184fc2ecf400d97`; embedded report hash
  `5c135eaa11f850bc1c707312d06521b9dc42312a19d72937584576110b17fdde`.
- `headroom-preflight.json`: file SHA-256
  `0e9aac6392c47e6b6cd81e1ef869316f47c4b1f327151b1488f4743165d87ae2`.
- `dind-runtime-receipt.json`: file SHA-256
  `6512a092fd1cc0d90b36d77d0a0c5f4758b5579046f47387bdd8230e9c20cb02`.
- PR-465 command diagnostic: file SHA-256
  `4af50b6a3f27bc14c74be35d37eba5fa6ad8187de38dba0338a20841a4c3756a`.
- PR-465 command-image build receipt: file SHA-256
  `3236caafebc697457760ca2033845659b5275fc487e2e94d252c5d592ede027f`.

The report is sealed as `stopped_without_provider_contract`, with zero completed task IDs, zero
provider calls, zero model processes, `provider_contract_published=false`, and
`dind_cleanup_confirmed=false`. The provider contract file is absent. All five tasks remain
provider-unconsumed because no provider boundary was crossed.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
