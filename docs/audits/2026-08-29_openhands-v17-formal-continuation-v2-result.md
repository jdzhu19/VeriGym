# OpenHands v17 正式采集 continuation v2 结果审计

日期：2026-08-29。结论：正式 exact-64K 数据门禁未通过，campaign 已 fail closed。禁止运行
剩余 provider tasks、32-step SFT、GPU 作业或 held-out A/B；`production_training_ready=false`、
`benchmark_score_claimed=false`。

> 后续根因更正：历史 scorecard 的 model/policy 分类忠实记录了当时 validator 的输出，但该
> validator 随后被证明会把 JSON 转义后的合法 RTL case-label 换行误判为 Windows 盘符路径。
> PR-2468 正好需要修改 `CSR_MCOUNTINHIBIT:` case。历史 attempt 与 output 仍保持不可变，且
> 不允许重跑；代码层根因与修复证据记录在同日的 provider path-validator 审计中。

## 冻结执行身份

- continuation contract hash：
  `df47b0ca1e3900ad1a82d359bfd1711d35cd4b30ae4fc1b88d966b855513b8f4`
- collector merge commit：`b195dd72918ffccbbdb6359d9c94886de94e2420`
- frozen agent source commit：`2980f6c9900d4d5b9d609adb3f50ac213d6f5426`
- frozen agent version hash：
  `4203ffe35823ba6ba83fa5ab5c351b19dc3a58cd4265c22cdb07883975bbe521`
- output：
  `/data/jzhu484/Agent/experiments/qwen35-hwe-openhands-v17-formal-collection/continuation-b195dd7-s487-v3`
- seed / sample index / retries：`487` / `3` / episode `0`、provider `0`

Runner 先验证并导入 PR-2944、PR-2248 与 PR-2282 三条 verifier-pass exact trajectories。
Initial gate 为 3 个 distinct training pass、0 个 validation pass、next role training；三组
records manifests 均已写入，PR-2282 `recovery_task_reexecuted=false`。8-task 内置 Docker
zero-call preflight 随后通过，没有使用 held-out。

## PR-2468 唯一 provider attempt

PR-2468 在第 4 次 provider response 后终止。四次调用、成功 response 和 usage record 完整对应；
accounting 为 4 model calls、4 canonical broker tool calls、16,818 input tokens、1,009 output
tokens、17,827 total tokens。Broker 接受 3 次 read 和 1 次 command，没有 patch、mutation、
finish、rejected broker call 或 workspace epoch 变化。

Scorecard 为 `resolved=false`，failure kind `model`、`infrastructure=false`，category 为
`openhands_hwe_provider_tool_arguments_policy`，ordinary termination reason 为
`policy_violation`。一次冻结 path-policy recovery 已发出 required-tool request，并收到一个
shape 为 `apply_patch` 的 function call，但 canonical argument validation 未通过：recovery
count/budget/forced request/validated tool 为 `1/1/1/0`。因此它不满足只允许 `0/0/0` 或精确
`1/1/1` 且有一次 verified canonical tool 的恢复合约。

原始 rejected arguments、message content 和 private reasoning 均未持久化；private raw audit
为 4 records、7,362 bytes，secret scan passed。独立对完整 output 与 launcher log 的 concrete
provider-value scan 覆盖 6,873 files，命中为 0。由于策略违规发生在普通 verifier 之前，未运行
verifier、未导出 trajectory，也未写通用 task security-scan；这不能作为训练样本或普通 verifier
rejection。

关键 SHA-256：

- scorecard：`837fb918d62ac56e0513b8ea71c8c7c5d2c233345b7ed282164430307c237ccb`
- accounting：`138752a5d378d97016ffd9f9d0d4b94f18a101141226070a15153190dde53277`
- broker：`2f883c415a86b7928d157f45e336f1fe183a52fd6aa4e3acc2086e99db41a06d`
- summary：`97c8fc7d22511054a479db5f88a9d2d1047c082f14fcaaee1732040151c358ce`
- artifact manifest：
  `6ff2d8b49c92da7734fafeb0be8e3f9770aeccc018f9a1d190dabc7d9d3b1be0`
- run manifest：`8ffe18316139a754c484da093053dbb5e7e884e07912bfcf55997806b8219367`
- campaign report：
  `81d5cc87846a362ea529259addc21a7c2c62bbc7e56a0b5dd6268e36b2556fa3`
- launcher log：`056d9d17db252af085deb9e706c944c575931ab158cb51c3ebcb0be1165d062a`

## 门禁结论与持久化修复

Campaign report/progress 正确记录
`formal_continuation_stopped_fail_closed`、`episode_execution:ConfigurationError`、
`data_gate_satisfied=false` 和 `gpu_submission_allowed=false`。历史 `data-gate.json` 是 provider
attempt 前写入的 initial `continue_training` gate；停止路径没有覆盖它，因此该文件不得单独用于
恢复或下游授权，历史 output 保持不可变。

代码修复使 formal 和 continuation 的 `_stop` 在写 stopped report 前同步覆盖 terminal gate：
`satisfied=false`、`possible=false`、`next_role=null`、
`reason=campaign_stopped_fail_closed`，并持久化原 capacity reason 与 stop reason。该修复不追改
历史 output，也不允许恢复本 campaign、重跑 PR-2468 或启动后续阶段。
