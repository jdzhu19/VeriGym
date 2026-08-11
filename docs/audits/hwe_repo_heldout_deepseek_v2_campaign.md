# HWE repo-level DeepSeek held-out v2 campaign

- Date: 2026-08-11
- Status: three samples completed; three ordinary rejections; not a benchmark score
- Code commit: `000c8e3c825e8728de6be5482cd63fc51829dddc`
- Agent: `deepseek-api-hwe-heldout-v2`, `deepseek-v4-flash`, thinking disabled
- Split: `hwe-repo-heldout-deepseek-v2`
- Sampling: one sample per task, base seed 3, no retry, no best-of-K

## Independent 16K freeze

This line replaces the earlier local 4,096-token request cap with an explicitly frozen
16,384-token cap. The cap is a VeriGym API-runner request policy, not an HWE-Bench restriction.
The v1 identity and results remain unchanged.

The v2 agent-version hash is
`27d037e3557552d155fe6061b0014e313496f3d18e12d5db48fd954f6d79013d`, the split
manifest hash is `a6b6e41f40aa1f4109e43a3226f86bbb26f08c7da086534ce1a7252a5cef0967`,
and the content-free freeze hash is
`19a8d95ce7daa64b7c049d60724f917288d80bcf3a59069eab050d77b968a2c6`.
The secret-free API request policy hash is
`ec3c34423d6f0b5976f0484bc9ee53c86a24f441ae646deffca1ca365270aa95`.
It binds the exact model, disabled thinking, 16,384 output tokens, 10-second connect and
120-second read/request timeouts, a 1 MiB response bound, and zero retry or selection.

Authentication and endpoint configuration came from the named
`VERIGYM_DEEPSEEK_API_KEY` and `VERIGYM_DEEPSEEK_API_BASE_URL` environment variables.
Their values were not placed in prompts, freezes, summaries, or audits.

## Outcomes

| Task | Provider finish | Usage (input/output) | Latency | Agent outcome | Resolved |
| --- | --- | ---: | ---: | --- | --- |
| Ibex PR222 | `stop` | 1,487 / 226 | 3.13 s | patch could not be materialized | no |
| CVA6 PR2945 | `length` | 8,392 / 16,384 | 61.42 s | response exhausted the larger cap | no |
| Rocket PR3065 | `stop` | 10,133 / 496 | 5.10 s | patch rejected by workspace policy | no |

The campaign plan hash is
`08669b8e7a5822f40871b8b8521b345a4d532f93c4f4c95646001952152122bb`.
All three endpoint calls returned `deepseek-v4-flash`; none timed out or became
infrastructure-invalid. The summary hash is
`4afdbc31ff6f1fe3fa73997aa77ac6ba596d285a4edfd2224f052e8b6ed271d9`.

The 16K cap removed the artificial 4K truncation for Ibex, but its response was still not a
usable repair. CVA6 generated pathological repeated output and consumed the entire 16K budget.
Rocket returned a bounded response but addressed a path outside the allowed repository root.
Increasing the cap therefore fixed the evaluation configuration without making these three
candidate repairs correct.

## Offline replay, training exclusion, and safety

Visible replay passed for all three runs. Observable trajectory export, validation, and source
replay agreed on dataset hash
`a205d9cdb68dc43717d3c35794486966955b460a5f48518b616f71231a5152ed`.
All three records remain assigned to the frozen `heldout` split. The external training-reference
preparation exited with code 2, created no bundle, and produced exclusion report hash
`91cb2efae5f6f14ff9d1a36927797041a8f0d7ec057838a5b0e450599bfd55c6`.

The final context-aware scan covered 84 exported files and 16,200,155 bytes. It passed with zero
hard secret leaks and zero scanner errors under report hash
`23c9a0f774ad00301e1340ad58644226c0cf4ca27728dcba443a9c758598e466`.
Raw repository inputs were not treated as exportable artifacts.

This is a bounded negative evaluation and request-policy qualification, not a formal model score
or evidence for expanding RL.
