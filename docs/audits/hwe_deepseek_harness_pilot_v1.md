# DeepSeek Harness × HWE-Bench 三任务采集审计

日期：2026-08-23。本审计记录一次冻结的三任务 collection pilot；它不是 benchmark
score，也不是 production training dataset。本轮未启动 SFT、GPU、HPC 或 held-out
evaluation。

## 结论

DeepSeek API、官方 DeepSeek Harness、六工具 broker、隔离 HWE runtime、私有审计和
Qwen action-conditioned loader 链路均已实际走通。但三个冻结任务都在普通 verifier
之前被严格轨迹策略拒绝，因此没有轨迹进入 SFT dataset：`0/3` verifier pass、
`0` eligible trajectories、`0` action records、`loader_ready=false`、
`production_training_ready=false`。

最终报告：
[campaign-report.json](/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/pilot-3task-v2/campaign-report.json:1)。
其 canonical `report_hash` 为
`7a78d29b28788065eb139f240f6830698a37b4b29cfb2a6fd9ef1e7965ac47b5`，文件 SHA-256
为 `206df476bef953e4880f46a2d002b002f971111bb5f0e4e124a54a82c8c8fa0d`。

## 冻结身份与边界

- DeepSeek Harness `0.1.1-rc.2`，revision
  `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`，source tree hash
  `22df3762b332f3651107756dc80a9397f27741c1256e83ca32614729f27bd566`。
- Harness controller image ID
  `sha256:daa74c183f7d8c1ba55ed79c76e912f50be8782ca9d2da640645f906dce474b8`；
  task runtime image ID
  `sha256:5b95472e7fbfa80eb0cf173099254ef5285fcd78f7c3c78b42678ae9181dd96e`。
- Provider/model 为 DeepSeek / `deepseek-v4-flash`；thinking disabled、reasoning off、
  temperature 0、maximum output 2048、serial tools、whole-episode retries 0、每任务一个
  sample、无 model substitution 或 best-of-K。
- 三个 task source hash 分别为 pr-2032
  `2db1658df59bd255ed99905f918074f303a70f5cccc84c018527d576927bf95e`、pr-2549
  `50a08b2358ddb7b939fa77ac7d726e1baf0735fa863d891c4325a3d204c5eaa0`、pr-2944
  `86228bcc27147400105b29069ee34a2b428cf897be700d77e3ed019760dd1e4f`。
- Qwen3.5-9B snapshot hash
  `fce78eefb5b60ff95c480d2fb823bb45370a4abc933d6114a84d6a321486b156`；tokenizer
  hash `440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e`；chat template
  hash `a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715`。

Controller 只持有 provider credential 和网络，不挂载任务 workspace；task runtime 不含
credential 且使用 `network=none`。模型只能通过 owner-only Unix socket 调用六个 typed
tools：`apply_patch`、`finish`、`inspect_diff`、`list_files`、`read_file` 和 `shell`。
隐藏 verifier、reference patch、raw provider events、private reasoning 和 raw observations
均未进入公开 dataset。

## 真实执行结果

| Task | Model calls | Input / output / total tokens | 拒绝原因 |
| --- | ---: | ---: | --- |
| pr-2032 | 17 | 16,454 / 6,718 / 23,172 | `incomplete_harness_trajectory`：达到 `max-tokens`，17 次合法 tool call 后仍未调用 `finish` |
| pr-2549 | 21 | 15,518 / 4,742 / 20,260 | `hwe_action_policy`：21 次 tool call 中有 1 次 shell action 被 HWE policy 拒绝 |
| pr-2944 | 20 | 15,504 / 3,417 / 18,921 | `assistant_prose_outside_action`：最终 assistant message 同时包含公开 prose 与 typed `finish`，不符合 v2 的 tool-only schema |

总计 58 次 model call，47,476 input tokens、14,877 output tokens、62,353 total tokens。
三个运行均为 infrastructure-valid；拒绝发生后没有重试、放宽策略、删除失败动作或把
prose 暗中转换为 `finish`。因此 ordinary verifier 未被解析为通过，dataset 保持空集。

pr-2032 的首次 `pilot-3task-v1` 在任何 model call 前因 runtime image 环境 allowlist
预检失败。该输出被原样保留，canonical report hash 为
`4bde6939112186d16edc3fc46097e3758a609b3f2b3c65ecaea91cd2ed2623b1`。修复
`CODEX_HOME` allowlist 和三镜像前置检查后，v2 通过显式 supersedes receipt 绑定 v1；
它不被计为模型轨迹重试。

## Dataset 与训练状态

Dataset manifest：
[dataset-manifest.json](/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/pilot-3task-v2/dataset/dataset-manifest.json:1)，
internal dataset hash 为
`36ca2639caa084c731a60fa33d107ec89566c6586cfeeadbfa396a71a3b75edf`。`train.jsonl`
为零字节，manifest 明确记录 `record_count=0`、`trajectory_count=0`、
`truncation=error` 和 `loader_ready=false`。

Qwen loader dry run 绑定 exact chat template、prefix token proof 和 final-assistant-action-only
loss mask；由于没有合格记录，其 `record_count=0`，没有伪造 token 或 loss-mask 统计。
Dataset artifact/secret scan 为 `pass`，hard secret leak count 为 0。该精确上下文路线没有
压缩或 masking，因此没有 NAP candidate、recovery 或 fallback；这表示 NAP 不适用，不是
NAP 通过。

训练配置保持 disabled，且没有从 R2E-Gym、SWE-Gym 或 DeepSWE 复制任务数值或 optimizer
超参数。三者只用于借鉴 immutable binding、typed actions、isolated execution、verifier
gate 和 append-only evidence 等方法学边界。

## 验证

- `ruff check .`、`ruff format --check .` 和 core mypy（202 source files）通过；
  `git diff --check` 通过。
- 普通 core tests：944 passed、1 skipped、52 deselected。DeepSeek Harness integration：
  6 passed、mypy 7 source files；其中包括 official controller image + credential-free fake
  provider 的真实 streaming/tool conformance。
- HWE plugin：34 passed、mypy 9 source files；Codex plugin：5 passed、mypy 22 source files；
  training-reference：94 passed、1 个缺少可选 `rllm` dependency 的 runtime test skipped、
  mypy 29 source files。
- Core 和 DeepSeek Harness 的 sdist/wheel build 通过；schema export drift check、dataset
  Pydantic validation、canonical report/evidence/dataset/dry-run hash validation均通过。
- 本次 runtime manifest 中的 19 个 task container 均已移除，运行中的 Harness controller
  container 为 0。

## 后续判断

失败可以解决，但应创建新的、明确版本化的 collection contract 后重新做小规模 pilot，
而不能修改本次冻结结果。优先验证的最小改动是：让 Harness/provider 强制产生 typed tool
action；把 terminal semantics 与 `finish` 对齐；为 action-policy rejection 规定可审计的
同轨修正语义；并根据 HWE 实测轨迹长度重新预注册 response/step budget。任何把末尾 prose
静默映射成 action、删除非法 action 或事后扩大 budget 的做法都会改变监督目标，不应
retroactively 用于本次数据。

资源状态：`gpu_hours=0`、`hpc_jobs_submitted=false`、`training_started=false`、
`heldout_evaluation_started=false`。
