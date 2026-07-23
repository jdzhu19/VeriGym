# Contributing

Use Python 3.11 or newer. Install the project with its development extras, then
run `ruff format --check .`, `ruff check .`, `mypy --strict src/verigym`, and
`pytest` before opening a pull request. External Docker, Yosys, and benchmark
tests are opt-in and must state their exact local prerequisites.

Keep changes within the documented MVP contracts. Add focused tests for schema,
artifact, security, replay, or comparison behavior, and update generated JSON
Schemas with `python scripts/export_schemas.py`. Never commit credentials,
downloaded benchmark corpora, run directories, virtual environments, or audit
bundles.

Commit subjects should be short, imperative, and scoped to one coherent change.
Pull requests should explain behavior and compatibility impact, link relevant
issues, list commands actually run, and include screenshots only for rendered
documentation or CLI-output changes.

For a local, non-publishing release audit with prebuilt reference Docker images:

```bash
python scripts/run_release_audit.py \
  --output release_audit \
  --docker-iverilog-image verigym/rtl-iverilog:12.0 \
  --docker-yosys-image verigym/open-rtl-tools:iverilog12-yosys067
```

Add `--verilog-eval-root /path/to/pinned/checkout` only for a user-supplied real
checkout. The command refuses to overwrite an existing audit directory and
returns nonzero whenever any required gate is failed, blocked, skipped, or
missing.
