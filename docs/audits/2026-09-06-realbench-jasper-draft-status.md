# RealBench / JasperGold 初版实施状态

2026-09-06。**纵向切片尚未完成，也没有 RealBench 分数或商业资格化结果。**
当前交付限于可检查的初版适配代码、无凭据测试和只读站点探测。

## Evidence

| ID | 证据与复现入口 | 观察 |
| --- | --- | --- |
| E1 | [Cadence tests](../../integrations/verigym-cadence/tests/test_sec_contract.py)；按该包 README 执行 pytest | 31 passed：真实 stdio/fake worker、身份漂移、严格状态、隐藏输出、候选边界及 native staging/cleanup |
| E2 | [RealBench tests](../../integrations/verigym-realbench/tests/test_source_projection.py)；按该包 README 执行 pytest | 6 passed：三类合成 module、公开/隐藏隔离、多文件 freeze/offline replay、只读图片篡改、缺失 profile 拒绝、source drift |
| E3 | 两个包的 mypy、ruff，`scripts/export_schemas.py --check`，`git diff --check` | 类型/风格通过，core schema 无变化 |
| E4 | `uv build --offline` 构建两个包；`scripts/audit_optional_plugin_distribution.py` 的 `cadence` / `realbench` policies | 四个 wheel/sdist 均通过数据、商业资产及凭据扫描；未发布包 |
| E5 | 操作者提供站点上的严格 host-key、非交互 SSH 只读探测；站点位置仅在本机交接文件中 | JasperGold 2022.12 安装存在；Yosys 0.44+9；另找到 Python 3.11.9 环境。未部署、未开展许可证资格化、未运行 SEC |
| E6 | [固定上游 catalog](https://github.com/IPRC-DIP/RealBench/blob/9bc9a6ac058b3a3acb09b9e7623526737bbf8312/benchmark_info.py) 与 [LICENSE](https://github.com/IPRC-DIP/RealBench/blob/9bc9a6ac058b3a3acb09b9e7623526737bbf8312/LICENSE) | 核实 60 module / 4 system metadata，冻结 commit、catalog 与 license hash；未下载或解密语料 |

E5 的第三方复现要求操作者持有站点授权；公开仓库不包含连接地址、账号、部署脚本或配置。
默认站点 Python 3.6、Anaconda 默认 Python 3.10 均不满足 VeriGym 要求；已有 Python 3.11
环境使新建全局环境并非必要。发现版本不等于已安装全部运行依赖或已验证兼容性。

共享 verifier-profile / installed-conformance 定向回归另有 16 passed；新增的独立 CI job
仅安装、测试和打包两个 draft integrations，不启用 Docker、真实模型或商业作业。

为生成任务的候选提供 `repository_candidate_workspace_contract` metadata，使 core offline
replay 可以读取已冻结 workspace contract，而不伪造 repair-only golden patch identity。
旧 `repository_repair` 入口及身份保持不变，双重 contract 不一致时拒绝。相关 repository
repair、offline replay、synthesis artifact 回归共 26 passed；core mypy（232 files）通过。

EDA 整合已通过最终全部 CI 并经 [PR #217](https://github.com/jdzhu19/VeriGym/pull/217)
合入主线，merge commit `c4fa86060aa6ce987b44bfff71ca87eb7f282f43`。
本文件对应的 [Draft PR #219](https://github.com/jdzhu19/VeriGym/pull/219) 保持独立，尚不合入。

## Findings

- F1（E1、E3、E4）：JasperGold fixed-profile MCP client/server 和可信 fixture native worker
  已实现。调用者只能提交固定 task/top、候选 bytes/hash 与预期身份；server 拒绝未审核
  candidate hash。profile、worker、server release、版本和私有资产均参与适当的身份检查。
- F2（E1）：仅 `proven` 是 proof success；counterexample、inconclusive、candidate compile
  failure 和基础设施/许可证/工具失败分开。无隐藏 counterexample、waveform、日志或任意
  异常文本回传。每个 server process 最多一个 SEC 作业，无自动重试。
- F3（E2、E6）：RealBench adapter 初版可校验 operator-owned source lock 并投影 Markdown、
  图片与多文件 stubs。synthetic fixture 与真实 pinned source 明确区分；不是完整 adapter。
- F4（E5、E6）：实际 RealBench 解密 checkout 尚未提供。远端隔离 worker 入口未确认。
  上游说明使用 Yosys 0.55，而站点探测为 0.44+9；需要显式选择/冻结兼容版本后再资格化，
  不能悄悄替换工具并声称上游一致。

## Path 与明确剩余项

E6 source 冻结规则 → E2 public-only task projection → **未实现的 public Verilator functional
backend** → **尚未验证的 typed finish 端到端闭环** → E2 的 multi-file freeze / offline replay → E1 的
final SEC transport → **尚未执行的真实 reference / negative-control SEC**。

继续需要操作者提供 RealBench external checkout，以及确认远端执行入口；源码中的
`approved_candidate_hashes` 不能因缺少隔离而直接移除。当前 server 仅适合预先审核的可信
小型 fixture。LSF job cancellation、生成 RTL 的 containment、license 行为和实际 cleanup
均未资格化。不得把这条初版分支标成 production-ready 或完整 module slice。

当前尚未实施：public functional wrapper、真实模型图片消费、原生 syntax/func/formal 指标
聚合、全 60 module / 4 system 扩展，以及 Codex 历史 unsupported-item 修复。旧 Codex
episode 没有保留 raw event stream，因此没有猜测新 allowlist，也没有改写或补跑该结果。
