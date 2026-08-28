# OpenHands v17 collection canary v2 审计

日期：2026-08-28。

> **结论边界：** v2 canary 已 fail closed。PR-2944 与 PR-2248 verifier pass，PR-3191
> 因模型生成的 `shell.command` 含 raw host path 而触发冻结 provider-tool-arguments policy。
> `canary_passed=false`、`formal_collection_allowed=false`、
> `production_training_ready=false`、`benchmark_score_claimed=false`。正式轨迹采集、GPU、
> SFT、checkpoint、adapter 和 held-out A/B 均未启动。

本报告只提交脱敏类别、计数、哈希和门禁结论。完整 run、trajectory、原始 observation 与
provider 证据保留在 Git 外的 experiment 目录中。本结果不是 benchmark score，也不能把前两条
通过轨迹单独重标为已通过正式数据门禁。

## 冻结范围

- v2 source commit：`ec8f3d93681f3cfe477a083371448ac1673f8eac`
- contract hash：`28a0da3b5ba9c51762c1d64af27c43064b6001e2c9cba65361faf29a3e6f8570`
- campaign：`openhands-hwe-v17-collection-canary-v2`
- agent version：`openhands-deepseek-v4-flash-hwe-v17-collection-canary-v2`
- model：`openai/deepseek-v4-flash`，thinking disabled，temperature `0`
- OpenHands SDK / LiteLLM / tiktoken：`1.42.1` / `1.93.0` / `0.7.0`
- seed / sample index：`486` / `2`
- limits：65,536 context tokens、2,048 output tokens、200 iterations
- retry：whole episode `0`，provider request `0`
- tool contract：精确六工具、metadata-free、workspace-relative path constraints v3
- schedule：PR-2944 training → PR-2248 training → PR-3191 validation
- held-out task IDs loaded：`0`

v2 clean commit 的 push run `33181556204` 与 PR run `33181559618` 均通过 8 项 Actions：
quality、package、reproducible-build、ordinary 3.11/3.12/3.13、OpenHands 3.12 和 Docker
external-agent zero-model security。

## v1 封存与扫描器修复

v1 source commit `3fba5777077d435b56b73918774a032a03903509` 的 PR-2944 scorecard resolved，
并生成 exact trajectory，但通用扫描器把
`broker.json:$.raw_audit_manifest.secret_scan` 的固定审计状态枚举误判为 concrete secret。
此前独立 exact provider-value byte scan 已为零命中；该次运行仍按规则封存，PR-2248 与
PR-3191 未启动，不能追认为有效 canary。

修复只把 `credential|secret|security` scan/check 字段的固定
`pass|passed|fail|failed` 值分类为 enum；同一字段中的任意非枚举值仍按 credential candidate
fail closed。扫描策略身份由 v2 升级为
`context_aware_structured_artifact_secret_scan_v3`，并新增 true-positive 回归测试。runner 同时
改为先原子持久化脱敏 scan report，再执行 pass gate。v1 与 v2 使用不同 campaign、contract、
agent version 和输出目录，没有续跑 v1。

v1 sealed report 内部 hash 为
`a2b5626b4cf4da84def71113eefc0139974c80cc9302f89d8e06c1de275864eb`，文件 SHA-256 为
`94d9bc705ccdb3d24d61d83280b6075ba8c4f10997548f6fedcfd4a55ef069a9`。

## v2 结果

| episode | verifier / policy | recovery | model / tool calls | total tokens | scan | trajectory |
| --- | --- | --- | ---: | ---: | --- | --- |
| PR-2944 training | verifier pass | direct | 14 / 15 | 133,273 | pass，0 hard / 0 error | fresh exact，14 decisions |
| PR-2248 training | verifier pass | direct | 14 / 18 | 98,093 | pass，0 hard / 0 error | fresh exact，14 decisions |
| PR-3191 validation | model provider-tool-arguments policy failure | recovery `1/1/1`，continuation `1/1/1` | 42 / 40 | 1,262,651 | 未到通用 scan gate | 未导出 |

PR-2944 与 PR-2248 均满足 infrastructure、runtime evidence、完整 accounting、无截断、
provider-value 零命中和通用 security scan。两条 trajectory 文件 SHA-256 分别为
`204df2561e59ab803b0df79182c8d6b8edaa222aabce19d332062292c93066d5` 与
`3e077dd0455b18efa9b61cd8ca2d5d15cd0111186ec5b3509521595e6d23f90f`。它们保留在
experiment 目录，不进入 Git，也不绕过三任务 canary gate。

PR-3191 完成 42 次 provider call，42 次均有成功响应与 usage record。一次 format recovery
返回 canonical `read_file`，一次 SDK continuation 返回 canonical `apply_patch`；两条 receipt
都只含一个 function call、一个 converted tool call、零 text part，因此 recovery 本身合规。
随后 provider 在 `shell.command` 中生成 raw host path，普通 agent loop 与 continuation 都记录
同类 `ProviderToolArgumentsPolicyError`。该失败为 `kind=model`、`infrastructure=false`；broker
没有 infrastructure failure、policy failure、rejected broker call 或 typed finish。原始命令内容
未写入脱敏 trace，message content 与 training trajectory 均未导出。

