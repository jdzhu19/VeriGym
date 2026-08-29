# OpenHands v18 repaired-validator canary 结果审计

日期：2026-08-29。结论：canary 在第一条 PR-2469 上按轨迹资格策略 fail closed；PR-3204
未运行。修复后的 path validator 没有再次误报，但 PR-2469 没有产生 verifier-pass exact
trajectory。剩余 distinct training capacity 最大为 7，小于目标 8，因此禁止正式 collection、
GPU、SFT 与 held-out A/B。`production_training_ready=false`、
`benchmark_score_claimed=false`。

## 冻结身份与代码门禁

- preregistration PR：[#12](https://github.com/jdzhu19/VeriGym/pull/12)
- preregistration commit：`03cb2904d662775be5d1fee8d563b13e3d3fafa1`
- merge commit / source commit：`5f2bd68a7ba4a729644fe4d3f30713315da10492`
- contract hash：`73841ad308d4db91fbe6c7190a832071bf4b94242bef01f18932e8958f4d3661`
- agent version hash：`6665267375ad40c0c44d5c324aab03a799cc8e3d5b44dda75fcbf1faec9592da`
- campaign：`openhands-hwe-v18-repair-canary-v1`
- seed / sample index：`488` / `4`
- provider retry / episode retry：`0` / `0`

Source commit 的 push run `33234087744` 与 pull-request run `33234090489` 均通过 8 项
Actions：quality、package、reproducible-build、ordinary 3.11/3.12/3.13、OpenHands 3.12 和
Docker external-agent zero-model security。

真实执行前重新验证了 source/task/image locks 和 4 个 Docker image IDs，并完成两任务
Docker zero-call preflight。运行环境采用冻结的 base-plus-overlay 布局：基础环境中的
tiktoken `0.11.0` 满足 LiteLLM `1.93.0` 的依赖声明，进程 `PYTHONPATH` 首位加载 SHA-256 为
`d20b5c6a…c15350` 的 tiktoken `0.7.0` wheel overlay；OpenHands SDK 为 `1.42.1`。所有版本检查
在首次 provider call 前通过。

## PR-2469 唯一 attempt

固定第一条 `training-pr2469-s488` 完成 51 次 provider calls；successful responses 和 usage
records 同为 51，无 provider 或 whole-episode retry。Accounting 完整对应：

- input / output / total tokens：`1,571,441` / `31,622` / `1,603,063`；
- broker tool calls：`50`，其中 command `28`、file read `15`、patch `4`；
- external file write / patch accounting：`4` / `4`；
- broker typed finish：`true`，finish calls `1`；
- rejected calls `0`，broker policy failure 与 infrastructure failure 均为 `null`。

一次 format recovery 和一次 SDK stop continuation 均满足冻结计数：format
count/forced request/validated canonical tool 为 `1/1/1`，continuation 为 `1/1/1`；响应分别是
一个无 text part 的 canonical `read_file` 和一个无 text part 的 canonical `apply_patch`。
Path-policy recovery 全零，说明 repaired decoded-string-leaf validator 没有复现 PR-2468 的
误报。Raw rejected provider arguments、message content 和 private reasoning 均未持久化。

最终 broker 虽观察到 typed finish，但 OpenHands 轨迹资格检查发现 assistant text 出现在非
recovery 或 terminal boundary。Scorecard 因此为 `resolved=false`、model failure、category
`openhands_hwe_training_ineligible`、termination `policy_violation`。Ordinary verifier 未启动，
training trajectory 未 capture/export，候选不能进入 SFT 数据集。Runner 将 schema/path/trajectory
hard-stop 统一封存为 `stopped_infrastructure_or_security_invalid`；该 umbrella status 不表示本次
存在 Docker 或 provider outage。

## 安全、封存与容量结论

Broker private raw-audit manifest 覆盖 50 records、55,582 bytes，secret scan passed；其 SHA-256
为 `a417a43f81dcebbd9f343ea8d2cee870f395d926319a65e4521f26b3ea2e52cd`。停止后对 5 个
OpenHands SDK evidence files 做独立 artifact scan，覆盖 7,894 bytes，hard-secret leaks 与 scanner
errors 均为 0，gate pass。对完整 output 和 launcher log 的 concrete provider-value scan 覆盖
7,258 files、159,531,157 bytes，命中为 0，provider values 未持久化或 hash。

Terminal canary report hash 验证通过：
`13a2d4d54412eedead3d86a0876895b4dcd1e8983514b2541d7b117a930ae1d8`。PR-3204 run directory
不存在，held-out task IDs loaded 仍为 0。

PR-2469 已消耗其唯一允许 attempt 且没有 pass trajectory。已有 3 条 training passes 加上尚未
尝试的 PR-2549、2589、2802、2916，最大只能达到 `3 + 4 = 7`，低于 exact-64K development
SFT 所需的 8 条 distinct training tasks。即使 PR-3204/PR-3168 后续都能通过，也不能修复训练
容量，因此 runner 正确地没有启动 PR-3204。

禁止重跑 PR-2469，禁止改用 PR-2032、PR-2468、PR-3191 或 held-out 补足，也不允许重标历史
trajectory。若未来要继续，必须先增加新的、独立 qualified public training task 容量，并建立
全新预注册与 agent identity；当前计划停在 canary gate，不启动 SFT。

## 关键 SHA-256

- agent version：`60f1c772c7796af72b6559accf82fdaa5088d1cdd7f31f0ca7003b657a84debd`
- canary report：`76f184da954dd333e333aea8b9267d26d29601565bf1ea655d62bdf4f3efeb60`
- scorecard：`603186963396d0306b63e4cc87838ab3ba591b55c85df69b9b0e4ed85adef729`
- accounting：`eb65d5fc6a23d7e0905f637ce5dc7238ce2a2ede78c9e312688373e07e758632`
- broker：`1eb324d5314f38e4f83053caf85f11b018dd62eb0f31d1bd83362a2bc627b79e`
- summary：`20cf9c6f210aa02095e52561cda8719c3ed52da3f51b942ba2a92e79d3990190`
- artifact manifest：`455c330e9e6230a13768004fa66d88ffca2cc136dce21dbd9f6a3e267aabde2c`
- launcher log：`e325063d1f5b140c4bfdfee03986c1ffa04aa68bc58b604f215eb9ea966ed505`

完整 run、private raw audit、patch 和 provider-free evidence 留在 Git 外：
`/data/jzhu484/Agent/experiments/qwen35-hwe-openhands-v18-repair-canary/canary-5f2bd68-s488-v1`。
Git 只提交本脱敏结果审计。
