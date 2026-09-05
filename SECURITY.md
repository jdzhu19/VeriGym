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
them. The v46 checked-in authorization follows the same boundary: it records a repository-local
isolated-runtime policy and equality requirements, not concrete repository, interpreter, prefix,
or package-root values. Regression coverage serializes the runtime receipt and requires a
context-aware scan against all known runtime roots to pass. V46 remains zero-provider and may only
prepare a distinct v47 canary fixed to PR-2802 then PR-3204, seed 496 and sample 12; it does not
authorize that canary. The provider-canary identity is consequently deferred to v47.

The sole authorized v46 execution successfully rebuilt and v2-scanned a fresh PR-2802 command
image while making zero provider calls. Its independent result scan covered the complete sealed
tree and compared the known host roots and active sensitive values only in memory; it found no raw
host path, credential, proxy value, or scanner error. The runtime receipt now exports only version,
content hash, and equality booleans. V46 remains a zero-provider materialization and does not
authorize task execution or collection. A v47 provider authorization must bind the complete v46
tree, image lock, scan, contract, merged result audit, and green post-merge main run before it may
attempt PR-2802 followed by PR-3204.

The separately versioned v47 authorization binds that complete v46 chain and permits only the
PR-2802 training episode followed by PR-3204 validation under protocol v22, seed 496, and sample
12. The host provider process is separate from both credential-free, Codex-free command images;
each command runtime has `network=none` and uses only `episode_container_exec_v1`. Before output,
the runner validates the clean merged source, exact public source and image locks, v33/v46 trees,
tokenizer/model lock, dependency versions, and both command adapters with zero provider calls.
After a task starts it is single-use with zero request and episode retries. Any infrastructure or
security invalidity stops immediately, and any failed PR-2802 result plane prevents PR-3204 from
starting. A two-task six-plane and exact-64K pass may set only
`formal_collection_allowed=true`; v47 cannot start formal collection, training, GPU work, or
held-out loading, and its result must still be independently audited and merged.

The sole authorized v47 launch stopped before output, runtime preflight, provider construction, or
task loading because its `--stopped-v37-canary-root` argument selected a nonexistent sibling rather
than the sealed predecessor root. V47 is frozen even though it made zero provider calls and
consumed neither PR-2802 nor PR-3204. Its content-free stop receipt records only the failed
argument name, normalized error category, zero accounting, and non-authorization flags; it omits
both path values, the raw exception, command line, and provider/proxy values. Any repair requires a
separately reviewed v48 identity that binds the exact stop evidence and its merged audit. Correcting
the argument and rerunning v47 is prohibited.

The separately versioned v48 authorization binds the exact v47 stop receipt, evidence tree,
merged audit, and green post-merge main run. It additionally compares the resolved v37 and v47
stop directories with their reviewed absolute identities before tokenizer loading or output
creation, and regression tests require both reviewed command arguments to retain the complete
`-pre-output-stop-v1` suffix. V48 may use only the still-unattempted PR-2802 then PR-3204 schedule
under a fresh campaign, agent, opt-in, broker, and output identity. The provider, six-plane,
exact-64K, zero-retry, command-image, and stop policies remain unchanged. V48 authorizes no formal
collection, training, GPU work, or held-out loading; a successful canary still requires a separate
result audit and green post-merge main run.

The sole authorized v48 provider run consumed PR-2802 as an ordinary model/trajectory failure. It
made 43 provider calls in one episode, exhausted the fixed one-million-token budget, produced no
candidate write or patch, and failed the verifier, protocol, trajectory, and SFT-admission planes
while infrastructure and security remained valid. PR-3204 did not start. V48, its output, and
PR-2802 are frozen; the task cannot be retried under a larger budget, changed prompt, or successor
identity.

The separately versioned v49 authorization is a zero-provider replacement materialization. It
binds the complete v48 failed tree, attempt and security receipts, merged audit, green post-merge
main run, and `failed_task_retry_authorized=false`. It builds and v2-scans one fresh PR-2916
command image from that task's frozen public task/source/verifier lock and reuses only the
still-unstarted v33 PR-3204 validation binding. The repository-local isolated runtime,
export-safe receipt, conservative six-image headroom threshold, network-none, cleanup, atomic
progress, and no-Codex/no-credential controls remain mandatory. V49 has no provider or episode
surface and cannot execute a benchmark task, start collection or training, use a GPU, or load
held-out data. A future v50 canary requires a separate authorization after the v49 result audit
and may use only PR-2916 then PR-3204 with protocol v22, seed 497, and sample 13.

The sole authorized v49 execution successfully built and v2-scanned that fresh PR-2916 command
image while making zero provider calls and executing zero benchmark tasks. Its independent result
scan covered the complete seven-file tree, compared active sensitive values and execution roots
only in memory, and found no credential, proxy value, raw host path, unsafe filesystem entry, or
scanner error. No command container remains. V49 stays a sealed zero-provider materialization and
does not authorize canary execution or collection. Any v50 provider authorization must bind the
exact v49 tree, image lock, scan, catalog, contract, merged result audit, and green post-merge main
run before attempting PR-2916 followed by PR-3204.

The separately versioned v50 authorization binds that exact v49 result and the frozen v48 ordinary
failure, and permits only PR-2916 followed by PR-3204 under protocol v22, seed 497, and sample 13.
PR-2802 remains consumed and non-retryable. V50 stops after the first failed result plane, uses
task-locked Codex-free command images with `network=none`, and requires exact-64K decision-only
trajectory admission. It does not authorize formal collection, training, GPU work, or held-out
loading; even a passing canary requires a separate merged result audit and green main workflow.

The sole authorized v50 provider run consumed PR-2916 as an ordinary model/trajectory failure. It
made 40 provider calls in one episode, exhausted the fixed one-million-token budget, produced no
candidate write or patch, and failed the verifier, protocol, trajectory, and SFT-admission planes
while infrastructure and security remained valid. PR-3204 did not start. V50, its output, and
PR-2916 are frozen; the task cannot be retried under a larger budget, changed prompt, or successor
identity. Any successor must bind the complete failed tree, merged audit, and green post-merge main
run, use a new identity and unattempted training task, and preserve the same fail-closed controls.

