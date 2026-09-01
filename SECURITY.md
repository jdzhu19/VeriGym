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
canonical visible-source modes frozen before runtime preparation, independently of the controller
umask; newly added files become mode `0644`, and
symlink, special-bit, or group/world-writable mode references fail closed. The export never trusts
the mutable visible-source staging tree after runtime execution. Repository contracts continue to
forbid mode changes, and canonical candidate comparison still checks every file mode.

The Docker CLI backend uses argument arrays with `shell=False`, bounded control-plane calls, and
no tar extraction. It never mounts the repository root, host home, Docker socket, or an external
benchmark checkout. Artifact acceptance rejects absolute paths, parent traversal, symlinked path
components, unverified hard links, devices, sockets, FIFOs, and per-file or aggregate size
violations.

Non-interactive command containers use separate bounded `start`, runtime `wait`, and output
`logs` phases. Control-plane startup time is not charged to the candidate wall-time budget. A
runtime timeout kills the container, waits for its terminal state, and only then reads bounded
logs. The attached streaming path remains limited to the separately bounded interactive external
agent protocol. Phase, elapsed time, timeout, exit, truncation, and cleanup state are retained as
content-free diagnostics; raw daemon output is not promoted into campaign receipts.

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

### Credential-free HWE command-image boundary

Successor HWE campaigns may configure a `command_image` instead of `external_agent`. This role
cannot launch an app server or provider client: its schema has no external executable or process
argv, and the two roles are mutually exclusive. The task-specific image retains the public
verifier toolchain, whites out the official task source, and adds only a separately acquired,
release-archive- and binary-hash-bound ripgrep executable. The image scan requires the Codex
command and known Codex paths to be absent. It also requires an exact credential-free environment,
an inert `tail -f /dev/null` default command, the immutable task/verifier labels, and the ordinary
network-none, non-root, read-only-root, cap-drop, no-new-privileges, private-PID/IPC, bounded
resource, and single-workspace-mount controls. Historical agent images and locks are not rewritten.

The default command backend remains one short-lived container per command. The opt-in
`episode_container_exec_v1` backend creates one equally constrained container per runtime session
and uses argument-array `docker exec` calls for subsequent commands. Startup and every exec are
bounded separately. A command timeout, OOM, stopped keepalive, Docker control-plane error, process
inventory error, or container cleanup error invalidates the container and fails closed. After each
ordinary command, VeriGym compares a bounded `docker top` fingerprint with the startup baseline.
Any background-process residue destroys the container, records only expected and observed process
counts (never raw arguments), and poisons the session so no later command can run. Session freeze
and close retain the ordinary force-removal and cleanup-accounting boundary. This optimization
does not persist a writable container layer: candidate state remains only in the private workspace
bind mount and bounded ephemeral `/tmp`.

Successor command-image materialization uses a separately versioned v2 scan receipt. Every
container assertion has a stable, non-content-bearing exit identifier. Docker create/start and
cleanup receipts retain only exit codes, byte counts, an empty-stream SHA-256 sentinel, fixed error
categories, and container/workspace cleanup state. Nonempty output is never hashed. Raw stdout,
stderr, daemon errors, assertion content, container IDs, and host paths are never persisted. A
start failure, an unknown exit, over-bound output, a
failed assertion, or incomplete cleanup writes a failed security receipt and cannot produce an
image lock. Historical v32 output and image tags remain frozen and cannot be promoted by the v2
scanner.

Before a successor builds a command image, a zero-provider headroom preflight checks absolute
available-byte and available-inode thresholds for the control root, Docker data root, scratch root,
and experiment-output filesystem. The six-image policy budgets 8 GiB per image with a two-times
Docker staging margin (96 GiB total), plus independent 4 GiB control-root, 8 GiB scratch, and 2 GiB
output thresholds. Percent-used values are deliberately not gates because a one-percent remainder
on a multi-terabyte filesystem can still provide ample bounded capacity. Receipts contain roles and
numeric capacity only, never resolved host paths or raw `docker info` output. Rejection occurs
before image construction and does not authorize an automatic retry or successor identity.

