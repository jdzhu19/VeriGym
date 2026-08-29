# RTL AgentEval Codex pilot v1 审计

> 结论：本 pilot 的基础设施与证据链完整，但候选结果未全部成功。不得将本次结果声明为 benchmark score，也不得据此启动后续扩大运行。

本报告是 `rtl-agenteval-codex-gpt54-xhigh-pilot-v1` 的脱敏审计。原始实验、数据集、商业资产和轨迹保留在仓库外；仓库只记录固定身份、聚合结果、允许的失败子类别和证据哈希。

## 结果摘要

pilot 使用 GPT-5.4、`xhigh` reasoning、seed 0、每个任务/profile 组合一次调用和进程级自动重试 0。执行前的 plan-only 资格测试完成且 `model_calls=0`；正式执行随后启动了 14 个真实 Codex CLI 进程。

| Suite / 路径 | 运行数 | Resolved | Typed finish | 结果 |
| --- | ---: | ---: | ---: | --- |
| RTLLM + OpenSTA/DC | 4 | 3 | 3 | 3 个合法候选 PPA；1 个终止性路径策略失败 |
| Verilog-Eval | 5 | 5 | 5 | 全部 resolved |
| RTL-Repo | 5 | 2 | 4 | 2 个 verifier rejection；1 个 contained model failure |
| 合计 | 14 | 10 | 12 | 14/14 进程与 identity observation 完整；0 infrastructure failure |

最终状态：

- `pilot_complete=true`，`infrastructure_complete=true`；
- 14/14 进程已启动，14/14 各有且仅有一个 external-agent identity observation；
- 14 条 identity 均为 `requested_only`，`observed_model_id=null`；没有持久化或推测 token usage；
- 14/14 `retry_count=0`，没有模型替换；
- 10/14 candidates resolved，12/14 由 typed `finish` 结束；
- 1 个 `workspace_path_policy`，2 个 verifier rejection，1 个 contained model failure；
- replay 14/14 integrity valid；泄漏扫描通过，0 findings；
- `fully_successful=false`，`pilot_is_benchmark_score=false`，`benchmark_score_claimed=false`。

## 固定身份与范围

| 项目 | 冻结值 |
| --- | --- |
| Campaign | `rtl-agenteval-codex-gpt54-xhigh-pilot-v1` |
| Predecessor | `rtl-agenteval-codex-gpt54-xhigh-smoke-v7` |
| Predecessor summary hash | `37c501c7200498ed1fc434fd775dffbc2aef78404f30473d400069742beac27b` |
| Agent version | `codex-cli-agenteval-gpt54-xhigh-v4` |
| Agent version hash | `3013e36846e016c6b57b9d28c811317718902e89b40fd522e4f49de3c93dd040` |
| Prompt hash | `607e0c73bd6fdead39fb63916cfb24eb5929c17a9e801309d1d8c100da1a6141` |
| Tool policy fingerprint | `115a39244d7f64c63fe8b5b2628cb829aafc1429e6d1d5acb22abdbe0ce7c052` |
| Codex CLI | `codex-cli 0.147.0` |
| Implementation commit | `cc442677535f19bbe8a96fd3099d3e0186bb89ff` |

工具边界如下：

- RTLLM 正式 run 使用隔离的 Icarus hidden functional verifier；
- OpenSTA 在正式 Open PPA run 中使用；DC/MCP 在正式 commercial PPA run 中使用；
- VCS/MCP 通过 execute 前的 reference/known-bad 资格测试，但未绑定到本 pilot 的 model-bearing verifier RunConfig；
- OpenSTA 与 DC 的连续 profile resolve、商业 release binding、Docker 控制面及 VCS/MCP 资格测试均在模型启动前完成；
- 商业资产、license、worker 地址、站点路径及原始工具诊断均未写入本报告。

OpenSTA scoring 修复使用完整活动身份（mode、activity、duty），而不是只比较粗粒度 mode。四条无模型综合资格记录均确认候选和 reference 的活动身份与 resolved profile 一致。正式结果中 3 个成功 RTLLM run 同时满足合法候选 PPA 与最终 PPA eligible；第 1 个 OpenSTA run 在 PPA 调用前因路径策略终止。

## 失败分类

| Run | 分类 | Typed finish | Infrastructure | 脱敏观察 |
| --- | --- | --- | --- | --- |
| `01-counter-open` | Policy failure | 否 | 否 | `workspace_path_policy`；hidden verifier 被跳过 |
| `11-rtl-repo-test-000002` | Verifier rejection | 是 | 否 | `rtl_repo.score` failed；termination 为 final submission |
| `12-rtl-repo-test-000003` | Verifier rejection | 是 | 否 | `rtl_repo.score` failed；termination 为 final submission |
| `14-rtl-repo-test-000005` | Contained model failure | 否 | 否 | termination 为 model error；无 policy/infra 子类别 |

