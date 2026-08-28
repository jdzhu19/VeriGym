# VeriGym Synopsys Integration

This optional package connects site-installed Synopsys VCS, Design Compiler, and Formality tools
to VeriGym.
It contains only Python adapters and generated flow logic: no vendor executable, library database,
license file, PDK, or benchmark asset is bundled.

Install it beside an editable VeriGym checkout:

```bash
python -m pip install -e ./integrations/verigym-synopsys
verigym doctor
```

`synopsys.vcs.simulate` is a trusted verifier-only regression tool. It accepts an explicit
candidate source list and hidden testbench, invokes VCS without a shell, recognizes pass/fail
sentinels, and maps license failures to `license_unavailable`. New remote or isolated campaigns
should select `synopsys.vcs.mcp` through a task-bound verifier profile instead. The MCP server owns
the hidden testbench and returns only a structured verdict. `synopsys.dc.synth` is a synthesis
backend that reports
mapped area, maximum-path delay, worst-negative slack, and estimated power from a hash-bound DB and
SDC pair. The current explicit-power v4 flow runs `compile_ultra`, records mapped cell count, and
retains `report_area`, `report_timing`, `report_power`, and `report_qor` artifacts. It annotates
non-clock primary inputs with a frozen clock-relative toggle rate and static probability. Power is
normalized as total dynamic plus cell leakage power. The v1/v2 area/timing flows and v3 legacy
vectorless-power flow remain accepted for exact replay. `synopsys.dc.mcp` provides the same DC
metric semantics through a fixed verifier-only MCP transport. `synopsys.formality.equivalence`
compares separately staged reference and implementation RTL, supports Verilog and SystemVerilog,
and emits a script-bound structured equivalence result. All plugins are verifier-only and intended
for site-controlled runtimes. Detailed Formality point reports are not exported because they can
reveal golden-design identifiers.

A bounded two-host run through the MCP client, fixed SSH transport, and real Design Compiler is
recorded in the [remote Synopsys MCP smoke audit](../../docs/audits/synopsys_mcp_real_dc_smoke.md).
The combined VCS/MCP and DC/MCP RTLLM qualification is recorded in the
[RTL commercial MCP qualification](../../docs/audits/rtl_commercial_mcp_qualification_v1.md).

## Task-bound VCS MCP verifier

Prepare one private server profile for each exact benchmark task. The server profile contains the
hidden testbench path and VCS setup, so it must stay on the verifier host:

```bash
verigym-synopsys-prepare-vcs-profile \
  --id rtllm-counter-vcs-v1 --task-id rtllm/counter_12 \
  --source rtl/counter_12.v --testbench /private/RTLLM/counter_12/testbench.v \
  --top counter_12_tb --pass-marker '===========Your Design Passed===========' \
  --fail-marker '===========Failed===========' --vcs /opt/synopsys/vcs/bin/vcs \
  --output-profile /private/profiles/counter-vcs-server.yaml

verigym-synopsys-vcs-mcp-server \
  --profile /private/profiles/counter-vcs-server.yaml \
  --work-root /private/verigym-vcs-work
```

Carry MCP stdio through a fixed local or SSH wrapper that accepts no arguments. After querying the
service's sanitized declared-profile and contract hashes, export the client-only profile:

```bash
verigym-synopsys-export-vcs-mcp-profile \
  --id rtllm-counter-vcs-client-v1 \
  --server-profile-id rtllm-counter-vcs-v1 \
  --server-declared-profile-hash "$SERVER_DECLARED_SHA256" \
  --server-contract-hash "$SERVER_CONTRACT_SHA256" \
  --task-id rtllm/counter_12 \
  --transport-executable /usr/local/bin/verigym-vcs-mcp-transport \
  --output-profile /private/profiles/counter-vcs-client.yaml
```

Select that profile independently of the final synthesis profile:

```bash
verigym run --suite rtllm --task counter_12 --suite-source /datasets/RTLLM \
  --mode chat --agent single-turn --model YOUR_MODEL --runtime local \
  --verifier-profile rtllm-counter-vcs-client-v1 \
  --verifier-profile-file /private/profiles/counter-vcs-client.yaml \
  --toolchain-profile site-synopsys-dc-mcp \
  --toolchain-profile-file /private/profiles/counter-dc-mcp-client.yaml \
  --output runs/
```

Resolution occurs before model lookup. Manifest, scorecard, experiment plan, and replay bind the
wrapper, server declared/resolved profile, public task contract, hidden-testbench result identity,
and exact VCS version. Candidate verdicts expose no stdout, stderr, VCS log, report, hidden RTL,
license value, or verifier path. See [verifier backend profiles](../../docs/verifier_profiles.md)
for the full contract and Icarus/VCS benchmark-version boundaries.

## Prepare a site profile

Prefer the PDK's prebuilt `.db` when available. The paired Liberty remains hash-bound provenance:

```bash
verigym-synopsys-prepare-profile \
  --liberty /path/to/cells.lib --sdc /path/to/design.sdc \
  --input-db /path/to/cells.db \
  --output-profile /private/profiles/dc.yaml \
  --source rtl/counter_12.v --top counter_12 --clock-period 10 \
  --power-base-clock clk --power-activity 0.1 --power-static-probability 0.5 \
  --license-environment SNPSLMD_LICENSE_FILE
verigym profiles validate site-synopsys-dc --file /private/profiles/dc.yaml
```

When the PDK has no compatible DB, replace `--input-db` with
`--output-db /private/profiles/cells.db`; Library Compiler will perform the conversion. Generated DB
files may not be byte-reproducible across invocations, so their exact emitted hash is the identity.

The profile stores hashes, tool versions, paths, and permitted environment **names**, never license
values. This synthesis estimate does not include a placed clock tree or extracted interconnect
parasitics and is explicitly non-signoff. Results are site-specific and comparable only when their
resolved profile hashes, activity settings, units, and all other profile identities match.
Commercial tests are opt-in; the ordinary VeriGym test suite requires no Synopsys installation or
credentials.

## Verifier-only DC MCP service

The package also installs `verigym-synopsys-mcp-server`, a bounded standard MCP stdio endpoint for
running DC on a site-controlled licensed machine. This is an alternative transport around the
same generated `compile_ultra` flow and parsers; it does not add a second PPA definition. The
server exposes exactly three tools:

- `verigym.synopsys.dc.list_profiles` lists sanitized server-approved profile identities;
- `verigym.synopsys.dc.resolve_profile` probes the exact server tool/profile identity;
- `verigym.synopsys.dc.synthesize` accepts a fixed top, the profile's exact ordered source list,
  SHA-256 identities, and bounded base64 RTL.

The request has no executable, Tcl, SDC, PDK, library, license, shell, timeout, or arbitrary
argument field. The service resolves those from profile files selected on its own command line,
regenerates and hash-checks the Tcl in the existing DC backend, and launches DC without a shell.
Candidate artifacts are bounded and returned with their hashes. Reference artifact contents are
never returned; only structured metrics and private-artifact identities cross the transport.

Run it locally on the licensed verifier host:

```bash
verigym-synopsys-mcp-server \
  --profile /private/profiles/dc.yaml \
  --work-root /data/verigym/.verigym-tmp/synopsys-mcp
```

MCP stdio can be carried over SSH without adding an HTTP listener. A verifier-side MCP client can
use a fixed executable wrapper equivalent to:

```text
ssh eda-verifier /opt/verigym/bin/verigym-synopsys-mcp-server \
  --profile /private/profiles/dc.yaml \
  --work-root /private/verigym-work
```

The wrapper must accept no arguments and connect its stdin/stdout directly to that fixed command.
Hash the wrapper on the VeriGym control-plane machine. Then, on a trusted administration machine,
export a client profile from the server profile and transfer only the sanitized output:

```bash
verigym-synopsys-export-mcp-profile \
  --server-profile /private/profiles/dc.yaml \
  --transport-executable /usr/local/bin/verigym-dc-mcp-transport \
  --transport-sha256 <64-lowercase-hex> \
  --output-profile /private/profiles/dc-mcp-client.yaml
```

Omit `--transport-sha256` when the wrapper is locally available to the exporter. Add
`--transport-environment SSH_AUTH_SOCK` only when the fixed SSH deployment needs that environment
name; values never enter the profile. The client profile contains remote DB, SDC, flow, and PDK
hashes but no remote asset paths, bytes, or license-variable names.

After installing the integration on the control-plane machine, `verigym run` selects the remote
backend through the client profile in the ordinary synthesis path:

```bash
verigym profiles validate site-synopsys-dc-mcp \
  --file /private/profiles/dc-mcp-client.yaml
verigym run --suite rtllm --task counter_12 --suite-source /path/to/RTLLM \
  --mode chat --agent single-turn --model YOUR_MODEL --runtime local \
  --toolchain-profile site-synopsys-dc-mcp \
  --toolchain-profile-file /private/profiles/dc-mcp-client.yaml --output runs/
```

Here `--runtime local` owns only the hash-bound MCP wrapper process; DC, the library, SDC, PDK, and
license remain on the remote verifier. Candidate flow and summary reports are imported into the
normal `synopsys_dc_mcp` artifact namespace. Large netlists and raw DC logs are not transported by
the client. Reference artifact content is never imported. Resolution and replay bind both the
client profile/transport hash and the independent server resolved-profile hash.

Use a dedicated SSH principal and a forced command or fixed wrapper in production so the client
cannot replace the server arguments. Do not enable SSH agent forwarding. Authentication and
host-key policy belong to SSH; the MCP protocol never transports license values. Keep the process
on a verifier control plane. Do not
register it as a candidate-agent/model-visible tool, because candidate RTL and commercial assets
must remain separated and the current DC execution backend still assumes a trusted,
site-controlled host. The existing in-process `synopsys.dc.synth` plugin and its `LocalRuntime`
contract remain available and unchanged.
