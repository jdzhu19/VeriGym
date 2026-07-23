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
  --output .verigym/release-audit-<commit> \
  --wheelhouse /path/to/hashed-wheelhouse \
  --python-311 /path/to/python3.11 \
  --python-312 /path/to/python3.12 \
  --python-313 /path/to/python3.13 \
  --verilog-eval-root /path/to/pinned/verilog-eval \
  --docker-iverilog-image verigym/rtl-iverilog:12.0 \
  --docker-yosys-image verigym/open-rtl-tools:iverilog12-yosys067
```

Prepare the dependency wheelhouse and exact-commit external checkout separately;
the audit does not download them. The command requires a clean committed
worktree, refuses to overwrite an existing audit directory, and returns nonzero
whenever any required gate is failed, blocked, skipped, or missing.
