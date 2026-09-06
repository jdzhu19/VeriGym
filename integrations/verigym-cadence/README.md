# JasperGold SEC integration (draft)

This integration is implemented and credential-free tested, **not site-qualified**. It currently
accepts only operator-audited candidate hashes. The native worker is trusted-fixture-only, not a
sandbox for generated RTL. No commercial tools, license values, site wrappers or golden assets
are distributed. Installing this package does not install JasperGold or Yosys.

## Check the implementation without commercial tools

From the repository root, using a Python 3.11+ environment:

```bash
python -m pip install -e '.[dev]' -e integrations/verigym-cadence
pytest -c integrations/verigym-cadence/pyproject.toml integrations/verigym-cadence/tests
mypy --config-file integrations/verigym-cadence/pyproject.toml integrations/verigym-cadence/src
verigym doctor
```

The tests use executable fake workers and real stdio JSON-RPC, not commercial binaries. They
exercise profile and tool identity, drift, candidate bounds, path safety, SEC status mapping,
one-job execution, hidden-output rejection, and native-worker staging/cleanup.

## Bind an approved site

The private `ServerProfile` in [protocol.py](src/verigym_cadence/protocol.py) fixes the task ID,
top, ordered sources, approved candidate hashes, timeout, worker executable and content hash,
JasperGold/Yosys versions, and every private asset's role/path/hash. The resolved identity binds
the server Python release as well. Site paths and environment values are not exposed or hashed.

The native worker accepts these private asset roles:

| Role | Meaning |
| --- | --- |
| `jaspergold`, `yosys` | Exact regular executable files, not symlinks |
| `reference:<relative RTL path>` | Verifier-only reference RTL with `ref_<top>` entry point |
| `dependency:<relative RTL path>` | Approved support RTL in both synthesis inputs |
| `sec_template` | Audited Tcl with `###TOPMODULE###`, reading `ref.f` and `top.f` |

A private no-argument wrapper selects the runtime and launches
`python -m verigym_cadence.native_worker`. A separate fixed transport launches
`python -m verigym_cadence.server --profile` with its operator-owned profile path. The caller does
not select that path. These site-specific wrappers are not generated or deployed automatically.

The client uses the existing `VerifierToolProfile` and `ResolvedVerifierToolProfile` schemas.
Its target is `cadence.jaspergold.sec.mcp`; `VERIGYM_JASPERGOLD_MCP_PROFILE` selects the local client
profile for doctor. Resolution verifies fixed assets and actual version output, but does not
check out a license or claim suite qualification. The server exposes `resolve_profile` and
`verify` MCP tools, never a shell or general Tcl interface.

## Interpret outcomes

The final result contains an enum only: `proven`, `counterexample`, `inconclusive`,
`candidate_compile_failure`, `timeout`, `license_unavailable`, `tool_unavailable`, or
`infrastructure_failure`. No counterexample, waveform, reference content, diagnostic log or
private exception text is returned. Unknown/malformed results fail closed. Only explicit
`proven` is success; upstream `determined` / `determined_or_skipped` are not silently promoted
to proof. Reference synthesis errors are infrastructure failures, not candidate rejections.

There is at most one SEC invocation per server process and zero automatic retries. Every new
attempt requires an explicit new invocation. Timeout handling kills the local worker process
group; this does **not** prove remote scheduler cancellation. A production site wrapper must
implement and qualify remote job termination before accepting generated candidates.

## Qualification still required

Real reference/negative-control SEC, site license behavior, remote scheduler isolation/cleanup,
and RealBench template/version compatibility remain unqualified. The operator must supply the
external checkout and approve the execution boundary before that work proceeds. Do not remove
the approved-candidate check as a substitute for isolation.
