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

### Runtime-owned Codex external-agent boundary

The Docker-backed Codex CLI integration uses architecture Path A from ADR 0012. The trusted host
Codex app-server owns the existing ChatGPT authentication and model transport. All
model-controlled shell, patch, and filesystem operations are routed to a separate, hash-bound
`codex exec-server` container through a loopback WebSocket-to-stdio bridge. No built-in host tool
fallback is permitted.

When provider proxy forwarding is enabled, the trusted host app-server receives only the approved
uppercase `HTTP_PROXY` and `HTTPS_PROXY` values. VeriGym synthesizes identical `NO_PROXY` and
`no_proxy` values that always contain `localhost`, `127.0.0.1`, and `::1`; host lowercase
transport proxies and `ALL_PROXY` are never forwarded. The runtime records only environment
names and the presence of the mandatory bypass, never proxy values.

The agent container has `network=none`, a read-only root filesystem, a mapped non-root UID/GID,
private PID and IPC namespaces, cap-drop `ALL`, no-new-privileges, bounded resources, `/workspace`
as its only bind mount, and bounded `/tmp` as its only other writable location. Its image and
environment contain no provider credential, proxy, Codex configuration, host home, source
repository, hidden verifier, or Docker socket. Effective controls, role image separation,
container exit state, removal, and absence from the managed-container inventory are recorded for
every episode. A missing or weakened control is an infrastructure/security failure.

The verifier uses a separate Icarus 12 image and network-none session after candidate freeze.
Replay discards external-agent configuration, removes Codex/auth/proxy availability, and can
recreate only verifier sessions. The residual trusted computing base includes the host Codex
control-plane binary, reviewed VeriGym/plugin code, Docker daemon, and host kernel; Docker does
not protect against compromise of those components.

### Claude CLI MCP external-agent boundary

The optional `verigym-claude-cli` plugin uses a distinct host-control-plane design because Claude
CLI does not implement the Codex app-server remote-environment protocol. Claude CLI owns only the
provider connection on the trusted host. It runs in `--bare`, non-persistent print mode from a
private empty control directory with an isolated `HOME`, cache, and temporary directory. User and
project settings, `CLAUDE.md`, hooks, plugins, repository-provided skills, browser integration,
session reuse, and all built-in tools are disabled. The prompt is supplied on stdin, not argv.

The only advertised tools are exact `mcp__verigym__*` names from one strict inline MCP
configuration. A fixed stdio adapter connects to a mode-0600 Unix socket inside a mode-0700 short
scratch directory. The host process receives exactly one explicitly resolved provider credential
form (`ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY`); the two forms are never aliased. The adapter
launcher removes both credential variable names, the provider base URL, proxy variables, and effort
environment before starting the MCP child. Nonessential Claude traffic is disabled. The model gets
no host-filesystem or shell tool; the trusted MCP adapter gets no provider credential or task-image
mount and exposes only its fixed socket protocol. Neither receives a settings file, Docker socket,
hidden verifier, or credential tool.

Core-owned file tools validate every relative read and write against `WorkspacePolicy`. Argument-
array commands run through the selected official task Docker session with `network=none`; no shell
string or environment injection is accepted. Declared public tests use the existing hash-bound,
read-only public-test path. A policy violation or runtime control-plane failure makes the episode
terminal, and the ordinary candidate freeze and separate hidden verifier still run only after a
structurally successful agent episode.

The plugin sets an explicit model and `max` effort. It configures Claude's native print-mode dollar
budget and independently monitors cache-inclusive provider token usage in the live stream. Usage is
deduplicated by provider message ID; crossing the threshold terminates the complete process group
and remains an infrastructure-valid agent failure. Because usage becomes observable only after a
provider response, one in-flight response can cross either threshold before cancellation. The
process wall timeout, bounded stdout/stderr capture, broker call limits, and campaign-wide observed
token/cost thresholds provide independent backstops. No retry, fallback model, best-of-K, or hidden
turn/model-call override is enabled. Raw prompts, stdout events, message text, tool payloads, and
thinking blocks are not persisted; only content-free event summaries, numeric usage, hashes,
policy outcomes, and bounded failure diagnostics are retained.

The residual trusted computing base adds the installed Claude CLI binary and the reviewed MCP
adapter/broker. Provider behavior and the CLI's own upstream response ceiling remain external
dependencies; Docker does not protect against compromise of the trusted host control plane.

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

New completed run and experiment roots also carry bounded artifact manifests. Verification accepts
only normalized relative ordinary-file entries and checks required roles, visibility, byte sizes,
and SHA-256 values before replay, resume, or reporting trusts content. Symlinks, external hard
links, devices, FIFOs, sockets, duplicates, traversal, and out-of-bound inventories are rejected.
Older artifacts without a manifest remain explicitly `legacy_unverified`; a mismatch is a
distinct integrity failure, never a candidate verdict.

External plugin packages are trusted host-process code and must be reviewed before installation.
Entry-point import failures are isolated and diagnostics omit exception detail, but discovery is
not a sandbox. Once loaded, plugins still cannot bypass the environment’s allowlisted tool/path
policy, hidden-asset separation, budgets, candidate freeze, or runtime controls through the
supported interfaces. Artifact loaders do not discover or execute plugins.

### Context-aware artifact secret scanning

The artifact scanner parses JSON, JSONL, YAML, TOML, and CSV before classifying values. It treats
environment-variable names, authentication modes, execution-boundary enums, boolean/null policy
values, declared hashes and identifiers, documentation, and normalized credential-free base URLs
as provenance metadata rather than credential material. A sensitive field containing a concrete
value, an environment-variable assignment, an authorization value, a private key, a
credential-bearing URL, or unknown high-entropy material still fails closed.

Findings expose only the relative artifact path, structured field path, semantic role, evidence
kind, and value length. Suspected credential values are neither serialized nor hashed. Exact proxy
matching similarly records presence only. Malformed structured artifacts, unknown evidence kinds,
unsafe filesystem entries, and scanner errors block finalization.

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
