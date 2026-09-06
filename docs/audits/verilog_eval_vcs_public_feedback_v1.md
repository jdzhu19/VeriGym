# VerilogEval iterative VCS/MCP feedback qualification v1

Date: 2026-09-03

## Decision and scope

The new `v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1` variant allows a gym operator to replace
VerilogEval AgentEval's existing iterative compile check with commercial VCS. This is a backend
choice for the same bounded feedback class, not a new correctness or PPA signal. The result remains
`diagnostic_only=true`, `benchmark_score_claimed=false`, and outside the upstream Icarus result
partition.

The variant requires two independent model-invisible profiles:

- `synopsys.vcs.public-compile.mcp` handles repeated public `compile` requests before submission;
- `synopsys.vcs.mcp` performs the final hidden regression only after submission.

The public protocol has no testbench, reference, simulation, pass/fail-marker, command, flags,
environment-value, or artifact-return field. It invokes VCS without `-R`. The agent receives only
pass/fail, a stable category, and at most 32 diagnostics containing the controlled candidate path,
line number, and VCS error code. Public and hidden profiles cannot satisfy each other's task
requirements.

## Real commercial qualification

The site-only bundle covered 155 of the 156 upstream VerilogEval tasks. The existing final-VCS
eligibility exclusion remains unchanged:

| Excluded task | Stable reason code |
| --- | --- |
| `Prob099_m2014_q6c` | `reference_testbench_port_contract_mismatch` |

Using VCS `V-2023.12-SP2-2_Full64`, the public bundle resolved every server/client/transport
identity live and executed exactly two compile jobs per eligible task:

| Check | Result |
| --- | --- |
| Reference candidates | 155/155 accepted |
| Compile-shaped syntax controls | 155/155 rejected as `compile_failed` |
| Commercial jobs | 310 |
| Model calls | 0 |
| Automatic retries | 0 |
| Infrastructure failures | 0 |

The public bundle identity is `3c1acf819a46…f8108d`; the full qualification identity is
`2cff28a1eeac…58af0`. The atomic receipt SHA-256 is
`2da28c5c3915571786c63591d82d68bb08891d230bb91105ca05997433e28bac`.

A separately prepared hidden-profile bundle for the same new variant retained all 155 eligible
task identities and the same exclusion. A bounded `Prob001_zero` qualification accepted the
reference and rejected the known-bad candidate in two real hidden VCS jobs, with no model call or
retry. Finally, an opt-in end-to-end run performed this sequence through VeriGym core:

1. apply invalid RTL;
2. receive a public VCS/MCP `compile_failed` observation;
3. repair the candidate and receive a public VCS/MCP pass;
4. submit once and pass the separate hidden VCS/MCP regression;
5. validate the frozen run by offline replay.

The end-to-end sequence passed first with the trusted local fixture runtime and then with the
digest-locked `verigym/rtl-iverilog:12.0` Docker runtime (`network=none`, UID/GID 10001). In the
Docker case, only the fixed public and hidden MCP wrappers ran on the trusted controller. The
public and hidden resolved profile hashes were both present and unequal, and the manifest recorded
two public invocations. This verifies actual multi-turn routing without calling a model or
rewriting an earlier episode.

## Isolation and regression evidence

After qualification, public qualification staging, server candidate staging, and the dedicated
process temporary directory contained zero residual files. A scan of the committed-style receipt
found no absolute site paths, license names or values, testbench identifiers, or reference RTL.
Server/client profiles, wrappers, hidden assets, raw VCS logs, and complete receipts remain in the
external site-data and experiment directories and are not committed.

Credential-free regression completed with 1,291 core tests passed, one real-Codex opt-in skipped,
and 52 unrelated tests deselected by the repository configuration. The Synopsys integration
completed 47 credential-free tests with one real-VCS opt-in skipped; that opt-in separately passed
against both local and Docker runtimes. Ruff, format checking, core mypy, integration mypy,
persistent-schema export/check, and diff checks also passed.

The Synopsys integration was reinstalled editable using only the environment's existing build
dependencies. All three new console entry points loaded, the run help exposed both public-profile
options, and `verigym doctor` reported both the direct public compiler adapter and the fixed public
VCS/MCP profile healthy.

Aggregate task-identity hashes for `v2-spec-to-rtl`,
`v2-spec-to-rtl-agent-eval-v1`, and `v2-spec-to-rtl-agent-eval-vcs-mcp-v1` were computed from the
pre-change commit and the final worktree and matched byte-for-byte. The new variant therefore adds
an identity partition without mutating a historical task identity.

This qualification establishes compiler replacement and isolation behavior. It does not claim
that compile success proves functional correctness, that the finite controls exhaust possible
errors, or that VCS results are numerically interchangeable with an upstream Icarus partition.

## Real Codex CLI integration smoke

One bounded scoring episode subsequently exercised the same route with the real Codex CLI rather
than the scripted zero-model agent. The frozen source commit was `80b6b76353ba…03b4201`; the source
tree was clean at planning time. The run used `codex-cli 0.147.0`, requested GPT-5.4 with `xhigh`
reasoning, and bound the `codex-cli-agenteval-gpt54-xhigh-v10` agent identity. The provider event
stream did not echo a model identifier, so the model identity remains explicitly
`requested_only`; no observed-model claim is made.

The single `Prob001_zero` episode completed successfully:

| Check | Result |
| --- | --- |
| Codex processes / automatic retries | 1 / 0 |
| Model calls reported by the complete CLI event stream | 1 |
| Repository tool calls | 10 |
| Reads / patches / diff inspections | 3 / 1 / 1 |
| Iterative public VCS/MCP compiles | 1, passed |
| Typed `finish` calls | 1 |
| Final hidden VCS/MCP regression | passed |
| Candidate resolved | yes |
| Process wall time | 66.935 s |
| Input / output / total tokens | 92,492 / 1,750 / 94,242 |

The public evaluation hash matched the frozen public profile, the final verifier hash matched the
frozen hidden profile, and the two resolved hashes were unequal. The Docker workspace used
`network=none`; its agent and verifier sessions reported complete cleanup, and the Codex process
group was cleaned. Offline replay and the model-facing leakage scan both passed. Raw event output,
message content, and reasoning content were not persisted.

The opt-in launcher is `scripts/run_verilog_eval_vcs_public_codex_smoke.py`. The external campaign
is `verilog-eval-vcs-public-codex-gpt54-xhigh-smoke-v1`; its plan, authorization ledger, manifest,
scorecard, replay, and security summaries remain outside the repository. This one-task smoke proves
that a real Codex CLI episode can consume iterative public VCS/MCP feedback and then receive a
separate hidden VCS/MCP verdict. It is not a benchmark score or a claim about all 155 eligible
tasks.
