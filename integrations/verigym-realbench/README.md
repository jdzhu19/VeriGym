# RealBench bounded module projection (draft)

This is an initial source adapter, **not an executable or qualified RealBench benchmark**.
The Verilator functional backend, typed-finish end-to-end qualification, native metric
aggregation, and full 60-module/4-system support are not implemented. Final SEC uses the optional
[Cadence integration](../verigym-cadence/README.md), which is also not site-qualified.

## Validate the adapter without benchmark data

From the repository root, using Python 3.11+:

```bash
python -m pip install -e '.[dev]' \
  -e integrations/verigym-cadence -e integrations/verigym-realbench
pytest -c integrations/verigym-realbench/pyproject.toml integrations/verigym-realbench/tests
mypy --config-file integrations/verigym-realbench/pyproject.toml integrations/verigym-realbench/src
```

Synthetic tests cover combinational, sequential and hierarchical task projections; they are
not official tasks or evidence of hardware correctness. They exercise source drift, multi-file
editable boundaries, Markdown/image projection, hidden-content exclusion and missing-profile
rejection. No tests download or decrypt a corpus.

## Supply an audited external source

The adapter accepts only an operator-prepared checkout and `verigym-realbench.lock.json` at its
root. [source.py](src/verigym_realbench/source.py) defines the strict lock schema. It binds:

- Upstream commit `9bc9a6ac058b3a3acb09b9e7623526737bbf8312`, exact MIT license and catalog bytes.
- At most three explicitly selected module tasks from the pinned 60-module catalog; the four
  systems are counted but not exposed as supported tasks.
- A written visibility-audit reference, and each spec, image, candidate stub, approved public
  dependency, verification asset, reference and SEC template hash.
- Public-only workspace destinations; hidden assets cannot have a public destination or share
  a content hash with a public asset within the same task.

The lock and datasets stay external. The adapter does not run `benchmark_info.py`, upstream
Makefiles, decryption scripts or task generators. It checks the catalog using literal AST
parsing, verifies all declared bytes and rechecks before materializing a task. A file-role
declaration is not a content audit: the operator still must verify that a purported stub or
public dependency does not disclose the target solution.

The variant is `module-slice-draft-v1`; the lock hash participates in task IDs and snapshots.
Markdown and image bytes are projected under read-only workspace globs; only declared stubs
are editable. No target golden, testbench or Tcl is copied into the model workspace. Image
projection is tested, but actual image consumption by a model is not yet demonstrated.

## Execution gates

Tasks require both a public profile targeting `realbench.verilator.public.mcp` and a final
profile targeting `cadence.jaspergold.sec.mcp`. The public backend is intentionally not yet
registered: missing functional support must fail preflight, not silently become lint-only.
The final DAG's `realbench.sec` source node must be replaced by the mandatory resolved profile.

Tasks are marked diagnostic-only, module-partitioned and non-scoring. The metadata records
the intended `syntax@k`, `func@k`, `formal@k` dimensions; it does not calculate those metrics.
The real source/visibility audit must precede implementation of the functional wrapper and
any claim about upstream-compatible scores or end-to-end typed finish/replay.

Upstream evidence: [repository](https://github.com/IPRC-DIP/RealBench),
[pinned catalog](https://github.com/IPRC-DIP/RealBench/blob/9bc9a6ac058b3a3acb09b9e7623526737bbf8312/benchmark_info.py),
[native verifier](https://github.com/IPRC-DIP/RealBench/blob/9bc9a6ac058b3a3acb09b9e7623526737bbf8312/run_verify.py).
