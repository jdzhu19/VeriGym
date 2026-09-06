# RTL AgentEval Gym-fix diagnostic v1 audit

> 结论：6 个冻结的单次 Codex CLI 进程与全部基础设施、身份、replay 和脱敏证据均完整，
> 但诊断未达到全成功门槛。该结果仅用于诊断，不是 benchmark score，也不授权自动启动
> pilot-v2。

本报告审计 `rtl-agenteval-codex-gpt54-xhigh-gymfix-diagnostic-v1`。原始实验、数据集、
商业资产和运行轨迹保留在仓库外；仓库只记录冻结身份、聚合终态、脱敏失败类别和证据哈希。
每项只运行一次，自动重试为 0，未替换模型。

## 结果摘要

| Run | Typed finish | 候选 / verifier 结果 | Episode 终态 |
| --- | --- | --- | --- |
| `01-counter-open` | 是 | compile 通过；candidate PPA 合法 | resolved；final PPA eligible |
| `02-counter-dc` | 是 | compile 与 hidden regression 通过；candidate PPA 合法 | `scoring_event_ineligible`；未 resolved |
| `03-rtl-repo-test-000002` | 否 | Exact Match 失败 | `scoring_event_ineligible`；未 resolved |
| `04-rtl-repo-test-000003` | 是 | Exact Match 通过 | `scoring_event_ineligible`；未 resolved |
| `05-rtl-repo-test-000005` | 是 | Exact Match 失败 | final submission；verifier rejection |
| `06-rtl-repo-test-000004-control` | 是 | Exact Match 通过 | `scoring_event_ineligible`；未 resolved |

聚合终态：

- 6/6 Codex 进程已授权并启动，各有且仅有一个 external-agent identity observation；
- 6/6 provider terminal usage 完整，6/6 无 timeout，自动重试为 0；
- identity evidence 均为 `requested_only`，不能声称 provider-confirmed observed model；
- 5/6 通过 typed `finish`，1/6 candidate resolved；
- 2/2 RTLLM candidate compile 通过且产生合法 candidate PPA，只有 OpenSTA 项最终 PPA
  eligible；
- 2/4 RTL-Repo candidate 通过官方 Exact Match，但其中两个都因 non-canonical MCP
  machine-event stream 被 fail-closed；
- 0 policy failure，0 infrastructure failure；
- offline replay、精确泄漏扫描和 redaction audit 全部通过；
- `diagnostic_only=true`、`benchmark_score_claimed=false`、
  `automatic_pilot_v2_authorized=false`、`fully_successful=false`。

这里的 `scoring_event_ineligible` 是脱敏后保留的 model failure 类别。持久化证据没有保留
raw Codex stdout 或原始异常，因此本报告不从该枚举进一步推测具体 machine-event 形态。
候选 correctness 与 episode eligibility 必须分开读取：test-000003 和 test-000004 的
官方 scorer 均通过，但 episode 按协议 fail-closed；DC 的 compile、hidden regression 和
candidate synthesis 也通过，但 correctness gate 因 episode 终态未满足，最终 PPA 不 eligible。

## 冻结身份与范围

| 项目 | 冻结值 |
| --- | --- |
| Campaign | `rtl-agenteval-codex-gpt54-xhigh-gymfix-diagnostic-v1` |
| Agent version | `codex-cli-agenteval-gpt54-xhigh-v5` |
| Adapter version | `5.0.0` |
| Agent version hash | `18e69a46fb8ecca8c1000cfb7997d17c27b572be1940e94a2dd26ced796945e8` |
| Prompt contract | `repository_action_v2_prompt_v4` |
| Prompt hash | `bd96dbf5defd6203d4939873f92817817bd5593750cd6e292a4c0240135edc5c` |
| Tool-policy fingerprint | `424e9d022ef0c9fb891260698f130d865e19dfcaa2a7bfe4ff818a410823340a` |
| Model / reasoning / seed | GPT-5.4 / `xhigh` / 0 |
| Codex CLI | `codex-cli 0.147.0` |
| RTL-Repo projection | `official-parquet-v1-agent-eval-v2` |

OpenSTA 与 DC/MCP 是本轮两个 model-bearing synthesis 路径。VCS/MCP 只在模型启动前完成
reference/known-bad preflight；本诊断没有把它报告为 model-bearing VCS verifier run。全部
benchmark verifier session 继续使用 `network=none`，商业 worker release、Docker 控制面、
profile identity、输出根目录和 broker 根目录均在首次模型授权前完成检查。

