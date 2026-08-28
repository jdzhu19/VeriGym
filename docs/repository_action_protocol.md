# Repository Action Protocol v2

`repository_action.v2` is VeriGym's provider-neutral, versioned action contract for bounded
repository-repair agents. Provider transport extraction and canonical action validation are
separate. A model client may supply `json_content` or `native_tool_call`; an experiment binds one
transport before planning. The M12A conformance pilot binds `json_content`.

The protocol envelope remains `repository_action.v2`, while the frozen state-machine and prompt
contract are versioned separately. Legacy `repository_action_state_machine_v1` requires a public
test observation before finish. `repository_action_state_machine_v2` requires it only when the
task declares public tests, allowing HWE repository tasks to use `apply_patch`, `inspect_diff`,
and `finish` without inventing a model-visible test. A frozen descriptor binds the selected
state-machine and prompt hashes, so the two semantics cannot be silently substituted.

AgentEval resolves `repository_action_state_machine_v3` while retaining the same v2 envelope,
six actions, and action-registry hash. A successful patch invalidates compile, PPA, and diff
evidence. PPA requires a compile pass for the same candidate hash; finish requires a current diff
and a current compile pass when the task exposes compile. See [RTL AgentEval v1](rtl_agent_eval.md).
Commercial VCS/DC MCP backends are never added to this six-action registry. A verifier/toolchain
profile is resolved in the trusted control plane before model lookup. Phase-two DC feedback still
arrives through `run_public_test("ppa")`; the control plane dispatches a disposable worker only
after the current candidate passes compile.

`agent_feedback_contract.v2` separates repository-action calls from synthesis executions. Cache
hits remain calls but not executions; a worker dispatch consumes an execution even if the flow
times out or crashes, while a pre-dispatch rejection does not. The observation declares metric
direction and retains only the last valid candidate metric vector. It never restores an older
candidate automatically, so the v3 finish rule continues to bind the latest revision.

Each completion represents exactly one object with `protocol`, `action`, and `arguments` fields.
The registered actions cover visible file listing and reads, unified-patch application, registered
public tests, repository diff inspection, and candidate finish. The registry's strict schemas
generate both the prompt contract and its frozen identity. General shell, network access, hidden
assets, reference patches, and unrestricted paths are never exposed.

Normalization is deliberately representation-only: UTF-8 decoding, one leading BOM, line-ending
normalization, outer whitespace stripping, and at most one response-wide JSON or unlabeled
Markdown fence. VeriGym never extracts JSON from prose, repairs syntax, coerces argument types,
renames actions, chooses between actions, or reprompts an invalid response. Rejections use stable
subcategories such as `agent_empty_output`, `agent_malformed_json`, `agent_multiple_actions`,
`agent_unknown_action`, and `agent_invalid_state_transition`.

## Repository conformance fixtures

The independent Apache-2.0 `repo-api-protocol` suite contains three synthetic tasks:

- `repo-api-protocol/protocol-valid-hold` exercises a one-file patch and public feedback.
- `repo-api-protocol/protocol-dual-fix` requires a two-file patch.
- `repo-api-protocol/protocol-pipeline-flush` exercises public feedback and candidate freeze.

All use the ordinary planner, batch runner, Docker workspace, trusted public-test launcher,
candidate freeze, and separate Icarus 12 hidden verifier. Per-turn raw/normalized hashes,
normalization decisions, validation results, action/tool linkage, state transitions, and terminal
taxonomy are persisted for deterministic zero-network replay. Credentials remain in the trusted
controller and never enter the agent or verifier container.

Teacher transcript capture is a separate, explicit training-only broker mode. The provider event
stream supplies assistant call IDs and canonical arguments; the broker-owned capture supplies the
exact public observation that crossed the repository boundary. Export requires the ordered tool
names and arguments to agree. Ordinary audit mode remains content-free, and enabling capture for a
held-out campaign is rejected before the broker starts.

## Online rLLM repository workflow

`VeriGymRepositoryWorkflow` uses rLLM's `Workflow`, `RolloutEngine`, and trainable
`Episode`/`Trajectory`/`Step` records. Every model turn emits exactly one protocol action and keeps
the original prompt IDs, completion IDs, and log probabilities. A hash-bound filesystem broker
delegates actions to a host-owned VeriGym episode. The training container receives neither the
prepared source root, Docker socket, hidden assets, nor reference patch; it receives only bounded
public observations and the final sparse outcome. veRL remains the training backend through the
existing rLLM `AgentTrainer` path.

Turn responses and episode termination use distinct immutable files. A turn response is never
replaced after the trainer has consumed it; the broker publishes the sparse outcome once as
`terminal.json`. The workflow waits for that terminal concurrently with every model generation.
If the host-owned episode ends while the model is producing its next action, the workflow cancels
the now-obsolete generation and closes the trajectory from the terminal outcome. The HWE episode
has one 3600-second session deadline, followed by a 3900-second broker-terminal grace and a
4200-second outer workflow deadline. A missing model action at the episode deadline is a model
timeout with reward zero, while a missing or invalid broker terminal remains an infrastructure
failure.

Large repositories use `verigym_repository_context_projection_v1`: the broker converts the full
flat tree into a deterministic shallow directory outline and shallow-first bounded file sample,
with exact included/omitted counts. Each turn is a self-contained rolling context containing the
latest bounded tool observation and an identity-bound summary of the immediately preceding action;
older turns are retained only in a fixed-size rolling summary, so raw action and observation
history is not appended indefinitely. The task description, action contract, state, and sparse
terminal outcome are unchanged by this projection.