v2 sealed report 内部 hash 为
`e50cb962b221e09fd0ca3a3c6fe7be7a6ae341159260582451fa9f7a72d47151`，文件 SHA-256 为
`8182c92ecf09aff989e5ac091b69ef4d2ec05f0f41101931b7fa3479f4c1d8ca`。

## Evidence → Finding → Path

### Evidence

- **E-001 / v1 sealed failure：**
  `/data/jzhu484/Agent/experiments/qwen35-hwe-openhands-v17-canary/canary-3fba577-s486-v1/canary-report.json`；
  记录 PR-2944 后 `SecurityScanFailure` 立即停止，文件 SHA-256 如上。
- **E-002 / scanner replay 与回归：**封存的六个 PR-2944 OpenHands evidence 文件在 scanner
  v3 下只读回放为 `gate=pass`、`hard=0`、`errors=0`；50 个 scanner focused tests 与 12 个
  canary focused tests通过。
- **E-003 / v2 sealed report：**
  `/data/jzhu484/Agent/experiments/qwen35-hwe-openhands-v17-canary/canary-ec8f3d9-s486-v2/canary-report.json`；
  内部 report hash 与文件 SHA-256 如上。
- **E-004 / positive episode scans：**PR-2944 与 PR-2248 scan report hash 分别为
  `fdc3bea98da92165091df48ab71557f1efade29185d5f4c85e8d1effdb39284d` 与
  `68d8599beaf30a3f617e85eab60e8ab300c55f79d2bff5cbf25a4e6b2e714090`，均为
  `hard=0`、`scanner_error=0`。
- **E-005 / PR-3191 policy receipt：**scorecard SHA-256
  `89f58765662f4e0eb0b38280e70f5f0f442c37107060ae013058a07b7c2fbcdc`，脱敏 trace SHA-256
  `cacc129fb276e486682853c8b0646dcb3171698bbde19737a0949a129d235e27`；receipt 只保留
  `tool_name=shell`、`argument_field=command`、`violation_kind=raw_host_path`。
- **E-006 / CI 与零下游副作用：**commit `ec8f3d9` 的两个 Actions run 均 8/8；sealed report
  记录 `training_started=false`、`optimizer_steps=0`、`checkpoint_written=false`、
  `adapter_written=false`、`hpc_jobs_submitted=false`、`gpu_seconds=0`。

### Findings

- **F-001 / scanner finding / validated false positive：**E-001、E-002 证明 v1 阻断是固定
  audit-status enum 的上下文误分类，而非 concrete provider credential 泄露；修复保留非枚举
  value 的 fail-closed 行为。
- **F-002 / two positive training canaries / validated：**E-003、E-004 支持 PR-2944 与
  PR-2248 的 verifier-pass exact trajectories；它们只证明两条 canary episode 有效。
- **F-003 / validation provider path policy failure / validated：**E-003、E-005 证明 PR-3191
  是真实模型参数越界，不是 recovery、Docker、provider availability 或 scanner failure。
- **F-004 / formal data and SFT gate closed / validated：**E-003、E-006 证明三任务 canary
  未通过；正式采集、64K dataset materialization、32-step SFT 和 held-out A/B 不得启动。

### Path

- **P-001 / canary gate path：**v1 clean CI → PR-2944 episode → scanner enum 误报 → v1 封存
  （E-001）→ scanner v3 与独立 v2 identity（E-002）→ v2 clean CI（E-006）→ PR-2944 pass →
  PR-2248 pass（E-004）→ PR-3191 exact recovery/continuation → raw-host-path policy failure
  （E-005）→ v2 sealed `formal_collection_allowed=false`（E-003、F-004）。

## 可复现的脱敏核验

以下命令只读取 sealed summaries，不读取 provider 环境变量或原始 observation：

```bash
gh run view 33181556204 --json status,conclusion,jobs,headSha
gh run view 33181559618 --json status,conclusion,jobs,headSha
sha256sum \
  /data/jzhu484/Agent/experiments/qwen35-hwe-openhands-v17-canary/canary-ec8f3d9-s486-v2/canary-report.json \
  /data/jzhu484/Agent/experiments/qwen35-hwe-openhands-v17-canary/canary-ec8f3d9-s486-v2/runs/validation-pr3191-s486/scorecard.json \
  /data/jzhu484/Agent/experiments/qwen35-hwe-openhands-v17-canary/canary-ec8f3d9-s486-v2/runs/validation-pr3191-s486/trace.jsonl
```

本 canary identity 已结束且不得重试。若未来要研究模型为何生成 raw host path，只能另立不改变
本门禁结论的 diagnostic identity；它不能恢复 validation capacity，也不能授权正式采集或 SFT。
