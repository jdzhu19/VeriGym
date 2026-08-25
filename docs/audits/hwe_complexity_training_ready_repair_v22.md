# HWE Complexity-Trap training-ready repair v22

日期：2026-08-23。此轮只验证 Complexity-Trap/action-conditioned 路线；没有启动 SFT、
训练、held-out evaluation 或新的 HPC 作业。CoACT 因用户选择 Complexity 路线而显式跳过。

## 结论

7 张 A30 的远端推理路径已经可以稳定运行，但数据仍未达到 `training_ready=true`。
构建器在 `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032` 的 sequence 32
按 NAP fail-closed；不是显存不足或 32K 超限。

状态文件：[run-status.json](/data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-complexity-repair-v22/run-status.json)。

## 固定输入与保护

- 原始 Complexity 输入保持 8 条 trajectory、419 条记录；旧 dataset hash 为
  `3a0905c578ca70b9af0ac5a17d0bf100d21e4357445882321616bf26f55fe841`，旧 JSONL SHA-256
  为 `663b279751639c7a52118719a65e7d9345162b057c8add4a4cd61b537a365200`。
- Qwen3.5-9B 使用冻结本地快照，snapshot hash 为
  `fce78eefb5b60ff95c480d2fb823bb45370a4abc933d6114a84d6a321486b156`；
  `local_files_only=true`、`trust_remote_code=false`。
- NAP 仍是 8 anchors、top-3 typed-action similarity、阈值 `0.6`；没有放宽门槛、
  删除失败动作或截断历史。

## sequence 32 的真实探针

所有候选都在 32K 内，但没有一个通过 NAP：

| history view | tokens | top-3 score | result |
| --- | ---: | ---: | --- |
| historical | 10,252 | 0.2000 | fail |
| recent=2, pinned=1 | 10,716 | 0.2000 | fail |
| recent=4, pinned=2 | 14,412 | 0.4133 | fail |
| recent=8, pinned=4 | 15,512 | 0.2000 | fail |
| recent=16, pinned=4 | 20,400 | 0.2000 | fail |

因此构建器输出 `record_count=0`，并保留明确的失败原因：
`NAP and 32K recovery failed ... sequence 32`。这表示当前冻结 base agent 在该动作处对
历史压缩不具备足够的 next-action preservation；增加 GPU 只能改善吞吐，不能使语义 gate
自动通过。

## 资源与运行边界

远端 bsub `466876` 仍为 `RUN`，独占 gpu03 的 7 张 A30（物理卡 0--6）。本轮没有提交
额外训练/HPC job，状态保持 `hpc_jobs_submitted=false`、`training_started=false`、
`heldout_evaluation_started=false`。

代码侧新增的隔离 worker 使用独立进程组，并将长上下文请求分为 2/2/3 卡的模型并行
worker；远端 grouped adaptive probe 已完成，未再出现此前的 CUDA/ProcessPool 切换阻塞。
这解决了资源路径问题，但没有掩盖 sequence 32 的 NAP 拒绝。
