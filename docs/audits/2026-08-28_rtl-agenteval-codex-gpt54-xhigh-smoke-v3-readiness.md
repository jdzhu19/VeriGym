# RTL AgentEval Codex GPT-5.4/xhigh smoke-v3 readiness

Date: 2026-08-28

Status: smoke-v3 was subsequently executed and stopped fail-closed. It is now a read-only failed
campaign. No benchmark score or pilot result exists, and smoke-v2 remains read-only.

## Execution outcome

The plan-only pass completed the real Docker/OpenSTA, DC/MCP, VCS/MCP, reference, known-bad, and
consecutive-resolution gates with zero model calls. The formal run then produced two ledger
records with zero retries:

- ordinal one started one real Codex process and recorded one complete provider observation, but
  ended in a contained terminal workspace-policy failure without typed `finish`;
- ordinal two was authorized but did not start a model process because exact commercial profile
  replay failed; ordinals three and four were never authorized.

The infrastructure mismatch was traced to `max_output_bytes`, which is tightened after a Docker
session is created but had been included in the MCP runtime resource hash. Preflight froze the
post-session value, while a fresh run resolved the profile before creating a session. The
successor excludes only this session-local field, continues to bind all stable memory, swap, CPU,
PID, tmpfs, timeout, and artifact limits, and uses campaign `smoke-v4` with a new commercial
release. Smoke-v3 is not resumed.

## Frozen campaign contract

- Campaign: `rtl-agenteval-codex-gpt54-xhigh-smoke-v3`.
- Agent: `codex-cli-agenteval-gpt54-xhigh-v2`.
- Model request: GPT-5.4, `xhigh`, seed 0, one process per task, no automatic retry.
- Four ordered tasks: the two RTLLM AgentEval variants, VerilogEval Prob001, and RTL-Repo
  `test-000000`.
- New DC site profiles must bind `commercial_worker_release.v1`; smoke-v2 profiles and output are
  not modified or resumed.

## Implemented gates

Resolved-profile comparison persists only expected/observed hashes and changed component names.
The components are runtime, transport, server release, remote tools, remote assets, flow,
reference, worker contract, and source projection. Smoke-v3 resolves every synthesis profile twice
before model authorization and fails closed on any component drift. A hash-only smoke-v2 baseline
can still be audited conservatively without exporting site values.

The commercial release binds server/worker/startup code, profile and remote-tool identities,
hash-only commercial asset manifests, and worker isolation. The release code bundle is read-only
and content-addressed. Resolve and execute carry the expected release hash; code mutation and
receipt mismatch are infrastructure failures. Legacy release-free worker-protocol-v1 messages
remain schema-compatible.

The Codex v2 adapter parses every returned process before classifying broker or infrastructure
failure and records exactly one observed or requested-only identity. Incomplete usage remains
explicitly incomplete and contains no inferred token counts. Broker responses contain only a safe
error subtype, minimal state, and next allowed actions; workspace-boundary violations remain
terminal.

The launcher ledger distinguishes authorization, actual process start, provider observation, and
retry count. Contained model failure or verifier rejection does not skip later ordinals;
infrastructure-invalid outcomes stop immediately. Four completed runs are replayed offline and
scanned for exact hidden/reference data, site paths, and commercial diagnostics.

## Promotion rule

The 14-run pilot remains unauthorized until a successor smoke has four real process starts, four unique
identity observations, four resolved candidates terminated through typed `finish`, current valid
candidate PPA for both RTLLM tasks, passing replay and leakage audit, and no policy or
infrastructure failure. Failure to meet any condition produces no benchmark score.

## Offline verification

- Core and Codex tests: `1047 passed, 1 skipped, 52 deselected`.
- RTLLM: `11 passed, 4 skipped`; RTL-Repo: `13 passed, 1 skipped`;
  VerilogEval code-complete: `5 passed, 1 skipped`.
- Synopsys integration, including release and mutation checks: `28 passed`.
- Ruff, repository format check, committed schema drift check, core mypy, Codex integration mypy,
  and Synopsys integration mypy passed.

The offline checks above predated the real execution. The execution outcome records the later
opt-in result; it did not satisfy the promotion rule.
