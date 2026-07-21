# Security policy and threat model

Benchmark sources and agent-generated RTL must be treated as untrusted. The Milestones 0–4
local runtime is for trusted fixtures and development only; it does not provide a container
security boundary.

The current implementation rejects absolute paths, parent traversal, symlink escapes,
edits outside task-declared globs, disallowed tools, shell command strings, and oversized
model-visible output. It launches tool commands as argument arrays with timeouts and a
minimal environment. Hidden tests are copied only into a physically separate verifier
session and never into the agent workspace or observations. Run manifests and traces do not
store credentials.

For untrusted benchmark repositories or agents, use the future Docker runtime described by
the build specification: non-root execution, disabled network, read-only root filesystem,
resource limits, no Docker socket, no home-directory mounts, and explicit artifact
extraction. Do not use `LocalRuntime` as a substitute for that isolation boundary.

Report security issues privately to the project maintainers rather than opening a public
issue containing exploit details.

