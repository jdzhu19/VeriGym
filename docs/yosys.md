# Yosys synthesis in VeriGym

Milestone 8 adds two verifier-only capabilities, `yosys.synth` and `yosys.stat`, implemented by
the same `ToolPlugin`. They execute through the selected `Runtime`; neither the orchestrator nor
the profile resolver invokes a shell. The canonical profile requires `DockerRuntime` and the exact
image identity resolved before model lookup.

## Reference image and source identity

The reproducibility image is defined in `docker/open-rtl-tools/Dockerfile`. Build it explicitly:

```bash
docker build \
  -f docker/open-rtl-tools/Dockerfile \
  -t verigym/open-rtl-tools:iverilog12-yosys067 \
  docker/open-rtl-tools
```

The Dockerfile downloads the official pinned Yosys release archive, checks its SHA-256, checks
the archive's recorded Yosys and vendored ABC source identities, builds it, and asserts the actual
inside-image versions. Icarus is pinned and checked independently. A mutable image tag is only a
requested reference: profile resolution records the actual image ID and tool output from inside
that image. `verigym run` never builds or pulls this image automatically.

Use the inspection commands after a build:

```bash
docker image inspect verigym/open-rtl-tools:iverilog12-yosys067
docker run --rm --network none verigym/open-rtl-tools:iverilog12-yosys067 yosys -V
docker run --rm --network none verigym/open-rtl-tools:iverilog12-yosys067 \
  yosys-abc -c 'version; quit'
```

The actual reported output—not the tag—is authoritative.

## Deterministic flow

The built-in flow accepts only validated relative source paths, a grammar-checked top module, and
grammar-checked preprocessor definitions. Candidate files are copied to deterministic safe names.
The implementation generates this fixed operation sequence:

```text
read Liberty and RTL
check hierarchy and synthesize the fixed top
map flip-flops and logic with the exact Liberty and ABC
clean and assert structural consistency
write JSON/Verilog netlists
write `stat -json -liberty ...` through Yosys `tee`
```

No candidate text is accepted as a Yosys command. The generated `flow.ys` is persisted with the
candidate synthesis artifacts and its SHA-256 is included in the resolved profile. Yosys receives
an argument array with `shell=False` semantics. Sources, statistics, logs, and netlists are all
bounded; path traversal, symlink escape, hard-link aliases, special files, invalid identifiers,
and unapproved inputs fail closed.

## Machine-readable results and failures

The parser consumes bounded `stat -json` output for the supported pinned Yosys shape. It reports
canonical wire, bit, memory, process, cell, cell-histogram, and Liberty-area fields. Structural
cell count is useful diagnostics but is not area. Mapped area is accepted only when the exact
hash-verified Liberty file named by the resolved profile was used.

Candidate RTL synthesis failure is distinct from tool absence, ABC absence, timeout, OOM, output
limit, sandbox failure, profile/asset mismatch, and statistics parser failure. A synthesis result
does not establish functional correctness. The score projection described in
[PPA profiles](ppa_profiles.md) is separately correctness-gated.

Raw Yosys logs are retained. They can contain temporary paths or run-time information, so VeriGym
does not claim byte-identical human logs; reproducibility comparisons use normalized structured
metrics and exact profile identity.

## Tests

Ordinary tests use bounded format-compatible checked-in JSON fixtures and need no Yosys or Docker.
Run real host-tool checks only on a trusted development machine:

```bash
VERIGYM_RUN_YOSYS_TESTS=1 pytest -m yosys
```

These local checks record the host executable hash and are exploratory, `local_trusted` results.
They are not comparable to the canonical Docker profile. Run the complete reference-image path
with:

```bash
VERIGYM_RUN_DOCKER_YOSYS_TESTS=1 \
VERIGYM_DOCKER_YOSYS_IMAGE=verigym/open-rtl-tools:iverilog12-yosys067 \
pytest -m docker_yosys
```

Unsupported in Milestone 8 are arbitrary user Yosys scripts, unconstrained SystemVerilog,
multi-clock timing, SDC, OpenROAD, delay, frequency, power, WNS/TNS, formal tools, and signoff.
