# Optional commercial-tool integrations

VeriGym core defines tool, synthesis-backend, profile, artifact, and result contracts; it does not
ship vendor software. The optional
[`verigym-synopsys`](../integrations/verigym-synopsys/README.md) package proves the interface with
site-local tools plus verifier-only MCP transports:

- `synopsys.vcs.simulate` runs a hash-bound hidden regression and classifies license, candidate,
  timeout, parser, and runtime failures separately.
- `synopsys.vcs.mcp` replaces that hidden-regression DAG node through a task-bound verifier
  profile. VCS, its license setup, hidden testbench, raw output, and reports stay behind a fixed
  local or SSH-connected stdio service.
- `synopsys.vcs.public-compile.mcp` optionally replaces VerilogEval AgentEval's iterative public
  compile check. It accepts only the candidate source and returns a sanitized compile verdict;
  it has no simulation or hidden-test interface.
- `synopsys.dc.synth` runs a generated DC flow and emits mapped area, mapped cell count,
  maximum-path delay, worst-negative slack, total dynamic plus cell leakage power, and QoR reports
  from an exact `.db`/SDC pair.
- `synopsys.dc.mcp` invokes the same generated DC flow through a hash-bound, verifier-only MCP
  stdio wrapper while keeping DC, the `.db`, SDC, PDK, and license on a remote controlled host.
- `synopsys.formality.equivalence` separately stages reference and implementation RTL, runs
  `match`/`verify`, and emits a script-bound equivalence status. Detailed unmatched/failing-point
  reports remain inside the ephemeral verifier session because they can reveal golden-design
  identifiers. It is an optional correctness gate, not a scoring metric.

The package contains no proprietary executable, `.db`, PDK, credential, license file, or license
server address. Users install the commercial tools and create a site profile from assets they are
authorized to use. `verigym-synopsys-prepare-profile` prefers a stable prebuilt `.db` when the PDK
provides one. It can otherwise convert a Liberty file with Library Compiler. The emitted strict
YAML contains hashes and re-resolution paths; generated `.db` bytes remain site-local.
The committed [real DC v2 smoke](audits/real_dc_v2_smoke.md) demonstrates mapped-cell extraction
and `report_qor` generation without publishing the site DB, raw logs, or license configuration.
It is historical v2 evidence and does not contain a power result. New explicit-power v4 profiles
run `compile_ultra` followed by `report_area`, `report_timing`, `report_power`, and `report_qor`.
Explicit multi-clock profiles use the distinct v5 flow, which aggregates the maximum arrival time
and worst slack across the timing paths returned for asynchronous clock groups. Single-clock v4
flow identity and generated script bytes are preserved.
The [NanGate45 synthesis PPA smoke](audits/nangate45_synthesis_ppa_smoke.md) covers both the open
and commercial paths.

## Secrets and private assets

Profiles allow only license environment-variable *names*. Values are injected into an ephemeral
runtime session, are redacted from tool output, and must never enter YAML, arguments, manifests,
traces, diagnostics, hashes, or artifacts. Candidate artifacts may contain sanitized reports and
netlists; reference RTL, reports, scripts, and netlists remain verifier-private, with only a bounded
reference summary exported.

## Comparability

Commercial results are `site_specific` or `private`, never public or signoff. Comparisons require
the same task/correctness identity and complete resolved profile hash, which binds tool version,
runtime, DB, SDC, generated script, units, clock period, power activity mode, flow, and reference.
Matching profile names alone is insufficient. Area, delay, WNS, and power stay separate; VeriGym
does not combine them into an opaque score or claim cross-tool equivalence. DC v4 explicitly
annotates non-clock primary inputs with a frozen clock-relative toggle rate and static probability;
clock-source activity remains derived from the SDC clock. The parsed total is dynamic plus cell
leakage power. It is a synthesis estimate without a placed clock tree or extracted parasitics, not
signoff power. DC v3 `vectorless_default` remains accepted only for exact replay of historical
profiles.

Ordinary CI uses fake command results and parsers. Real VCS/DC/Formality tests are explicit,
site-owned, license-gated checks and must not become dependencies of the ordinary test suite.
PrimeTime, HSPICE, Genus, Innovus, Xcelium, and Library Compiler installations are not selected by
the current RTL AgentEval contract. Library Compiler may prepare a DC `.db`; it is not a scored
backend. Adding any other commercial tool requires a new explicit plugin/profile identity and
qualification rather than PATH-based discovery.