## Evidence → Finding → Path

所有 source reference 均相对于仓库外 campaign 目录 `<campaign>/`。哈希为 SHA-256，
`observed_at` 使用 campaign 完成日期。

### E-001

- title: Frozen six-run diagnostic plan
- observed_at: 2026-08-29
- source_type: file
- source_ref: `<campaign>/plan.json`
- content_hash: `4c1285ac2e23a01c0696d2ab7f951ffb92369a3abdde78617fe5c8cd123cf9b6`
- repro_command: `sha256sum "$VERIGYM_DIAGNOSTIC_ROOT/plan.json"`
- raw_excerpt: 6 个固定 run；GPT-5.4/xhigh/seed 0；零重试；diagnostic only
- linked_workitem: n/a
- supersedes: none

### E-002

- title: Process authorization ledger
- observed_at: 2026-08-29
- source_type: file
- source_ref: `<campaign>/evidence/process-authorizations.json`
- content_hash: `18cf13346336b8b988368d00716503a923715467512e1e9d814fb65714eb5870`
- repro_command: `sha256sum "$VERIGYM_DIAGNOSTIC_ROOT/evidence/process-authorizations.json"`
- raw_excerpt: 6 authorizations；6 starts；6 unique identity observations；retry count 均为 0
- linked_workitem: n/a
- supersedes: none

### E-003

- title: Offline replay receipt
- observed_at: 2026-08-29
- source_type: file
- source_ref: `<campaign>/replay.json`
- content_hash: `91bc7083b4507e285d78c24892ff1b36614dde941e574c639320c7319fbe0dc1`
- repro_command: `sha256sum "$VERIGYM_DIAGNOSTIC_ROOT/replay.json"`
- raw_excerpt: `all_valid=true`；6/6 run integrity valid
- linked_workitem: n/a
- supersedes: none

### E-004

- title: Exact leakage scan receipt
- observed_at: 2026-08-29
- source_type: file
- source_ref: `<campaign>/security-scan.json`
- content_hash: `1cc2d895955cdb1bc154399b5950fbd5ee7af45ef3a2ba633148b3ee7dfc1ce7`
- repro_command: `sha256sum "$VERIGYM_DIAGNOSTIC_ROOT/security-scan.json"`
- raw_excerpt: `passed=true`；`findings=[]`
- linked_workitem: n/a
- supersedes: none

### E-005

- title: Broker redaction audit
- observed_at: 2026-08-29
- source_type: file
- source_ref: `<campaign>/redaction-audit.json`
- content_hash: `5bee478ea99bd2c89701b99acae2dffb6059008fdac5abd3ddedab4e64fbc30a`
- repro_command: `sha256sum "$VERIGYM_DIAGNOSTIC_ROOT/redaction-audit.json"`
- raw_excerpt: 6/6 passed；无 forbidden artifacts；terminal tool/category 均 bounded
- linked_workitem: n/a
- supersedes: none

### E-006

- title: Independently finalized diagnostic summary
- observed_at: 2026-08-29
- source_type: file
- source_ref: `<campaign>/summary.json`
- content_hash: `e3a8b051e516a5a3dd550b4e8ed0282416d4c521d8bb12b6a65daec8c7633d4c`
- repro_command: `sha256sum "$VERIGYM_DIAGNOSTIC_ROOT/summary.json"`
- raw_excerpt: 6 starts；6 observations；5 typed finish；1 resolved；fully successful false
- linked_workitem: n/a
- supersedes: none

### F-001

- title: 六进程诊断与基础设施证据完整
- severity: info
- category: design
- status: validated
- evidence_ids: [E-001, E-002, E-003, E-004, E-005, E-006]
- location: `scripts/run_rtl_agenteval_codex_gymfix_diagnostic.py`
- impact: 证明冻结 v5 Agent 可在零重试边界下完成六次真实进程；没有 timeout、policy、
  Docker、DC/MCP 或其他 infrastructure failure。
- confidence: high
- repro_steps: 先运行 plan-only，再经显式 opt-in 执行一次正式诊断，最后运行
  `--finalize-existing`。
- remediation: n/a

### F-002

