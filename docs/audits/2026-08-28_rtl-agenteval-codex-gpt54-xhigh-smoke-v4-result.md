# RTL AgentEval Codex GPT-5.4/xhigh smoke-v4 result

Date: 2026-08-28

Status: smoke-v4 executed all four frozen Codex processes but did not pass. The campaign is now
read-only, no benchmark score exists, and the 14-run pilot is not authorized.

## Scope and frozen identity

- Campaign: `rtl-agenteval-codex-gpt54-xhigh-smoke-v4`.
- Agent: `codex-cli-agenteval-gpt54-xhigh-v2` at VeriGym commit `4280ed8f3bb0`.
- Model request: GPT-5.4, `xhigh`, seed 0, one process per task, and zero automatic retries.
- Ordered tasks: RTLLM counter with open PPA, RTLLM up/down counter with DC/MCP PPA,
  VerilogEval Prob001, and RTL-Repo `test-000000`.

The plan-only pass and the fresh formal preflight completed before model authorization. Dataset,
Codex CLI, digest-pinned Docker/OpenSTA, both content-addressed DC worker profiles, VCS/MCP,
reference, known-bad, output-directory, and broker-root gates passed. Both DC profiles resolved
twice without component drift. A fresh post-plan resolution probe also reproduced the exact
up/down DC resolved hash and every redacted component hash.

## Execution outcome

All four authorizations launched a real Codex process and recorded exactly one external-agent
identity record. Each accounting record reports one model call and complete provider usage; the
identity records are nevertheless `requested_only` because no observed model ID was present.
Every retry count is zero.

| Ordinal | Task | Tools / reads / patches | Public tests / PPA | Diff / finish | Outcome |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | RTLLM counter, open | 11 / 6 / 3 | 1 / 0 | 0 / 0 | terminal workspace policy |
| 2 | RTLLM up/down, DC | 13 / 8 / 3 | 1 / 0 | 0 / 0 | terminal workspace policy |
| 3 | VerilogEval | 11 / 7 / 2 | 1 / 0 | 0 / 0 | terminal workspace policy |
| 4 | RTL-Repo | 7 / 5 / 0 | 0 / 0 | 0 / 0 | broker tool infrastructure |

No task reached typed `finish`, no candidate resolved, and neither RTLLM task produced a current
candidate PPA observation. The run therefore proves that the four model processes and the
preflight open/commercial control planes can be exercised; it does not prove successful
multi-turn completion with either open or commercial feedback.

The persisted safety evidence intentionally contains only the bounded terminal categories
`workspace_policy` and `runtime_tool_infrastructure`. It contains no raw process output, prompt,
response, reasoning, site path, commercial report, or concrete broker error. Consequently the
exact policy subtype for the first three tasks and exact tool subtype for RTL-Repo cannot be
recovered from this campaign without guessing.

## Replay and leakage status

The fourth result was infrastructure-invalid, so the launcher stopped immediately and did not
write campaign-level `summary.json`, `replay.json`, or `security-scan.json`. This is the formal
fail-closed result.

Separate read-only diagnostics found all four run manifests structurally verified, with event
counts 13, 13, 13, and 12. Running the same exact hidden/reference, site-path, and commercial
diagnostic scan over the materialized outputs produced zero findings. These diagnostics did not
modify or complete the failed campaign and are not a substitute for its absent formal
post-processing evidence.

## Promotion decision and next gate

The promotion rule failed on resolved candidates, typed `finish`, RTLLM PPA, policy safety,
infrastructure safety, and formal post-processing. No pilot may start and no benchmark score may
be generated from smoke-v4.

Before another model campaign, a new frozen agent/campaign version should:

1. persist a bounded, non-sensitive terminal broker subtype so the repeated workspace-policy and
   RTL-Repo infrastructure failures can be reproduced without retaining raw output;
2. replay the failing broker action sequences deterministically with scripted clients and verify
   repository-relative path handling for every suite;
3. preserve fail-fast execution while finalizing replay and leakage evidence whenever all four
   run directories were materialized; and
4. require a new empty smoke output and repeat the same four-run matrix with no retries.

The 14-run pilot remains gated on four resolved typed-finish candidates, legal current PPA for
both RTLLM tasks, four valid single-call identity observations, passing formal replay and leakage
evidence, and no policy or infrastructure failure.
