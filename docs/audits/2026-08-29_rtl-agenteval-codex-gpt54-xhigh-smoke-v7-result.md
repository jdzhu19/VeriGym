# RTL AgentEval Codex GPT-5.4/xhigh smoke-v7 result

Date: 2026-08-29

Status: smoke-v7 passed its frozen four-process qualification. The campaign authorizes the
separately gated 14-run pilot, but the pilot has not started and no benchmark score is claimed.

## Scope and frozen identity

- Campaign: `rtl-agenteval-codex-gpt54-xhigh-smoke-v7`.
- Model request: GPT-5.4, `xhigh`, seed 0, one process per task, and zero automatic retries.
- Agent: `codex-cli-agenteval-gpt54-xhigh-v4`, with version hash
  `3013e36846e016c6b57b9d28c811317718902e89b40fd522e4f49de3c93dd040`.
- Commercial worker release hash:
  `0ac64101403e24a61bffbd1621af552dcbb6f95501c24a68d2951eaeeef27e76`.
- Ordered tasks: RTLLM counter with open PPA, RTLLM up/down counter with commercial PPA,
  VerilogEval Prob001, and RTL-Repo `test-000000`.

The complete plan-only pass recorded zero model calls. Dataset, Codex CLI, Docker/OpenSTA,
content-addressed commercial workers, VCS/MCP, reference, known-bad, candidate-feedback,
output-directory, and broker-root checks passed before formal model authorization.

## Execution outcome

All four authorizations started exactly one real Codex CLI process, recorded exactly one valid
external-agent identity observation, and used retry count zero. Every candidate resolved through
one typed `finish`; no run had a policy or infrastructure failure.

| Ordinal | Task | PPA feedback | Typed finish | Resolved | Outcome |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | RTLLM counter, open | 2 | 1 | yes | completed |
| 2 | RTLLM up/down, commercial | 3 | 1 | yes | completed |
| 3 | VerilogEval Prob001 | 1 | 1 | yes | completed |
| 4 | RTL-Repo `test-000000` | 0 | 1 | yes | completed |

Both RTLLM manifests contain a passing current-candidate PPA observation bound to the final
candidate and resolved profile hashes. The open run's final ranking projection separately marks
power-activity comparability ineligible; that does not erase its legal candidate-feedback
observation and no benchmark score is derived from this smoke.

## Replay and leakage evidence

The first campaign-level replay attempt failed closed after all four model processes had finished.
It exposed a replay validator defect: the Yosys/OpenSTA flow identity is the hash of a deterministic
two-script bundle, while replay incorrectly required either individual script hash to equal the
bundle hash. No model process was retried.

Replay now reconstructs the exact two-script bundle identity, continues to validate every exported
artifact's size and content hash, rejects unknown or duplicate script bundles, and retains the
single-script commercial flow check. A no-model finalizer validates the frozen plan, exact four-run
layout, authorization ledger, and materialized identity evidence before writing campaign evidence.

Final evidence reports:

- four of four offline replays integrity-valid;
- exact leakage scan passed with zero findings;
- four model identities valid and four provider observations present;
- four candidates resolved with typed `finish`;
- both RTLLM candidates have legal current PPA feedback;
- no policy or infrastructure failures; and
- `fully_successful=true`, `pilot_authorized=true`, and `benchmark_score_claimed=false`.

The committed audit contains no prompt, response, reasoning, commercial report, private asset,
site path, worker address, or credential.

## Verification

- `ruff check .`
- `ruff format --check .`
- `mypy src`
- `pytest -q`: 1066 passed, 1 skipped, 52 deselected
- Codex CLI integration: 5 passed; mypy passed
- RTLLM integration: 11 passed, 4 opt-in tests skipped; mypy passed
- RTL-Repo integration: 13 passed, 1 opt-in test skipped; mypy passed
- VerilogEval integration: 5 passed, 1 opt-in test skipped; mypy passed
- Synopsys integration: 31 passed; mypy passed

## Promotion decision

The smoke gate authorizes the 14-run pilot under the same frozen identities and execution policy.
Pilot execution remains a separate user action. Smoke-v7 is a qualification result, not a
benchmark score, and must not be aggregated or reported as one.
