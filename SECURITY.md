# Security policy and threat model

VeriGym treats benchmark repositories, RTL and testbench sources, agent-generated patches,
generated artifacts, and compiler/simulator output as untrusted inputs. A malicious input may try
to read host files, consume resources, escape a workspace, expose verifier-only material, or leave
processes and files behind.

Protected assets include the host filesystem and home directory, SSH/cloud/model/package-registry
credentials, Docker credentials and socket, network access, hidden verifier assets, benchmark
golden sources, and workspaces belonging to other runs.

## DockerRuntime boundary

`DockerRuntime` is an opt-in, Linux-first containment profile labeled `docker_standard`. For each
command it creates a short-lived container around one private VeriGym staging directory. It
requests and then inspects the effective container configuration before starting the command.
Mandatory controls are:

- a verified non-root UID/GID;
- `network=none`;
- a read-only container root filesystem;
- a bounded `/tmp` tmpfs with `noexec`, `nosuid`, and `nodev`;
- all Linux capabilities dropped and no added capabilities or devices;
- `no-new-privileges` and an init/reaping process;
- mandatory memory/swap, CPU, PID, output, and host-side wall-time limits;
- one canonical private `/workspace` bind mount and no arbitrary mount interface;
- a fixed environment plus explicitly allowlisted, non-secret names;
- bounded, declared artifact collection with path, file-type, link, and size validation;
- unique ownership labels, `finally`-path cleanup, and stale-resource diagnostics.

The model client and its API credential remain on the host and are never injected into RTL
containers. Docker registry authentication may be used by the host Docker CLI only when the user
explicitly selects `pull_policy=if_missing`; it is neither copied into a container nor recorded in
run artifacts. Secret-like environment names containing `TOKEN`, `KEY`, `SECRET`, `PASSWORD`,
`CREDENTIAL`, or `AUTH` are rejected.

Agent and verifier workspaces are physically distinct. The agent receives only public/editable
task files. On final submission, the agent session is frozen, a canonical candidate is exported,
and only that snapshot is copied into a new verifier staging tree. Hidden inputs are added only to
that verifier tree. The verifier uses read-only file permissions for candidate and hidden sources,
with `.verigym_internal/` as its writable build area. Hidden inputs are hashed before and after
verification. This combined verifier-only tree is a deliberate compatibility tradeoff for Icarus;
it is never shared with the live agent and is removed after required artifacts are persisted.

The Docker CLI backend uses argument arrays with `shell=False`, bounded control-plane calls, and
no tar extraction. It never mounts the repository root, host home, Docker socket, or an external
benchmark checkout. Artifact acceptance rejects absolute paths, parent traversal, symlinked path
components, unverified hard links, devices, sockets, FIFOs, and per-file or aggregate size
violations.

## Yosys and profile-specific protections

Toolchain profile resolution is a verifier-side configuration step and completes before model
lookup. Profile documents are strict, versioned data. A resolved profile binds the declared
profile to the effective runtime or immutable Docker image, inside-runtime Yosys and ABC
identities, exact Liberty bytes, deterministic generated-script hash, synthesis flow, metric
units, and reference strategy. Missing tools, unsupported versions, incompatible runtimes, and
asset-hash mismatches fail closed; there is no Docker-to-local fallback.

Candidate-controlled top names, source paths, and preprocessor defines are accepted only after
grammar and boundary validation. The Yosys script is generated exclusively from validated tokens,
then persisted and hashed. Yosys is invoked as an argument array with shell execution disabled.
Candidate sources are copied into a private verifier session; external source paths, traversal,
symlinks, hard-link aliases, and special files are rejected. The educational Liberty file is
staged from hash-verified package data and is never taken from the candidate workspace.

Reference RTL and reference synthesis artifacts exist only in a separate verifier session. They
are absent from the agent container, model prompt, trace, public candidate artifacts, and
candidate-synthesis session. Only a bounded reference metric summary is persisted publicly. Raw
Yosys output and machine-readable statistics are size-bounded and treated as untrusted data; the
JSON parser rejects malformed, oversized, unsupported, non-finite, and excessively nested input.
Human logs are preserved rather than claimed to be bit-for-bit reproducible when the tool prints
paths or timing data.

Private and site-specific profiles may allowlist the *names* of license-configuration variables,
but VeriGym never serializes their values. Private Liberty, PDK, and script bytes remain
user-owned external assets: only their logical identities and hashes belong in portable run
metadata. Such runs must be labeled site-specific/private and are comparable only when their
complete resolved profile hashes match. VeriGym does not ship commercial binaries, vendor
scripts, PDKs, license files, credentials, or a licensed-host runtime.

## Experiment and report artifact safety

Experiment YAML/JSON and persisted parent artifacts are untrusted data. Configuration loading is
size/depth bounded, duplicate-key rejecting, safe-YAML only, and refuses symlinked files. Planning
stores credential environment names but never values. Model/agent pairing, source content,
mandatory tools, immutable Docker image identity, and optional profile assets are validated before
model lookup. Each child receives expected task/source/runtime/profile identities; drift fails
closed rather than mixing results.

Parent state, events, indexes, and reports use same-directory temporary files, `fsync`, and atomic
replacement. Experiment roots and report discovery refuse symlink roots and escapes. Child
validation requires contained relative paths, ordinary files/directories, no symlinks or special
files anywhere in the child tree, bounded JSON, matching manifest/score/index hashes, and exact
plan bindings. Corrupt or incompatible attempts are preserved for audit and excluded from metrics.

Reporting is intentionally offline: it does not invoke models, tools, runtimes, Docker, or the
network, and it does not parse candidate or hidden source for scoring. Arbitrary-root discovery
does not follow symlinks. CSV output normalizes control characters and prefixes spreadsheet
formula leaders; Markdown text and link paths are escaped. Reports contain descriptors, hashes,
counts, relative paths, and bounded structured diagnostics—not prompts, RTL, hidden tests, traces,
logs, credential values, or unredacted environments. Treat generated CSV/Markdown as untrusted
content in downstream viewers despite these defenses.

## Trust assumptions and residual risk

Docker is not a virtual machine and is not a perfect security boundary. The Docker daemon, its
effective site configuration, and the host kernel are trusted. Residual risks include container
escape, kernel vulnerabilities, daemon compromise, hardware and filesystem side channels,
resource-accounting differences between platforms, and weaknesses introduced by site-specific
Docker configuration. A compromised daemon can defeat all runtime controls.

The reference image is a small reproducibility and conformance target, not signoff-quality EDA
infrastructure. Licensed commercial tools are not included because their images, license servers,
credentials, redistribution terms, and vendor-specific isolation requirements require a separate
threat model.

`LocalRuntime` remains labeled `local_trusted`. It runs tools directly on the host and is suitable
only for trusted fixtures and development. It must not be used for untrusted benchmark
repositories, generated RTL, or adversarial agents.

## Reporting a vulnerability

Report security issues privately to the project maintainers through the repository's configured
private security-reporting channel. Do not open a public issue containing exploit details,
credentials, hidden benchmark material, or sensitive host information. Include the affected
version, runtime, platform, minimal reproduction, observed impact, and whether cleanup left any
VeriGym-labeled resources.
