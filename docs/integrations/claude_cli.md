# Claude CLI external repository agent

The optional [Claude CLI package](../../integrations/verigym-claude-cli/README.md) provides the
`claude-cli-agent` entry point. It is separate from both `codex-cli-agent` and the single-response
`api-repository-agent`: Claude CLI owns an internal multi-turn loop, but every workspace action is
mediated by VeriGym's strict MCP broker and official network-none Docker runtime.

The accepted security design is recorded in
[ADR 0017](../adr/0017-claude-cli-runtime-mcp-tools.md) and the [security policy](../../SECURITY.md).
Use this integration only with a distinct frozen agent version and report its result as a Claude
CLI harness result, never as a direct DeepSeek API or Codex result.