The one-use OpenHands v33 authorization is a successor materialization identity, not a retry of
v32. It hash-binds the exact two-file v32 terminal inventory, requires zero locked v32 command
images, and prohibits importing either failed v32 image ID. It reuses the sealed v29 public-task
qualification without verifier replay. After the authorization commit is merged to `origin/main`,
the runner must repeat the absolute headroom gate and persist its receipt before constructing the
first of six task-distinct command images. Every successful image must bind a passed v2 security
receipt; a failed scan may contribute only the closed, content-free diagnostic summary to terminal
progress. A missing or malformed receipt, insufficient capacity, unexpected file, cleanup failure,
or binding mismatch stops the identity without retry. This authorization does not permit provider
access, canary execution, trajectory collection, SFT, inference evaluation, or held-out access.

The separately versioned OpenHands v40 authorization materializes one new PR-2549 training-canary
command image after all three v33 training reserves were consumed by frozen successor canaries. It
does not change the PR-2989 or PR-3059 validation-reserve roles and reuses only the unstarted v33
PR-3204 validation binding in its static successor contract. The runner binds the exact v33 and
v39 evidence, v22 protocol repair, historical PR-2549 v2 task/source/verifier lock, and independently
acquired ripgrep release. It retains the conservative six-image absolute headroom gate even though
only one image is constructed. A successful future PR-2549 canary must be imported without formal
re-execution; a failed canary freezes the task and identity. V40 itself has no provider or episode
surface and cannot start canary execution, formal collection, training, or held-out access.

The separately versioned OpenHands v41 authorization may execute only the v40 PR-2549 training
binding followed by the still-unstarted v33 PR-3204 validation binding. It binds the sealed v39
failure, the merged v22 SDK-normalized empty-content repair, the complete v40 result chain, exact
host dependencies, and a distinct seed/sample/runtime identity. The command containers retain
`network=none`, contain no provider credentials or Codex, and expose no external-agent process.
Before output and before provider construction, the runner revalidates the merged source and all
predecessor evidence, then starts both command runtimes and adapters under a zero-call preflight.
Any drift or preflight failure stops without consuming a task.

Once a provider episode starts, its task is single-use. All six result planes plus v22 trajectory,
decision, exact-64K/no-truncation, decision-only-mask, and security receipts are mandatory. A
failed training plane prevents validation from starting; no retry, fallback identity, reserve
substitution, historical relabeling, or PR-2549 formal re-execution is implicit. Even a two-task
pass authorizes only the later audited readiness work: v41 cannot start formal collection,
training, GPU work, or held-out loading.

The separately versioned OpenHands v42 authorization is a zero-provider successor to the sealed
v41 ordinary token-budget failure. It never retries or relabels PR-2549. Instead, it binds the
complete v41 evidence tree and post-merge eight-class check, materializes one task-distinct
PR-2589 command image from its frozen public task/source/verifier lock, and reuses only the
still-unstarted v33 PR-3204 validation binding. The same v2 content-free scan, cleanup receipt,
network-none runtime, exact ripgrep identity, and conservative six-image headroom policy remain
mandatory. V42 has no provider client or episode surface and cannot start canary execution,
formal collection, training, GPU work, or held-out loading. A later PR-2589 provider attempt
requires a new authorization and becomes single-use as soon as its first provider episode starts.

The separately versioned OpenHands v43 authorization may execute only the v42 PR-2589 training
binding followed by the still-unstarted v33 PR-3204 validation binding. It directly binds the
sealed v41 PR-2549 token-budget failure and the complete audited v42 result, including its exact
evidence tree, catalog, contract, image locks, security scans, and green post-merge main run. V43
uses a fresh campaign, agent-version, seed, sample, broker, output, receipt, and opt-in identity;
no predecessor output is replayed, reconstructed, or relabelled.

Both command containers remain credential-free and Codex-free with `network=none`. Before output
and before provider construction, the runner validates all predecessor inventories, source locks,
the tokenizer/model lock, dependency versions, and both command-runtime/adapter paths with zero
provider calls. Each started task is single-use with zero request and episode retries. Any failed
training plane prevents validation from starting; infrastructure or security failure stops
immediately. A two-task pass may set only `formal_collection_allowed=true` pending a separate
result audit. V43 cannot itself start formal collection, training, GPU work, or held-out loading.

The separately versioned OpenHands v44 authorization is a zero-provider successor to the sealed
v43 ordinary token-budget failure. It never retries or relabels PR-2589 and keeps the earlier
PR-2549 failure immutable. Instead, it binds the complete v43 evidence tree and post-merge
eight-class check, materializes one task-distinct PR-2802 command image from its frozen public
task/source/verifier lock, and reuses only the still-unstarted v33 PR-3204 validation binding. The
same v2 content-free scan, cleanup receipt, network-none runtime, exact ripgrep identity, and
conservative six-image headroom policy remain mandatory. V44 has no provider client or episode
surface and cannot start canary execution, formal collection, training, GPU work, or held-out
loading. A later PR-2802 provider attempt requires a new authorization and becomes single-use as
soon as its first provider episode starts.

