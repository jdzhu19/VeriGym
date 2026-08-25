# HWE CoACT observation-compression pilot: pr-2032

日期：2026-08-23。本次只做 CoACT-style 本地推理 pilot；没有启动 SFT、compressor
训练、held-out evaluation 或新的 HPC 作业。所有失败均保留，未降低 NAP 阈值、删除动作
或截断 transcript。

## 结论

CoACT 的 observation-entry 方案在有限前缀上可以安全压缩并通过因果检查，但完整
`pr-2032` pilot 在两个多卡 Qwen NAP worker 布局下都因 CUDA 驱动错误失败。因此当前
不能标记 `training_ready=true`，也没有足够证据把它扩展为 8 条完整 SFT trajectory。

## 固定输入

- CoACT checkpoint：`Kndy666/CoACT`，revision
  `1b2d660dfa5fccf80a5e3c508a9f0d3c1930ccf5`，本地推理使用
  `trust_remote_code=false`、offline/local-files-only。
- checkpoint lock hash：
  `d1cbbd4de32c881a05f079ed44eb5c5067e44c14ccb358b7aa775462099cc6b6`。
- `model.safetensors`：8,410,314,240 bytes；SHA-256
  `bd2546d7a571bd4e20b899175d0169e9368edfe8dd2357267e2534e91528cb35`。
- 完整源 transcript 的精确计数为 95 个 observation、84,491 message tokens；试验使用
  固定的 8 candidate seeds、512-token bypass、8-anchor typed-action NAP、top-3
  similarity threshold `0.6` 和 `truncation=error`。

## 已成功的有限前缀

33-observation 前缀的结果文件为
[pilot-result.json](/data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/coact-pilot-pr2032-seq32/pilot-result.json)：

- 36,290 → 30,076 tokens，减少 6,214；没有超过 64K；
- 6 个 observation 被压缩，24 个回退或 bypass；改变的 observation 的 NAP failure 为 0；
- causal validation `passed`；
- target sequence 32 没有候选同时通过诊断证据和 NAP，故安全回退原文，而不是伪造压缩成功。

这说明 CoACT 的“候选不安全就回退”机制在 HWE typed tools 上有效，但没有解决
sequence 32 的 next-action preservation 问题。

## 完整 pilot 的两次真实失败

| attempt | NAP worker layout | result | artifact SHA-256 |
| --- | --- | --- | --- |
| `coact-pilot-pr2032-full` | 2/2/2 cards | `LocalModelUnavailable: CUDA driver error: invalid argument` | result `b199204920818c24c8b7963c32f43f207b34e9f26a2bec9addc222bedc1e41d8` |
| `coact-pilot-pr2032-full-3x3` | 3/3 cards | same `LocalModelUnavailable` error | result `b199204920818c24c8b7963c32f43f207b34e9f26a2bec9addc222bedc1e41d8` |

第二次约运行 103 分钟后失败；它已经稳定越过模型加载并持续运行很长时间，最后仍在
isolated Qwen replica worker 抛出相同的 driver-level `invalid argument`。对应的完整
结果为
[pilot-result.json](/data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/coact-pilot-pr2032-full-3x3/pilot-result.json)，
日志为
[pilot.log](/data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/coact-pilot-pr2032-full-3x3/pilot.log)。

## 资源与边界

两次尝试都只使用现有的 LSF job `466876` 的 gpu03 物理卡 0--6；没有提交额外 bsub、SFT
或评估作业。pilot 结束后该 job 仍保持用户原先的 `RUN` bash 申请，
`hpc_jobs_submitted=false`。

## 下一步判断

增加 A30 数量或改变 2/2/2 为 3/3 能改善并行布局和吞吐，但不能修复已经重复出现的
CUDA worker 稳定性故障，也不能使 sequence 32 的 NAP gate 自动通过。要继续完整 CoACT
路线，应先单独修复为持久化/更少进程切换的 NAP 推理服务并做短回归；若目标是让压缩器
学会 HWE 特有诊断保留规则，则需要另行安排 ACON-style guideline/compressor 训练。本轮
不把这些未验证的方案称为 training-ready。
