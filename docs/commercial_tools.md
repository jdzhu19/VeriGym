# Optional commercial-tool integrations

VeriGym core defines tool, synthesis-backend, profile, artifact, and result contracts; it does not
ship vendor software. The optional
[`verigym-synopsys`](../integrations/verigym-synopsys/README.md) package proves the interface with
three site-local plugins:

- `synopsys.vcs.simulate` runs a hash-bound hidden regression and classifies license, candidate,
  timeout, parser, and runtime failures separately.
- `synopsys.dc.synth` runs a generated DC flow and emits mapped area, mapped cell count,
  maximum-path delay, worst-negative slack, and a QoR report from an exact `.db`/SDC pair.
- `synopsys.formality.equivalence` separately stages reference and implementation RTL, runs
  `match`/`verify`, and emits a script-bound equivalence status. Detailed unmatched/failing-point
  reports remain inside the ephemeral verifier session because they can reveal golden-design
  identifiers. It is an optional correctness gate, not a scoring metric.

The package contains no proprietary executable, `.db`, PDK, credential, license file, or license
server address. Users install the commercial tools and create a site profile from assets they are
authorized to use. `verigym-synopsys-prepare-profile` can locally convert a Liberty file with
Library Compiler and emit a strict YAML profile containing hashes and re-resolution paths.

## Secrets and private assets

Profiles allow only license environment-variable *names*. Values are injected into an ephemeral
runtime session, are redacted from tool output, and must never enter YAML, arguments, manifests,
traces, diagnostics, hashes, or artifacts. Candidate artifacts may contain sanitized reports and
netlists; reference RTL, reports, scripts, and netlists remain verifier-private, with only a bounded
reference summary exported.

## Comparability

Commercial results are `site_specific` or `private`, never public or signoff. Comparisons require
the same task/correctness identity and complete resolved profile hash, which binds tool version,
runtime, DB, SDC, generated script, units, clock period, flow, and reference. Matching profile names
alone is insufficient. Area, delay, and WNS stay separate; VeriGym does not combine them into an
opaque score or claim cross-tool equivalence.

Ordinary CI uses fake command results and parsers. Real VCS/DC/Formality tests are explicit,
site-owned, license-gated checks and must not become dependencies of the ordinary test suite.