The separately versioned v51 authorization adds only public CVA6 PR-2728 as an unattempted
training candidate and permits one zero-model base-FAIL/reference-PASS qualification. It binds the
complete v50 terminal evidence and green audit merge, the official dataset and selected-record
hashes, and a content-free compatible one-file patch-shape receipt. Dataset scanning extracts only
top-level PR numbers until the selected public row is found; held-out row values are never decoded,
selected into the temporary one-row dataset, loaded into Docker, or copied to output. Candidate
transfer alone may use `verigym-hwe-net`; verification remains `network=none`. Clean merged source,
Docker-root headroom, digest/config/tarball identities, non-root read-only transfer containers,
bounded content-free diagnostics, atomic progress, cleanup, and zero retries remain mandatory.
V51 has no provider, command-image build, canary, collection, training, GPU, or held-out authority.
Either an ordinary qualification mismatch or an infrastructure/security stop permanently consumes
the v51 attempt; a successful result still needs a separate audit before command-image work.

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

The separately versioned OpenHands behavior protocol v23 restores provider-default `auto` tool
choice for ordinary requests and accepts optional public rationale plus one or more typed calls.
Before returning a response to OpenHands, the local LLM subclass validates every sibling's exact
name, strict JSON object, HWE v2 schema, workspace-relative path, and shell-safety policy. One bad
sibling rejects the entire decision before dispatch. Accepted siblings use the SDK's fixed
single-worker executor and therefore run serially in provider order. Only the one private-state-
bound content recovery request uses `required`, and it accepts exactly one provider-emitted
canonical call. Private reasoning fields, hidden thinking blocks, foreign tools, a sibling
`finish`, counter drift, and caller-supplied tool choice fail closed. Provider-native hidden
thinking remains disabled, and v17-v22 behavior and evidence remain immutable.

V23 additionally enables the SDK stuck detector and a broker-owned pre-edit progress gate. The
broker hashes the effective editable workspace before and after each accepted action; if no
effective modification exists, action 16 appends one fixed public checkpoint and action 32 pauses
the conversation as the explicit infrastructure-valid `no_progress` behavior outcome. The first
effective modification permanently releases that gate. Model-visible `read_file` output is
bounded to 400 lines and 128 KiB. Shell stdout and stderr each retain an exact 64 KiB head and
64 KiB tail with omitted-byte count and full-stream SHA-256; a projection that cannot fit the
frozen context fails closed instead of silently dropping that boundary. Complete raw streams stay
only in the existing bounded, secret-scanned private sidecar. Successful v23 SFT export supervises
one complete assistant decision, including public rationale and all sibling calls; content-only
recovery and failed-tool decisions remain loss-masked context. Every row is re-tokenized with the
frozen exact Qwen tokenizer and is rejected above 65,536 tokens without truncation.

The v52 authorization is a zero-provider materialization identity only. PR-2728 transfer uses a
fixed persistent content-addressed layer cache with task-specific staging, digest-and-size
validation, same-filesystem atomic rename, and bounded digest/size/cache-hit inventory. Raw
transfer stderr is temporary; a failure receipt retains only byte count, SHA-256, and one closed
error family. Each temporary archive has one cleanup owner. The atomic stage sequence then
requires public base-FAIL/reference-PASS qualification under verifier `network=none`, the v2
Codex/credential/hidden-asset/network scan, a task-specific PR-2728 command-image lock, and
revalidation of the sealed PR-3204 lock before publishing a canary contract. Failure removes the
staging tree and publishes no partial canary authorization. V52 cannot invoke a provider, execute
the canary, start collection or training, use held-out data, or claim a benchmark result.

All trajectory formats reject private reasoning, thinking blocks, dynamic context, skills,
critics, unknown
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

The v69 successor materializes a five-task provider contract without constructing a provider
client or accepting a provider credential. Its immutable manifest records every selected,
fallback, reserved, historical, previously authorized, and provider-consumed public task known to
the campaign. Reference-patch compatibility and dataset/source identity are checked for all five
tasks before any image archive or Docker operation. Only completed local archives are accepted;
the archive SHA-256 sidecar, registry-manifest digest lock, Docker archive manifest, config digest,
repository base, source commit, and official verifier image must all agree. Registry access and
`.partial` archives are forbidden. Each task must independently reproduce base-FAIL and
reference-PASS with verifier network disabled and pass the task-specific command-image v2 scan.
The provider contract is published last and only when all five ordered task receipts pass; any
failure leaves progress evidence but no partial authorization. Even a complete v69 contract keeps
provider execution, formal collection, SFT training, and production readiness disabled pending an
independent successor audit.

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

A separately versioned zero-provider materializer may use the trusted non-root host control plane
instead of the project controller when no agent or provider process exists. That path must reject
provider configuration and any pre-existing Docker endpoint override, create a new campaign-bound
Unix socket, and route Docker commands to it only inside the bounded offline materialization
window. The sidecar may receive only the new campaign output root plus its sentinel and two
campaign-specific volumes. The data and socket volumes may use exact, owner-only bind backing on a
separate filesystem; their local-driver options and labels must be inspected before use so volume
metadata in the host Docker root cannot redirect task layers there. The persistent data volume may
retain only inner images. The provider contract is published only after the inner container and
volume inventories are empty, the sidecar is removed, and the transient socket volume and socket
are gone. The data volume remains labeled, identity-bound infrastructure for an independently
authorized successor.

If a predecessor's physical data-volume opening was observed but its logical reopen counter was
not persisted, the physical observation wins: that volume is frozen and a successor must use a
new exact bind backing and re-materialize from locked local archives. Opening is recorded
immediately after the outer sidecar starts, before readiness polling. An individual bounded
`docker info` timeout is a retryable not-ready observation; the enclosing startup deadline still
fails closed, removes the sidecar, and cannot publish a partial scaffold.

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

### Resumable HWE environment provisioning