The one authorized v44 invocation stopped before runner `main`, output creation, Docker, or a task
attempt because an ambient Conda editable install resolved `verigym` from an older temporary
checkout. V44 is permanently sealed and may not be retried. The separately versioned v45 repair
binds that exact stop receipt, its merged audit, and the green post-merge main run. It requires the
repository `.venv` with system site-packages disabled, prepends the current merged `src` before any
`verigym` import, verifies the loaded package root, and regression-tests a competing stale import
path. V45 retains the same PR-2802 input, v33 PR-3204 reuse, headroom, v2 content-free scan,
network-none, atomic-write, and zero-provider boundaries. It cannot execute a task, call a model,
start collection or training, use a GPU, or load held-out data; any provider canary requires a new
v46 authorization.

The one authorized v45 invocation completed its internal image, lock, catalog, and contract gates,
but the independent result audit rejected the evidence root. The runtime receipt persisted the
absolute interpreter, virtual-environment, and package roots in `materialization-progress.json`.
Those values were useful for the in-memory launcher gate but are raw host paths and therefore are
not export-safe provenance. V45, its result tree, and both produced image IDs are permanently
sealed and cannot be retried, edited, or promoted. The PR-2802 task remains provider-unattempted.
A separately versioned v46 materialization repair may repeat only the zero-provider image build
after binding this exact failed tree and merged audit. It must validate the absolute runtime paths
in memory while persisting only booleans, versions, and content identities; its result audit must
scan the repository, result, predecessor, provider, and proxy values without printing or hashing
them. The provider-canary identity is consequently deferred to v47.

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

The separately versioned v18 HWE collection profile permits one additional same-session recovery
only when the local provider-response validator identifies the safe structured category
`raw_host_path` before OpenHands or the broker dispatches the action. The rejected arguments and
response body are neither inserted into model history nor persisted; the SDK error event is
snapshotted as content-free causal metadata. The adapter records only the canonical tool name,
argument-field name, violation category, and hashes of generic local error and feedback text, then
adds one fixed user feedback message and requires exactly one provider-emitted canonical tool call
through the bounded Responses path. A second path violation, another violation category, an
ambiguous parent recovery, a missing or malformed required tool, counter drift, or any raw argument
retention fails closed. When the rejected response belonged to the one SDK continuation, the
validated replacement closes both continuation and path-recovery accounting; no action is
synthesized. Exact v6 trajectories hash-bind the sanitized receipt and model-visible feedback,
keep decisions before the feedback unaware of it, and remain ineligible unless the ordinary hidden
verifier resolves the episode.

The pre-dispatch path validator scans decoded JSON string leaves. It must not re-serialize decoded
values before applying host-path expressions: JSON newline escapes can otherwise turn a legal
source label such as `CSR_MCOUNTINHIBIT:` into the drive-like byte sequence `T:\n`. Malformed raw
JSON uses a separate escape-aware expression, while decoded `path`, `cwd`, command, patch, and
summary values retain the ordinary POSIX and Windows host-path rejection boundary.

The independent v19 HWE profile sends `tool_choice=required` on every active synchronous,
asynchronous, Chat Completions, and Responses request. It accepts exactly one content-free
canonical call from the six-tool contract. A provider may instead emit one content-only response;
the trusted Stop hook retains that public response, injects the existing canonical
`source=environment` feedback in the same session, and permits one later canonical provider tool
decision. A second content-only response, mixed text and tools, multiple or foreign tools,
non-canonical arguments or `finish`, weakened tool choice, missing token accounting, or recovery
counter drift fails before the response can enter the broker. The installed SDK remains unchanged
and the adapter never synthesizes a tool call. v19 freezes 64 provider calls, 1,000,000 cumulative
provider tokens, a 65,536-token context, and 2,048 output tokens. The cumulative token check runs
after SDK accounting but before agent or broker dispatch, so an over-budget response is accounted
and rejected. Successful protocol receipts bind request, canonical response, content-only,
recovery, call, token, and broker-decision identities.