- title: 候选结果未达到诊断全成功门槛
- severity: info
- category: other
- status: validated
- evidence_ids: [E-002, E-006]
- location: `<campaign>/summary.json`
- impact: 只有 1/6 resolved、5/6 typed finish，不能生成 benchmark score，也不授权
  pilot-v2。
- confidence: high
- repro_steps: 对照 summary 中每项 typed finish、resolved、compile 和 PPA eligibility。
- remediation: 在新的冻结 agent/campaign 中诊断 machine-event eligibility；不得续跑或改写
  本 campaign。

### F-003

- title: Candidate correctness 与 scoring-event eligibility 可被独立审计
- severity: info
- category: design
- status: validated
- evidence_ids: [E-003, E-006]
- location: `<campaign>/runs/*/scorecard.json`
- impact: 两个 RTL-Repo Exact Match 和 DC candidate synthesis 已通过，但三个 episode 因
  non-canonical MCP event stream fail-closed；报告不会把协议终态误写为候选错误。
- confidence: high
- repro_steps: 对照 per-run verifier result、failure category 与 campaign summary。
- remediation: 后续先用不调用模型的合成 event fixtures 界定不合格 event 形态，再冻结新
  agent/version；本诊断保持只读。

### F-004

- title: Replay、泄漏扫描与脱敏审计通过
- severity: info
- category: design
- status: validated
- evidence_ids: [E-003, E-004, E-005]
- location: `<campaign>/{replay,security-scan,redaction-audit}.json`
- impact: 6 个持久化 run 的完整性通过；未发现 hidden/reference 内容、站点路径、商业诊断、
  raw 异常或未界定 terminal metadata 泄漏。
- confidence: high
- repro_steps: 运行 `--finalize-existing`，核对 replay `all_valid` 以及两个审计的
  `passed=true`。
- remediation: n/a

### P-001

- title: Frozen gym-fix diagnostic execution and finalization
- path_type: callflow
- start: v5 Agent、RTL-Repo projection v2 和六项 launcher 冻结
- goal: 六个独立 Codex episode 的可审计终态
- steps:
  1. action: 校验数据、CLI、Docker/OpenSTA、DC release、DC/VCS MCP 和 profile identity — evidence: E-001 — finding: F-001
  2. action: plan-only 冻结六个 RunConfig 且 model calls 为 0 — evidence: E-001 — finding: F-001
  3. action: 串行授权六个单次进程并记录 identity、usage 和零重试 — evidence: E-002 — finding: F-001
  4. action: 保留 model failure 与 verifier rejection，禁止模型重试 — evidence: E-002, E-006 — finding: F-002
  5. action: 独立 finalization、offline replay、精确泄漏扫描与 redaction audit — evidence: E-003, E-004, E-005, E-006 — finding: F-004
- residual_risks: 4 个 candidate 未 resolved；machine-event 不合格原因只保留固定枚举；
  identity 为 requested-only；VCS 尚无 model-bearing run；结果不构成 benchmark score。

## 验证记录

实现完成后执行：

- `ruff check .`、`ruff format --check .`、schema export check；
- core mypy：214 个 source files 无问题；
- core pytest：1099 passed、1 个真实 Codex opt-in test skipped、52 deselected；
- Codex CLI integration：5 passed，mypy 25 files；
- RTLLM integration：11 passed、4 个 site opt-in tests skipped，mypy 2 files；
- RTL-Repo integration：22 passed、1 个 external test skipped，mypy 4 files；
- Verilog-Eval integration：5 passed、1 个 external test skipped，mypy 3 files；
- Synopsys integration：31 passed，mypy 17 files；
- official RTL-Repo first-row external contract：1 passed；
- launcher 定向回归：9 passed。

正式执行前的完整 plan-only preflight 报告 `planned_codex_processes=6`、`model_calls=0`。
正式 campaign 完成后，独立 `--finalize-existing` 未调用模型，重新校验 frozen plan、六条
authorization、六个 RunConfig、replay、leakage scan 和 redaction audit，并复现相同 summary。

## 后续动作

本 campaign 保持只读，不重试、不生成 benchmark score，也不自动启动 pilot-v2。下一轮应先
以合成、无模型 machine-event fixtures 覆盖本轮保留的 `scoring_event_ineligible` 终态；如需
改变 scoring event contract，必须注册新的 Agent/version 和 campaign，不能回写本轮结果。
