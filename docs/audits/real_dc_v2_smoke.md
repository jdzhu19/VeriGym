# Real Design Compiler v2 smoke

Date: 2026-08-06 (Asia/Shanghai)

This bounded smoke validates the `synopsys-dc-area-timing-v2` flow with a real licensed Design
Compiler invocation. It is not a full RTLLM campaign, a PPA comparison, or a signoff result. No
model call was made.

## Frozen inputs and tools

- VeriGym implementation: commit `cfd34ce8aa77b23f1e1c6cb473e3c05995d89d00`.
- RTLLM source: commit `41b26896e33b536940116a975626455eed3de65e`, normalized
  `counter_12` candidate SHA-256
  `ba2c20ea3f3f2957d80ac17598ea4bfa5fbf10a97a8c4c233ddeef6554151a9d`.
- Design Compiler: `T-2022.03-SP1`; Library Compiler: `T-2022.03-SP3`.
- Sky130HD Liberty source: OpenROAD-flow-scripts commit
  `778c4e556a6f1d104621b92f6a851324bf34ff1a`, SHA-256
  `ec0e1067a35c8bf20b11e58d1e8ac53326067e4dac84a125cc1b917a3518d0d9`.
- Locally converted private DB SHA-256:
  `4869e69e924a73a37561d38cd6d5f07705fab406eade748b7b9afb5247b3f5f5`.
- 10 ns SDC SHA-256:
  `60d14fdff23c21247d0407074c3812338a87166bc11145b5222c02146433c161`.

## Result

The plugin returned `success` and parsed the `VERIGYM_DC_METRICS_V2` protocol:

| Metric | Structured value | Independent DC report |
|---|---:|---:|
| Mapped leaf cells | 13 | `report_qor`: leaf cells 13; `report_area`: cells 13 |
| Mapped area | 153.8976 um^2 | `report_qor`: 153.897599 um^2 |
| Critical-path delay | 0.810319 ns | `report_qor`: 0.81 ns |
| Worst-negative slack | 0.0 ns | `report_qor`: design WNS 0.00 ns |
| Clock period | 10.0 ns | `report_qor`: 10.00 ns |

The generated Tcl hash was
`8535890a0d0c9ae70007fce8eaa14644c5f226dafc095c66b1df54439a64fed6`. The structured metrics
file hash was `f5dcedeeb1cfcaf2d27ff38df5d9ebef6cfd975602527466c9348ea39e312c1c`.
The nonempty `qor.rpt` was 2,413 bytes with SHA-256
`89a3b4c480c9c609065315a02b5f03fffc3a5ac531cd763e4e2cfae329d3ba6c`.

## Security and scope

The experiment used a site-private DB and license environment. License values, DB bytes, raw tool
logs, generated netlists, machine-local paths, and the scratch workspace are not committed. An
explicit scan found no license value in the retained private artifacts. Only this bounded,
path-free summary is public.