OpenHands v55 separates registry-backed environment provisioning from public task qualification,
command-image security scanning, canary authorization, and provider execution. Provisioning owns
only an environment identity. It does not allocate a model, seed, sample, campaign, or provider
task identity, and a provisioning failure does not consume a benchmark task or a provider
behavior-failure slot. Historical v51--v54 identities and their one-shot failure receipts remain
immutable; this separation applies only to the explicitly authorized v55 protocol.

Each registry layer is downloaded into task-specific staging and must match the manifest-bound
size and SHA-256 before same-filesystem atomic publication into the fixed content-addressed cache.
V55 permits at most three attempts for one missing layer and at most three append-only provisioning
sessions for the same environment identity. A retry is permitted only for a closed allowlist of
DNS, timeout, connection/stream interruption, selected transient HTTP status, or task-staged
size/checksum failures. TLS, permission, disk-full, persistent-cache corruption, archive, unknown,
and policy failures stop without another session. Every failed partial layer is removed before a
retry; verified cache entries remain reusable.

Raw stderr remains transient and retains the existing 32 MiB command-output bound. A persisted
diagnostic contains only the closed family and reason, optional allowlisted HTTP status, retry
decision, byte count, SHA-256, and a statement that raw content was not persisted. Session
receipts are bounded, sequential, append-only, and state explicitly that no environment manifest,
provider identity, benchmark disposition, collection, or training was produced. Only a complete
digest-verified assembly may atomically publish the environment manifest. Provider retries remain
zero, verifier execution remains `--network none`, and later qualification/security/canary stages
require separate authorization after revalidating this manifest.

### DeepSeek Harness official-matrix execution on bind-backed DinD

HWE source preparation uses a caller-selected Docker control-plane timeout only when a reviewed
campaign manifest requires extra cold-start headroom. The default remains 60 seconds and the
integration rejects values outside the integer range 1--300 seconds before any Docker access.
The bound covers image inspection, runtime baseline reads, and container create/remove controls;
the existing 300-second repository-copy bound is unchanged. Extending this timeout does not
authorize a retry, network access, provider execution, verifier relabelling, or reuse of a frozen
Docker data root.

An audited zero-provider scaffold may authorize one official provider matrix only through
a new, merged, immutable manifest. The runner must bind the complete predecessor report,
contract, task/source/image locks, command-image scans, controller transfer provenance,
DinD runtime and cleanup receipts, independent audit commit, and its successful post-merge
main run. Partial authorization, task substitution, retry under the same identity, and
registry repair are forbidden.

The campaign reopens its purpose-bound DinD data volume at most once. The volume uses a
local-driver bind under the declared `/data2` campaign directory; it does not change the
host daemon data root. Its owner-only socket backing is recreated for the run and removed
with a networkless, read-only cleanup container holding only `CHOWN`, `DAC_OVERRIDE`, and
`FOWNER`. The runner never prunes Docker, restarts the daemon, changes VPN/proxy settings,
or removes unrelated resources.

Provider access is limited to the Harness controller on the named user-defined bridge.
Task and verifier containers remain `network=none`. The command image is credential-free,
Codex-free, task-specific, label-checked, digest-locked, and distinct from the official
verifier image. An offline-loaded controller is accepted only when its exact image ID,
canonical tag, empty inner `RepoDigests`, and audited source-receipt hash all match; this
exception does not permit a pull or weaken the ordinary repository-digest path.

The public provider-start marker defines consumption. Missing markers on infrastructure
failure preserve the task; invalid or unreadable markers are conservative consumed stops.
Infrastructure or security failures stop the matrix, ordinary model or verifier failures
may continue, and two consecutive no-progress-like outcomes stop remaining tasks. Each
attempt records verifier, protocol, trajectory, infrastructure, security, SFT-admission,
and exact-64K planes independently. Candidate SFT files are published only after all
planes pass and remain unauthorized for import until an independent result audit.

The separately authorized v121 startup diagnostic is narrower than a zero-provider scaffold. It
may inspect only the already-local immutable DinD image, create two fresh bind-backed volumes under
its exact `/data2` identity, and make one bounded outer-DinD startup attempt with `network=none`.
It cannot read a task archive, import or build an image, create an inner network, start Harness, or
construct a provider client. Docker control output is capped and reduced in memory to exit state,
byte counts, validated booleans, and one allowlisted category; raw output, output hashes, container
identities, environment values, and host paths are not persisted in diagnostic receipts.

V121 cleanup treats the main container, its networkless ownership-restoration helper, and each
volume as independent resources. A failed `docker run --rm` for the helper is followed by explicit
container removal, while volume removal is attempted separately and only after exact v121
owner/role/bind options are revalidated. Cleanup success additionally requires both backing
directories to be empty, owner-only, and returned to the invoking UID/GID. The frozen v118 volumes
and backing data are never inspected or mutated. A cleanup ambiguity fails closed and requires an
independent audit; v121 cannot authorize a provider contract or a five-task successor.

The separately authorized v123 identity probe is another one-use zero-provider diagnostic. It
uses only fresh v123 bind-backed volumes and may start one networkless DinD daemon after validating
the immutable v121 evidence and v122 audit. It determines the inner identity from one explicit
`docker info` formatter containing only server version, storage driver, and default runtime. The
older `docker version` formatter is diagnostic-only and cannot make an otherwise exact explicit
identity fail. Its stderr is mapped in memory to an allowlisted formatter, connection, API, or
other command category and is never persisted or hashed.

V123 receipts retain only bounded command metadata, selected-field presence/equality booleans,
and content-free categories. Raw output, exceptions, container identities, host paths, and
environment values remain prohibited. Cleanup validates the exact v123 owner, role, and bind
options before removing anything, restores the two empty backing directories to the invoking
UID/GID at mode `0700`, and fails closed on ambiguity. The probe cannot read tasks, create an inner
network, run a verifier or Harness, contact a registry/provider, or authorize a five-task scaffold
without an independent result audit.

