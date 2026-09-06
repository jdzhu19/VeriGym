# RealBench SEC 站点预检与许可证阻塞

2026-09-06。**三题 SSH/MCP 预检通过；首个真实 SEC 调用返回 `license_unavailable` 后停止。
没有得到任何 formal proof，不能宣称 site-qualified、suite-qualified 或 benchmark 分数。**
本文接续 [functional slice](2026-09-06-realbench-functional-slice.md)，不覆盖旧证据。

## Scope

用户批准临时固定 worker，只接受 `aes_sbox`、`aes_rcon`、`aes_key_expand_128` 的预审
reference/function-negative，最多六次 SEC 调用、零自动重试、零模型调用。候选 bundle
hash 在 MCP server、native worker 和站点一次性执行记录中再次检查。没有执行模型 RTL，
没有移除 trusted-fixture gate，也没有修改站点全局环境或部署常驻服务。

实际执行一次参考控制，其余五次未执行。旧 public functional 九个控制和 scripted typed
finish/offline candidate proof 保留原身份，未重跑或改标成此次 SEC 结果。

## Evidence

下列文件名相对于操作者外部 evidence/profile 目录；不公开站点地址、账户、绝对路径、
许可证配置值、原始工具日志或 golden 资产。原始商业调用不因阅读本报告而自动重跑。

| ID | 观察与证据 | SHA-256 / 复现限制 |
| --- | --- | --- |
| E1 | `realbench-sec-slice-v1/preflight.json`：入口预检失败，商业调用 0 | `9a4be2bf9b09d4387b046f3f6278d56d1757b73e347335a00f8c51b9be0931f7`；站点只读检查确认 `/etc/profile` 在启动期 `set -e` 下提前退出 |
| E2 | `realbench-sec-slice-v2/preflight.json`：三个固定任务全部 resolve；scratch/process/reservation 均为 0 | `9a2e94d6f65987b57da4b25c9b74066fbfeaf7611b0eb7570bb3a916331858ce`；使用新 profile 身份，未覆盖 E1 |
| E3 | `realbench-sec-slice-v2/manifest.json`：冻结六个候选、源、任务、核心 release 和派生 Tcl | `7e2aa83bef0288476a7cccbba38e7de898ccca809791e67d01b63acc01324a9a`；private 站点部署及候选审计是前置条件 |
| E4 | `realbench-sec-slice-v2/qualification.json`：S-box reference，7.183 s，`license_unavailable`、`candidate_failure=false`；批次 `stopped` | `a0fe50dcf0493cfff07e104d640dbd69325fb3ac691889f4469d0bb7c473c335`；一次调用，无重试，无 proof |
| E5 | `realbench-sec-slice-v2/license-status.json`：只读 `lmutil lmstat -a` 检查；许可证服务器可达，可列出通用 Jasper features | `20a7581c675e79d0c6544206d40cbdb1a0f35296438fac96aa6e4c14eaf4754f`；不 checkout，不公开配置值或使用者信息 |
| E6 | `realbench-sec-slice-v2/deactivation.json`：v1/v2 各四个临时入口已取消执行权限；记录和私有资产保留 | `065656cb8f7ba75985167037479e9fccbc6d0667d45a1dbe157565ab397e6efb`；v2 scratch entries=0、所属工作目录 process=0、reservation=1 |
| E7 | Cadence 单元回归、lint、format、mypy 与 wheel/sdist 内容扫描 | 33 tests passed；5 个 source files typing 通过；两个发布包扫描通过，未发布 |

### 冻结身份

- Source lock：`ae36fb99aebe9ea169abca1adc8e9486538fc4b615b03bb9066e9a002230cdef`。
- 实际工具为 JasperGold `2022.12p001`、Yosys `0.44+9`（git `4b9f45273`），不是上游
  说明的 Yosys `0.55`。JasperGold 补丁号必须完整匹配，不折叠成 `2022.12`。
- Cadence server release：`25ab5a13e867947c3727cfef496eeb9a19fcb16bd8d06de2355fd106ebae5792`。
- 核心部署代码 hash：`1c544def509564dc91188d16d6eacc05ce0e349075fd1f952ba8909f83f62d95`。
- 派生 Tcl：`4cd51087ad8114c2f81b72f1626164a02d97dc9d61693b37f04c74024bc28d0c`；将
  本地 proofgrid 并行上限从 16 降为 2，并让捕获的 Tcl 错误以非零退出。原 template hash
  `de412534168d514a7b4779852cf15789b91e5ebf3b4ff155e457a6ef3fb300a9` 未改写。
- S-box 实际候选 bundle hash：
  `492a491775366b9c39bacd1ee03ace19536297c200a4fdb0eb66b52f122e2aa3`。
- S-box 客户端 resolved profile：
  `ecc1bce844ec330abe2fa0380d217f311b80c155e70d29f65f8c82acd61d8f5d`；服务端 resolved
  profile：`4264c30df3dd9389965e9f1de89b6dfbdb3381cbd21e471f70f146eaacc2d900`。

这是有界、直接启动的 trusted-fixture worker，不是 scheduler/container 隔离资格化。
正常返回后的临时目录和工作目录进程检查，不证明异常断连、超时或生产调度器取消行为。

## Findings

- F1（E1、E2、E7）：修复了 JasperGold `p001` 补丁版本无法识别的问题，并通过原版本与
  补丁版本各自的 positive/negative fake-tool 回归。启动环境错误属于私有站点 wrapper；
  修正后新身份预检通过，没有将预检通过解释成许可证可用。
- F2（E3、E4）：第一次实际 SEC 被归类为许可证基础设施失败，而非 reference 不等价。
  停止后的五个未执行控制不能进入分母或被补成失败/通过。
- F3（E4、E5）：许可证服务器可达和通用 Jasper features 存在，不等于该启动环境具有
  SEC 授权。当前证据不足以区分具体缺少的 feature、版本/授权范围或配置问题；不能据此
  断言“服务器全挂了”或“只是许可证忙”。需要站点管理员确认 SEC entitlement/config。
- F4（E6）：两个临时部署均已停用，未删除失败记录或一次性 reservation。恢复执行需要
  先解决许可证问题，再批准一个新 invocation；不能清空 reservation 或覆盖冻结 v2 证据。

## Path 与下一步

E1 启动预检失败 → F1 新身份修正 → E2 三题 resolve → E3 冻结六个候选 →
E4 首次 SEC license failure → E5 只读许可证状态检查 → E6 停用临时入口。

下一步由站点操作者确认 JasperGold SEC 授权及适用的工具版本/环境；任何配置或工具变化
使用新 profile/release 身份。在新调用获准前，不提交余下控制或重试 S-box reference。
后续仍需真实 reference/negative SEC、完整 orchestrator 最终验证，以及生成 RTL 所需的
独立隔离/取消资格化。当前 PR 保持 draft。

不依赖站点、数据或许可证的代码检查可在仓库根目录复现：

```bash
pytest -c integrations/verigym-cadence/pyproject.toml integrations/verigym-cadence/tests
ruff check integrations/verigym-cadence
ruff format --check integrations/verigym-cadence
mypy --config-file integrations/verigym-cadence/pyproject.toml integrations/verigym-cadence/src
```
