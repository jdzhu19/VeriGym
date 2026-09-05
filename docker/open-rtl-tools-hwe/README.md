# Offline open HWE command image

This image is the agent-only, non-authoritative toolchain for the PR-1816 comparison. It combines
Verilator 5.008, Icarus 12, Yosys 0.67, and ripgrep 15.2.0 from locally hash-locked inputs. It does
not inherit from, copy from, or contain an HWE-Bench task/verifier image.

The v172 qualification runner performs the only authorized build. It first imports the already
accepted VeriGym open-tools image and an offline-cache materialized builder into a fresh `/data2`
DinD daemon, then builds this Dockerfile with `--network=none` and `--pull=false`. The runner scans
the resulting image and keeps its result distinct from the authoritative HWE verifier receipt.

Do not build this file manually for campaign evidence. A tag is never accepted as identity; the
runner resolves and records the final image ID and every required executable hash.
