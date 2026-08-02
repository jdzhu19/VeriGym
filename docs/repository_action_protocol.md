# Repository Action Protocol v2

`repository_action.v2` is VeriGym's provider-neutral, versioned action contract for bounded
repository-repair agents. Provider transport extraction and canonical action validation are
separate. A model client may supply `json_content` or `native_tool_call`; an experiment binds one
transport before planning. The M12A conformance pilot binds `json_content`.

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
