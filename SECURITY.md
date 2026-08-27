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

Docker UID mapping may temporarily broaden regular-file permissions inside the private agent
staging tree. Candidate export removes that runtime-only broadening: existing files recover their
frozen visible-source modes, newly added files become mode `0644`, and symlink, special-bit, or
group/world-writable mode references fail closed. Repository contracts continue to forbid mode
changes, and canonical candidate comparison still checks every file mode.

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

The opt-in CVA6 HWE native-shell profiles add protocol-aware inspection between the host app-server
and task-keyed Codex 0.147.0 exec-server image. They correlate JSON-RPC requests and responses,
including the bounded exec-server `process/start` through `process/output`, `process/exited`, and
`process/closed` lifecycle. It buffers streamed output privately and forwards only one compacted
replacement, rejects command environment injection, interactive process control, unmatched
process identifiers, and fails closed on unknown output-bearing command, process, or filesystem
methods. Legacy `hwe_standard_v1` also rejects lexical shell workspace escapes. Current
`hwe_standard_v2` deliberately allows container-native shell reads such as `find ..` and absolute
tool inspection: its read boundary is the isolated agent container, not a path-string filter.
Direct filesystem/patch methods and all persistent candidate changes remain restricted to
`/workspace/repository`; non-workspace direct read-only discovery is mapped to one fixed
nonexistent workspace path, exposes no container metadata or file contents, and is not recorded as
a training action. Mutations still fail closed, and legacy HWE v1 keeps its original behavior. The
v2 process transport additionally normalizes only the direct parent of the visible workspace back
to the repository root; any other external or noncanonical `cwd` still fails closed. The image
root is read-only and `/tmp` is bounded and ephemeral. Original
public command output is
written only to a bounded, secret-scanned
`private-audit/` artifact and frozen read-only; only the deterministic compact projection may reach
the public transcript. These HWE profiles do not broaden or replace the strict typed-tool paths.

The optional HWE action-conditioned masking derivation operates only on the already-public compact
transcript. It never reads private-audit output. It preserves assistant action bytes and replaces
eligible older tool observations with typed markers containing only public compact-content hashes,
sizes, token counts, normalized sequence, action, and workspace epoch. Its records explicitly state
that counterfactual next-action validation was not run, remain primary-ineligible, and cannot be
mixed into the frozen primary dataset formats. Because the Codex app-server owns live provider
history, the exec-server broker does not claim or attempt retroactive rollout-history mutation.

### OpenHands SDK trajectory boundary

The optional `verigym-openhands` integration runs OpenHands SDK 1.42.1 as a trusted host control
plane with an empty private workspace. Default OpenHands terminal, file-editor, browser, plugin,
skill, client-tool, condenser, and repository-mount surfaces are disabled. The SDK receives only
one owner-controlled MCP server and never receives the Docker socket, hidden verifier assets,
reference solutions, host home, or another run's workspace. Ordinary repository actions and the
optional HWE native-shell actions remain broker-owned. HWE shell commands execute only in the
task-keyed networkless agent container through the existing DeepSeek HWE broker; they are not host
shell commands.

The separately versioned required-tool HWE profile subclasses the public OpenHands `LLM`
completion interface and supplies `tool_choice=required` to every synchronous and asynchronous
chat request. It does not modify the installed SDK or accept content-only completion. The profile
fails closed if the policy is weakened, if the exact six-tool contract is empty, or if a
content-only Stop-hook recovery is still needed. The broker-observed typed `finish` remains the
only completion authority.

The current validated-recovery-state profile leaves ordinary turns at the SDK/provider default
`auto`. It selects the concrete `finish` function only after validating the private mode-0600 state
receipt atomically written by the trusted Stop hook for a content-only completion attempt. The
model cannot access that host control path. Before OpenHands dispatch, the local LLM subclass also
requires the provider response to contain exactly one `finish` call and records content-free request
and validation counters. A missing, altered, unsafe, or out-of-budget receipt, a caller-supplied
tool choice, a missing or duplicate `finish` schema, a non-finish provider response, an interrupted
run, an unexpected exception wrapper, or any later broker mismatch fails closed. The adapter walks
only the bounded local `__cause__`/`__context__` chain needed to recognize its own controlled
protocol violation; it never persists raw exception text or model content. The provider still emits
the typed call; the adapter does not synthesize an action or infer completion from arbitrary
assistant text. Earlier message-shape-bound v4/v5, unvalidated state-bound v6, and outer-exception-
only v7 profiles remain separately versioned historical diagnostics.

