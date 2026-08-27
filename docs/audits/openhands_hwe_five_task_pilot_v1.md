# OpenHands × HWE-Bench 五任务 pilot 审计

日期：2026-08-26。本审计记录预注册的五任务 OpenHands trajectory collection pilot
及其 fail-closed 结果。它不是 benchmark score，也没有产生新的 SFT dataset、GPU 训练、
checkpoint 或 adapter。

## 结论

collector、OpenHands 1.42.1、LiteLLM 1.93.0、六工具 MCP bridge、隔离的 agent/verifier
images 和冻结 Qwen3.5-9B tokenizer 均完成真实路径启动。历史 verifier-pass 的 pr-2944
trajectory 只做 hash-bound 重 materialization，没有重新采样；20 条 decision rows 的最大
长度为 13,107 tokens，零 overlength、零 truncation。

首次 campaign 在零模型调用阶段发现 CLI 误用了旧 32K decision dry run 校验 64K
OpenHands rows。修复为 `dry_run_decision_record_v4` 后，第二个不可覆盖 campaign 完成所有
零调用门禁，并对 pr-2032 执行了一次真实 OpenHands episode。该 episode 产生 11 条受控
tool observations 和 candidate patch，但模型没有通过 typed `finish` 结束；sealed scorecard
将其分类为 `openhands_hwe_missing_finish`、`infrastructure=false`、`verifier_pass=false`。
因此没有导出正样本 trajectory。

agent adapter 在这个模型拒绝分支落盘 accounting 之前退出，而 collector 当时要求所有
非基础设施结果必须有 `accounting.json`，导致 post-run collector failure。按照预注册的
“infrastructure-invalid stops campaign”和 one-shot/no-retry 规则，本轮没有重跑 pr-2032，
也没有执行 pr-2549、pr-2248 或 pr-2282。最终状态为
`stopped_infrastructure_invalid`、`loader_ready=false`、
`pilot_yield_sufficient=false`。

第二次 campaign 的 canonical `report_hash` 是
`57ac5f15401904cf033e7cb6cc89694f7cc9f8a2c7d4b8f47de50f91fb65a8fc`，报告文件
SHA-256 是 `d39662442bb4ae9289ea365f01637877a9b42045f72eaa23a53a0aaf877aebc8`。
本地实验根为 `openhands-hwe-five-task-pilot-v1-attempt2`；只提交本审计摘要和代码，
不提交 run、trajectory、private audit 或 dataset 内容。

## 已修复的接口问题

- pilot CLI 使用 exact 64K dry run，拒绝 token IDs、loss mask、tool schemas、template hash、
  max length 或 truncation contract 的任何漂移。
- OpenHands HWE adapter 现在会在 broker infrastructure failure、tool policy rejection、
  missing typed finish 和 trajectory normalization failure 分支先持久化 accounting/identity
  evidence，再返回分类后的 termination。
- collector 将非基础设施的模型终止分类为 `model_rejected`。为兼容本次已经完成的旧 run，
  缺失 accounting 只在 sealed scorecard 明确 `infrastructure=false` 时允许记录为 unknown；
  resolved run、ordinary verifier rejection 或 infrastructure failure 缺 accounting 仍会
  fail closed。

## 验证和边界

- OpenHands integration tests：25 passed。
- 修复文件通过 Ruff、format check 和 mypy。
- pr-2944 的真实 tokenizer replay：20 rows，max 13,107，零 overlength，零 truncation；
  tokenizer hash `440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e`，
  chat-template hash `a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715`。
- 两个 campaign artifact roots 的 provider credential 精确扫描均通过；第二次 report seal
  复算通过。
- 隔离 Python 3.12 环境完全从本地 wheelhouse 安装；138 个 wheels 的文件名和 SHA-256
  已写入未提交的 environment receipt，receipt hash 为
  `e869310a20862dc59b83951286b595b9707722edec0661ccb1056b58c62185ea`。
- `whole_episode_retries=0`、`optimizer_steps=0`、`checkpoint_written=false`、
  `adapter_written=false`、`hpc_jobs_submitted=false`、`gpu_seconds=0`。

本轮没有满足“至少一个新 verifier-pass trajectory”的 pilot yield 门，也没有形成 aggregate
dataset，所以不执行 rLLM/veRL loader dry run 或后续 SFT。下一次真实采集必须注册新的
campaign/agent version；不能把本次 pr-2032 结果改写为成功，或在本轮内追加第二次尝试。
