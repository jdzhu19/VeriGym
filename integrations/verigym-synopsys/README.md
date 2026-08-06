# VeriGym Synopsys Integration

This optional package connects site-installed Synopsys VCS, Design Compiler, and Formality tools
to VeriGym.
It contains only Python adapters and generated flow logic: no vendor executable, library database,
license file, PDK, or benchmark asset is bundled.

Install it beside an editable VeriGym checkout:

```bash
python -m pip install -e ./integrations/verigym-synopsys
verigym plugins list
```

`synopsys.vcs.simulate` is a verifier-only regression tool. It accepts an explicit candidate source
list and hidden testbench, invokes VCS without a shell, recognizes pass/fail sentinels, and maps
license failures to `license_unavailable`. `synopsys.dc.synth` is a synthesis backend that reports
mapped area, maximum-path delay, and worst-negative slack from a hash-bound DB and SDC pair.
The current DC v2 flow additionally records mapped cell count and a complete `report_qor` artifact;
the v1 flow remains accepted for replay compatibility. `synopsys.formality.equivalence` compares
separately staged reference and implementation RTL,
supports Verilog and SystemVerilog, and emits a script-bound structured equivalence result. All
three plugins are verifier-only and intended for site-controlled runtimes; DC profiles explicitly
require the trusted local runtime. Detailed Formality point reports are not exported because they
can reveal golden-design identifiers.

## Prepare a site profile

Library Compiler can convert a user-supplied Liberty file to the `.db` format required by DC:

```bash
verigym-synopsys-prepare-profile \
  --liberty /path/to/cells.lib --sdc /path/to/design.sdc \
  --output-db /private/profiles/cells.db \
  --output-profile /private/profiles/dc.yaml \
  --source rtl/counter_12.v --top counter_12 --clock-period 10 \
  --license-environment SNPSLMD_LICENSE_FILE
verigym profiles validate site-synopsys-dc --file /private/profiles/dc.yaml
```

The profile stores hashes, tool versions, paths, and permitted environment **names**, never license
values. Results are site-specific and comparable only when their resolved profile hashes match.
Commercial tests are opt-in; the ordinary VeriGym test suite requires no Synopsys installation or
credentials.
