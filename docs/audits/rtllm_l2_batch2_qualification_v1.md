# RTLLM L2 batch-two qualification v1

Date: 2026-09-01

Status: passed. This is zero-model qualification of independently authored public functional
projections for three frozen RTLLM tasks. It is not a model campaign, native RTLLM score, PPA
qualification, or evidence that the remaining RTLLM tasks have L2 coverage.

## Scope and selection

The new variant is `v2-agent-eval-functional-l2-batch2-v1`, with task IDs of the form
`rtllm/v2-agent-eval-functional-l2-batch2-v1/<task-name>`. It contains:

- `Control/Finite State Machine/sequence_detector`;
- `Miscellaneous/Others/synchronizer`;
- `Miscellaneous/RISC-V/RAM`.

The source checkout remains frozen at commit
`41b26896e33b536940116a975626455eed3de65e`. Its 50-task, 207-file inventory hashes are unchanged.
These tasks were the three no-typed-finish control outcomes in the preceding 12-task L1 Codex
pilot. That observation was not a hidden functional verdict. Batch two isolates whether adding
task-specific functional feedback makes these tasks operable; it does not relabel the L1 results
as failures.

The variant records `gym_qualification_level=L2_functional_smoke`, `diagnostic_only=true`, and
`benchmark_score_claimed=false`. PPA is explicitly disabled in both task scoring and the
AgentEval tool contract. This stage invoked no model, Yosys/OpenSTA, VCS, or Design Compiler.

## Public contracts

Each task has one repository-relative candidate file, one independently authored public smoke,
and its original verifier-only hidden testbench. The public smokes derive from the upstream prompt
and interface without copying hidden vectors, expected-output tables, or pass/fail logic.

| Task | Public coverage | Public smoke SHA-256 |
| --- | --- | --- |
| `sequence_detector` | active-low reset, `1001` detection, overlap, near misses, output latency | `822d602bc674ee5b52bd3fb419b9682e398555ada400cdd064eedacfdac724ce` |
| `synchronizer` | two clocks, delayed enable, stable multi-bit transfer, hold behavior, source/destination resets | `ce1663a66d4c9cb93f6328559bc5a6c6bc35565cfa04bcf1a4ab0b9c4dd7a296` |
| `RAM` | initialized contents, synchronous reads, simultaneous independent-port access, read-disable clearing, reset | `57b07132eaee886a2957730036fd879ea9bddc2b242aada596afdc654acba464` |

Separately appended projection notes resolve prompt ambiguity without changing the frozen upstream
prompt bytes. They define overlapping same-cycle sequence detection, the two-domain enable/data
contract, and the RAM's six-bit data by eight initialized address projection.

| Task | Frozen task manifest hash | Public contract hash | Projection-note hash |
| --- | --- | --- | --- |
| `sequence_detector` | `df64756b1035b4b4d4ef6933382e775cc81d2fd7d7dcfdfcb0b18b58a3252d50` | `6f990846d1048720677fbff5fbd7881d2a48a81f01935ecc9c63f59e68952786` | `e6193dee2feefca6401a152e6e864e2f163def6d463c66481354a62b63720167` |
| `synchronizer` | `6d32368103a642b1e6655e375cf516ae1134f74e958173b3b456aebca6b81fe2` | `810048506f8ba756365c1dc8e7dc477d481191ff46bafdcc8ac33fea0ee8e3df` | `81442b9c35666b8dd985ef8b2e20f95daf3d03a6f2df970b5797fcf361e7f2ed` |
| `RAM` | `7429f9b86f4e283d1e127e34b46c0f4db61c3296dbc14e14421258d141fdee59` | `6e9a8c619f61ac8a629e86bc1f96cf4c26ca7dd1450c59fc9821ac79d42fdd47` | `cf42239e2fde10bcc7d20ecb943cf998f22a67c7a4b1bf6421fc41900fa88cb5` |

Public assets are hash-bound, read-only public-test mounts rather than editable candidate files.
Hidden testbenches remain outside the visible workspace and are staged only after typed `finish`;
all three tasks carry `verification_requires_final_submission=true`.

## Qualification result

Qualification used `verigym/open-rtl-tools:iverilog12-yosys067-opensta310`, resolved as
`sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`.
Every short-lived container used networking disabled, a non-root user, a read-only root
filesystem, dropped capabilities, and bounded resources.

For each task, the upstream reference had to pass both the public smoke and original hidden
verifier. Four independently authored negative controls had to be rejected by both paths:
stuck-zero, reset error, protocol/latency error, and task-specific functional error.

| Check | Cases | Result |
| --- | ---: | --- |
| Reference public smoke | 3 | passed |
| Reference hidden verifier | 3 | passed |
| Four known-bad categories, public smoke | 12 | rejected |
| Four known-bad categories, hidden verifier | 12 | rejected |

The final post-refactor full-batch command passed three task-level tests in 502.27 seconds. Each test exercised
ten isolated public/hidden paths, for 30 total verifier paths. There were no model calls and no
automatic candidate retries.

During development, the synchronizer public smoke initially made two invalid assumptions. It
first sampled the output before a reset or destination clock edge, then changed `data_in` before
the delayed enable had drained from the destination pipeline. Both revisions corrected the
independent public driver to satisfy the prompt's reset and stable-data contract. The hidden
testbench, upstream reference, vectors, expected outputs, and pass/fail parser were not modified.

Batch-one and batch-two workspace, public-smoke, hash, suite-version, adapter-version, evaluation,
and feedback identities are resolved through one frozen functional-batch spec mapping. Adding a
later L2 batch therefore extends task/spec data and assets without another task-name control-flow
branch in the adapter.

## Implementation checks

- RTLLM plugin Ruff and format checks passed; strict mypy passed for four source files.
- Ordinary credential-free plugin tests passed: 63 passed and 20 explicit external/commercial
  opt-ins skipped.
- Source-backed adapter and frozen-identity tests passed: 71 passed.
- CLI source validation returned `valid=true` for the batch-two variant and frozen checkout.
- A no-isolation wheel build included all six batch-two public-smoke/workspace assets and no
  `testbench` or `verified_` protected source.
- Repository-wide Ruff and format checks passed for 672 files; core strict mypy passed for 215
  source files.
- Repository-wide ordinary tests passed: 1,241 passed, one real-Codex opt-in skipped, and 52
  external cases deselected.

## Interpretation and next stage

The first two L2 batches now add six qualified functional-smoke tasks to the two original counter
tasks and four harder tasks. There are therefore 12 distinct RTLLM tasks with a functional public
projection and 38 remaining at L1 compile-only coverage.

The next bounded step is a separate three-slot, GPT-5.4/xhigh, seed-0, serial, zero-retry diagnostic
using this batch-two variant. Its purpose is to observe whether these prior no-finish tasks now
produce typed finish and visible repair loops. It must retain one process and identity per slot,
run hidden verification once only after typed finish, keep PPA disabled, and report actual outcomes
without converting them into a benchmark score. A later L2 corpus-expansion batch should remain
independent of that diagnostic outcome.