The separately authorized v125 readiness probe consumes the audited v123 false-positive result and
uses only fresh v125 bind-backed volumes. Its sole inner readiness command formats server version,
storage driver, and default runtime explicitly. Exit zero is insufficient: readiness requires no
timeout or truncation, empty stderr, exactly three parsed values, and exact `23.0.6`, `vfs`, and
`runc` matches. Incomplete or connection-failure responses remain transient until a monotonic
120-second deadline with no smaller fixed poll-count cap. A clean complete response with different
values fails immediately as an identity mismatch.

V125 remains a one-start, zero-provider diagnostic with `network=none`. It may not read a task or
archive, materialize an image, start a verifier, Harness controller, or model, create a Docker
network, or access a registry. Receipts retain only bounded counts, equality booleans, timing state,
and allowlisted categories. Raw output, exceptions, container identities, environment values, and
host paths are not persisted or hashed. Exact owner, role, and bind validation precedes cleanup;
only an independent v126 audit may authorize any five-task successor.

The separately authorized v127 scaffold applies the audited v125 readiness predicate to the
frozen five-task v118 materialization path. Its fresh bind-backed data and socket volumes live
under the exact v127 `/data2` identity; predecessor Docker volumes are never inspected or mutated.
One outer DinD start is allowed. Every inner-Docker operation is gated by an explicit three-field
`docker info` response matching `23.0.6`, `vfs`, and `runc`, under a 120-second monotonic deadline,
five-second command limit, and no smaller fixed poll-count cap. JSON-formatted info is not a
readiness signal.

V127 remains provider-free. It may read only completed local archives, verifies every frozen
source/image/task lock and base-FAIL/reference-PASS result, and keeps all command and verifier
containers on `network=none`. Runtime preparation, full inner inventory, network control, and
streaming attach use the explicitly bound v127 Unix socket. All five tasks and deterministic
cleanup must pass before one atomic scaffold contract can be published. A partial contract is
forbidden, and an independent v128 audit is required before any provider execution.

The separately authorized v130 command-image probe narrows the successor work to Ibex PR-465 and
the scanner boundary that stopped v127. It uses a fresh VFS DinD data/socket identity under
`/data2`, revalidates the byte-exact audited v127 evidence without inspecting or mutating the
frozen v127 volume, and reads only the completed local PR-465 archive. Importing that immutable
task image and rebuilding the credential-free, Codex-free command image are allowed solely to
place the same task/toolchain binding in the fresh daemon. Task execution, base/reference
verification, Harness initialization, registry access, model startup, and provider access remain
forbidden.

V130 assigns the scan container a deterministic owner/name identity and bounds Docker create,
each inspect, diagnostic start, removal, and the overall scan at 300, 60, 180, 120, and 720 seconds
respectively. The scanner retains only byte counts, empty-stream hashes, allowlisted categories,
control booleans, and the frozen timeout policy; nonempty output and raw exceptions are neither
persisted nor hashed. A timed-out create triggers deterministic name-based removal, and final
success additionally requires an empty all-container/all-volume inventory on the explicitly bound
inner daemon. The outer daemon uses `network=none`; the scan container remains non-root,
read-only, capability-free, no-new-privileges, resource-bounded, and limited to one workspace
mount.

V130 is one-shot and requires its implementation merge plus all eight post-merge `main` checks.
Cleanup validates exact v130 ownership before removing the outer container or bind-backed volumes,
uses a networkless least-capability helper to restore only the fresh backing paths, and must be
confirmed even after scan failure. The probe can publish evidence only, never a provider contract;
an independent v131 audit is required before deciding any later scaffold or provider authorization.

The separately authorized v132 scaffold applies the v130 bounded command-image scanner to the
complete frozen five-task v127 schedule. It revalidates the byte-exact v127, v128, v130, and v131
inputs and uses only fresh v132 bind-backed data and socket volumes under `/data2`. The predecessor
Docker volumes remain forbidden to inspection or mutation. Every task is read only from its
completed local archive; registry access and `.partial` archives are forbidden.

For each of Ibex PR-465, PR-1135, PR-1780 and CVA6 PR-2017, PR-2711, the security-scan container
has a deterministic task-specific name and v132 owner labels. Docker create, each inspect,
diagnostic start, removal, and the overall scan are bounded at 300, 60, 180, 120, and 720 seconds.
Receipts retain no raw Docker output or exceptions and do not hash nonempty diagnostic output.
The command image remains credential-free, Codex-free, non-root, read-only, capability-free,
resource-bounded, `network=none`, and limited to one writable workspace mount. Official verifier
containers also remain `network=none`, and command-image results cannot replace official verifier
results.

V132 remains zero-provider and permits one startup attempt only after its implementation merge and
all eight post-merge `main` checks. All five tasks must independently satisfy archive, source,
image, command-toolchain, base-FAIL/reference-PASS, security-scan, and empty inner-inventory gates
before one atomic scaffold contract can be published. Any partial result is non-authorizing.
Infrastructure or cleanup ambiguity stops fail-closed and freezes the exact owned data volume for
independent analysis; it never permits broad deletion. An independent v133 result audit and a
separate merged v134 authorization are required before any provider request. Collection, SFT
training, and production readiness remain closed.

The separately authorized v134 official matrix binds the byte-exact v132 tree and merged v133
audit, and reuses the retained v132 DinD data volume exactly once. The predecessor data volume
keeps its v132 owner label; only the recreated socket volume, provider DinD sidecar, and cleanup
helper use the v134 runtime owner. This owner split prevents a successor from relabeling or broadly
claiming predecessor storage. The v92 runner and manifest are hash-bound only as the audited
provider-protocol baseline; v134 uses fresh campaign, episode, progress, attempt, decision, and
dataset identities and the fresh v132 task-specific command-image locks.

V134 permits the fixed PR-465, PR-1135, PR-1780, PR-2017, PR-2711 order with seed/sample `502/18`,
DeepSeek v4 Flash, Harness `0.1.1-rc.2`, 64 calls and 1,000,000 provider tokens per task, 65,536
context tokens, 2,048 output tokens, temperature zero, and no request or episode retry. Only the
outer provider DinD and inner controller use `verigym-hwe-net`; task command and official verifier
containers remain `network=none`. Agent-toolchain diagnostics remain non-authoritative and cannot
replace the separately bound official verifier result.