这些结果是独立样本的终态，不进行自动重试。第 1 项保留终止性 workspace policy 等级；第 11、12 项保留 verifier rejection；第 14 项保留 model failure，不把它们重分类为基础设施问题。

## Evidence → Finding → Path

所有 source reference 均相对于仓库外 campaign 目录 `<campaign>/`。哈希为 SHA-256，`observed_at` 使用 campaign 完成日期。

### E-001

- title: Frozen pilot plan
- observed_at: 2026-08-29
- source_type: file
- source_ref: `<campaign>/plan.json`
- content_hash: `141a6b90d67f2efce6f76f5165400d84d099a9d516d1bb90450fb187f03c2164`
- repro_command: `sha256sum "$VERIGYM_PILOT_ROOT/plan.json"`
- raw_excerpt: campaign、模型、seed、14 个 run config hash、四个 profile identity 与 predecessor receipt 已冻结
- linked_workitem: n/a
- supersedes: none

### E-002

- title: Process authorization ledger
- observed_at: 2026-08-29
- source_type: file
- source_ref: `<campaign>/evidence/process-authorizations.json`
- content_hash: `d2396fce70872e670865c664310c548a57ccacde1edd47aca76483eac3d87cf8`
- repro_command: `sha256sum "$VERIGYM_PILOT_ROOT/evidence/process-authorizations.json"`
- raw_excerpt: 14 records；每项 authorization granted、process started、identity observation recorded；retry count 均为 0
- linked_workitem: n/a
- supersedes: none

### E-003

- title: Offline replay receipt
- observed_at: 2026-08-29
- source_type: file
- source_ref: `<campaign>/replay.json`
- content_hash: `b636561323b914da80a8ffbdcbaf19d874f93acfadd7e315860bbf09b5753310`
- repro_command: `sha256sum "$VERIGYM_PILOT_ROOT/replay.json"`
- raw_excerpt: `all_valid=true`；14/14 run integrity valid
- linked_workitem: n/a
- supersedes: none

### E-004

- title: Exact leakage scan receipt
- observed_at: 2026-08-29
- source_type: file
- source_ref: `<campaign>/security-scan.json`
- content_hash: `1cc2d895955cdb1bc154399b5950fbd5ee7af45ef3a2ba633148b3ee7dfc1ce7`
- repro_command: `sha256sum "$VERIGYM_PILOT_ROOT/security-scan.json"`
- raw_excerpt: `passed=true`；`findings=[]`
- linked_workitem: n/a
- supersedes: none

### E-005

- title: Final campaign summary
- observed_at: 2026-08-29
- source_type: file
- source_ref: `<campaign>/summary.json`
- content_hash: `f239bdc0eb4cf0e470f6bd176910fe4f3a74dde6b82639c1ae4dff3b2042acd8`
- repro_command: `sha256sum "$VERIGYM_PILOT_ROOT/summary.json"`
- raw_excerpt: pilot/infrastructure complete；14 starts；14 observations；10 resolved；fully successful false；benchmark score false
- linked_workitem: n/a
- supersedes: none

### E-006

- title: Requested-only identity confidence audit
- observed_at: 2026-08-29
- source_type: command
- source_ref: 14 个 `<campaign>/runs/*/artifacts/codex_cli/identity.json`
- content_hash: n/a
- repro_command: `rg -l '"identity_confidence": "requested_only"' "$VERIGYM_PILOT_ROOT/runs" -g identity.json | wc -l`
- raw_excerpt: 14/14 identity confidence 为 requested only；observed model 为空；每项 invocation count 为 1
- linked_workitem: n/a
- supersedes: none

### F-001

- title: 14-run 调用与基础设施证据完整
- severity: info
- category: design
- status: validated
- evidence_ids: [E-001, E-002, E-003, E-005]
- location: `scripts/run_rtl_agenteval_codex_pilot.py`
- impact: 证明 Codex CLI 可在冻结身份、零重试和隔离工具边界下完成 RTLLM、Verilog-Eval、RTL-Repo 的 14 个独立 multi-turn episode；未观察到 infrastructure failure。
- confidence: high
- repro_steps: 运行无模型 plan-only；满足 opt-in 后运行正式 pilot；再以 `--finalize-existing` 独立复核。
- remediation: n/a

### F-002

- title: 模型候选结果未达到 fully successful 门槛
- severity: info
- category: other
- status: validated
- evidence_ids: [E-002, E-005]
- location: `<campaign>/summary.json`
- impact: 10/14 resolved、12/14 typed finish；不得生成 benchmark score，也不得把本 pilot 描述为四项 PPA 与全部 suite 均成功。
- confidence: high
- repro_steps: 对照 ledger 的四个非 completed 终态与 summary 的 per-run records。
- remediation: 在新版本 agent/campaign 中分析路径策略、RTL-Repo verifier rejection 与 model error；不得重写或续跑本 campaign。

