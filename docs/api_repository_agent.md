# API-Backed Repository Agent

VeriGym's `openai-compatible` model client provides a provider-neutral, bounded
chat-completions transport. Configure provider and model identity, a base-URL environment name,
and a credential environment name through `ModelRunConfig`; credential values are read only by
the trusted controller at request time and never enter descriptors, hashes, traces, or reports.
The client rejects non-2xx responses, malformed or oversized JSON, missing content, inconsistent
usage, and requested/observed model mismatch when exact identity is required.

The `api-repository-agent` reads only the task's visible issue, public-test contract, README, and
declared RTL entrypoints through ordinary `file.read` actions in the Docker workspace. It makes
one model request for a strict four-action plan: one unified patch, one declared public test,
`file.diff`, and final submission. The existing workspace policy validates every action; policy
violations remain safely contained outcomes. Candidate freezing, deterministic patch
reapplication, public tests, hidden Icarus verification, reporting, and replay all use the
ordinary repository-repair path.

The agent accepts an explicit `max_output_tokens` execution option. The effective limit may only
tighten a task-level limit and is included in the agent-configuration identity. Frozen evaluation
uses the ordinary `agent_version_id`, `agent_version_hash`, and bounded manifest options, so the
resolved prompt policy records the exact immutable agent version without inserting repository
contents into that version manifest.

For real providers, launch VeriGym from a trusted shell and supply only environment variable
names in configuration. Keep Docker `environment_allowlist` empty unless a non-secret task value
is explicitly required. The repository-agent and verifier containers receive neither API
credentials nor controller proxy credentials. Replay reads sealed artifacts only and does not
instantiate the model client or access the network.

## Frozen API repository campaigns

`scripts/run_api_repository_campaign.py` is the independent provider-neutral campaign entry
point. It accepts repeated `--source-task SOURCE::TASK_ID` selections, persists progress after
every task, stops on the first infrastructure-invalid result, and never retries or performs
best-of-K selection. Held-out mode requires the complete content-free split freeze and exact
agent-version manifest before it creates the output directory. It verifies the complete task set,
task/source hashes, current clean source commit, agent descriptor, model/reasoning/auth semantics,
secret-free API request-policy hash, and all outer, agent-role, and suite-managed image IDs.

DeepSeek evaluation should use `thinking_mode=disabled` with an explicit output cap. The campaign
runner defaults to 16,384 output tokens; a frozen campaign binds the effective value in both the
request-policy and agent-version hashes. The provider request remains in the trusted host
controller; both Docker roles use `network_mode=none` and an empty environment allowlist. Only the
credential and base-URL environment variable *names* are recorded. The opt-in environment variable
`VERIGYM_RUN_API_REPOSITORY_CAMPAIGN=1` is required, and the named variables must already exist in
the trusted launching shell.

Tasks that intentionally expose no public test, including HWE repo-repair tasks, use the frozen
`strict_three_action_repository_repair_v1` response protocol: apply one patch, inspect the diff,
then submit. Tasks with declared public-test IDs keep the four-action protocol. The three-action
protocol is rejected for tasks that do expose public tests; it changes neither hidden-verifier
execution nor verifier isolation.

For multi-turn provider-neutral agents, use `provider-neutral-api-repository-agent` with the
versioned [`repository_action.v2`](repository_action_protocol.md) contract. It accepts exactly one
strict registered action per completion, preserves precise protocol rejection subcategories, and
replays normalization and action validation without a provider call.
