# OpenHands v17 collection canary v3 结果与 v4 预注册

日期：2026-08-29。

> **结论边界：** v3 已 fail closed，不能追认。PR-2944 与 PR-2248 verifier pass；PR-3191
> 完成 200 次 provider call 和 200 次合法工具调用后达到冻结 iteration 上限，但 adapter 将
> 第 201 个受 broker hard limit 拒绝的 action 误分类为一般 action-policy failure。v4 只修复该
> 精确终止分类。真实 v4 provider canary 尚未运行，正式采集、GPU、SFT 与 held-out 均未启动。

## v3 冻结执行与结果

- source commit：`e132aa7e2ac630508299f73fbb76913f99182b24`
- contract hash：`6e2b576f09d7ca3e7c888729e2d380f36bbac90dabea80be4f47ca9e8f843d13`
- campaign：`openhands-hwe-v17-collection-canary-v3`
- agent version：`openhands-deepseek-v4-flash-hwe-v17-collection-canary-v3`
- model / SDK / LiteLLM / tiktoken：DeepSeek v4 Flash / `1.42.1` / `1.93.0` / `0.7.0`
- schedule：PR-2944 training → PR-2248 training → PR-3191 validation
- seed / sample index：`486` / `2`
- provider retry / episode retry：`0` / `0`
- held-out task IDs loaded：`0`

该 source commit 的 push run `33193505816` 与 pull-request run `33193510604` 均通过 8 项
Actions：quality、package、reproducible-build、ordinary 3.11/3.12/3.13、OpenHands 3.12 和
Docker external-agent zero-model security。

| episode | 结果 | model / tool calls | total tokens | recovery | trajectory |
| --- | --- | ---: | ---: | --- | --- |
| PR-2944 | verifier pass | 13 / 17 | 97,198 | direct | fresh exact，13 decisions |
| PR-2248 | verifier pass | 8 / 11 | 56,917 | direct | fresh exact，8 decisions |
| PR-3191 | v3 fail-closed classification | 200 / 200 | 完整 accounting | direct | 未导出 |

前两条均通过 infrastructure、runtime evidence、provider-value byte scan、artifact security
scan、完整 accounting 与无截断门禁。trajectory 文件 SHA-256 分别为
`6365a602eb39d7adc5aff21cb25b2f06434f193750fc7bd8aaa9d1af507a7518` 和
`d2b2265825708bd98ed594bb4ada1a978dccaa1b341c38480280dfadb95ba688`。它们仍只属于 v3
canary，不能单独导入正式 collection identity。

PR-3191 的脱敏证据为：provider call / successful response / usage record 均为 `200`；broker
接受 `200` 个工具调用，记录 `decision_steps=201`，唯一 rejection code 为 `episode_limit`，
policy failure 为 `decision_steps_hard_limit`；SDK event counts 为 Action/Observation `201/201`、
ConversationError `1`；format、continuation 与 path recovery 计数全部为零；无 finish、无
trajectory、无 infrastructure failure。该精确形状说明模型跑满预算未完成，而不是 raw host
path、非法 schema、provider outage 或恢复协议失败。

v3 sealed report 内部 hash 为
`4df881ce8b6d434a3b8f65a9ed29cae270dde3624c7210779acac3a1149ad3dc`，文件 SHA-256 为
`831fd4931564260a39ddb1552fd2757ad6050ba1933ce1ff49a9dc8dc9c9af90`。报告保持
`formal_collection_allowed=false`、`training_started=false`、`optimizer_steps=0`、
`hpc_jobs_submitted=false`。

## 根因与 v4 修复边界

v3 adapter 先检查 `stats.policy_failure/rejected_calls`，后检查 `not stats.finished`。因此 SDK
达到 200 iterations 后产生的第 201 个 broker decision-limit rejection 被一般化为
`openhands_hwe_action_policy`，runner 随即按 schema/path/trajectory policy fail closed。

v4 注册 `openhands_sdk_broker_bounded_iteration_exhaustion_v1`，只有同时满足以下条件才分类为
`openhands_hwe_missing_finish`：

- 未 typed finish、finish call 为零、broker infrastructure failure 为空；
- provider call、成功响应与 usage record 精确为 `200/200/200`；
- broker 接受工具调用 `200`，decision steps `201`；
- 唯一 rejected call 为 `episode_limit`，policy failure 精确为
  `decision_steps_hard_limit`；
- Action/Observation event 精确为 `201/201`，ConversationError 精确为 `1`，Interrupt 为零；
- 不导出 message content 或 trajectory，private raw-artifact secret scan pass；
- recovery 全零，accounting 与 broker/provider counters 完整一致。

mutation hard limit、其他 policy/rejection、多个错误事件、provider usage 缺失、计数偏差或任何
持久化漂移仍归 action-policy/security invalid。v4 不改变 v3 文件、hash 或结论。

## v4 冻结合约

- contract：`configs/training/qwen35_hwe_openhands_v17_canary_v4.json`
- contract hash：`18ba9369eb59b96b468f42e2338600d0c029ad3c9f0a64763125af9b4360fb83`
- campaign：`openhands-hwe-v17-collection-canary-v4`
- agent version：`openhands-deepseek-v4-flash-hwe-v17-collection-canary-v4`
- opt-in：`VERIGYM_RUN_OPENHANDS_HWE_V17_COLLECTION_CANARY_V4=1`
- model、版本、temperature、limits、retry、任务顺序、seed/sample、task/source/image hashes 与
  v3 相同；held-out 仍不加载。
- PR-2944 必须 verifier pass；PR-2248/PR-3191 至少一条 pass。PR-3191 若是精确 bounded
  non-finish，可作为有效 model failure 进入 canary gate，但不能生成训练 trajectory。
- validation 正式容量仍为未运行的公开 PR-3204 与 reserve PR-3168；不使用 held-out。

只有当前 v4 clean commit 的 push 与 PR event 均通过全部 8 项检查并 merge 后，才允许从最新
`main` 运行一次真实 v4 canary。任何基础设施、安全或 exact-shape 漂移立即封存；失败时不启动
正式采集或 SFT。本预注册不是 benchmark score，`production_training_ready=false`。

## 脱敏证据

- v3 report：
  `/data/jzhu484/Agent/experiments/qwen35-hwe-openhands-v17-canary/canary-e132aa7-s486-v3/canary-report.json`
- PR-3191 scorecard SHA-256：
  `75c56716285af99d04dd35656b8fb369b7088a704fc584fe83d9599ffce6f62e`
- PR-3191 summary / broker / accounting SHA-256：
  `e4b71f46af023c30cac25a8a092a236b2dd8142c4577f53b604477c334fb07e3` /
  `943c9d476cc661be17aac0940996a7b5ff88d86d832d130157c88f7d72670f69` /
  `85661c85f11e1038016b525d2c79a0d6452e04bc863805434d36a87c49b4522a`

完整 run、原始 observation 与 trajectories 留在 Git 外 experiments；Git 只提交上述脱敏
类别、计数和 hashes。
