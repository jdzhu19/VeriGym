# OpenHands v17 collection canary v4 结果

日期：2026-08-29。

> **结论边界：** v4 三任务 canary 已通过，`formal_collection_allowed=true`。PR-2944 与
> PR-2248 verifier pass 并导出 fresh exact trajectories；PR-3191 为 infrastructure、runtime
> evidence、accounting 与 security 全部有效的 model non-finish，不导出 trajectory。该结果只
> 授权进入正式采集实现与独立 PR/CI 门禁，不表示数据门禁、SFT 或 production readiness 已通过。

## 冻结身份与实现门禁

- source commit：`2d8cf58ad0e1fdc6d4d3e0ecacfb67cd275f5fc2`
- contract hash：`18ba9369eb59b96b468f42e2338600d0c029ad3c9f0a64763125af9b4360fb83`
- campaign：`openhands-hwe-v17-collection-canary-v4`
- agent version：`openhands-deepseek-v4-flash-hwe-v17-collection-canary-v4`
- agent version hash：`30fb666319eef0edbc3737ac7242b438f58c211d4b434871ec5284e33dfb4cdd`
- model：DeepSeek v4 Flash，thinking disabled，temperature `0`
- OpenHands SDK / LiteLLM / tiktoken：`1.42.1` / `1.93.0` / `0.7.0`
- seed / sample index：`486` / `2`
- whole-episode / provider retry：`0` / `0`
- schedule：PR-2944 training → PR-2248 training → PR-3191 validation
- held-out task IDs loaded：`0`

实现 commit `da21cec653c3b57075d42340083c2a6e008e1cd1` 的 push run `33200911466` 与
pull-request run `33200931932` 均通过 8 项 Actions：quality、package、reproducible-build、
ordinary 3.11/3.12/3.13、OpenHands 3.12 与 Docker external-agent zero-model security。PR #5
以普通 merge commit 合并后，真实 canary 从上述 latest clean `main` source commit 运行。

## 三任务结果

| episode | 结果 | model / tool calls | total tokens | recovery | trajectory |
| --- | --- | ---: | ---: | --- | --- |
| PR-2944 training | verifier pass | 19 / 21 | 154,283 | direct | fresh exact，19 decisions |
| PR-2248 training | verifier pass | 13 / 15 | 100,179 | direct | fresh exact，13 decisions |
| PR-3191 validation | model non-finish | 31 / 29 | 716,530 | validated required-tool continuation | 未导出 |

三条均满足：infrastructure valid、runtime evidence valid、完整 provider/tool/token accounting、
provider-value byte scan pass、artifact security scan pass、recovery accounting valid 与零截断。
PR-2944 和 PR-2248 的 trajectory 文件 SHA-256 分别为
`c1ed33da089ab637fb36e8278bfa4952b8a7ea01da66e6daa5ef90759d6a4371` 与
`b39478423ea72f38c18abfc8b29affe1bca8ce17f40190675756a2921c19a9dc`。

PR-3191 在一次无工具响应后由 stop hook 阻止停止，并在同一 session 完成冻结恢复：

- format recovery / required-tool request / validated tool：`1/1/1`；
- SDK continuation / forced request / validated tool：`1/1/1`；
- path-policy recovery：`0/0/0`；
- bounded iteration-limit exhausted：`false`；
- broker typed finish：`false`；ordinary verifier：未运行/未通过；
- message content、positive trajectory 与 verifier-pass artifact：均未导出。

因此该 episode 被分类为 `model_did_not_finish`，不是 infrastructure failure、raw-host-path、
schema drift、recovery violation 或 bounded-limit receipt。它不贡献 validation pass，但作为有效
样本进入 canary gate。

## Gate 与剩余容量

最终 gate：

- `canary_passed=true`；
- `formal_collection_allowed=true`；
- `pr2944_passed=true`；`secondary_pass_count=1`；
- `pr3191_passed=false`；
- maximum training pass count：`9`，target：`8`；
- maximum validation pass count：`2`，target：`2`；
- training / validation capacity sufficient：`true / true`。

两条 canary training pass 已计入最终 8 条 distinct training target，因此正式 training 顺序中的
7 条任务最多允许各运行一次，并在再获得 6 条 pass 后立即停止；这提供 1 条失败余量。由于
PR-3191 未通过，正式 validation 没有失败余量：公开 PR-3204 与 role-overlay reserve PR-3168
必须各自 verifier pass，才能达到 2 条 distinct validation target。任一任务结束后都必须重新计算
当前 pass + 剩余 distinct capacity；不足即 fail closed，不补采样、不使用 held-out。

## Sealed evidence

- report 内部 hash：`33619e73dd87a9085ba92445f856839de750b54d8bf6653e93c14717a6a37676`
- report 文件 SHA-256：`6b5b8f6016d5be59c012a55c651dbdba31e417cc19e9477338fbfa181952232f`
- gate 内部 hash：`6dd5917d5c27afd4be7b2b443a9369fb09d0dc6f009280c532e8552e97ee8ee3`
- gate 文件 SHA-256：`2ca11c0474125b2ca1459dcc93feca63b7d69cf653f4f5f2289e79665d282a2c`
- PR-2944 / PR-2248 / PR-3191 security scan SHA-256：
  `5020d72493de2198c7f38394db758a9622be7ff590fa2504327d9e19dfdd678e` /
  `bce528ca26189572b64d7aa296deb6c27ee8b1ffd6cbf9f8b8ee992cd6a134d5` /
  `8dec1a5fd9516554b4b2bedbe02ae3750ce343509eb0fed6505f36e692360347`。

完整 evidence 位于 Git 外：
`/data/jzhu484/Agent/experiments/qwen35-hwe-openhands-v17-canary/canary-2d8cf58-s486-v4/`。
Git 只提交本脱敏审计。sealed report 保持 `production_training_ready=false`、
`benchmark_score_claimed=false`、`training_started=false`、`optimizer_steps=0`、
`checkpoint_written=false`、`adapter_written=false`、`hpc_jobs_submitted=false`、
`gpu_seconds=0`。