v19 does not change the compatibility meaning of `ScoreCard.resolved`. Campaign classification
derives `benchmark_verifier_pass` directly from the actual verifier result nodes and records it
independently from agent-protocol validity, trajectory eligibility, infrastructure validity,
security validity, and SFT admission. Only evidence satisfying all admission planes may receive a
v19 trajectory and exact-decision sidecar. Those sidecars retain abnormal assistant text and
environment recovery feedback only in the masked input prefix; the complete later canonical tool
decision is the sole supervised target. Historical attempts and identities remain immutable, and
sealed historical scorecards may be used only for offline classification regressions, never to
reconstruct or retroactively admit a trajectory.

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

The v17 formal collector has a separate agent and campaign identity from its three-task canary. It
imports only the two hash-bound, verifier-passed canary training trajectories and validates the
sealed canary report, gate, agent manifest, trajectory bytes, task/source hashes, and candidate and
verifier receipts before re-tokenization. New public tasks run once in frozen order with no
provider or episode retry. After every atomic attempt, the collector recomputes distinct-task pass
capacity and stops immediately when either target is impossible or when the exact 8-training /
2-validation target is reached. It never loads held-out tasks. Only verifier-passed trajectories
may produce decision rows; every row preserves complete model-visible messages and six-tool schema,
uses a decision-only loss mask and exact Qwen receipt, and fails rather than truncates above 65,536
tokens. Training and validation datasets, equal-trajectory schedules, and security scans are sealed
separately. Passing this data gate authorizes only the preregistered bounded development SFT; it does
not make the dataset or a later adapter production-ready and does not support a benchmark claim.

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

### Daemonless registry prewarm boundary

The separately authorized OpenHands v20 prewarm preflight replaces the networked privileged DinD
downloader with a pinned `crane` release running as a single-purpose process in an ordinary Docker
container. A digest-locked Python bootstrap image may download only the registered GitHub release
asset, checksum list, and provenance envelope through the dedicated `verigym-hwe-net` bridge. The
bootstrap validates exact byte sizes and SHA-256 values, confirms that the checksum and provenance
payload bind the registered Linux x86-64 asset, and extracts only one bounded regular `crane`
binary. The committed authorization binds the helper script and all three upstream artifacts.

Both the bootstrap and `crane` execution containers run as the invoking non-root UID/GID with a
read-only root filesystem, private IPC and PID namespaces, cap-drop `ALL`, no-new-privileges,
bounded memory, CPU and PIDs, a bounded `/tmp`, no published or exposed ports, and one narrow
scratch mount. They receive no Docker socket, Docker or registry authentication, provider
credential, proxy value, host home, repository checkout, task source, hidden verifier, or reference
patch. The bootstrap mount is writable only for the registered public tool files; later `crane`
checks mount it read-only. Effective image, path, argv, environment, network, mount and resource
controls are inspected before each container starts, and cleanup is verified afterward. No
`dockerd` process or TCP Docker API is started.

The first authorization permits only the pinned release bootstrap, a network-none `crane version`
check, and one digest lookup for a registered non-candidate public image. It explicitly forbids
candidate image download or load, qualification, provider calls, training and held-out access.
Passing this preflight is evidence about downloader controls only; it is not a benchmark result and
does not authorize the next stage. A failed command, identity mismatch, unexpected output,
candidate image presence or cleanup failure stops the stage as infrastructure/security invalid.
The downloaded SLSA envelope is hash- and subject-checked but its DSSE signature is not independently
verified in this preflight; the pinned GitHub release digests and reviewed authorization remain part
of the trusted supply-chain input.

The v20 identity is historical and remains subject to that residual risk. Its v21 successor adds a
separately pinned `slsa-verifier` v2.7.1 binary and follows the producer's release-workflow command
to verify the Sigstore bundle signature, artifact digest, source repository, release tag, builder,
and source commit. The helper also validates the exact Sigstore bundle media type, nested DSSE
payload, unique artifact subject, SLSA predicate, build type, workflow entry point, and material
binding before extraction. Both tool binaries and all public release inputs remain size- and
SHA-256-bound in the reviewed authorization.

v21 command success is determined by a zero exit code and role-specific exact stdout; stderr is a
bounded attached stream, not independently a failure. Reports retain only the stage, exit code,
stdout/stderr byte counts, stderr-presence bit, effective-control hash, and cleanup state. The
bootstrap helper atomically updates a similarly content-free receipt before and after each download,
validation, signature-verification, extraction, and receipt stage. Output bodies and exception
messages are not persisted. Candidate access and every later campaign stage remain outside this
authorization.