### F-003

- title: 开源与商业工具路径均获得真实成功样本
- severity: info
- category: design
- status: validated
- evidence_ids: [E-001, E-005]
- location: `<campaign>/plan.json` and `<campaign>/summary.json`
- impact: OpenSTA 和 DC/MCP 均有 resolved、typed finish、合法候选 PPA 与最终 eligible PPA；VCS/MCP 仅证明 prelaunch reference/known-bad 资格，不等价于 model-bearing VCS verifier run。
- confidence: high
- repro_steps: 检查 RTLLM run 2、3、4 的 summary PPA 字段，并检查 plan 中的 `qualifications.vcs_mcp`。
- remediation: 若需验证 model-bearing VCS verifier，冻结一个独立 verifier-profile campaign，不修改本 pilot。

### F-004

- title: Replay 与泄漏扫描通过
- severity: info
- category: design
- status: validated
- evidence_ids: [E-003, E-004]
- location: `<campaign>/replay.json` and `<campaign>/security-scan.json`
- impact: 已持久化 run 的离线完整性验证通过，未发现 hidden/reference 内容、站点路径、symlink 或商业诊断泄漏。
- confidence: high
- repro_steps: 运行 `--finalize-existing`，核对 replay `all_valid` 与 scan 空 findings。
- remediation: n/a

### F-005

- title: Provider 终止身份与 usage 未被观测
- severity: info
- category: design
- status: validated
- evidence_ids: [E-002, E-006]
- location: `<campaign>/runs/*/artifacts/codex_cli/identity.json`
- impact: 每个真实 Codex 进程都有唯一、绑定 requested model/reasoning 和 agent fingerprint 的 identity evidence，但不能声称 provider-confirmed observed model 或完整 token usage。
- confidence: high
- repro_steps: 统计 14 个 identity 文件的 `identity_confidence`、`observed_model_id` 与 `invocation_count`；确认 run manifest 未包含 usage 字段。
- remediation: 若后续 Codex JSONL 暴露稳定的模型终止与 usage 事件，在新 agent version 中记录 observed identity；继续禁止推测 token。

### P-001

- title: Frozen pilot execution and audit path
- path_type: callflow
- start: fully successful smoke-v7 predecessor receipt
- goal: 14 个独立 Codex episode 的可审计终态
- steps:
  1. action: 校验 predecessor、数据源、CLI、Docker、commercial release、DC/MCP 与 VCS/MCP — evidence: E-001 — finding: F-001
  2. action: plan-only 冻结 14 个 RunConfig，保持 model calls 为 0 — evidence: E-001 — finding: F-001
  3. action: 串行授权 14 个真实进程，记录 starts、identity observations 与 retry count — evidence: E-002 — finding: F-001
  4. action: 保留 policy、verifier 和 model 终态，不重试或替换模型 — evidence: E-002, E-005 — finding: F-002
  5. action: 离线 replay、精确泄漏扫描和独立 finalizer 复核 — evidence: E-003, E-004, E-005 — finding: F-004
- residual_risks: 本 pilot 未验证 model-bearing VCS verifier；4 个候选未 resolved；identity 均为 requested only；结果不构成 benchmark score。

## 验证记录

提交 `cc44267` 前完成：

- `ruff format --check .` 与 `ruff check .`；
- `mypy src`：214 个 source files 无问题；
- core pytest：1075 passed、1 个真实 Codex opt-in 测试按预期 skipped、52 deselected；
- Codex CLI integration：5 passed，mypy 25 files；
- RTLLM integration：11 passed、4 个 site opt-in tests skipped，mypy 2 files；
- RTL-Repo integration：13 passed、1 个 official snapshot opt-in test skipped，mypy 4 files；
- Verilog-Eval integration：5 passed、1 个 official checkout opt-in test skipped，mypy 3 files；
- Synopsys integration：31 passed，mypy 17 files；
- pilot launcher/scoring 定向回归：38 passed。

正式 campaign 完成后，`--finalize-existing` 在不调用模型的情况下重新校验 frozen plan、predecessor receipt、14 个 run config hash、process ledger、replay 和 scan，并复现相同 summary。

## 后续动作

本 campaign 保持只读，不续跑失败项，也不生成 benchmark score。下一轮应使用新的 agent version 与 campaign ID，并先完成以下无模型改进：

1. 在不降低 workspace policy 的前提下，检查为何模型仍提交终止性路径动作；
2. 对 RTL-Repo 两个 typed-finish verifier rejection 做候选 diff 与公开任务契约诊断；
3. 对最后一个 contained model error 核对安全子类别、usage completeness 和 broker state，继续禁止保存 raw output；
4. 如需证明 VCS model-bearing verifier，新增独立冻结 campaign，而不是扩大本 pilot 的结果声明。
