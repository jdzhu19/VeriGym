# OpenHands v18 repaired-validator canary 预注册

日期：2026-08-29。

> **执行边界：** 本文只预注册修复后的两任务 canary。真实 provider episode 尚未运行，正式
> collection、GPU、SFT 与 held-out 均未启动。历史 v17 campaign 保持 fail closed；禁止重跑
> PR-2468、PR-3191 或 PR-2032，也不追改任何历史 output。

## 触发原因与身份隔离

PR #11 已修复 provider argument path validator：合法 JSON 解码后只递归扫描字符串叶节点，
不再把重新序列化产生的 `T:\n` 形状误判为 Windows drive path；malformed raw JSON 仍由独立、
escape-aware 的 fail-closed 检查处理。该修复解释 PR-2468 的历史分类，但不使该 attempt 可重跑、
可恢复或可作为训练样本。

修复后执行使用全新的非 diagnostic v18 身份，不修改或重标 v12–v17：

- contract：`configs/training/qwen35_hwe_openhands_v18_repair_canary_v1.json`
- contract hash：`73841ad308d4db91fbe6c7190a832071bf4b94242bef01f18932e8958f4d3661`
- campaign：`openhands-hwe-v18-repair-canary-v1`
- agent version：`openhands-deepseek-v4-flash-hwe-v18-repair-canary-v1`
- opt-in：`VERIGYM_RUN_OPENHANDS_HWE_V18_REPAIR_CANARY_V1=1`
- provider argument validator policy：`decoded_json_string_leaf_host_path_validator_v1`

Agent version 必须从本 PR merge 后的 clean source commit 生成，并绑定该完整 Git SHA、插件全部
Python source hashes、contract hash、Python executable、三项精确依赖版本和两任务 image locks。
不允许在 dirty tracked tree 或其他 commit 上执行。

## Distinct-task 容量账本

当前可用的 verifier-pass training trajectories 为 PR-2944、PR-2248 和 PR-2282，共 3 条。
PR-2468 已尝试且不可重跑。剩余未尝试 training tasks 恰为 PR-2469、2549、2589、2802、2916，
因此训练目标的最大值是 `3 + 5 = 8`，失败余量为 0。

Validation 中 PR-3191 已尝试但未完成且不可重跑；未尝试的 PR-3204 与公开 training reserve
PR-3168 恰好可提供 2 条，失败余量同样为 0。PR-2032 已在更早身份采样，明确排除。

| role | 已通过 | 本 canary | canary 后剩余 | target / maximum |
| --- | --- | --- | --- | --- |
| training | PR-2944、2248、2282 | PR-2469 | PR-2549、2589、2802、2916 | 8 / 8 |
| validation | 无 | PR-3204 | PR-3168 | 2 / 2 |

六个 held-out task 不加载、不解析、不用于容量补足；contract 中
`heldout_task_ids_loaded=[]`、`heldout_tasks_eligible=false`。

## 冻结 canary

固定顺序与参数：

1. PR-2469，training，seed `488`，sample index `4`；
2. PR-3204，validation，seed `488`，sample index `4`。

两条均固定为 DeepSeek v4 Flash、OpenHands SDK `1.42.1`、LiteLLM `1.93.0`、tiktoken
`0.7.0`、temperature `0`、maximum context `65,536`、maximum output `2,048`、maximum
iterations `200`、episode retry `0`、provider retry `0`、Docker runtime network `none`。

Task/source/image bindings：

| task | task hash | source hash | image-lock hash |
| --- | --- | --- | --- |
| PR-2469 | `2c90d93d…c97f56e` | `faf37d7a…784f00` | `a237392f…51f0db` |
| PR-3204 | `9322fa0b…229e86` | `15861c5f…94f02f` | `b3fe6732…1933b` |

完整 64-hex hashes、agent image IDs 与 verifier image IDs 由 code-frozen contract 精确绑定，
表中仅缩写用于人工阅读。

## 门禁与停止条件

PR-2469 和 PR-3204 都必须同时满足：

- infrastructure valid、runtime evidence valid、secret/artifact scan passed；
- 完整 provider/broker/token/tool accounting，无截断；
- recovery 只能是冻结的允许状态；path recovery 若发生，必须是一次 required-tool request 和
  一次已验证 canonical tool，即精确 `1/1/1`；
- ordinary verifier pass，且导出 fresh exact、SFT-eligible trajectory。

任一 infrastructure、安全、schema/path 或 accounting 错误立即封存并停止。普通 verifier reject
或 exact bounded model nonfinish 可作为有效模型失败记录，但因为容量为零余量，仍令
`formal_collection_allowed=false`，不得进入正式 collection 或 SFT。

只有两条均通过时，training maximum 才为 8、validation maximum 才为 2，canary gate 才允许
建立后续独立正式 collection 身份。后续固定顺序为 training PR-2549、2589、2802、2916，最后
validation PR-3168；这些任务仍需另行预注册、CI 与逐任务容量重算。

## 执行顺序

1. 本实现与预注册在同一 clean commit 上通过本地零-provider 测试；
2. 提交独立 PR，等待 push 与 pull-request event 的 8 项保护检查全部成功并 merge；
3. 从最新 `origin/main` 验证 source/task/image locks、Docker zero-call preflight 和精确依赖版本；
4. 只运行上述两条 provider episodes，每条最多一次并原子落盘；
5. 写入 Git 外 experiments 的完整输出和 Git 内脱敏结果审计，再决定是否创建正式 collection PR。

本 canary 不是 benchmark score，始终记录 `benchmark_score_claimed=false` 和
`production_training_ready=false`。