The v21 identity is sealed after its verifier process did not start: its restricted subprocess
`PATH` intentionally excluded the writable download mount, while argv item zero contained only a
filename. The v22 successor does not add that mount to `PATH`. It resolves the registered verifier
to the exact ordinary, executable, single-link file
`/download/slsa-verifier-linux-amd64`, rejects a symlink or path escape, and passes that fully
qualified path to the subprocess. The exact path is also bound into the atomic helper progress and
final receipt. v22 retains v21's download, network, output, diagnostic, cleanup, and no-candidate
boundaries; it authorizes one new preflight only after its distinct authorization merges.

The v22 identity is likewise sealed after its verified `crane version` command returned a
successful seven-byte output that differed from an eight-byte value derived from the release tag.
The v23 successor treats the Git release tag and CLI build-version output as independent bindings.
It registers the exact output observed from the SHA-256-bound public binary, validates that this
value is not `release_tag + newline`, compares exact bytes under `network=none`, and persists only
the byte count and SHA-256 in the outer report. A future binary update must register its own output;
it cannot inherit or infer the value from a tag. v23 uses a new cache and does not reuse v22's
promoted public-tool evidence.

The v23 identity is sealed after its final public registry probe used a CA-less Debian slim image.
The v24 successor reuses the already digest-locked, CA-bearing Python slim image for execution and
requires it to equal the bootstrap image binding. Before any crane command, v24 runs the fixed
`/usr/bin/test -s /etc/ssl/certs/ca-certificates.crt` argv under `network=none` and the same
non-root, read-only-root controls. Success must emit no output, and the content-free receipt is
included in the final report. Runtime package installation, TLS disabling, `--insecure`, old-cache
reuse, credentials, and proxy forwarding remain forbidden.

The separately authorized v25 qualification reuses only the eight exact, hash-checked public files
from the passed v24 tool cache. Candidate transfers run one at a time through `crane` on
`verigym-hwe-net`; the container has a read-only tool mount and one writable transfer/cache mount,
but remains non-root, read-only-root, capability-free, non-privileged, port-free, and socket-free.
The host Docker daemon receives only the completed, bounded tarball through `docker image load`.
No nested daemon or TCP API is started.

The go-containerregistry tarball format is loadable by Docker but does not preserve a registry
manifest digest across a tarball round trip. v25 therefore resolves the public tag once, pulls the
digest-qualified reference, hashes the exact remote config bytes, requires that hash to equal the
loaded Docker image ID, validates the bounded tar member inventory and generated digest-sentinel
tag, and only then applies the frozen candidate tag. The separately recorded remote manifest
digest and local config/image identity become the preparation override; any existing Docker
`RepoDigests` must either be empty or agree. An override cannot accompany an implicit Docker pull
or cover a task other than the explicitly selected source.

Qualification stays on `network=none`, makes zero model calls, and runs immediately after each
successful transfer. A content-addressed layer cache is shared only inside this one v25 run. The
runner atomically recomputes qualified count plus remaining distinct capacity after every outcome,
stops before transferring an unnecessary fallback once five tasks qualify, and stops early when
five are no longer possible. Transfer, infrastructure, security, cleanup, or binding errors stop
the stage immediately with no retry. Provider canary, agent-image build, collection, training, and
held-out access remain separately gated.

The v25 identity is sealed after its first digest-qualified `crane pull` returned zero but emitted
bounded diagnostic output. Its local empty-stderr rule stopped before Docker load or verification.
The v26 successor keeps stdout empty as a semantic requirement, permits stderr only after the
controlled command has exited zero and the existing byte bound has been enforced, and never
persists raw output. Before applying that policy it atomically records a content-free receipt with
stream byte counts and digests, so a later stop remains diagnosable. Tar inventory, remote config,
loaded image ID, manifest binding, network isolation, cleanup, capacity, and no-retry controls are
unchanged; bounded diagnostics cannot substitute for any integrity check.

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

### OpenHands bounded-iteration termination

The OpenHands HWE adapter distinguishes a typed broker finish from one exact SDK iteration-limit
boundary. An iteration-limit outcome is model non-completion only when the frozen provider budget
is fully accounted, every provider response has a usage record, the broker accepted exactly the
configured number of canonical actions, the next decision alone was rejected as
`decision_steps_hard_limit`, and the sanitized SDK event counts match the registered boundary.
The outcome exports no training trajectory and does not invoke the verifier.

