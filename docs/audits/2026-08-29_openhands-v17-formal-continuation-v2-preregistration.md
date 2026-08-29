# OpenHands v17 正式采集 continuation v2 预注册审计

日期：2026-08-29。正式采集 v1 在完成 PR-2282 的唯一 provider episode 后，collector 在
decision JSONL 已原子写入、其 manifest 与 campaign progress 尚未写入时触发
`KeyError: transcript_hash`。这不是 verifier、provider、Docker 或安全扫描失败；PR-2282
已通过 verifier，并生成完整 OpenHands exact trajectory。历史 v1 root 保持不变，不恢复执行，
也不重跑 PR-2282。

## 已封存恢复边界

- parent formal contract hash：
  `886aefb295c822554eba6fa8efb9e83a8d4da8d6812930843592048a4f2260e4`
- parent source commit：`2980f6c9900d4d5b9d609adb3f50ac213d6f5426`
- frozen agent version：
  `openhands-deepseek-v4-flash-hwe-v17-formal-collection-v1`
- frozen agent version hash：
  `4203ffe35823ba6ba83fa5ab5c351b19dc3a58cd4265c22cdb07883975bbe521`
- PR-2282 run hash：
  `4970a9ba6ce338991faf3bdf5417cb5411e1aafa7b9deb4261d3c9a8933ae3e9`
- trajectory file SHA-256：
  `2b1322e65a137635ccf0931808ab1e33c8a273bf1039d28657e0b3526ce2ad8f`
- transcript hash：
  `6461692703555a11cc93e43ce0f69e92b3d7bbf96b6ca5b0882d5a63137e9740`
- partial decision JSONL SHA-256：
  `cc31dcece94a7f37c3db6af2c7648c1213800891c5a7192f80f82a628028db8e`
- 32 条 assistant decision records，最大 42,915 tokens，无截断。

Continuation contract 逐文件绑定 agent、image receipt、preregistration、progress、scorecard、
artifact manifest、accounting、broker、summary、trajectory、security scan 和 partial JSONL 的
SHA-256，并要求 `campaign-report.json`、`data-gate.json` 与 PR-2282 records manifest 在恢复
root 中仍不存在。任一文件、身份、verifier 结论、recovery accounting、secret scan 或 crash
boundary 漂移均拒绝恢复。

## continuation v2 合约

- contract：
  `configs/training/qwen35_hwe_openhands_v17_collection_continuation_v2.json`
- contract format：`verigym_openhands_hwe_v17_formal_continuation_v2`
- contract hash：
  `df47b0ca1e3900ad1a82d359bfd1711d35cd4b30ae4fc1b88d966b855513b8f4`
- campaign：`openhands-hwe-v17-formal-continuation-v2`
- opt-in：`VERIGYM_RUN_OPENHANDS_HWE_V17_FORMAL_CONTINUATION_V2=1`

Agent behavior、模型、OpenHands/LiteLLM/tiktoken 版本、temperature、seed 487、sample index 3、
六工具 schema、镜像和零重试策略均保持 v1 身份。Collector 使用新的 source commit 单独审计，
但向 provider 传递并复建的仍是冻结 source commit 与 agent version；本阶段不得修改
`integrations/verigym-openhands/src/verigym_openhands/*.py`，否则 agent package hash 会漂移并
fail closed。

PR-2282 只从封存 trajectory 重新 materialize，并要求结果逐条等于 partial JSONL；这不会发出
provider 请求。成功导入 PR-2944、PR-2248 canary 和 PR-2282 recovery 后，原始 gate 应精确
位于 3 个 distinct training passes，下一条 provider task 必须是 PR-2468。后续 training 唯一
顺序为 PR-2468、2469、2549、2589、2802、2916；达到 8 条 training pass 后，validation
唯一顺序为 PR-3204、PR-3168。PR-3168 的 development-validation role overlay 已在 canary v3
clean commit 中预注册并早于 v4 真实运行，不是本 continuation 新增的容量，也未曾用于 v17
采集。每任务最多一次，不补采样、不加载 held-out。

## 持久化与停止策略

原 collector 为 fresh attempt 补齐用于 records manifest 的 `transcript_hash`。Trajectory JSONL
和 manifest 作为一对写入；manifest 写入失败时删除该未提交 pair。每个 episode 的 records、
campaign progress 与 data gate 持久化都处于同一 fail-closed exception boundary，错误原因附带
精确 persistence stage，并立即写 stopped report。任何基础设施、安全、schema/path、accounting、
token 超限或持久化错误都停止整个 campaign，不能转成 verifier rejection 或任务重试。

Continuation 在创建新输出 root 前先在内存中验证并重 materialize 三条 imported trajectories；
随后在 Docker preflight 和 provider service 创建之前写入 agent/image identity、preregistration、
三组 records/manifest、initial progress 与 initial data gate。初始化任一阶段失败同样 fail closed。

Continuation 仍使用原 exact-64K gate：8 个 distinct training verifier-pass trajectories 和
2 个 distinct validation verifier-pass trajectories。只有独立 final report、training/validation
dataset manifests、equal-trajectory sampler manifests 与 security scans 全部完成后，才允许
进入 SFT 预注册；此前 `production_training_ready=false`、`benchmark_score_claimed=false`、
`gpu_submission_allowed=false`。完整 run 与 trajectory 仅留在 experiments，不提交 Git。
