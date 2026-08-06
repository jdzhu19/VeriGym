# Real campaign smoke evidence

Date: 2026-08-06 (Asia/Shanghai)

This bounded campaign proves that one VeriGym report can combine real chat and agent evaluations
with an evolving-agent control. It is a platform smoke, not a full RTLLM benchmark or a statistical
performance claim. The generated [JSON](real_campaign_smoke/campaign_report.json),
[CSV](real_campaign_smoke/campaign_report.csv), and
[Markdown](real_campaign_smoke/campaign_report.md) reports are committed as the reviewable result.

## Frozen inputs and tools

- VeriGym report code: commit `e49fb436108af18d94720627325c9876f59eed5e` with a clean source
  tree at generation time.
- RTLLM source: commit `41b26896e33b536940116a975626455eed3de65e`, task
  `Control/Counter/counter_12`.
- Functional and synthesis tools: VCS `V-2023.12-SP2-2` and Design Compiler
  `T-2022.03-SP1`; Library Compiler `T-2022.03-SP3` produced the private DB.
- Library source: OpenROAD-flow-scripts commit `778c4e556a6f1d104621b92f6a851324bf34ff1a`;
  Sky130 HD typical Liberty SHA-256
  `ec0e1067a35c8bf20b11e58d1e8ac53326067e4dac84a125cc1b917a3518d0d9`.
- DC profile: declared hash
  `8f63348cc7a3308a4098e4cbf859b2afcba1af7f4f97c956d1dc61fee94e58cb`, resolved
  hash `5aeb2f92cb1758282d2d1800f390cb0b966dd72ee08b9374f2229775b216e720`, with a
  10 ns clock.

## Results

DeepSeek `deepseek-v4-flash` resolved the single RTLLM sample in both modes. Chat used one model
call, 2,043 tokens, no agent tool calls, and 125.046 s. Strict JSON ReAct agent mode used four
model calls, 11,706 tokens, three tool calls, and 138.169 s. Both passed VCS, candidate/reference
DC, and quality projection with no infrastructure or license failure.

Both runs share PPA comparison partition
`cf70ac24a484bdcea8b2a95038f2ce6f21aa204789484cdfb5c0b38aa8f00b91`. Candidate/reference
mapped area was `153.8976/153.8976 um^2`, maximum-path delay was
`0.810319/0.810319 ns`, and WNS was `0.0/0.0 ns`; area and delay ratios were `1.0`.

The evolving control used one first-party toy task, two scripted versions, and three samples per
version. All six runs resolved with pass@1/2/3 of `1.0`. Its report explicitly sets
`establishes_general_improvement=false`; it validates the evolving-report contract only.

## Report integrity and limits

Campaign `campaign-d3c7e6df55399bce` has report hash
`7e6877877e7c6423a50d6f69dc6849193594f4c363fb79cdcb118de9e07feb61`. Two independent offline
generations produced identical files:

- JSON: `15aea4ad49016c082be2cba429dcfbe9a6a84567de6723772122fdbd12994a7a`
- CSV: `e1f82e697d339c92018664a1ec99ab33f266af42a91e839ddde57881a0cc8b48`
- Markdown: `65188b414223594cc3d472a1ed7e575bda9c735781304b52547fb8b816750cdc`

Report generation made zero model and zero tool calls. Model cost is unavailable because this
provider response had no configured cost accounting. Credentials, license values, private DB
bytes, machine-local paths, and generated run workspaces are not committed. These results are not
signoff timing, a cross-tool comparison, or evidence of general agent improvement.
