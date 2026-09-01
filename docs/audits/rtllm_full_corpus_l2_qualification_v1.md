# RTLLM full-corpus L2 qualification v1

Date: 2026-09-01

Status: passed. This is zero-model qualification of a derived, diagnostic-only functional Gym
projection for all 50 frozen RTLLM 2.0 tasks. It is not a native RTLLM score, a model campaign,
PPA qualification, or proof that the public smokes exhaustively specify each design.

## Frozen scope

- Variant: `v2-agent-eval-functional-all-v1`.
- Task IDs: `rtllm/v2-agent-eval-functional-all-v1/<task-name>`.
- RTLLM commit: `41b26896e33b536940116a975626455eed3de65e`.
- Frozen inventory: 50 task directories and 207 files.
- Dataset-files hash:
  `5877ebc9ab8dbf6aada22a981cd9e087423ea95ce15e527e9cac47122733edda`.
- Aggregate task-identity hash:
  `9a36fdf432c0cbfc2dfaef7a2b067a5ef02b83578e38c0f2015113e7ae9e3d38`.
- Aggregate 50-entry public-smoke hash-map identity:
  `67ebd073f9e03e87322764b9bdc6950d14342e7497fcb5036acc1c1938b26e48`.
- Aggregate 50-entry workspace-scaffold identity:
  `c66f51cdc10bb94b7f53c9dea74db243e108fa96b629dc9398941171f732de68`.
- Adapter/suite identity: `0.10.0` /
  `rtllm-41b2689-v2-agent-eval-functional-all-v1`.

The variant reuses the two counter, four harder, and six batch-one/batch-two functional assets and
adds independently authored public smokes and interface-only candidate skeletons for the remaining
38 tasks. It records `gym_qualification_level=L2_functional_smoke`, `diagnostic_only=true`, and
`benchmark_score_claimed=false`. Both `agent_eval.ppa_supported` and `scoring.ppa_enabled` are
false. No Yosys, OpenSTA, VCS, Design Compiler, model, or agent process ran in this qualification.

## Functional and isolation contract

Every task exposes exactly one editable repository-relative entry,
`repository/rtl/<task-name>.v`, plus a read-only public smoke. Public smokes are derived from the
upstream prompt and interface and do not copy hidden vectors, expected-output files, or pass/fail
markers. They cover task-appropriate reset, boundary, data, ordering, handshake, and latency
behavior. Individual smoke SHA-256 values are frozen in
`FULL_FUNCTIONAL_PUBLIC_SMOKE_SHA256`.

The upstream prompt bytes remain unchanged; ambiguity notes are separately appended and hashed.
Hidden testbenches and auxiliary files remain outside the model-visible workspace and public-test
mount. They are declared by content hash and staged only for final verification after typed
`finish`. `asyn_fifo` auxiliary files and other task data files were checked absent from visible
workspaces.

Two underconstrained upstream testbenches required explicit, verifier-only judgeability guards:

- `edge_detect`: four boolean checks used conjunction, so a single wrong output could pass. The
  frozen projection changes those four guards to disjunction; projected SHA-256 is
  `1977e8409bdac622923e0410fe2df517497b5ca00a6245689d98b2e0decd7eda`.
- `square_wave`: the upstream test rejected overly long high runs but accepted a permanently low
  output. The frozen projection counts high samples and requires at least one; projected SHA-256
  is `7aed90f4de40fdc561324c4eeb62e84ae1e85eed887c69418cf7ba540eac5c7b`.

These projections preserve the original stimulus and expected design values. They make the
derived verifier stricter and are therefore part of this diagnostic variant's identity; results
must not be reported as native RTLLM leaderboard results.

## Qualification matrix

For every task, the normalized upstream reference and four independently authored, compile-shaped
negative controls were run against both the public smoke and hidden verifier. The four categories
were stuck-zero, reset/initial-boundary error, protocol/latency or wiring error, and task-specific
functional error. Combinational tasks interpret the reset/protocol buckets as initial-boundary and
wiring controls because they have no clock or reset protocol.

| Check | Cases | Result |
| --- | ---: | --- |
| Reference public smoke | 50 | passed |
| Reference hidden verifier | 50 | passed |
| Four controls, public smoke | 200 | rejected |
| Four controls, hidden verifier | 200 | rejected |
| Total compile/simulation verdicts | 500 | matched expectation |

Development prequalification used host Icarus 12 and produced the same 500/500 matrix. Final
qualification used `verigym/open-rtl-tools:iverilog12-yosys067-opensta310`, resolved without pull
to `sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`.
All 250 candidates were staged into a verifier-only Docker session and executed as 250 public plus
250 hidden compile/simulation paths with networking disabled. The final opt-in test passed in
48.81 seconds. There were no compile failures, timeouts, automatic candidate retries, or model
calls.

## Implementation and artifact checks

- Full source-backed RTLLM plugin tests: 127 passed, 13 explicit Docker/commercial opt-ins
  skipped; strict mypy passed for all four plugin source files.
- Repository-wide ordinary tests: 1,241 passed, one real-Codex opt-in skipped, and 52 external
  cases deselected.
- Repository-wide Ruff lint and format checks passed for 673 files; core strict mypy passed for
  215 source files.
- CLI source validation returned `valid=true` for the full L2 variant and frozen checkout.
- A protected-asset scan compared 76 new packaged assets with 106 upstream testbench, reference,
  and auxiliary files: no hash collision or protected marker/path reference was found.
- A no-isolation wheel build contained exactly 38 new public smokes and 38 new interface
  skeletons, with no testbench, `verified_`, verifier, or hidden file.

## Interpretation

The RTLLM frozen corpus now has 50/50 functional L2 Gym coverage under the unified variant. The
older `v2-agent-eval-all-v1` remains a distinct 50-task L1 compile-only identity, and all historical
counter, harder, and batch variants remain available unchanged.

This result establishes that every task has repeatable candidate-only functional feedback, a
passing normalized reference, four rejected control classes, a final hidden verifier, and protected
asset isolation. It does not establish exhaustive correctness for unseen candidate bugs, PPA
fitness, commercial-tool compatibility for all tasks, model success rate, or a benchmark score.
Any later PPA-enabled corpus variant requires separate per-task synthesis qualification and a new
frozen identity.