An infrastructure or security invalidity stops immediately. An ordinary model or verifier failure
consumes its task and may continue, while two consecutive no-modification, no-progress, or
trajectory-structure failures stop the remainder. Every candidate requires all six admission
planes, the exact Qwen tokenizer, decision-only masking, at most 65,536 tokens per decision, and no
truncation. V134 may list candidates pending an independent v135 audit, but cannot import them,
start formal collection or training, claim a benchmark score, or authorize production use.

The sole v134 execution stopped during its zero-provider PR-465 command-runtime preflight with the
allowlisted exception class `DockerImageError`. The public provider marker remained absent and no
provider episode, call, token, task modification, verifier run, or trajectory occurred, so all five
tasks remain provider-unconsumed. The v132 data-volume reopen budget was nevertheless consumed when
the provider DinD started. V134 and that retained volume are frozen. A successor must use fresh
`/data2` volumes and a new identity, record only an allowlisted content-free image-error subreason,
and complete an independently audited zero-provider diagnostic before any new provider
authorization. It may not diagnose by reopening or internally inspecting the v132 data volume.

The separately authorized v136 diagnostic uses a new bind-backed VFS DinD data/socket identity
under `/data2` and may read only the completed local PR-465 archive. It independently rebuilds and
v2-scans the credential-free command image, transfers only the trusted workspace-runtime image
from the host Docker image store. Because Docker creation metadata makes IDs unstable across clean
rebuilds, it requires the new lock's task, source, toolchain, protocol, environment, tool hashes,
security properties, and execution backends to equal the frozen v132 semantic baseline while
assigning fresh image, scan, and lock identities. The frozen v132 Docker volume is neither reopened,
inspected, nor mutated. Registry access, `.partial` archives, task execution, base/reference verification,
Harness startup, provider configuration, and model calls remain forbidden.

V136 runs exactly two content-free preparation probes with the same v134 runtime configuration.
The first reproduces the inherited-environment construction and may retain only an allowlisted
`DockerImageError.subreason`; raw exception text, details, and Docker output are not persisted or
hashed. The second injects a `DockerCliEngine` explicitly bound to the canonical fresh nested Unix
socket and must pass with an empty inner container/volume inventory. The diagnostic succeeds only
when the first probe reports `image_missing`, the explicitly bound probe passes, and deterministic
owner-checked cleanup restores and removes only v136 resources. It is one-shot, requires its
implementation merge and eight green post-merge `main` check classes, and produces evidence for an
independent v137 audit only; it does not authorize provider execution or collection.

The sole v136 execution stopped during local PR-465 task-image import after the trusted
workspace-runtime transfer and before any command-image build, runtime probe, task execution,
Harness startup, or provider request. Its broad controller boundary retained only
`unexpected_controller_failure`, so the intended nested-endpoint diagnosis was not reached and
must not be inferred. The cleanup controller timed out just before its exact owner-scoped helper
exited zero; independently verified late cleanup removed only the v136 helper and two empty
bind-backed volumes. V136 remains failed and frozen. Any successor must use fresh `/data2`
resources, retain stage-specific allowlisted import diagnostics without raw output, and establish
an explicitly bound nested Docker endpoint before a separate provider authorization.

The separately authorized v138 scaffold returns to the audited v132 five-task materialization path
with a fresh identity and fresh bind-backed VFS DinD volumes under `/data2`. It validates the
completed local tar and immutable image metadata for each task, then runs every load, image-ID
check, and tag operation through an environment explicitly bound to the exact v138 Unix socket.
Each import produces a stage-specific receipt containing only exit codes, byte counts, bounds, and
an allowlisted category; raw output and exceptions are neither persisted nor hashed. Registry
access, `.partial` archives, provider configuration, and all v132 volume access remain forbidden.

V138 retains the v132 base-FAIL/reference-PASS checks, task-specific credential-free command-image
build, v2 scan, and five-task runtime-prepare preflight. The preflight injects a
`DockerCliEngine` with the exact nested endpoint for every runtime and requires empty bound inner
container/volume inventories. A task import, materialization, security, infrastructure, or cleanup
failure prevents the atomic scaffold contract. Success retains only the exact v138 data volume for
one separately audited and authorized successor; v138 itself cannot contact a provider or start
collection or training.

The sole v138 execution explicitly imported and identity-checked the completed local PR-465 HWE
image, then reproduced base-FAIL without an infrastructure error. Its reference verifier returned
an infrastructure timeout with no execution metadata or output and therefore did not establish
reference-PASS. V138 stopped before command-image build, scan, runtime preparation, Harness, or any
provider request; its atomic scaffold contract was not published and all five tasks remain
provider-unconsumed. The planned v140 official matrix identity is consequently unreachable and is
not authorized. V138 and its retained owner-labelled data volume are frozen. A provider-free
successor must use fresh `/data2` resources, record separate content-free Docker verifier control
stages, and may widen only the cold-VFS Docker control bound while leaving official verifier
semantics and test timeout unchanged.

The separately authorized v140 verifier-control scaffold is that provider-free successor. It
uses fresh bind-backed v140 VFS data/socket volumes under `/data2`, imports only completed local
archives through the exact nested Unix socket, and never opens the frozen v138 volume. Docker
image inspection, verifier cache-volume creation/removal, verifier-container creation/removal,
and cleanup have a distinct maximum 300-second control bound. The official verifier execution
retains its unchanged 900-second test timeout, task script, image binding, result semantics,
resource profile, and `network=none` isolation.

Every successful base and reference verifier result must record the completed control stage, both
timeout values, network isolation, and successful container cleanup. The campaign promotes only
allowlisted status, category, numeric, and boolean fields into a self-hashed control diagnostic;
raw output and nonempty output hashes are excluded. Any control timeout, cleanup ambiguity,
base infrastructure error, missing reference PASS, import failure, scan failure, or partial
five-task result prevents the atomic scaffold contract. V140 has no provider surface and can
produce evidence only for a v141 audit. A later official DeepSeek attempt requires a distinct v142
authorization after that audit is merged and its post-merge `main` checks pass.

