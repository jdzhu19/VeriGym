# VeriGym Verilator 5.052 + Icarus 12 image

This public, credential-free image adds the exact upstream Verilator v5.052 peeled commit to the
published VeriGym Icarus 12 runtime. It supports the optional candidate-only Verilator public
compile/lint feedback path while retaining Icarus for the independent hidden functional verifier.
It does not claim that lint proves functional correctness.

The image is non-root (`10001:10001`), includes the exact Verilator source archive and license
set, and contains no dataset, candidate, hidden test, commercial asset, model, credential, or
trajectory. Build it explicitly from the repository root:

```bash
docker build \
  -f docker/verilator5052-iverilog12/Dockerfile \
  -t verigym/rtl-verilator:5.052-iverilog12-r1 \
  docker/verilator5052-iverilog12
```

The publication workflow pushes the separate immutable public identity
`ghcr.io/jdzhu19/verigym-rtl-verilator:5.052-iverilog12-r1` with SBOM and provenance.