The separately versioned v9 profile keeps every ordinary action on the historical Chat
Completions route. Only the private-receipt-bound recovery request uses the provider's Responses
API, with the same complete message history and exact six-tool contract. Because OpenHands SDK
1.42.1 normalizes Responses tool choice back to `auto`, the local subclass rebinds only its own
named `finish` choice after the SDK serializer returns; it does not modify the installed SDK,
remove tools, synthesize a call, or expose recovery state. The response must still contain exactly
one provider-emitted `finish` call before broker dispatch. Responses thinking is explicitly
disabled, storage is disabled, raw request and response bodies are not persisted, and all existing
receipt, counter, exception-chain, interruption, verifier, and trajectory gates remain in force.
For the text-only HWE contract, the adapter additionally normalizes the SDK's multiple adjacent
`function_call_output` items for one tool message into one output with byte-preserving text
concatenation. It rejects non-text output, missing call IDs, and reuse of a closed call ID. The
diagnostic records the normalization count and requires a nonzero count before claiming the
full-history regression passed.
The subsequent response-shape diagnostic stores only bounded raw output types, exact names from
the already-public six-tool contract, raw/converted item counts, and text-part counts. Unexpected
names are replaced by their SHA-256 digest. It never stores response text, arguments, reasoning,
provider response IDs, raw bodies, or credentials.

Training transcript capture is explicit and training-role-only. The v1 collector accepts exactly
one linear system/user/action/observation trajectory ending in typed `finish`. The HWE v2
collector additionally permits one frozen same-session format recovery: when OpenHands attempts
to stop before the broker has accepted typed `finish`, a trusted Stop hook reads only the broker's
content-free terminal state over its private mode-0600 Unix socket, denies that stop once, and
injects one canonical user feedback message. A private mode-0600 state file enforces the recovery
budget; a second premature stop is allowed to unwind and then fails the broker-owned finish gate.
No workspace reset or whole-episode retry occurs. The v2 trajectory hash binds the premature
assistant text, canonical feedback, hook receipt, and recovery count; downstream SFT masks that
history as input and supervises only complete later assistant tool decisions.

Both formats reject private reasoning, thinking blocks, dynamic context, skills, critics, unknown
events, duplicate call IDs, rejected calls, missing observations, and any mismatch between the SDK
event and broker-owned canonical arguments or compact-observation hash. The exact effective
OpenHands tool schemas, including SDK-added metadata fields, are retained so downstream token
receipts bind the actual model-visible contract. Raw hook output, raw provider events, uncompacted
observations, private reasoning, credentials, host paths, hidden assets, and reference solutions
are not exported.

Message content remains in memory until the ordinary verifier completes. A public training
trajectory is written only for a resolved, infrastructure-valid episode; all other episodes remain
SFT-ineligible. Downstream decision export supervises one complete assistant tool decision at a
time, passes the same tools to the frozen Qwen chat template, fails above 65,536 tokens without
truncation, and seals input-ID and loss-mask hashes. The residual trusted computing base adds
OpenHands SDK, its model client dependencies, the reviewed MCP adapter and broker, Docker daemon,
and host kernel. The model endpoint remains external, and Docker does not protect against a
compromised trusted host control plane.

### DeepSeek Harness HWE controller boundary

The opt-in `verigym-deepseek-harness` integration runs the pinned official Harness source in a
digest-locked, read-only controller container. The controller is the only component that receives
the DeepSeek credential and provider base URL. It has the dedicated `verigym-hwe-net` network but
does not receive the task workspace, source checkout outside the pinned Harness tree, Docker
socket, hidden verifier assets, reference patch, host home, or unrelated experiment roots.

The controller can reach one mode-0600 Unix socket under a mode-0700 run directory. A reviewed
plugin exposes exactly the six HWE native-shell v2 tools with serial execution; built-in bash,
jobs, skills, workspace context, runtime context, and Harness compaction are disabled. The host
broker validates each typed action and call ID. Core file tools retain normal `WorkspacePolicy`
checks. Shell diagnostics run in the task-keyed repository-agent image through a new short-lived
container with `network=none`, a fixed credential-free environment, read-only root, non-root user,
cap-drop `ALL`, no-new-privileges, bounded resources, and only the visible workspace/public mounts.
No provider or proxy variable is forwarded to that command image.