The sole v140 execution completed all five base-FAIL/reference-PASS qualifications, command-image
v2 scans, runtime-preparation probes, and the synthetic zero-provider Harness initialization. It
then stopped before atomic contract publication because both the primary and best-effort
socket-cleanup helpers exceeded the inherited 60-second controller timeout in created state. No
provider request or model process started. An independently bounded late cleanup validated the two
exact owner-labelled helpers, removed one duplicate, started the other with a 300-second wait, and
confirmed its zero exit, auto-removal, empty restored socket backing, socket-volume removal, and
absence of v140 containers. Only the exact v140 data volume remains frozen under `/data2`.

The late cleanup does not repair or relabel the immutable failed report. V140 and its planned v142
official-matrix successor are not executable. A provider-free successor must rematerialize into
fresh `/data2` volumes and may widen only the socket-cleanup control wait to 300 seconds while
retaining the qualified task, verifier, scanner, runtime, and zero-provider semantics. It requires
another independent audit before any DeepSeek authorization.

The separately authorized v142 cleanup-control scaffold is that provider-free successor. It uses
fresh bind-backed v142 VFS data/socket volumes under `/data2` and never opens the frozen v140 data
volume. The five-task schedule, local completed archives, verifier-control split, official test
semantics, task-specific v2 command-image scans, runtime probes, and synthetic zero-provider
Harness initialization remain unchanged. Only the socket-cleanup controller wait and exact
socket-volume removal wait are widened from the inherited 60 seconds to a maximum of 300 seconds.

Each cleanup attempt uses an exact v142 owner-labelled, `network=none`, read-only-root,
capability-minimized helper. Its receipt and separate stage diagnostic retain only allowlisted
status, category, exit-code, byte-count, timeout, ownership, mode, and cleanup fields. Raw output,
raw exceptions, and nonempty output hashes remain forbidden. A timeout, nonzero helper result,
oversized output, failed socket-volume removal, or unconfirmed empty restored backing prevents the
atomic scaffold contract. V142 has no provider surface and can produce evidence only for a v143
audit. Only a successful v142 contract followed by the independent merged v143 audit and green
post-merge `main` checks may authorize the distinct v144 official DeepSeek matrix identity.

The sole v142 execution completed all five local archive imports, base-FAIL/reference-PASS
qualifications, task-specific command-image builds, and v2 scans. It also fixed the v140 cleanup
blocker: the exact owner-scoped helper and socket-volume removal both completed under their new
300-second control bounds, the socket backing was restored empty, and no v142 container remains.
V142 nevertheless stopped fail-closed during the first DockerRuntime command-image identity probe,
before a runtime-preparation receipt, Harness initialization, scaffold publication, model process,
or provider request. Its planned v144 official-matrix identity is unreachable and unauthorized.

The inherited command-image probe has a hard 60-second maximum and can report a combined failure
for an engine error, timeout, OOM kill, output truncation, or nonzero exit. V142 retained only the
exception type, so no specific member of that set is proven. Its exact data volume and evidence
tree are frozen and must not be reopened, inspected, mounted, mutated, retried, or promoted. A
fresh provider-free successor may use new `/data2` resources, an allowlisted content-free probe
diagnostic, and an explicit probe-control bound of at most 300 seconds while leaving image
identity, probe semantics, runtime limits, and Harness behavior unchanged. It requires another
independent audit before any later unused official DeepSeek identity can be authorized.

The separately authorized v144 command-probe control scaffold is that provider-free successor.
It uses fresh v144 bind-backed VFS data/socket volumes and never opens the frozen v142 data volume.
The five-task schedule, completed local archives, official verifier semantics, task-specific v2
command-image scans, and synthetic network-isolated Harness initialization remain unchanged.
Existing command-image configurations retain their 60-second probe default; v144 explicitly binds
each of its five command-image identity probes to a maximum 300-second control timeout.

The v144 probe diagnostic retains only fixed task identity, allowlisted subreason and protocol,
failure reason/origin, timeout/OOM/truncation booleans, exit code, and the fixed control bound. Raw
output, raw exception text, arbitrary detail fields, and nonempty output or exception hashes are
forbidden. All five probes and empty inner inventories must pass before atomic publication. V144
has no provider surface and can produce evidence only for an independent v145 audit. The retired
v144 official-matrix identity remains unusable; a later official matrix requires a distinct unused
identity, a successful v144 contract, the merged v145 audit, and green post-merge `main` checks.

The sole v144 start stopped at the outer execution boundary because the launcher removed only a
documented subset of the complete provider-configuration environment-name set. No output root,
Docker backing path, volume, container, archive import, task verifier, Harness process, or provider
request was created or started, and all five tasks remain provider-unconsumed. Values were never
printed, persisted, or hashed. V144 is nevertheless consumed by its one-shot start, and its planned
v146 official-matrix successor is unreachable. A fresh provider-free successor must use a new
identity and resources and must derive its sanitized child environment from the exact same frozen
provider-name set enforced by the runner before it can repeat the v144 scaffold behavior.

The separately authorized v146 environment-boundary scaffold is that provider-free successor. Its
launcher compares the manifest with the exact 12-name provider set enforced by the runner, adds
the two Docker endpoint names, and selects allowed environment entries by name before reading any
value. It never reads, prints, persists, or hashes a blocked value. The child receives only the
v146 opt-in and fixed boundary marker in addition to allowed entries; the runner validates the
same set and marker before output or Docker resource creation, and the inherited boundary checks
absence independently. Hand-maintained `env -u` lists are not an authorized substitute.

