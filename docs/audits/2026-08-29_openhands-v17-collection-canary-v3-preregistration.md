# OpenHands v17 collection canary v3 预注册审计

日期：2026-08-29。

> **状态边界：** 本文件只预注册 v3 canary 实现与后续容量门禁。真实 provider canary 尚未
> 运行，`formal_collection_allowed=false`、`production_training_ready=false`、
> `benchmark_score_claimed=false`。只有本实现的 clean merge commit 通过全部保护检查后，
> 才能按冻结顺序执行三条 canary。

## v2 问题与 v3 边界

v2 的 PR-3191 在一次合法 format recovery 和一次合法 SDK continuation 后，由 provider 在
`shell.command` 中生成 raw host path。该响应在 broker dispatch 前被本地策略拒绝，随后旧的
通用 continuation 又得到同类响应，最终按模型策略失败封存。v3 不修改或重标 v2 结果，也不
改变历史 v12–v17 identity。

v3 注册新的 `validated_responses_recovery_state_required_tool_v18`。它只对本地异常链确认的
`raw_host_path` 类别开放一次恢复：

- 原始 provider arguments 不进入 OpenHands 消息、broker、trajectory 或公开 evidence；
- 只保留 canonical tool name、argument field、violation kind 和通用文本哈希；
- adapter 在同一 Conversation 中加入一条固定反馈，并只允许一次 Responses
  `tool_choice=required` 请求；
- provider 必须返回恰好一个六工具合约内的 canonical tool call，且纠正后的参数重新通过完整
  pre-dispatch policy；
- 第二次越界、其他 violation kind、计数或 response-shape 漂移立即 fail closed；
- 若错误发生在 SDK continuation 中，纠正动作同时闭合 continuation 与 path-recovery 计数，
  但仍完全由 provider 生成，adapter 不合成动作。

通过 verifier 的恢复轨迹使用独立 v6 trajectory/decision/dataset identity。路径错误事件只保留
content-free 因果位置，固定反馈进入精确 model-visible messages，反馈之前的 decision 看不到该
信息。所有 decision 仍执行 exact 65,536-token 无截断门禁。

## 冻结合约

- contract：`configs/training/qwen35_hwe_openhands_v17_canary_v3.json`
- contract hash：`6e2b576f09d7ca3e7c888729e2d380f36bbac90dabea80be4f47ca9e8f843d13`
- campaign：`openhands-hwe-v17-collection-canary-v3`
- agent version：`openhands-deepseek-v4-flash-hwe-v17-collection-canary-v3`
- model：`openai/deepseek-v4-flash`，thinking disabled，temperature `0`
- OpenHands SDK / LiteLLM / tiktoken：`1.42.1` / `1.93.0` / `0.7.0`
- seed / sample index：`486` / `2`
- limits：65,536 context tokens、2,048 output tokens、200 iterations
- retry：whole episode `0`，provider request `0`，path-policy recovery budget `1`
- schedule：PR-2944 training → PR-2248 training → PR-3191 validation
- held-out task IDs loaded：`0`

PR-2944 必须 verifier pass 并导出 fresh exact trajectory；PR-2248 与 PR-3191 至少一条 verifier
pass。每条 episode 后都必须通过 infrastructure、完整 accounting、schema/path、provider-value
byte scan、通用 artifact scan 和无截断检查。

## 公开 development split 容量修复

原始 qualification split hash
`68c76482f81ac4bbbb64a54d0886fda4b1a0b7c38e489916b919f768ec3146e6` 只有 PR-3191、
PR-3204 两条 validation task。v3 通过纯 manifest role overlay 将尚未用于 v17 正式采集的公开
PR-3168 从 training 移到 development validation reserve；task/source 内容、哈希和归属不变，
held-out 六条 task 的列表、顺序和 `heldout_assets_loaded_after_version_hash` 原样保留且不加载。
派生 split 为：

- ID：`cva6-multiturn-sft-2026-08-v2-path-recovery-capacity`
- manifest hash：`a4678fdf8ca8f13ab1e722b0738a66736ba3c074962c8982b1ad0744affef618`
- validation 顺序：canary PR-3191；正式 PR-3204；容量备用 PR-3168。

因此即使 PR-3191 verifier reject，只要 PR-2944 和 PR-2248 满足 canary 质量门禁，仍有两条
未运行且 distinct 的公开 validation task 可达到目标；这不是重试 PR-3191，也不使用 held-out。
training 目标仍为八条 distinct pass：canary 最少贡献 PR-2944，正式顺序为 PR-2282、2468、
2469、2549、2589、2802、2916。历史 PR-2032 明确排除，不重复采样；每任务最多一次，并在
达到目标后立即停止。

## 后续授权条件

1. 当前 preregistration commit 必须通过 quality、package、reproducible-build、ordinary
   3.11/3.12/3.13、OpenHands 3.12 与 Docker security 八项保护检查。
2. 合并后从最新 `main` 的 clean commit 运行一次 v3 canary，完整输出只写 Git 外 experiments，
   Git 只提交脱敏报告。
3. 任一 infrastructure/security 错误立即封存；canary 或 distinct-task capacity gate 未通过时，
   不启动正式采集、GPU、SFT 或 held-out。
4. 只有达到 8 条 distinct training pass 与 2 条 distinct validation pass，并通过 exact-64K
   dataset/security receipt 后，才能提交独立 32-step development SFT 预注册。

本预注册不是 benchmark score，也不表示 production training ready。
