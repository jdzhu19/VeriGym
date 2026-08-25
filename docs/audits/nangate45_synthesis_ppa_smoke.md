# NanGate45 synthesis PPA smoke

Date: 2026-08-13 (Asia/Shanghai)

This bounded smoke validates the new synthesis-only area/timing/power paths on one trusted 16-bit
counter. It is not a benchmark score, a physical-design comparison, or a signoff result. No model
or benchmark corpus was invoked.

## Frozen inputs and tools

- VeriGym source base at execution: `fe479e0e23af9dbadd81877b9664727a8d462142`; the PPA changes
  described here were present in the working tree.
- Trusted counter RTL SHA-256:
  `c3eacb21d1be60a7efa3c7b4586d43f3e0bf5af4aac38a947d234c166386f8c7`.
- SDC SHA-256: `4304b9beb86a22802c27464cfe36b3c52a0b976c4c69cd59bb3d2f30a60a665e`;
  named clock `clk`, period 10 ns.
- NanGateOpenCellLibrary PDK `PDKv1_3_v2010_12`: 5,349 files and 613,868,677 bytes;
  canonical tree SHA-256
  `bfd16e1b72f5aaafdcf540b58d86e72ca3ab32d2e812768b13cf6529a7d98de9`.
- Typical NLDM Liberty SHA-256:
  `2efd0b32eb580e4e60e72fc0575bb3bc69aac907c91d908442e4ae6d7fe55895`.
  The library corner is 1.10 V, 25 C, process 1.0 with wire-load model `5K_hvratio_1_1`.
- Yosys `0.45+139`, git identity `4d581a97d`; ABC `1.01`.
- Standalone OpenSTA `3.1.0`, source commit
  `b6a817bab88e79c4121a93aa6b7ea423a3b87cf3`; executable SHA-256
  `eeccd172132ab4fff8a613571a7e607efaed58b2b716aba1cda4ca315673e68a`.
- Design Compiler `T-2022.03-SP1`. It used the PDK's prebuilt typical DB, SHA-256
  `3c205f46310315953d992fb014e814a1f12e9cb2a0030f900dc366131f7fc425`.

The complete PDK manifest and both resolved profiles are stored outside the repository with the
experiment. The PDK, DB, generated netlists, raw logs, and license configuration are not committed.

## Result

Both plugins returned `success` and parsed their versioned structured metrics:

| Metric | Yosys + OpenSTA | DC `compile_ultra` |
|---|---:|---:|
| Mapped leaf cells | 59 | 55 |
| Mapped cell area | 118.37 um^2 | 109.326 um^2 |
| Maximum-path arrival | 0.534645 ns | 0.954533 ns |
| Worst-negative slack | 0.0 ns | 0.0 ns |
| Total estimated power | 12.0027144 uW | 14.1047 uW |

OpenSTA used global clock-relative activity 0.1 and duty 0.5. DC used toggle rate 0.1 per `clk`
period and static probability 0.5 on non-clock primary inputs; clock activity was derived from the
SDC clock. Both totals include internal, switching, and leakage power. Neither includes placement,
clock-tree synthesis, routing, or extracted parasitics.

The OpenSTA resolved profile hash was
`90b46d1204e165c52ae7b4da3eec61ad9e73e789e17df0abd3e488be1999b9f9`. The DC resolved profile
hash was `279606f3e638c0f5932bd7279de78b9438e60597fe3039ea1b3c80a4177d43d6`. These results are not
ranked against each other: the tools produced different mapped netlists and use different activity
propagation and power models.

## Findings closed during the smoke

- Tcl `exec` treats unredirected child stderr as an error even when Yosys exits zero. The OpenSTA
  driver now merges Yosys stderr into the captured result and still fails on a nonzero exit code.
- OpenSTA path slack belongs to the `PathEnd` returned by `find_timing_paths`. Reading slack from
  the internal path object produced an incorrect negative value; the flow now reads the `PathEnd`.
- DC `-type inputs` also annotated the clock port and overrode derived clock activity. The v4 flow
  now subtracts all clock-source ports before annotating primary data inputs.
- Library Compiler conversion of the same Liberty produced different DB hashes across invocations.
  The profile preparer now supports binding a PDK-provided prebuilt DB; conversion remains a
  fallback whose exact output hash is frozen.

## Scope and security

The smoke ran only trusted RTL through the trusted local runtime. This does not authorize local
execution of generated or external RTL. Public evaluation requires an immutable verifier image,
network isolation, and resource controls. OpenROAD was not used: this profile intentionally ends
at synthesis plus wire-load-model STA/power.

## OpenSTA v2 diagnostic follow-up

The `verigym-yosys-opensta-atp-v2` flow was rerun on the same trusted counter after adding required
unit and activity-annotation diagnostic artifacts. The resolved profile hash was
`f87c52234f7cf2d2cc94758ae9fafeb7b198185d8a33c3a393c1c86920db9361`, and the generated combined
Yosys/OpenSTA script hash was
`f67e44b066945347dddd28fbed99a5b44550e63d018898923854a69600cd39a8`.

The parsed PPA values were unchanged: 118.37 um^2 area, 0.534645 ns maximum-path arrival, 0.0 ns
WNS, and 12.0027144 uW total power. `units.rpt` recorded 1 ns, 1 fF, 1 kohm, 1 V, 1 mA, 1 nW,
and 1 um library units. `activity_annotation.rpt` recorded 243 unannotated pins. This is expected
for the v2 global vectorless profile because OpenSTA's annotation report counts explicit
VCD/SAIF/port annotations rather than the global fallback; the report is diagnostic and is not an
annotation-coverage acceptance threshold.

The first bounded v2 attempt also confirmed fail-closed behavior: OpenSTA rejected shell-style
redirection on `report_units`, the plugin returned `tool_failed`, and no PPA metrics were accepted.
The frozen v2 driver now uses OpenSTA's namespaced report redirection API, after which the rerun
passed and retained both diagnostic artifacts. Raw outputs remain under
`/data/jzhu484/Agent/experiments/ppa-smoke-v2-opensta-diagnostics/` and are not committed.