## Optional MCP deployments

`synopsys.vcs.mcp` is selected by `--verifier-profile` and replaces only the task's hidden
functional-verifier node. The server approves exact task profiles and exposes list, resolve, and
simulate. It owns the top, source order, hidden testbench, pass/fail markers, timeout, VCS
executable, and tool-version contract. Requests contain bounded hash-checked candidate RTL but no
testbench, command, flags, environment, or artifact policy. Responses contain a sanitized verdict
but no raw output, log, report, hidden RTL, license value, or server path.

The VerilogEval `v2-spec-to-rtl-agent-eval-vcs-mcp-v1` projection uses this path as a commercial
replacement for its final hidden functional regression. Its public multi-turn compile feedback
still uses Icarus 12, and it intentionally exposes neither DC nor PPA. The VCS result belongs to a
separate profile partition and is not reported as an upstream-Icarus benchmark result.

The distinct `v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1` projection uses two independently
resolved profiles: `--public-test-profile` selects compile-only VCS/MCP during iteration, while
`--verifier-profile` selects the final hidden VCS/MCP regression. The public service exposes only
compile pass/fail and bounded candidate-file/line/error-code diagnostics. It neither links nor
runs a testbench, and it contains no hidden or reference asset. Therefore this is a commercial
replacement for the existing compile feedback, not an added PPA signal or stronger correctness
oracle. Results remain diagnostic-only and belong to their own public and final VCS partitions.
The [qualification audit](audits/verilog_eval_vcs_public_feedback_v1.md) records the real 155-task
commercial compile sweep and a dual-profile multi-turn smoke.

`synopsys.dc.mcp` is selected independently by `--toolchain-profile` and supplies final
synthesis-only PPA after hidden correctness passes. New commercial RTLLM runs can select both
profiles; their requested, declared, and resolved identities are frozen separately in manifests,
experiment plans, scorecards, and replay. VCS identity is not a PPA comparison key, and VCS/MCP
does not turn an Icarus-based AgentEval partition into the official VCS partition.

`verigym-synopsys-mcp-server` makes the DC evaluator available as a verifier-only MCP stdio
service. It is useful when the licensed installation lives on a dedicated workstation or HPC
login/worker rather than on the VeriGym control-plane machine. Standard input/output can be
forwarded by a fixed SSH wrapper, so no general network listener is required.

The server operator approves profile files at startup. Callers select only an approved profile ID
and declared hash, a reference-candidate hash, candidate/reference/agent-feedback role, fixed top, and the exact
ordered hash-bound RTL sources. The service does not accept tool paths, license configuration,
PDK/library bytes, constraints, commands, or Tcl. It returns a sanitized resolved identity and
structured DC metrics. Candidate reports/netlists are bounded artifact payloads; reference
artifact bodies stay on the server. Message, individual-source, aggregate-source,
individual-artifact, and aggregate-artifact limits are enforced before data is accepted or
exported.

The installable `synopsys.dc.mcp` synthesis backend is the matching VeriGym client. A separate
sanitized client profile selects it, identifies the fixed transport executable by SHA-256, and
binds the server profile ID/hash. `verigym-synopsys-export-mcp-profile` derives that client
contract without copying remote URIs, asset bytes, or license environment names. Normal
`verigym run` and replay then resolve the server before synthesis and bind both client and server
resolved hashes. Candidate summary reports return through the ordinary artifact path; raw logs,
large netlists, and every reference artifact body stay remote.

Transport and policy mediation alone are not a sandbox for hostile RTL. Final frozen-candidate PPA
may retain the historical trusted verifier service. Iterative commercial feedback requires the
phase-two worker mode: a fixed hash-bound launcher dispatches one candidate to one disposable LSF
job, container, or VM; the worker returns no artifact bodies or diagnostics and deletes its
workspace before its receipt is accepted. The client profile freezes the combined launcher and
isolation-contract hash. Missing or altered worker identity fails before model lookup rather than
falling back to the trusted service or open PPA.

The model never calls MCP directly. It retains `run_public_test("ppa")` under the existing
six-action repository contract. Default/max real executions remain 3/8, cache hits consume no
execution, and a dispatched timeout/crash does. The scheduler or worker may require a site license
network; that network belongs to trusted commercial infrastructure and is not inherited by the
networkless agent container.
