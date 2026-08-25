# Optional commercial-tool integrations

VeriGym core defines tool, synthesis-backend, profile, artifact, and result contracts; it does not
ship vendor software. The optional
[`verigym-synopsys`](../integrations/verigym-synopsys/README.md) package proves the interface with
site-local tools plus one remote synthesis transport:

- `synopsys.vcs.simulate` runs a hash-bound hidden regression and classifies license, candidate,
  timeout, parser, and runtime failures separately.
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

## Optional MCP deployment

`verigym-synopsys-mcp-server` makes the DC evaluator available as a verifier-only MCP stdio
service. It is useful when the licensed installation lives on a dedicated workstation or HPC
login/worker rather than on the VeriGym control-plane machine. Standard input/output can be
forwarded by a fixed SSH wrapper, so no general network listener is required.

The server operator approves profile files at startup. Callers select only an approved profile ID
and declared hash, a reference-candidate hash, candidate/reference role, fixed top, and the exact
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

This boundary is transport and policy mediation, not a sandbox for hostile RTL. Run it under a
dedicated account or scheduler job on a controlled verifier host, restrict the SSH principal to a
fixed command, and never expose the MCP tools to the model/agent session. The in-process local DC
backend remains supported for sites with a co-located licensed installation; both paths use the
same generated flow and metric semantics.