V146 otherwise repeats the v144 five-task, local-archive, base-FAIL/reference-PASS, bounded-scan,
300-second command-probe, synthetic Harness, and exact cleanup semantics in fresh bind-backed
`/data2` resources. It has no provider surface and can publish only an atomic scaffold pending an
independent v147 audit. The v146 official-matrix identity is retired; any provider execution moves
to a distinct later identity after successful audit and eight green post-merge `main` checks.

The sole v146 execution fixed the environment boundary and passed all five local archive imports,
base-FAIL/reference-PASS qualifications, command-image v2 scans, 300-second command-image probes,
empty inventories, and synthetic Harness initialization. It stopped only after the outer DinD was
removed, when the inherited v142 cleanup implementation rejected the correct v146 socket volume
against a literal v142 volume name. No provider request or model process started. The v146 data
and socket volumes and evidence are frozen; no v146 container remains. A provider-free successor
may use fresh `/data2` resources and change only cleanup identity binding so the exact successor
manifest volume, owner, and backing replace the predecessor literal. It requires an independent
audit before any later provider identity can be authorized.

The separately authorized v148 cleanup-identity scaffold is that provider-free successor. It
repeats the audited v146 schedule, completed local archives, official verifier controls,
task-specific v2 command-image scans, 300-second command probes, and synthetic network-isolated
Harness initialization in fresh v148 bind-backed `/data2` resources. It does not inspect, mount,
mutate, remove, or otherwise reuse either frozen v146 volume.

V148 replaces cleanup delegation with a locally implemented, fail-closed cleanup function. Before
any Docker operation, that function requires the exact current manifest's v148 socket-volume name,
owner identity, and backing path, plus the fixed cleanup policy. Its capability-minimized helper
uses `network=none`, a read-only root, and only the current v148 socket volume. The removal command
uses the same manifest value, and publication still requires an empty mode-0700 backing restored to
the caller. A predecessor literal, changed owner or backing, timeout, nonzero result, oversized
output, failed volume removal, or failed backing confirmation prevents publication. Raw output,
raw exceptions, and nonempty output hashes remain forbidden. V148 has no provider surface and can
produce evidence only for an independent v149 audit; only that merged audit and eight green
post-merge `main` check classes can authorize the distinct v150 official matrix identity.

The separately authorized v150 matrix is the sole provider-bearing successor to the audited v148
scaffold. It may reopen the exact retained v148 data volume once and must create a v150-owned
socket volume over the already restored v148 socket backing. The launcher removes the complete
12-name provider configuration set and both Docker endpoint variables before copying back only the
two names required by the DeepSeek Harness process. It reads no blocked alias value, and the runner
requires that exact child boundary before output creation or Docker access. Concrete provider and
proxy values are never printed, persisted, or hashed.

V150 binds both the v92 wire-protocol baseline and the v134 official-matrix implementation
baseline, then uses only the fresh task/source/image locks published by v148. Its zero-provider
preflight repeats every task-specific command-runtime preparation with a 300-second image probe,
uses the v148 120-second monotonic DinD readiness policy, and requires the complete 12-image nested
inventory before the first provider request. Only the outer DinD sidecar and inner Harness
controller use the named `verigym-hwe-net` bridges. Task and official verifier containers retain
`network=none`, separate workspaces, non-root execution, read-only roots, capability removal,
bounded resources, and exact agent-toolchain/verifier-image roles. Host `LocalRuntime`, registry
access, partial archives, and task substitution remain forbidden.

Tasks execute strictly as Ibex PR-465, PR-1135, PR-1780, then CVA6 PR-2017 and PR-2711 under the
single-use provider-marker policy. A pre-marker infrastructure or security failure stops without
task consumption; the same failure after a valid or conservatively unreadable marker consumes the
current task and stops. Ordinary model or verifier rejection consumes the task and continues, but
two consecutive no-progress, no-effective-modification, or trajectory-structure outcomes stop the
remainder. Every admitted decision uses the exact Qwen tokenizer, is strictly shorter than 65,536
tokens, applies no truncation, and supervises only the complete assistant decision.

All output is pending an independent v151 audit. Passing official-route trajectories may only be
listed as candidate SFT inputs; failed or verifier-rejected trajectories remain audit context.
V150 cannot import candidates, begin formal collection or SFT, use a GPU, claim a benchmark score,
or authorize production training. Its 300-second cleanup helper accepts only empty output and
must remove the exact v150-owned socket volume while restoring the fixed backing to empty mode
`0700`; the v148 data volume remains frozen after the single reopen.

The sole v150 execution stopped before its DinD daemon or provider boundary because the host
containerd shim had insufficient space on `/`. V150 is frozen. The separately authorized v152
host-headroom scaffold is the provider-free prerequisite imposed by the v151 audit. Before Docker
access it requires at least 4 GiB and 100,000 available inodes on the host root filesystem. It uses
only fresh v152 bind-backed data and socket volumes under `/data2`, starts the exact local
`docker:23.0.6-dind` image once with outer `network=none`, and applies the audited explicit
three-field, 120-second readiness predicate.

V152 then requires empty inner container, image, volume, and custom-network inventories. Cleanup
may remove only exact v152-owned resources; its bounded, networkless helper must emit no output,
both volumes must be absent, both backings must be restored empty at mode `0700` to the caller, and
the same host-root headroom gate must pass afterward. It does not inspect, mount, mutate, or reopen
the retained v148 data volume or its socket identity, and it has no task, archive, verifier,
Harness, model, registry, or provider surface. A complete atomic scaffold contract remains
non-authorizing until an independent v153 audit is merged and eight post-merge `main` check classes
pass.

The separately authorized v154 matrix is the one-use replacement for the frozen v150 execution.
It preserves the exact v150 task order, seed/sample, provider protocol, command images, official
verifiers, exact-tokenizer admission, consumption, stopping, and network controls. It additionally
binds the complete v150 failure and cleanup-recovery evidence, the v151 audit, all eleven v152
scaffold evidence files, the v153 audit, and their green post-merge `main` gates. Neither v150 nor
v152 may be rerun or relabelled.

