# DeepSeek Harness × HWE-Bench v3 三任务审计

日期：2026-08-23。本审计记录独立版本化的 native Harness v3 pilot。它验证公开
assistant text、sibling typed tool calls、同-session 格式恢复以及完整 decision loss mask；
不是 benchmark score，也不是 production training dataset。本轮未启动 SFT、GPU、HPC
或 held-out evaluation。

## 结论

v3 解决了 v2 的输出 schema 不匹配：`2/3` 任务形成因果完整 transcript 并通过普通 HWE
verifier，pr-2944 的 21 个 decision rows 全部满足 32K；pr-2549 也通过 verifier，但长
trajectory 的 62 个 rows 中有 19 个超过 32,768 tokens，最大 50,117。因此整个 pilot
dataset 按 `truncation=error` 保持 `loader_ready=false`，不能称为 training-ready。

pr-2032 在第一次 max-token 后使用了唯一一次同-session recovery，但恢复 interval 再次
max-token，按预注册规则 fail closed。三任务共发生 2 次 recovery，1 次恢复成功。没有
whole-episode retry、样本替换、截断、删除失败动作或 verifier 放宽。

最终报告：
[campaign-report.json](/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/pilot-3task-v3/campaign-report.json:1)。
canonical `report_hash` 为
`f686cf31336f22c31344c908dac72e81ff1c2b8d1c86a70ddbb3bf05986e386d`，文件 SHA-256 为
`2914374d9b499f82631ec9faf9139adeae32f4715f424c645148f5b18c4b9814`。报告绑定 v2
predecessor hash `7a78d29b28788065eb139f240f6830698a37b4b29cfb2a6fd9ef1e7965ac47b5`，
且没有复用 v2 trajectory。

## v3 contract

- DeepSeek Harness `0.1.1-rc.2`、revision
  `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`；DeepSeek `deepseek-v4-flash`，
  thinking disabled、reasoning off、temperature 0、每次最多 2,048 output tokens。
- 接受一个 assistant decision 中“公开 text + 一个或多个 typed tool calls”；sibling calls
  按输出顺序串行执行。公开 text 是模型可见回答，不是 private reasoning export。
- pinned Harness `GenerateOptions` 没有 `tool_choice` 字段，因此 receipt 明确记录 provider
  为 auto，而不伪称 `required`。安全边界仍由六工具 schema、broker 参数检查、串行执行、
  task runtime `network=none` 和普通 verifier 提供。
- `invalid_arguments` 会作为公开 tool error 返回同一 session；包含失败 call 的整个
  assistant decision 保留在后续上下文但不监督。其他 broker rejection 仍为 terminal。
- text-only 或 max-token interval 最多触发一次固定
  `VERIGYM_HWE_FORMAT_RECOVERY_V1` user message。session、workspace 和 candidate 不重置。
- SFT row 监督完整最终 assistant decision；system、user、tool 以及所有历史 assistant
  messages 全部 loss-masked。完整 OpenAI context 和六工具 schema 使用冻结 Qwen3.5-9B
  chat template 做 prefix/token/loss-mask dry run。

Controller 只持有 provider credential 和网络，不挂载 task workspace；task runtime 不含
credential 且无网络。公开 dataset 不含 raw provider events、raw observations、private
reasoning、hidden verifier、reference patch、credential value 或 raw host path。

## 真实执行

| Task | Decisions / accepted actions | Recovery | API tokens (in / out / total) | Verifier / dataset |
| --- | ---: | ---: | ---: | --- |
| pr-2032 | 19 / 18 | 1，失败 | 15,534 / 9,201 / 24,735 | 未 finish；policy rejected |
| pr-2549 | 63 / 63 | 1，成功 | 37,405 / 15,632 / 53,037 | verifier pass；62 rows，19 overlength |
| pr-2944 | 21 / 22 | 0 | 9,756 / 3,135 / 12,891 | verifier pass；21 rows 全部 ≤32K |

合计 103 model calls、103 accepted tool actions、62,695 input tokens、27,968 output
tokens、90,663 total tokens。三个任务的 broker rejected-call count 都为 0；本次没有真实
触发 `invalid_arguments`，该恢复分支由 official Harness + credential-free fake provider
conformance 和单元测试覆盖。

pr-2549 的 recovery 前有一个 text-only/max-token decision，因此 transcript 中有 63
assistant decisions，但只有 62 个 supervised decisions。pr-2944 有一个 sibling-call
decision，所以 21 个 supervised decisions 对应 22 个 canonical HWE actions。v3 没有把
sibling actions 拆成缺失共同 assistant context 的独立 targets。

## Dataset 与长度门

Dataset manifest：
[dataset-manifest.json](/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/pilot-3task-v3/dataset/dataset-manifest.json:1)，
dataset hash 为 `b362cc1df0969f1bad368c939110175502d8ff0d97aef62c93cccd18871e351a`。

- 2 条 verifier-passed trajectories，83 个完整 assistant-decision rows，覆盖 85 个
  supervised canonical tool actions；57 个 targets 含公开 assistant text。
- pr-2549 token 范围 2,001–50,117，19/62 overlength；pr-2944 为
  1,883–13,430，0/21 overlength。
- 所有 rows 合计 1,778,130 masked input tokens 和 15,557 supervised target tokens。
  这些是 action-conditioned 重复上下文成本，未被隐藏。
- `truncation=error`、`overlength_record_count=19`、`loader_ready=false`、
  `production_training_ready=false`。没有通过删掉 pr-2549 后 19 个 actions 来制造可训练集。
- dataset artifact/secret scan 为 `pass`。exact context 未压缩或 observation masking，故
  NAP 不适用；这不是 NAP pass 声明。

## 判断

v3 证明“DeepSeek API + 开源 Harness 采集，再用 Qwen 复现同一 Harness decision 格式”在
HWE 上方法学可行，并显著优于 v2 的 tool-only parser。剩余阻塞不是 GPU 数量：当前没有
开始训练。阻塞是数据 contract/长度——pr-2549 的后 19 个目标超过冻结 32K trainer。

下一步需单独预注册二选一并重新验证，而不能修改本 pilot：使用 64K Qwen trainer 保留
exact context，或对 observation-entry 做 action-preserving compression 并逐 changed
observation 过 NAP。前者资源成本更高但因果最直接；后者可降低重复上下文成本，但必须
解决此前 CoACT/ACON 路线的 HWE NAP 问题。任何路线都应先修正 rLLM/veRL 的 tool-aware
loader binding，再设置 HWE-specific optimizer 数值。

资源状态：`gpu_hours=0`、`hpc_jobs_submitted=false`、`training_started=false`、
`heldout_evaluation_started=false`；运行中的 Harness controller/container 为 0。
