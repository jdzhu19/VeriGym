# Commercial P0 smoke evidence

Date: 2026-08-06 (Asia/Shanghai)

This opt-in site smoke used only external/private runtime assets; none are committed. It exercised
the ordinary VeriGym orchestration path with the independently installed `verigym-rtllm` and
`verigym-synopsys` entry-point packages.

- RTLLM source: `41b26896e33b536940116a975626455eed3de65e`, task
  `Control/Counter/counter_12`; all adapter-pinned file hashes passed.
- Functional verifier: VCS `V-2023.12-SP2-2`, full-64-bit mode. The pinned upstream reference,
  normalized only from `verified_counter_12` to `counter_12`, passed the hidden regression.
- Synthesis: Design Compiler `T-2022.03-SP1` with Library Compiler `T-2022.03-SP3`.
- Library source: OpenROAD-flow-scripts Sky130 HD typical Liberty at commit
  `778c4e556a6f1d104621b92f6a851324bf34ff1a`, SHA-256
  `ec0e1067a35c8bf20b11e58d1e8ac53326067e4dac84a125cc1b917a3518d0d9`.
- Constraint: 10 ns clock; exact SDC and generated `.db` identities were bound in the resolved
  site profile.

The final run passed VCS plus candidate/reference DC synthesis. The correctness-gated summary was
eligible and reported candidate/reference equality: mapped cell area `153.8976 um^2`, maximum-path
delay `0.810319 ns`, and WNS `0.0 ns`; all three reference ratios/deltas were exactly neutral.

This is interface and execution evidence, not a performance claim, cross-tool comparison, public
reproducibility claim, or signoff result. License values and private DB bytes were not persisted in
the repository.
