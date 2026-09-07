# JasperGold SEC integration (draft)

This integration has **bounded trusted-fixture site evidence, not general suite qualification**. It
accepts only operator-audited candidate hashes. The native worker is trusted-fixture-only, not a
sandbox for generated RTL. No commercial tools, license values, site wrappers or golden assets
are distributed. Installing this package does not install JasperGold or Yosys.

After fixing license-environment forwarding and verifier-owned log collection, all three audited
RealBench reference/negative pairs matched expected SEC outcomes. A separately audited public-spec
S-box also completed the full scripted orchestrator with final `proven` and offline replay.
See the [qualification evidence](../../docs/audits/2026-09-07-realbench-sec-qualification.md).
Historical license and result-collection failures remain invalid; they were not rewritten as
passes. All temporary commercial entries are disabled, and no invocation retries automatically.

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
Patch releases such as `2022.12p001` are preserved and matched exactly, not reduced to `2022.12`.

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

The operator's server startup must load the site's environment before launching Python. The
server explicitly forwards only `CDS_LIC_FILE` and `LM_LICENSE_FILE` to the fixed worker; the
native worker forwards the same allowlist to its tools. Values remain in subprocess environments,
never in requests, profiles, hashes, traces or responses. Core `LocalRuntime` still strips other
ambient variables and uses a temporary `HOME`; a worker's `module load` alone does not guarantee
that the user's shell license configuration has been loaded. Do not forward the entire ambient
environment or restore the real home directory to work around this boundary.

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

The fixed `jgproject/jg.log` output may link to a bounded, single-link regular file within that
invocation's non-symlinked project. Escapes, dangling/cyclic links, hard links, special files and
oversized logs fail closed. This tool-output exception does not relax candidate/site input asset
path checks; it remains within the trusted-fixture boundary.

There is at most one SEC invocation per server process and zero automatic retries. Every new
attempt requires an explicit new invocation. `ServerProfile.timeout_s` is one native invocation
budget, including version probes, both synthesis steps and SEC. Each subprocess receives only the
remaining budget (rounded up to integer seconds); no new phase starts after expiry, and late proof
output cannot turn a timeout into success. Resolution probes share at most 20 seconds. The outer
worker watchdog has 10 seconds of grace; the client's transport timeout is not a remote cancel RPC.

The [lifecycle follow-up](../../docs/audits/2026-09-07-realbench-sec-lifecycle-report.md) used only
synthetic tools to verify deadline exit after an observed active SSH invocation was interrupted.
It did not rerun the seven frozen commercial invocations. Timeout handling kills the local worker process
group; this does **not** prove remote scheduler cancellation. A production site wrapper must
implement and qualify remote job termination before accepting generated candidates.

## Qualification still required

Current site evidence covers the pinned three-task template/tool combination and successful-path
cleanup only. Remote abnormal cancellation, scheduler isolation and arbitrary generated RTL remain
unqualified, as do other tool versions and tasks. Continue authorized bounded diagnosis/fixes with
fresh invocation identities; never remove the approved-candidate gate as a substitute for isolation.
