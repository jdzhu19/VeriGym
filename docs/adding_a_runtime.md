# Adding a runtime

A runtime provides isolated command sessions and a truthful `RuntimeDescriptor`. It must stage
only approved inputs, invoke argument arrays with `shell=False`, bound time/output/resources,
freeze submitted workspaces, collect declared artifacts safely, and clean up every terminal path.

`LocalRuntime` is `local_trusted`: it is appropriate only for trusted fixtures. `DockerRuntime`
adds verified non-root, network-none, read-only-root, dropped-capability, no-new-privileges,
resource, mount, environment, and cleanup controls. Docker still shares the host kernel and daemon
and is not a formal isolation proof.

New runtimes need conformance tests for agent/verifier separation, traversal and link rejection,
timeout/OOM/cancellation, exact replay identity, cleanup, secret exclusion, and no fallback to a
weaker runtime. Repository-level adapters and commercial execution are outside the MVP.
