# OpenHands v17 正式轨迹采集预注册

日期：2026-08-29。

> **授权边界：** v4 canary 已授权进入正式采集实现，但尚未授权训练。真实 provider 采集只能从
> 本文件、正式合约与 runner 所在的同一 clean commit 开始，并且该 commit 的 push 与 PR event
> 必须先通过 8 项保护检查。数据门禁未达到 8 个 distinct training task 和 2 个 distinct
> validation task 时，禁止提交 GPU 作业。

## 冻结身份

- contract：`verigym_openhands_hwe_v17_formal_collection_v1`
- contract hash：`886aefb295c822554eba6fa8efb9e83a8d4da8d6812930843592048a4f2260e4`
- campaign：`openhands-hwe-v17-formal-collection-v1`
- agent version：`openhands-deepseek-v4-flash-hwe-v17-formal-collection-v1`
- parent canary report SHA-256：
  `6b5b8f6016d5be59c012a55c651dbdba31e417cc19e9477338fbfa181952232f`
- model：DeepSeek v4 Flash，thinking disabled，temperature `0`
- OpenHands SDK / LiteLLM / tiktoken：`1.42.1` / `1.93.0` / `0.7.0`
- Qwen3.5-9B snapshot / tokenizer：
  `fce78eefb5b60ff95c480d2fb823bb45370a4abc933d6114a84d6a321486b156` /
  `440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e`
- new provider episodes：seed `487`，sample index `3`，whole-episode/provider retry `0/0`
- held-out task IDs loaded：`0`

正式身份不会重标 v13 或 canary 数据。它只导入 v4 canary 中 PR-2944 与 PR-2248 两条
verifier-pass exact trajectories；导入同时绑定原始 trajectory file、transcript、run、candidate、
verifier、task、source 和 image hashes。PR-3191 未通过 verifier，不进入数据集。

## 顺序、容量与停止规则

training 固定顺序为 PR-2282、2468、2469、2549、2589、2802、2916。两条 canary training
pass 已计入 8 条目标，因此最多再需要 6 条 pass，并保留 1 条失败余量。达到 8 条后必须立即
跳过剩余 training task。

validation 只在 training 达标后运行，固定顺序为 PR-3204、PR-3168；后者是公开 training pool
中的 development-validation role overlay。由于 canary PR-3191 未通过，两条都必须通过，失败
任意一条即容量不足并 fail closed。

每个任务最多运行一次。每条结束后原子写入 progress、attempt、security scan 和（仅 verifier
pass 时）trajectory records，然后重算“当前 distinct pass + 未运行 distinct task”。基础设施、
schema/path、accounting、recovery、安全扫描或 64K receipt 任一无效，立即封存并停止。不补采样、
不重试、不运行 PR-2032、不使用 held-out。

## Exact-64K 数据合约

- 每个 supervised row 是一个完整 assistant decision；历史 input 全部 loss-masked。
- 保留完整 model-visible messages、逐回合六工具 schema、task/source/candidate/verifier binding、
  exact token receipt 和 decision-only loss mask。
- 使用冻结 Qwen3.5-9B chat template 重新计算 token IDs 与 mask hashes；超过 65,536 tokens 直接
  拒绝，禁止截断。
- training 与 validation 分别写入 dataset manifest、loader dry-run、security scan 和
  equal-trajectory sampler manifest。
- sampler 冻结为 `trajectory_balanced_decision_target_token_mean_batch1_v1`：trajectory 等权，
  trajectory 内按 transcript hash 与 decision index 确定性调度。
- loader 支持并验证 OpenHands v1-v6 direct/recovery/masked/continuation/path-recovery rows，不丢弃
  source record、messages、tools 或 recovery receipts。

## 后续授权

只有正式 report 同时满足 `data_gate_satisfied=true`、training `8`、validation `2`、两份 dataset
security scan pass、provider-value scan pass 且无 overlength，才允许新建独立的 32-step SFT
预注册与远端非交互 LSF payload。当前始终保持 `production_training_ready=false`、
`benchmark_score_claimed=false`、`training_started=false`、`optimizer_steps=0`、
`checkpoint_written=false`、`adapter_written=false` 和 `hpc_jobs_submitted=false`。
