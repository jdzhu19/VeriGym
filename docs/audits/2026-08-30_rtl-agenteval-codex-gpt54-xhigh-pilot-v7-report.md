# RTL AgentEval Codex qualification v6 and pilot v7 audit

> 结论：RTL-Repo v3 修复通过 3/3 资格测试，随后完整执行了一轮新的 14-run。
> 14/14 进程、typed `finish`、provider usage、唯一身份观察、replay 和安全审计均完整；
> 11/14 candidates resolved，另外 3 项是普通 RTL-Repo Exact Match verifier rejection。
> `pilot_complete=true`，但 `fully_successful=false`；本结果不是 benchmark score。

原始实验、数据集、商业资产和运行轨迹保留在仓库外。仓库只记录冻结身份、聚合终态、
脱敏证据哈希和不含 target/candidate 内容的结构审计。资格测试和 pilot 均为每项一次真实
Codex CLI 进程，自动重试为 0，未替换模型。

## 修复依据

失败的 v10 资格样本把目标行之后的文件后缀压成一个候选物理行。上游
[RTL-Repo paper](https://arxiv.org/abs/2405.17378) 将任务定义为根据完整 repository context
与当前文件目标行之前的内容预测目标单行；[RTL-Repo repository](https://github.com/AUCOHL/RTL-Repo)
和 [TuRTLe](https://github.com/HPAI-BSC/TuRTLe) 的集成同样将其作为 single-line completion。
因此修复没有读取 hidden target，也没有修改官方 scorer，而是新增独立 projection
`official-parquet-v1-agent-eval-v3`，冻结 `immediate_next_physical_line_v1` 契约：只写第一条
缺失的物理源码行，不拼接、压平或包含后续行。

Codex typed MCP 的 direct exposure 与 JSONL eligibility 修复则依据
[non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode) 和精确
`rust-v0.147.0` 源码中的
[JSONL event projection](https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/exec/src/event_processor_with_jsonl_output.rs)
及 [exec event types](https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/exec/src/exec_events.rs)。
Agent v10 通过 `omit_tools_from=["deferred"]` 冻结六个 broker tools 的 direct MCP surface；
broker 的 canonical tool sequence 与 accepted finish index 是评分资格的权威证据，server label
只作为 bounded advisory metadata。

## 冻结身份

| 项目 | 值 |
| --- | --- |
| Qualification | `rtl-agenteval-codex-gpt54-xhigh-nextline-qualification-v6` |
| Pilot | `rtl-agenteval-codex-gpt54-xhigh-pilot-v7` |
| Agent | `codex-cli-agenteval-gpt54-xhigh-v10` |
| Agent version hash | `47673eb65a0595944eb622c6f8d8c66df7502e19d2616d03470f08410bfd71b9` |
| Prompt contract / hash | `repository_action_v2_prompt_v6` / `fe8bc9e5f2e3b91443bb9130e51b4de7cde4be5fe9d2b4ba97bc16417d0b2e79` |
| Tool-policy fingerprint | `0b2c999374b827b9023bec19c2e5eaed6676893a91a1769ac9de1e1d3d5ba643` |
| Model / reasoning / seed | GPT-5.4 / `xhigh` / 0 |
| Codex CLI | `codex-cli 0.147.0` |
| RTL-Repo projection | `official-parquet-v1-agent-eval-v3` |
| RTL-Repo suite revision | `rtl-repo-official-context-projection-agent-eval-v3` |
| Completion contract | `immediate_next_physical_line_v1` |

全部 17 个正式进程（qualification 3 + pilot 14）各有且仅有一个 identity observation。
pilot 的 14 个 identity 均为 `requested_only`，`observed_model_id=null`；不得声称 provider
confirmed model identity。14/14 provider terminal usage 完整，没有估算 token。

## Qualification v6

| Run | 结果 |
| --- | --- |
| `01-counter-open` | resolved；compile 通过；candidate PPA 合法且 final eligible |
| `02-rtl-repo-test-000003` | resolved；官方 Exact Match 通过 |
| `03-rtl-repo-test-000004` | resolved；官方 Exact Match 通过 |

聚合：3/3 resolved、3/3 typed `finish`、3/3 usage complete、3 个唯一 identity、0 retry、
0 timeout/policy/infrastructure failure。`pilot_v7_authorized=true`。原先失败的 test-000003
候选为 20 UTF-8 bytes、一个换行、以换行结尾；结构审计确认没有后缀拼接。

## Pilot v7

| Suite / 路径 | Runs | Resolved | Typed finish | 结果 |
| --- | ---: | ---: | ---: | --- |
| RTLLM + OpenSTA/DC | 4 | 4 | 4 | 4/4 compile；4/4 合法 candidate PPA 与 final PPA eligible |
| VerilogEval | 5 | 5 | 5 | 全部 compile 并 resolved |
| RTL-Repo v3 | 5 | 2 | 5 | `000039`、`000069` 通过；其余 3 项 Exact Match rejection |
| 合计 | 14 | 11 | 14 | 14/14 进程与证据完整；0 infrastructure failure |

最终状态：

- `pilot_complete=true`、`infrastructure_complete=true`；
- 14/14 processes started，14/14 provider observations，14/14 typed `finish`；
- 14/14 provider usage complete，14/14 unique identity observations；
- 0 automatic retry、0 timeout、0 policy failure、0 infrastructure failure；
- offline replay `all_valid=true`，exact leakage scan 与 redaction audit `passed=true`；
- 11/14 resolved；`fully_successful=false`、`benchmark_score_claimed=false`。

3 个 rejected RTL-Repo candidates 分别为 25、1、14 bytes；每个恰有一个换行并以换行结尾。
这证明 v3 的单物理行结构契约生效，rejection 是正常候选 Exact Match 结果，不是先前的多行后缀
压平、MCP eligibility、timeout 或基础设施回归。campaign 保持只读，不重试这些样本。

## 脱敏证据

所有路径均相对于仓库外 qualification 或 pilot 根目录。

| Evidence | Qualification SHA-256 | Pilot SHA-256 |
| --- | --- | --- |
| `plan.json` | `44699446ab2caa1bf33de1571d277d3a681184180c2e89043422f77d1157e1eb` | `0d9f12e5e5f68554d69ec885974198af8602e589bb13a5107667cd1e56604a1e` |
| `evidence/process-authorizations.json` | `d1a385c06007d51a9080c48c2246ec2d4987f1baadb49032a69a6b554b39d64c` | `b7a14c79c200efeb0df894f123207b094a64e9a302ab5ebf4d83f9da70c21d7b` |
| `replay.json` | `e5e027479f9bc54c8bdfbc2cc861d48904a87d54f7a992ff8de4859068869dba` | `48abd19c578cf4dcb330cfb15c09dc632f7ca82f72a94b20589f5c9d232db12f` |
| `security-scan.json` | `1cc2d895955cdb1bc154399b5950fbd5ee7af45ef3a2ba633148b3ee7dfc1ce7` | `1cc2d895955cdb1bc154399b5950fbd5ee7af45ef3a2ba633148b3ee7dfc1ce7` |
| `redaction-audit.json` | `d1b725dd3cde98dabaa356ae8795e9a6a6ff63d5a1394f2a29f3c7c26bcc49e8` | `70eca675ae205d5c3b69a321418469624ef72a41322725601f3e8ee9357160cc` |
| `summary.json` | `7dc5b0306fc26d6b3eae29e71bbdc9af5e30e57d2cb04da18c49ee920038a59f` | `de8ba31c0b51a98ae9cfd53aa5b680e4885d0f27aa0675a717dc80f0560f779e` |

独立 `--finalize-existing` 没有调用模型，重新校验 frozen plan、predecessor receipt、全部
RunConfig hash、process ledger、offline replay、leakage scan 和 redaction audit，并复现同一
summary。launcher 返回 2 是因为 `fully_successful=false`，不表示 pilot 未完成。

## 验证记录

- `ruff check .`、`ruff format --check .`；
- core mypy：214 source files；
- root pytest：1144 passed、1 个真实 Codex opt-in test skipped、52 deselected；
- Codex CLI integration：5 passed，mypy 25 files；
- RTLLM integration：11 passed、4 个 site opt-in tests skipped，mypy 2 files；
- RTL-Repo integration：24 passed、1 个 official snapshot opt-in test skipped，mypy 4 files；
- VerilogEval integration：5 passed、1 个 official checkout opt-in test skipped，mypy 3 files；
- Synopsys integration：31 passed，mypy 17 files；
- 定向 launcher、broker、scoring、projection 回归：146 passed，1 deselected；
- qualification v6 与 pilot v7 的正式执行已实际覆盖 Codex CLI、RTLLM、RTL-Repo、
  VerilogEval、OpenSTA、DC/MCP 和 VCS/MCP preflight。

## 结果边界

本轮已经满足“完成一轮新的 14-run”，但不是 14/14 resolved。不得把 11/14 写成 benchmark
score，也不得重试、替换模型或回写本 frozen campaign。VCS/MCP 仍只做无模型
reference/known-bad preflight；若要证明 model-bearing VCS，应另建独立冻结 campaign。
