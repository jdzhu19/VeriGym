# RTLLM full-L2 Codex 12 题对照诊断 v1

日期：2026-09-02

状态：诊断已完成。12 个冻结模型进程 slot 均到达不可变终态，每个进程恰有一次有效
identity observation，且没有重试；9 个候选 resolved。自动 finalization 与独立
`--finalize-existing` 均通过 offline replay、精确泄漏扫描和脱敏审计。本结果是有界的
L1→L2 对照诊断，不是原生 RTLLM score，也不构成 benchmark 成绩声明。

## 冻结范围与限制

- Campaign ID：`rtllm-full-l2-codex-gpt54-xhigh-12task-contrast-v1`。
- 对照基线：`rtllm-full-l1-codex-gpt54-xhigh-12task-pilot-v1`。
- 数据源 commit：`41b26896e33b536940116a975626455eed3de65e`。
- Suite variant：`v2-agent-eval-functional-all-v1`。
- 50 题聚合 task identity：
  `9a36fdf432c0cbfc2dfaef7a2b067a5ef02b83578e38c0f2015113e7ae9e3d38`。
- 请求模型与 reasoning：`gpt-5.4` / `xhigh`。
- Functional agent identity：`codex-cli-agenteval-gpt54-xhigh-functional-v3`。
- Agent version hash：
  `467d2ba0847fab60f39ee7d85a7073abc832e5c35fa299d8e09cb5761c230b3c`。
- Codex CLI：`codex-cli 0.147.0`；可执行文件 SHA-256：
  `134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477`。
- Prompt hash：`14635a854a76a46c8260572cf3a303c0672da77e8b52cdae09427582e79b8ee9`。
- Tool-policy fingerprint：
  `6a0cf3b44d0bdb1b6ba2a016607db639e857af8979389ece947c8bea55415ef4`。
- Seed 与样本数：seed 0，每题一个进程。
- 执行策略：串行；每个 slot 一个进程；自动重试次数和重试授权均为 0。
- PPA：public feedback 和 final scoring 均禁用。
- Runtime image：
  `sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`。
- Launcher SHA-256：
  `661bbe187ea799e9b1b6495818d456289fe18bb6b796c201828025eb06608be4`。

任务名称及顺序与 L1 pilot 完全一致：`adder_32bit`、`fixed_point_substractor`、
`div_16bit`、`multi_booth_8bit`、`adder_pipe_64bit`、`JC_counter`、
`sequence_detector`、`LFSR`、`synchronizer`、`RAM`、`freq_divbyodd` 和
`serial2parallel`。Plan 将模型 ID、reasoning、seed、样本数、串行执行、零重试和禁用
PPA 明确记录为受控维度。

这不是只改变单一变量的严格因果实验。L2 必须使用独立注册的 functional-v3 prompt/tool
identity，才能把功能型 public validation 和 repair evidence 纳入 agent 合同；suite task
identity 和 public feedback 也从 L1 compile-only projection 变为 full-L2 functional
projection。外部模型不会因为记录了 seed 0 就成为确定性采样。因此，逐题变化只能解释为本次
有界对照的观测，不能全部归因于功能反馈。

## 零模型资格化证据

正式资格化在授权任何模型进程前完成。对每道题，reference 均通过独立 public functional
smoke 和最终 hidden verifier；stuck-zero、reset/初始边界错误、协议/延迟或接线错误以及
任务特定功能错误这四类 control 均被 public 和 hidden 两条路径拒绝。

| 检查 | 数量 | 结果 |
| --- | ---: | --- |
| Reference public smoke | 12 | 全部通过 |
| 四类 control 的 public smoke | 48 | 全部拒绝 |
| Reference hidden verifier | 12 | 全部通过 |
| 四类 control 的 hidden verifier | 48 | 全部拒绝 |
| 编译/仿真 verdict 合计 | 120 | 全部符合预期 |

60 个候选在一个 `network=none`、仅 verifier 可见的 Docker session 中分别执行 public 和
hidden 仿真。Session 关闭后，包含 normalized reference 和 hidden asset 的资格化 staging
目录被删除；它没有进入模型 workspace 或最终扫描范围。冻结 plan 对每题记录
`model_calls=0`、`gym_qualification_level=L2_functional_smoke` 和
`ppa_supported=false`。

## 逐题结果

Authorization ledger 包含 9 个 `completed`、2 个 `verifier_rejection` 和 1 个
`contained_model_failure`。12 个 Codex 进程全部启动，并各自产生一次有效 identity
observation。11 个进程到达 typed `finish`；`freq_divbyodd` 在 public test 持续失败后超时，
没有 finish。每个 typed-finish 候选恰好执行一次 hidden verification；no-finish 候选完全没有
执行 hidden verifier。

| 任务 | L1 终态 | L2 public 序列 | Typed finish | L2 hidden | L2 终态 |
| --- | --- | --- | ---: | --- | --- |
| `adder_32bit` | resolved | 首次通过 | 是 | 一次通过 | resolved |
| `fixed_point_substractor` | resolved | 首次通过 | 是 | 一次通过 | resolved |
| `div_16bit` | resolved | 首次通过 | 是 | 一次拒绝 | verifier rejection |
| `multi_booth_8bit` | resolved | fail→repair→pass（`1/1/1`） | 是 | 一次通过 | resolved |
| `adder_pipe_64bit` | verifier rejection | 首次通过 | 是 | 一次通过 | resolved |
| `JC_counter` | resolved | 首次通过 | 是 | 一次通过 | resolved |
| `sequence_detector` | 无 typed finish | fail→repair→pass（`1/1/1`） | 是 | 一次通过 | resolved |
| `LFSR` | verifier rejection | fail→repair→pass（`2/2/2`） | 是 | 一次拒绝 | verifier rejection |
| `synchronizer` | 无 typed finish | 首次通过 | 是 | 一次通过 | resolved |
| `RAM` | 无 typed finish | fail→repair→pass（`1/1/1`） | 是 | 一次通过 | resolved |
| `freq_divbyodd` | resolved | 9 次失败、8 次 repair、未通过 | 否 | 未执行 | 模型超时 |
| `serial2parallel` | verifier rejection | fail→repair→pass（`1/1/1`） | 是 | 一次通过 | resolved |

