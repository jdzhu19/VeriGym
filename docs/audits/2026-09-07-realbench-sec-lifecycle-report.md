# RealBench SEC 总时限修复与远端生命周期检查

2026-09-07。**已修复每个阶段重复取得完整时限的问题，并用 HPC 假工具验证正常超时及
SSH 中断后的到期退出。本轮商业调用和模型调用均为 0。** 这不是即时远端取消、恶意
后代进程清理或生成 RTL 隔离资格；不覆盖、不重跑[先前七次真实 SEC](2026-09-07-realbench-sec-qualification.md)。

## Scope 与 Evidence

在既有 trusted-fixture 边界内修改时限计算；没有改变候选白名单、协议、输入路径限制、
许可证环境白名单、core runtime 或全局设置。站点能力检查只读；远端测试使用独立临时
目录中的合成 RTL、注释 Tcl 和 Python 假工具，工具入口显式清除两个许可证变量。
测试入口均已停用，回执和一次性 reservation 保留。

| ID | 外部证据或本地检查 | SHA-256 / 观察 |
| --- | --- | --- |
| E1 | `realbench-sec-lifecycle-audit-v1/capabilities.json` | `1c94f30db081e233e7cbd6f12437e291029e689af982ef2b32ed6ab211306f98`；只读能力检查，无容器、namespace 或调度作业启动 |
| E2 | 本地共享 deadline 回归 | 修复前总预算 2 秒仍经过三个 1.1 秒阶段并返回 `proven`；修复后第二次综合超时，不启动 SEC |
| E3 | `realbench-sec-lifecycle-synthetic-v1/qualification.json` | `8f1723852a7045d628a74a82c25aacb59a7f3b9e326fe7a1e3b71fdb048d75c8`；正常超时验证通过；断连注入过早，整体记录 `stopped` |
| E4 | `realbench-sec-lifecycle-synthetic-v2/qualification.json` | `b7440054130964f7ce9de389ecfb3eb546c48e4f224db3178515474c0f5a48c7`；确认综合已开始后中断 SSH，远端按预算退出 |

外部文件可由持有者使用 `sha256sum` 核对。远端复现需要私有 SSH 配置、新的冻结 profile
和独立临时目录；公开报告不分发站点路径、账户、私有包装器、许可证值或原始日志。
假工具内另有短 alarm 作为失效保险，不能据该保险外推商业工具本身的清理能力。

### 观察结果

| 检查 | 时限与结果 | 清理及覆盖限制 |
| --- | --- | --- |
| v1 正常调用 | 共享 4 秒；4.558 秒返回 `timeout`；第二次综合只分到 2 秒，SEC 未启动 | scratch=0，匹配工作目录的所属进程=0 |
| v1 早期断连 | 未取得 verify reservation，也没有 worker 回执 | 不算已测远端运行中取消，不补记为成功 |
| v2 活跃断连 | 观察到综合 `started` 后中断；共享 8 秒，8.463 秒记录 `timeout` | scratch=0，匹配工作目录的所属进程=0；不是即时取消 |

v1 有两次 transport 尝试但仅一次 synthetic verify；v2 有一次新的 transport/verify。
合计两次 synthetic verify、三次 transport 尝试，零商业作业、零模型调用。v1 三个入口和
v2 两个入口均停用，各保留一个 reservation；旧 commercial 入口未重新启用。

## Findings

- F1（E2、E3）：原 native worker 把 `profile.timeout_s` 分别给两次综合与 SEC，另有两次
  version probe；内层总耗时可能超过外层 worker/transport watchdog。现在从 invocation
  开始设置单个 monotonic deadline，每次执行只取剩余额度；到期不再启动后续工具，
  迟到的正常退出也标记为 timeout。验证阶段的版本超时返回 timeout；resolve 的版本
  超时返回 tool unavailable 并停止第二个工具，不能误记为 candidate failure。
- F2（E3、E4）：测试确认了这组固定假工具在 SSH 中断后仍会自行到期并清理。其机制是
  deadline，不是取消信号传播。因此不能声称 SSH 断开即停止商业作业，也不能证明
  setsid/chdir 后代、监督进程被杀或调度器取消场景；应使用容器/cgroup 级作业归属。
- F3（E1）：当前账户能访问 Docker daemon，报告有 seccomp；不是 rootless/userns 模式。
  `max_user_namespaces=0`，cgroup v2 不可见、cgroup root 不可写；未发现 bwrap、Podman、
  Apptainer 或 Singularity。命令存在不等于隔离资格，也不能将 LSF 命令存在当成已获调度
  作业/安全边界授权。可优先评估专用 Docker 入口，但实际部署是需要明确批准的新边界。

新 Cadence release 为 `3b15713a3841564acdda492ee253494e50c6d1611d223d05e5aac2f3dc6847ba`。
先前真实 SEC 证据仍绑定 `fb83af49…` release，不把这次 synthetic 检查写成新商业 proof。
保留 profile/transport/release 身份，不覆盖旧配置。

## Path、检查与下一步

E1 只读能力检查 → E2 复现迟到 proof → 共享 deadline 修复 F1 → E3 正常超时通过、断连
未覆盖 → 新单次配置等待活跃回执 → E4 中断 SSH、最终到期退出 → 停用测试入口。

从仓库根目录、已安装 Cadence 插件的开发环境运行：

```bash
pytest integrations/verigym-cadence/tests tests/unit/test_verifier_profiles.py -q
ruff check integrations/verigym-cadence
ruff format --check integrations/verigym-cadence
mypy integrations/verigym-cadence/src
```

本地首轮 61 passed；新增的 probe/verify 版本超时分支另有 2 passed。lint、format 和
5 个 source files typing 通过。文档/示例契约 1 passed；Cadence wheel/sdist 分发审计、
公开文件站点标识检查、相对链接和外部证据 hash 核对通过。范围未影响 RealBench public
functional 后端，不重跑其矩阵。

下一阶段建议为此项目新建专用 Docker SEC 隔离入口：固定非 root 用户、只读工具/输入、
有限工作目录和资源、无 Docker socket/用户 home、明确的容器级取消与清理，并单独设计
仅允许许可证所需通信的网络边界。先做无许可证隔离检查，再验证商业工具兼容性；通过
前保持候选白名单、不接受任意模型 RTL。不得以 host network、privileged 或放宽共享
DockerRuntime 的 network-none 策略临时凑通。该部署尚未获批、尚未执行，PR 保持 draft。
