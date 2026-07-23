# Adding an agent

Implement `AgentAdapter` from `verigym.plugin_api` and register it in `verigym.agents`. An agent
receives only observations from the environment and returns typed actions. It must not receive a
runtime session, hidden asset path, verifier object, or unrestricted filesystem interface.

Use the environment’s visible tools for reads and edits, honor termination and budget signals,
and end with one final submission. The orchestrator freezes the candidate before verification;
post-submission mutation cannot affect the verifier snapshot.

Document whether an agent is deterministic and which model interface it needs. Test malformed
actions, disallowed tools, model transport errors, turn/tool/token budgets, and repeatability.
External coding-agent frameworks are outside the MVP.
