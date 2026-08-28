# OpenHands HWE typed-continuation diagnostic v17

Date: 2026-08-28

This audit records one bounded PR-2032 adapter diagnostic. It is protocol and infrastructure
evidence only: it is not a benchmark score, a verifier-passed trajectory, an SFT dataset, or a
training-readiness claim.

## Frozen scope

- task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032`
- model: `openai/deepseek-v4-flash`, thinking disabled, seed `486`
- OpenHands SDK / LiteLLM / tiktoken: `1.42.1` / `1.93.0` / `0.7.0`
- source commit: `7c12f137e6bc86c6f612be29d0f63130fa6fe174`
- source hash: `2db1658df59bd255ed99905f918074f303a70f5cccc84c018527d576927bf95e`
- task hash: `b28544e30225034efb92a35c84a3fa7f30faa0cdf08849df5389a744f600ca71`
- image-lock hash: `c1cb9fdfc78e210dfad5268039b57e8ec7f02cd55def17470c0ccea800a77aa8`
- agent version: `openhands-deepseek-v4-flash-hwe-typed-continuation-v17-diagnostic`
- agent version hash: `fd8f384ba8c71773f0892a709ec66bffd8cda90bca40308a2e3a7c850e032a4c`
- provider tool schema: `canonical_hwe_without_sdk_metadata_all_string_host_path_constraints_v3`
- ordinary tool choice: `auto`
- recovery/continuation choice: `tool_choice="required"` over the exact six-tool contract
- limits: 65,536 context tokens, 2,048 output tokens, 200 iterations, no retry

## Protocol evolution

The following table records the real bounded attempts. A missing or zero counter means that the
corresponding path was not exercised in that attempt; it is not inferred from the model transcript.

| policy | source commit | recovery | SDK continuation | typed tool validation | broker tools | result | report hash |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| v14 | `b219c65` | 1 | not armed | required-tool recovery | 19 | model did not finish | `89ef8cba1083f6b1efd403f0c25548f19a69983c3f07629f06ef6f862c79d1bb` |
| v15 | `9beccaf` | 0 | 0 | provider-argument boundary | 20 | model/provider policy rejection | `c1bf48d22b6d269c930454174ae4d34d16e98838c9941928ff190ede83e2a119` |
| v16 | `bf81be3` | 1 | 1 | required-tool recovery | 17 | model did not finish | `b52eedff862d73b1449de0b27d60d23ace7c7b678ce3b14892db83593f6c6778` |
| v17 | `7c12f13` | 1 | 1 | 1 validated continuation tool | 14 | model did not finish | `440b47085983bd204713c5c732905eef67ff8d94d0053cadd9a2eb5cb57bd423` |

The v14 row is the infrastructure-valid rerun recorded by its sealed report. Earlier v14
diagnostic failures and the v8 evidence remain immutable historical records in their respective
audits.

## v17 result

The diagnostic passed its adapter/protocol acceptance gates:

- one Stop-hook recovery was recorded (`format_recovery_count=1`);
- one same-session SDK continuation was armed and consumed;
- the continuation sent exactly one `tool_choice="required"` request;
- the provider returned exactly one known canonical tool, `read_file`, with no text;
- one validated continuation tool was dispatched through the unchanged broker;
- all string-field host-path checks passed, with no path violation;
- the ordinary verifier and artifact evidence remained causally valid;
- credential-value scanning reported zero matches.

The continuation response-shape receipt contained one raw `function_call`, one converted tool call,
and no converted text parts. The run made 16 model calls, 14 broker tool calls, and no patch or
`finish` call. It ended as the infrastructure-valid model failure
`openhands_hwe_missing_finish`; the workspace was unchanged, the ordinary verifier was unresolved,
and no positive trajectory or dataset row was exported.

The sealed diagnostic report has hash
`440b47085983bd204713c5c732905eef67ff8d94d0053cadd9a2eb5cb57bd423` and trace hash
`ea0a055f3148bc8563080cfbc766104ad5b40d566f83558a934b20dceec5fd9e`. Provider usage was
230,690 input and 29,727 output tokens; wall time was 805.301 seconds. The complete experiment
and trace remain outside Git at
`/data/jzhu484/Agent/experiments/qwen35-hwe-openhands-typed-continuation-v17/`.

## Boundary and next step

v17 closes the observed adapter, SDK continuation, tool-choice, and path/schema accounting
defects. It does not make the provider/model complete the repository repair. No `finish` was
synthesized, no tool schema was removed, no context was truncated, and PR-2032 is not to be retried
under this diagnostic identity.

The next permitted action is a new, separately frozen collection canary on PR-2944, PR-2248, and
PR-3191. A canary failure must stop before formal collection; it cannot be converted into a
positive trajectory by post-processing. Training remains bounded development-only and keeps
`production_training_ready=false`, `training_started=false`, `optimizer_steps=0`,
`checkpoint_written=false`, and `adapter_written=false` until the independent data gate passes.
