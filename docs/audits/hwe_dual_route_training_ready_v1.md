# HWE 双路线 Training-Ready 数据实验审计

日期：2026-08-22。此审计记录本轮真实执行结果；未启动 SFT、GPU 训练、HPC 或
held-out evaluation。

## 结论

本轮没有路线达到 `training_ready=true`，因此没有生成可供训练加载的双路线 dataset
或 dual-route handoff。构建器按 fail-closed 处理了 verifier/NAP 拒绝和本地推理资源
阻塞，没有通过改桶、截断、删除动作或放宽 gate 来制造成功。

最终状态：[training-ready-dual-route-v5/run-status.json](/data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-dual-route-v5/run-status.json:1)。

## 冻结输入

- 历史 Complexity-Trap 输入：8 条 source transcript、419 条 action-conditioned 记录。
  原始 dataset hash 为
  `3a0905c578ca70b9af0ac5a17d0bf100d21e4357445882321616bf26f55fe841`，原始 JSONL
  SHA-256 为 `663b279751639c7a52118719a65e7d9345162b057c8add4a4cd61b537a365200`。
  冻结检查确认旧记录 hash 与字节内容未改变。
- 原始 transcript SFT token 数为：pr-2032 `84491`、pr-2248 `22266`、pr-2282
  `43793`、pr-2468 `22533`、pr-2469 `60232`、pr-2549 `32886`、pr-2589
  `49054`、pr-2944 `39062`；最大值为 `84491`。
- Base Qwen3.5-9B snapshot hash：
  `fce78eefb5b60ff95c480d2fb823bb45370a4abc933d6114a84d6a321486b156`；tokenizer
  hash：`440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e`。
  推理使用 `local_files_only`、`trust_remote_code=false`。
- CoACT checkpoint revision：
  `1b2d660dfa5fccf80a5e3c508a9f0d3c1930ccf5`；`model.safetensors` 大小
  `8410314240`，SHA-256 为
  `bd2546d7a571bd4e20b899175d0169e9368edfe8dd2357267e2534e91528cb35`。
  模型卡未声明 license；源码仓库记录为 MIT，未把两者混同。

## Complexity-Trap 路线

实现了 8-anchor、top-3、阈值 0.6 的 frozen Qwen NAP gate，typed action similarity
覆盖六个 HWE 工具；历史 M1/P1 失败时按 `(M,P)=(2,1),(4,2),(8,4),(16,4)` 恢复，
并同步保存所选 recovery policy hash。

真实构建中，pr-2032 的早期动作无法在历史视图及全部恢复视图同时满足 NAP 与 32K
约束；一次复现阻塞在 sequence 3，收紧 action decode 上限后的复现阻塞在 sequence 1：

`NAP and 32K recovery failed for ... pr-2032 sequence 3/1`

因此没有写入新的 419 条 ready 记录，也没有覆盖历史 M1/P1 数据。旧路线的静态输入
规模仍为 419 records、最大 26486 tokens（训练数据未宣称 ready）。

## CoACT 路线

实现了按 observation entry 顺序的一次性永久替换、≤512 bypass、8 个 seed 候选、
token non-growth、code line-range 重建、诊断/exit code/changed paths/diff 证据保留、
NAP gate、因果 chronology 和 no-truncation schema。为适配原始 HWE 多行输出，display
line numbers 只加入 compressor prompt，重建仍使用未编号原文。

官方 checkpoint 的单候选 smoke test 能产生合法 `N-M:reason` code candidate；但完整
8-trajectory构建在第一个大 observation 的 candidate/NAP 循环上测得每个候选需数分钟。
8 候选、145 个超过 512-token 的 observation 以及每候选 9 次 frozen Qwen 调用会形成
不可接受的本地作业时长。第二次有界重试在未封存任何 CoACT trajectory 前停止，状态写为
`bounded local inference interrupted after CoACT candidate/NAP resource check`。

因此 CoACT trajectory、压缩 token 分布、fallback 数和 pr-2032 ≤65536 结果均未被
宣称；需要单独安排压缩器推理/LoRA 资源后再继续，不能把本次 pilot 当作 benchmark。

## Handoff 与验证

已添加但保持 `start=false` 的配置：[Complexity config](/data/jzhu484/Agent/VeriGym/configs/training/qwen35_hwe_training_ready_action_conditioned_sft_v1.json:1)、
[CoACT config](/data/jzhu484/Agent/VeriGym/configs/training/qwen35_hwe_coact_multiturn_sft_v1.json:1)。
预注册配方为同一 Qwen base、seed 484、3 epochs、learning rate `1e-4`、6 optimizer
updates、LoRA rank 8/alpha 16/dropout 0.05，并要求按 trajectory 累积、按 supervised
tokens 归一化；本轮没有执行它。

新增 provider-neutral HWE native-shell v2 rLLM bridge 及 zero-call conformance；新增
schemas、NAP/CoACT 单元测试、trainer dry-run loader 和 artifact/secret 约束。

验证结果：`ruff check .`、`ruff format --check .`、`mypy src`、普通 `pytest`（930 passed、
1 skipped、52 deselected）、training-reference plugin（94 passed、1 skipped）和 schema
export drift check 均通过。`hpc_jobs_submitted=false`、`training_started=false`、
`heldout_evaluation_started=false`。
