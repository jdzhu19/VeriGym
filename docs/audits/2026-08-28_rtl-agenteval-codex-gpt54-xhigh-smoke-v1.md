# RTL AgentEval Codex GPT-5.4/xhigh smoke audit

Date: 2026-08-28

Status: implementation qualified; real four-process smoke not executed.

This is a development and infrastructure qualification, not a benchmark score. No candidate
result, pass rate, or PPA comparison is reported because no Codex model process was observed.

## Frozen identities

- Agent: `codex-cli-agenteval-gpt54-xhigh-v1`.
- Model request: GPT-5.4 with `xhigh` reasoning, seed 0, one sample per task.
- Codex CLI: `codex-cli 0.147.0`.
- Codex executable SHA-256:
  `134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477`.
- Open tool image:
  `sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`.
- OpenSTA executable SHA-256:
  `343bdff22f5d81d92f6bd1286e064b590305503c514194fae02e6c9cc3626662`.

The open image was built through the qualified user-defined build bridge. Its networkless probe
confirmed Icarus 12, Yosys 0.67, the pinned ABC source identity, and OpenSTA 3.1.0. Benchmark,
agent, synthesis, and verifier sessions remained `network=none`.

## Implemented boundaries

- The scoring-only Codex adapter exposes exactly the six `repository_action.v2` MCP tools through
  the Unix-socket broker. It uses an ephemeral empty control directory, a read-only sandbox, and
  disables shell, Web, skills, plugins, apps, rules, and user configuration.
- The adapter permits 40 total repository calls, 20 patches, and three consecutive rejected calls.
  It exports only sanitized identity, usage, event counts, broker counters, hashes, and failure
  categories; it does not export prompts, responses, raw event streams, or training transcripts.
- `synthesis_source_projection.v1` binds AgentEval workspace sources under `repository/rtl/` to the
  existing profile/server contract under `rtl/`. Candidate, reference, feedback, final scoring,
  profile resolution, and replay use the same projection hash.
- Docker OpenSTA identity is resolved inside the immutable image, not through a host executable
  path. A process-local cache reuses only an exact image-ID/executable observation.
- DC/MCP remains a host verifier control-plane transport with a hash-bound disposable worker.
  VCS/MCP remains an independent hidden functional verifier and is never model-visible.
- The launcher preflights all data, CLI, Docker, open synthesis, commercial synthesis, and VCS
  identities before model authorization. It freezes four ordered runs and has no automatic retry.

## No-model qualification and stopped executions

One complete plan-only qualification passed both RTLLM Icarus reference/known-bad cases, both open
reference synthesis cases, the DC/MCP reference synthesis case, and both VCS/MCP reference/known-bad
cases. It emitted `qualified_plan_only` with `model_calls: 0`.

The first execution attempt then stopped before Codex launch because the launcher had frozen only
the `expected_*` agent bindings, not the identical batch pre-launch `resolved_*` bindings. The
orchestrator rejected the mismatch before creating a run directory or external-agent observation.
The authorization ledger therefore contains one failed pre-launch authorization, but that record
does not represent a spawned Codex process or provider request.
The launcher now binds the prompt, prompt hash, agent configuration hash, action protocol, and
feedback contract in both namespaces. A regression test covers all five bindings. Because this
changes run configuration hashes, the corrected launcher registers campaign `smoke-v2` and uses a
new experiment root; the scoring-agent identity is unchanged because neither its prompt nor adapter
changed.

The corrected plan-only qualification later stopped on the first OpenSTA reference synthesis
qualification. The qualification path and all frozen inputs were unchanged from the earlier
successful checks, and the failure occurred before the corrected pre-launch binding was consumed.
This was treated as an infrastructure-invalid shared Docker control-plane outcome. Repository
discipline requires stopping rather than authorizing model processes after such an outcome.

Observed real Codex process count: **0**. Offline replay and artifact leakage scanning were not run
because there were no completed model runs. The 14-run bounded pilot remains unauthorized.

## Verification

- Core: `1017 passed, 1 skipped, 52 deselected`.
- Ruff: passed.
- Format check: passed for 633 files.
- Core mypy: passed for 213 source files.
- Codex CLI integration mypy: passed for 25 source files.
- RTLLM integration: `11 passed, 4 skipped`; mypy passed.
- RTL-Repo integration: `13 passed, 1 skipped`; mypy passed.
- VerilogEval integration: `5 passed, 1 skipped`; mypy passed.
- Synopsys integration: `23 passed`; mypy passed.
- Added-line security scan found no concrete site address, HPC path, credential, proxy value, or
  private key. Dataset contents, PDK files, SDCs, image layers, commercial reports, and experiment
  trajectories remain outside the repository.

## Resumption condition

Resume only in a fresh campaign root after the shared Docker control plane again completes the
entire no-model qualification. Preserve GPT-5.4/xhigh, Codex CLI and executable hashes, seed 0,
sample count 1, image ID, profile hashes, and worker identity. Do not retry a started Codex process.
Any agent or prompt change requires a new agent version and another fresh experiment root.
