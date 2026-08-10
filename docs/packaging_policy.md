# Packaging policy

The wheel contains Python modules plus explicitly declared first-party runtime assets: toy tasks,
the VerilogEval adapter metadata, built-in profiles, and the educational toy Liberty file. The
sdist additionally contains source, tests, documentation, Docker recipes, scripts, and the
installable plugin-conformance fixture.

First-party optional integrations under `integrations/` remain separate packages rather than part
of the core wheel. Package CI builds `verigym-codex-cli` and
`verigym-verilog-eval-codecomplete` independently and installs their wheels beside the core wheel.
The alpha release audit additionally performs the Codex-specific credential and executable scan.
The `verigym-hwe-bench` wheel contains only adapter code: prepared JSONL records, golden patches,
testbench scripts, extracted repositories, OCI archives, and per-PR images are forbidden members.

Included fixtures are small, synthetic, and explicitly licensed. Packages must not contain an
external VerilogEval checkout, commercial binaries, PDKs, proprietary cell libraries, model
weights, credentials, audit runs, caches, virtual environments, Docker layers, private
configuration, or host-specific absolute paths. User-supplied benchmark and licensed-tool assets
are referenced only by safe logical identity and hashes.

Runtime dependencies have lower and upper bounds; optional HTTP support is isolated in the
`openai-compatible` extra. Package metadata uses SPDX `Apache-2.0`, includes `LICENSE` and
`NOTICE`, declares Python 3.11+, and publishes repository/documentation/issue URLs.

Before a candidate build, inspect both archive member lists, validate `METADATA`, scan names and
text for forbidden paths/secrets or generated plugin build trees, install the wheel in an isolated
environment, run `pip check`, and compare two builds made with the same `SOURCE_DATE_EPOCH`.
Installed public-API conformance also runs the complete RTL example and therefore requires real
`iverilog` and `vvp` executables; their version outputs are evidence, not package contents.

The local audit driver requires a clean committed worktree plus explicit release inputs:

```bash
python scripts/run_release_audit.py \
  --output .verigym/release-audit-<commit> \
  --wheelhouse /path/to/hashed-wheelhouse \
  --python-311 /path/to/python3.11 \
  --python-312 /path/to/python3.12 \
  --python-313 /path/to/python3.13 \
  --codex-binary /path/to/codex-0.144.6 \
  --verilog-eval-root /path/to/pinned/verilog-eval
```

The wheelhouse and external checkout are prepared outside the audit. When a wheelhouse is supplied,
both the isolated build frontend and clean-install checks resolve dependencies from it with package
indexes disabled. The driver never publishes, tags, pushes, pulls images, or downloads a benchmark.
It refuses dirty source and existing output; unavailable required resources remain blocked/skipped
evidence and fail the candidate gate.