Any different policy failure, rejection code or count, mutation limit, provider/accounting drift,
interrupt, additional conversation error, persisted message content, or missing private-artifact
scan remains fail closed. Historical reports retain their original classification; a newer policy
identity cannot relabel a prior canary or authorize downstream collection retroactively.

### OpenHands formal-collection continuation

An OpenHands formal collection may continue after a collector-side persistence failure only through
a new, reviewed continuation contract. The continuation must bind the exact prior contract, agent
version, agent source commit, task and image locks, run and trajectory hashes, security scan,
accounting evidence, materialized decision rows, and observed crash boundary. It must rebuild the
same provider-visible agent identity and must not replay the completed provider episode. A changed,
missing, symlinked, or newly finalized recovery artifact fails closed.

Recovery imports are deterministic re-materializations, not reconstructed or relabeled samples.
The imported records must exactly equal the already persisted partial JSONL, remain below the
frozen token limit, and pass the original runtime-evidence and secret-scan gates. The continuation
uses a new collector identity and output root, starts at the next distinct preregistered task, keeps
provider and whole-episode retries at zero, and loads no held-out task. Per-episode trajectory,
manifest, progress, and gate persistence errors are terminal collection failures and cannot be
treated as verifier rejection or authorization to resample.

A fail-closed stop must overwrite any earlier capacity gate with a terminal gate whose `possible`
and `satisfied` fields are false and whose next role is absent. Offline consumers must require that
terminal gate and the stopped campaign report to agree; an older pre-attempt gate cannot authorize
resume, collection, or training.

Neither a recovered sample nor a completed continuation authorizes GPU work by itself. Training is
allowed only after the continuation emits its independent final report and the original exact-64K
distinct-task gate is satisfied. Historical incomplete roots remain immutable audit evidence.

### Public qualification continuation and safe diagnostics

A stopped public qualification is never retried under its frozen identity. A successor may import
qualified evidence only after binding the complete predecessor progress hash, file hash, task and
source hashes, image and manifest identities, transfer receipts, terminal diagnostic receipt, and
audit commit. Every previously attempted task remains single-use; continuation starts at the next
distinct frozen candidate. Imported evidence is identified as predecessor evidence and is not
relabelled as a new execution.

Raw registry, transport, cache, archive, and container diagnostics may contain endpoints,
credentials, or host paths and must not be persisted. A bounded diagnostic may be inspected only
in memory and mapped to a closed, non-content-bearing error category. Receipts retain byte counts,
SHA-256 values, exit state, the allowlisted category, and cleanup state. Unknown or over-bound
output, a nonzero command, invalid classification, or a cleanup failure remains fail closed. Error
classification does not authorize an automatic retry or convert an infrastructure failure into a
verifier result.

### HWE reference-patch compatibility preflight

Official HWE-Bench fixes may contain ordinary text edits, file creation or patch shapes that a
VeriGym `Candidate` overlay cannot reproduce, including deletion, rename, copy, mode-only and
binary changes. Before Docker inspection, image transfer, source extraction or verification, the
HWE integration classifies each selected reference patch with Git's metadata-only `apply
--numstat -z` and `apply --summary` modes. The patch is supplied on standard input; the command
does not receive a repository and has no Docker or network access.

Only regular UTF-8 edits and regular mode-100644 text-file additions are representable. The
preflight requires the machine-readable patch paths to match the official `modified_files`
manifest exactly and rejects unsafe or non-UTF-8 paths, malformed or over-bound metadata, binary
patches, deletions, renames, copies, mode changes, non-regular creations and unknown summary
records. A compatible addition is materialized from the fully patched reference tree as an
ordinary Candidate file. Missing, symlinked or non-UTF-8 reference outputs still fail closed.

Raw patch metadata output and paths remain in memory and are not written to a campaign receipt.
Campaign receipts may retain only the classifier version, compatibility reason, bounded counts,
booleans establishing that raw output was not persisted and that network and Docker were not
accessed, and a hash of that content-free receipt. Compatibility is an adapter capability result,
not a benchmark verifier result or an infrastructure result. A successor campaign may use the
preflight to avoid work on an unrepresentable never-attempted candidate, but it may not retry,
reconstruct or relabel a sealed historical attempt.

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