6 个 episode 的首次可见功能验证即通过。5 个 episode 出现可见的 public
fail→patch→recheck pass，其中 4 个最终 resolved，`LFSR` 仍然 hidden incorrect。
`freq_divbyodd` 在 9 次 public failure 后完成 8 个 repair patch 和 8 次 recheck，但始终没有
得到 public-pass revision，也没有 typed finish。

与 L1 pilot 相比，5 题从未 resolved 变为 resolved：`adder_pipe_64bit`、
`sequence_detector`、`synchronizer`、`RAM` 和 `serial2parallel`；2 题反向变化：
`div_16bit` 和 `freq_divbyodd`。另有 4 题保持 resolved，`LFSR` 继续被拒绝。Resolved
总数从 6/12 增至 9/12，typed finish 从 9/12 增至 11/12。这些配对单次观测说明 L2 可以
暴露可操作的 repair loop；但两项反向变化，以及早先三题 L2 campaign 中不同的逐题结果，也
直接说明存在采样方差。它们不是因果效应或总体准确率的估计。

所有 run 的 PPA evaluation 数均为 0，且都没有 final PPA object。Yosys/OpenSTA、VCS 和
Design Compiler 均未调用；本 campaign 使用的唯一 HDL 工具路径是冻结的 Icarus 12
编译/仿真环境。

## Replay、用量与脱敏证据

自动 finalization 报告 `infrastructure_complete=true` 和 `diagnostic_complete=true`。
独立 `--finalize-existing` 没有调用模型，并复现同一 9/12 结果。Replay 验证 12 条记录
全部有效；精确泄漏扫描没有 finding；脱敏审计没有发现 forbidden artifact 或未界定的
terminal-path disclosure。

11 个 typed-finish episode 的 provider usage 完整，合计 1,187,752 input tokens、976,384
cached input tokens、47,902 output tokens 和 1,235,654 total tokens。超时的
`freq_divbyodd` usage 保留为 incomplete，没有估算补值。Provider 未记录 cost。

| 证据 | SHA-256 |
| --- | --- |
| Frozen plan | `d4f55f7a239a7ce874ddf6bdb466bea7a7f5d8a0bcd25c6b9b349faba0a91627` |
| Summary | `6dba72a4227e45f45833ea87a71b6c17090ca53a6d25f9785c8f5f55fcb06d66` |
| Authorization ledger | `400d94c5fe573507411290d0196fc3ea795299363725cb7e191b4155877f1cd9` |
| Offline replay | `1fb7b3ecb50e2ce19776970539eecf16626f501e6c7e1da1e78a412541eca4d8` |
| Leakage scan | `1cc2d895955cdb1bc154399b5950fbd5ee7af45ef3a2ba633148b3ee7dfc1ce7` |
| Redaction audit | `63a0ccb1d4e3b2995bdcc2006ea93addf28b25b6e3ed6dcb931313ed72718f0b` |

实验输出继续保存在仓库外。本文没有提交数据集 checkout、normalized reference RTL、hidden
testbench、hidden auxiliary data、生成候选、原始 trajectory、模型 reasoning、Docker layer、
credential、proxy value 或商业资产。

## 实现验证

- 仓库级 Ruff 与 format check 覆盖 675 个文件并通过；core strict mypy 对 215 个 source
  file 通过。
- RTLLM plugin 测试为 118 passed、22 个显式 external/commercial opt-in skipped；plugin
  strict mypy 对 4 个 source file 通过。
- 使用 pinned checkout 的 RTLLM source-backed adapter 检查 9/9 通过。
- 三个相关 launcher 测试文件合计 36/36 通过；新增 full-L2 launcher 文件为 12/12 通过。
- 仓库普通 pytest 为 1,251 passed、1 个显式 real-Codex opt-in skipped、52 个 external
  case deselected，并在未修改的 loopback stdio broker 测试中出现两个时序失败。单文件重跑
  为 4/5，通过隔离运行剩余测试后为 1/1 通过。本文保留这项测试环境时序证据，不将仓库级
  pytest 声明为一次性全绿。

## 结论与下一步

这次 campaign 在与 L1 完全相同的 12 题集合上验证了 full-L2 multi-turn 路径：功能反馈能
驱动可观察 repair，final-only hidden gate 仍严格强于 public smoke，no-finish 候选保持
unverified，不可变零重试纪律也能跨正常模型失败持续执行。

下一项带结果的工作不应立即重跑这些 slot。任何新 campaign 都应采用新冻结 identity 和预先
声明的 sampling design。对于 benchmark integration，当前 50 题 L2 variant 已可用于有界
functional diagnostic。PPA 仍是独立的 L3/L4 资格化问题；在每题 synthesis top、clock 及
open/commercial profile 均完成独立资格化并冻结新 variant 前，应继续禁用。
