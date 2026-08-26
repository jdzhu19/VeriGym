# Real remote Synopsys MCP smoke

Date: 2026-08-26 (Asia/Shanghai)

This bounded smoke used one trusted 16-bit counter. It exercised the VeriGym control-plane MCP
client, a fixed SHA-256-bound SSH stdio wrapper, a private HPC MCP server, and a real Design
Compiler `compile_ultra` candidate/reference evaluation. It is not a benchmark score, a physical
design result, or a signoff result.

## Frozen identities

- VeriGym MCP implementation commit: `ca01d79`.
- Design Compiler: `T-2022.03-SP1`.
- PDK/library: NanGateOpenCellLibrary PDK v1.3, typical NLDM prebuilt DB.
- DB SHA-256: `3c205f46310315953d992fb014e814a1f12e9cb2a0030f900dc366131f7fc425`.
- RTL SHA-256: `a5a22f0eaee5f8945ef84ee6ab8f59f6756a9d5c96bc38b4ab51adfa6c88b52d`.
- SDC SHA-256: `69a86abd0d85ebb20aef22d29da5379f0c675a9f1d4484d8ae8de3247720e88e`.
- Reference candidate hash: `93166b3bc263a592f03453c1739c9896791a4aa99357060d063e78a768db4d51`.
- Sanitized client profile hash: `0c9143a4004f7c44a1a8176de27c8f10570bd7a23caa76a52f07b8fbf72d456b`.
- Server profile hash: `4663df90d346d68d80394d93c1740ec795df7df0152e5c3572cf67aa38a8af66`.
- Client resolved profile hash: `5c4b369c6d683111348726ed0b12419ec91521a4873a0afec294763a4ae93e61`.
- Server resolved profile hash: `f644b3491b1ab54ac59fd8f56bd3d150beb8dc6a49897dc3666e480c43f402f0`.
- Generated DC script hash: `ec0befcab50848cb0ae32145c217e3d0e4d2e554a349e2c5110b932504f937f9`.
- Fixed transport wrapper hash: `b3deaa8000bb191a4cfe7a4866c759e866d0f5d0d14bfe33e47104b73a0da1f8`.

## Result

Both candidate and reference returned `synthesis_ok=true` with identical metrics:

| Metric | Value |
|---|---:|
| Mapped leaf cells | 56 |
| Mapped cell area | 124.754 um^2 |
| Maximum-path arrival | 0.725298 ns |
| Worst-negative slack | 0.0 ns |
| Total estimated power | 14.6373 uW |

The clock period was 10 ns. Non-clock primary-input activity used the frozen
`global_clock_relative` mode, toggle rate 0.1, and static probability 0.5.

Exact profile replay succeeded before synthesis. The candidate imported only `flow.tcl`,
`metrics.kv`, `area.rpt`, `timing.rpt`, `power.rpt`, and `qor.rpt`; neither `netlist.v` nor raw
`dc.log` crossed the MCP boundary. The reference imported no artifact content, RTL, or netlist.
Its local summary retained only metrics and eight verifier-private artifact identities. The
sanitized client profile contained no remote asset path or license-variable name. The remote
ephemeral work directory was empty after both calls.

The orchestration probe attempted to print a nonexistent convenience `status` attribute only
after both real synthesis calls and all metrics had been returned, causing the probe wrapper to
exit nonzero. A separate post-run validator checked the persisted structured outputs and all
isolation assertions successfully. This was a probe-script diagnostic error, not an MCP, SSH,
license, or Design Compiler failure.

Commercial reports, profiles containing site paths, the wrapper command, PDK assets, license
configuration, and transported RTL remain uncommitted in experiment scratch storage.