The pinned Harness uses streaming requests and private JSONL session persistence without
compression. Session events and uncompacted command output remain private audit material. Public
transcripts are reconstructed only when every assistant message is exactly one known tool call,
every result is causally matched, the effective request headers contain the frozen model/settings
and exact tool schemas, and the episode concludes with one typed `finish`. Thinking/reasoning
blocks, assistant prose outside tools, foreign tools, duplicate call IDs, malformed events, policy
violations, and controller/broker failures fail closed.

The residual trusted computing base adds the pinned Harness source, its locked Node controller
image and installed dependencies, the reviewed tool plugin/helper/broker, Docker daemon, and host
kernel. The controller deliberately has provider network access, so compromise of those trusted
components can expose the provider credential. Docker is not a defense against compromise of the
host control plane. The three-task collection output is permanently pilot-only and cannot claim
production training readiness.

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

### Opt-in nested Docker boundary for HWE-Bench

The HWE-Bench DinD launcher is a compatibility path for hosts whose daemon/runtime stack cannot
start a frozen benchmark image. Only an official, immutable Docker 23.0.6 daemon sidecar receives
outer `--privileged`. The launcher validates its official entrypoint, server version, `vfs` storage
driver, `runc` default runtime, socket group, and empty container/volume inventory. The sidecar has
`network=none`, never receives the host Docker socket, and uses a dedicated labeled data volume.

The VeriGym project controller remains an unprivileged, non-root, networkless, read-only-root
container. It receives only the nested socket and narrow source, scratch, task, verifier-output,
and report mounts. It receives no host Docker socket, provider credential, provider configuration,
host home, or `--privileged`. Inner benchmark containers keep their ordinary `network=none`,
cap-drop, no-new-privileges, PID/memory/CPU limits, and built-in seccomp profile. The launcher does
not use `seccomp=unconfined` or propagate sidecar privilege to either layer.

The privileged daemon sidecar is trusted infrastructure, not a security boundary against the host
kernel. Compromise can affect paths deliberately mounted into it, and its persistent data volume
retains imported image layers. Operators must use a controlled worker, digest-locked images,
narrow mounts, and a dedicated data volume; they must not mount the host home, repository root,
credentials, hidden assets, or unrelated experiments. A nonempty inner runtime inventory or failed
cleanup is an infrastructure/security failure. See [the HWE DinD runtime guide](docs/hwe_dind_runtime.md).

### Verifier-only Synopsys MCP transport

The optional `synopsys.dc.mcp` backend moves licensed DC execution to a separately administered
verifier host; it is not a model-visible tool or a general remote shell. The control plane launches
one regular, executable, SHA-256-bound wrapper without arguments or a shell. A profile may pass
only `SSH_AUTH_SOCK` or `KRB5CCNAME` by name to that wrapper. SSH deployments must use a dedicated
principal, host-key verification, a forced command or otherwise fixed server command, and no SSH
agent forwarding. Transport environment values are never serialized.

The stdio MCP server approves its site profiles at startup and accepts only a profile ID plus
declared hash, a reference-candidate hash, fixed top and ordered source names, candidate/reference
role, bounded hash-checked RTL, and one bounded artifact-return policy. It does not accept an
executable, shell command, Tcl, SDC, PDK/library bytes or paths, license configuration, timeout, or
environment. It regenerates and hash-checks the existing DC flow. Messages, sources, output, and
artifacts have individual and aggregate bounds. The client validates the server/protocol version,
server profile and resolved hashes, DC version, remote asset hashes, flow/activity settings,
metrics, and artifact hashes before importing candidate summary reports. Reference artifact
content never returns. MCP/SSH payload logging must remain disabled because a reference call
necessarily transports verifier-private reference RTL to the remote verifier.

This transport separates the ordinary control-plane host from commercial assets, but it is not an
OS sandbox for hostile RTL. The current server invokes DC through the trusted local backend on the
licensed host. Sites must use trusted/qualified inputs or add their own dedicated disposable
account, scheduler job, VM, or equivalent containment around the server. The MCP label alone must
not be used to claim that adversarial generated RTL is safe to parse on a shared licensed host.
The residual trusted computing base includes the fixed wrapper, SSH client/server, MCP adapter,
licensed EDA installation, verifier host, and its site-specific containment.

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
