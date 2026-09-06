# RealBench bounded module projection (draft)

This is a bounded module adapter with a Docker-only functional backend, **not a suite-qualified
RealBench benchmark**. Three real modules have reference, functional-negative and syntax-negative
coverage. Final SEC still requires the optional [Cadence integration](../verigym-cadence/README.md)
and approved site execution. Native metric aggregation and full 60-module/4-system execution are
not implemented. See the [qualification evidence](../../docs/audits/2026-09-06-realbench-functional-slice.md).
The subsequent [SEC site attempt](../../docs/audits/2026-09-06-realbench-sec-site-attempt.md)
passed three profile preflights but stopped on the first reference's license failure; no formal
control has been qualified, and no further SEC invocation is automatic.

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

The adapter reuses core candidate freezing and offline patch replay. A synthetic two-file edit
round-trips exactly without source data or EDA tools during replay; changed read-only image bytes
are rejected. These tests do not substitute for final commercial SEC qualification.

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
profile targeting `cadence.jaspergold.sec.mcp`. Both are model-invisible tool integrations:
missing functional support must fail preflight, not silently become lint-only.
The final DAG's `realbench.sec` source node must be replaced by the mandatory resolved profile.
Final verification additionally requires typed final submission. Preparing data or passing a
public test does not authorize commercial execution.

## Prepare the three-module functional slice

The operator must first provide the pinned decrypted checkout and independently authored,
interface-only stubs at `verigym-inputs/aes_sbox.sv`, `verigym-inputs/aes_rcon.sv`, and
`verigym-inputs/aes_key_expand_128.sv`. The selected modules' public specs define those interfaces.
Do not use the upstream target `.v` files as stubs: they contain the solutions. The hierarchy task
receives submodule interfaces in its specification; submodule RTL stays verifier-only, including
the S-box and Rcon solutions that are targets elsewhere in the slice.

From the repository root, set `REALBENCH_SOURCE` to the prepared checkout, `REALBENCH_BUNDLE` to a
new external profile directory, `REALBENCH_IMAGE`/`REALBENCH_IMAGE_ID` to an installed
[functional image](../../docker/realbench-verilator/README.md) and its full immutable image ID,
and `TMPDIR` to the designated scratch directory. Then explicitly prepare:

```bash
python -m verigym_realbench.prepare --source-root "$REALBENCH_SOURCE" \
  --visibility-audit docs/audits/2026-09-06-realbench-functional-slice.md
python -m verigym_realbench.prepare_public --source-root "$REALBENCH_SOURCE" \
  --bundle-root "$REALBENCH_BUNDLE" \
  --image "$REALBENCH_IMAGE" --image-id "$REALBENCH_IMAGE_ID"
```

Preparation refuses existing outputs. The source lock and full 60/4 asset-hash inventory remain
external. The client/server profiles and no-argument stdio wrappers also remain external; they
contain operator paths and must not be published. Preparation starts no Docker, model or SEC job.

For explicit zero-model functional qualification, set `REALBENCH_RESULT` to a new JSON output:

```bash
python -m verigym_realbench.qualify_public --source-root "$REALBENCH_SOURCE" \
  --bundle-root "$REALBENCH_BUNDLE" --output "$REALBENCH_RESULT"
```

This runs at most nine controls (three per module), stops on unexpected/infrastructure outcomes,
and never overwrites or resumes a previous invocation. `--task` and `--case` can narrow it.
Reference candidates are verifier-only controls, not agent inputs. The existing test ID `compile`
now runs both syntax and function for this explicitly named backend; returned fixed messages
distinguish syntax/policy rejection, functional mismatch and infrastructure failure. Private
testbench output does not reach the agent. No upstream Makefile is executed.

The flow intentionally differs from native scoring: it accepts only a restricted single-module
RTL subset, suppresses raw diagnostics, requires complete output verdicts, and recognizes the
hierarchy testbench's alternate mismatch format that the upstream parser misses. Trace/coverage
generation and annotation are omitted; source, assertion, timing and warning settings remain
bound by the implementation and image. These results must not be reported as native pass@k.

`scripts/realbench_scripted_functional_slice.py` exercises the shared public environment, typed
finish, candidate freeze, leakage checks and source-free candidate replay on one scripted S-box.
It computes a repair from public GF(256) math, never reads golden RTL into the agent, and explicitly
does not execute final SEC or produce an orchestrator scorecard.

Tasks are marked diagnostic-only, module-partitioned and non-scoring. The metadata records
the intended `syntax@k`, `func@k`, `formal@k` dimensions; it does not calculate those metrics.
The bounded functional evidence does not establish complete module/system coverage, model image
consumption, commercial-tool qualification, or native-score compatibility.

Upstream evidence: [repository](https://github.com/IPRC-DIP/RealBench),
[pinned catalog](https://github.com/IPRC-DIP/RealBench/blob/9bc9a6ac058b3a3acb09b9e7623526737bbf8312/benchmark_info.py),
[native verifier](https://github.com/IPRC-DIP/RealBench/blob/9bc9a6ac058b3a3acb09b9e7623526737bbf8312/run_verify.py).
