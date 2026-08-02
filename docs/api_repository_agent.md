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

For real providers, launch VeriGym from a trusted shell and supply only environment variable
names in configuration. Keep Docker `environment_allowlist` empty unless a non-secret task value
is explicitly required. The repository-agent and verifier containers receive neither API
credentials nor controller proxy credentials. Replay reads sealed artifacts only and does not
instantiate the model client or access the network.

For multi-turn provider-neutral agents, use `provider-neutral-api-repository-agent` with the
versioned [`repository_action.v2`](repository_action_protocol.md) contract. It accepts exactly one
strict registered action per completion, preserves precise protocol rejection subcategories, and
replays normalization and action validation without a provider call.