Before any Docker access, v154 persists an absolute host-root headroom receipt requiring at least
4 GiB and 100,000 available inodes. A rejected gate cannot invoke even Docker cleanup and stops
with zero provider calls and zero v148 data-volume reopens. After a passed gate, v154 may reopen
the exact retained v148 data volume once while creating a fresh v154-owned socket volume and fresh
socket, control, runtime, output, and receipt identities under `/data2`. The outer DinD sidecar and
inner provider controller alone may use `verigym-hwe-net`; agent command images and official
verifiers remain `network=none`. The v154 result stays pending an independent v155 audit and cannot
start formal collection, candidate import, SFT, GPU work, held-out access, or production training.

The sole v154 execution stopped during the first zero-provider command-runtime preparation with
`DockerImageError`, marker `not_started`, zero provider calls or tokens, no task consumption, and
confirmed cleanup. V154 is frozen. Its retained v148 data-volume reopen allowance is exhausted.
The v155 audit permits only a fresh v156 command-runtime diagnostic; it does not authorize a
provider retry.

V156 uses new bind-backed data and socket volumes under `/data2`, reads only the completed and
SHA-verified PR-465 archive, and never mounts or inspects the retained v148 data volume. It starts
one networkless DinD, imports through the exact nested Unix socket, transfers the locked workspace
runtime from the exact local host image, and rebuilds a semantically equivalent task command
image. It compares one unbound Docker runtime preparation with one explicitly bound
`DockerCliEngine(docker_host=...)` preparation. Only allowlisted Docker image subreasons and
content-free probe metadata may be recorded; raw exceptions, Docker output, credentials, task
execution, Harness/provider startup, collection, and training remain forbidden. V156 must clean
all fresh resources and requires an independent v157 audit plus eight green post-merge `main`
checks before any new provider identity can be considered.

The v156 comparison proved that the local images and command image are valid when the runtime is
explicitly bound to the fresh nested Unix socket; the unbound path instead queried the host daemon
and reported `image_missing`. The independent v157 audit and its eight green post-merge `main`
checks authorize only the provider-free v158 transport qualification.

V158 adds an optional explicit local Unix-socket binding to the Docker runtime template. The
template creates a fresh CLI engine for every configured task runtime, so closing one task cannot
close the next task's transport. The DeepSeek Harness settings validate the same canonical,
non-symlink Unix socket, include the binding in the configuration fingerprint, use it for controller
image inspection, and pass it explicitly to the agent's controller helper. TCP endpoints, ambient
Docker contexts, and simultaneous injected-engine/endpoint configuration fail closed. V158 must
re-import and qualify all five completed local task archives into a new `/data2` DinD data volume;
it cannot inspect or mutate retained predecessor volumes and cannot access a registry or provider.
Even a complete v158 scaffold is non-authorizing until an independent v159 audit is merged and all
eight post-merge `main` check classes pass.

The sole v158 execution completed all five offline task qualifications and both explicit-endpoint
preflights, but its final contract publication failed closed because the sealed Harness receipt
recorded separate `values_persisted=false` and `values_hashed=false` facts without the legacy
aggregate field required by the inherited v97 contract builder. V158 is frozen and must not be
rerun. Its independent v159 audit and eight green post-merge `main` check classes authorize only
the provider-free v160 contract repair.

V160 revalidates the complete immutable v158 evidence tree and every bound implementation and
receipt hash. It may query only the retained v158 Docker data volume's metadata and usage state;
it cannot mount, inspect, mutate, remove, or reopen that volume. The missing legacy aggregate is
derived only when both sealed split facts are false and the synthetic-value scan is empty, then
the original v158 pure contract-builder chain is rerun in memory against schedule-ordered copies
of the persisted inventories. No predecessor file is changed. Publication is atomic and occurs
only if the reconstructed contract is complete, the provider-free child boundary is exact, and
all five formal collection and training flags remain false. V160 has no registry, task execution,
Harness process, model, credential, collection, or training surface. Its output is non-authorizing
until an independent v161 audit is merged and all eight post-merge `main` check classes pass; only
that later gate may authorize the distinct v162 provider identity to reopen the frozen data volume
once.

The independent v161 audit and all eight post-merge `main` checks passed. V162 is the sole one-use
provider successor. It revalidates the complete v158 and v160 evidence trees, then may reopen only
the retained v158 data volume once with a fresh v162 socket, control, runtime, output, and receipt
identity under `/data2`. It does not pull, import, rebuild, substitute, or use partial task images.
The real runtime registry creates a fresh Docker CLI engine explicitly bound to the v162 nested
Unix socket per configured task, and the Harness settings fingerprint and forward that same
endpoint to the controller helper. Agent command and official-verifier sessions remain
`network=none`; only the outer DinD and inner controller use `verigym-hwe-net`.

V162 preserves the strict five-task order, provider budgets, marker-based consumption, bounded
continuation, six-plane admission, and exact untruncated 64K decision checks. Provider values are
temporary and never printed, persisted, or hashed. Its output remains candidate-only and pending
an independent v163 audit; formal collection, SFT, GPU work, benchmark-score claims, and production
training remain closed.

The independent v163 audit froze the v162 pre-provider Harness initialization failure and permits
only a separately authorized v164 controller diagnostic. V164 may reopen the retained v158 data
volume once under a fresh socket, control, runtime, output, and receipt identity, but it cannot run
a task, invoke an official verifier, access a registry, or issue a provider request. The launcher
removes the full provider and Docker-endpoint environment-name set before reading any blocked
value. The child uses a random synthetic key and a loopback-only URL solely while initializing the
exact audited controller. A private first-request marker is a hard failure, and all private
controller state is scanned for those synthetic values and removed before publication. The result
retains only a fixed structured category, bounded counts, hashes of non-secret receipts, and
content-free Docker control facts; raw helper exceptions, stderr, and synthetic values are neither
persisted nor hashed. A direct container probe first checks the explicit nested endpoint, immutable
image, exact mounts, non-root and read-only execution, resource limits, capabilities, namespaces,
network, and absence of provider environment names. V164 is one-use, pending an independent v165
audit, and cannot authorize a replacement provider matrix or any collection or training state.

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
