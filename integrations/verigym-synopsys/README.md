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

`synopsys.vcs.simulate` is a verifier-only regression tool. It accepts an explicit candidate source
list and hidden testbench, invokes VCS without a shell, recognizes pass/fail sentinels, and maps
license failures to `license_unavailable`. `synopsys.dc.synth` is a synthesis backend that reports
mapped area, maximum-path delay, worst-negative slack, and estimated power from a hash-bound DB and
SDC pair. The current explicit-power v4 flow runs `compile_ultra`, records mapped cell count, and
retains `report_area`, `report_timing`, `report_power`, and `report_qor` artifacts. It annotates
non-clock primary inputs with a frozen clock-relative toggle rate and static probability. Power is
normalized as total dynamic plus cell leakage power. The v1/v2 area/timing flows and v3 legacy
vectorless-power flow remain accepted for exact replay. `synopsys.formality.equivalence` compares
separately staged reference and implementation RTL,
supports Verilog and SystemVerilog, and emits a script-bound structured equivalence result. All
three plugins are verifier-only and intended for site-controlled runtimes; DC profiles explicitly
require the trusted local runtime. Detailed Formality point reports are not exported because they
can reveal golden-design identifiers.

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
