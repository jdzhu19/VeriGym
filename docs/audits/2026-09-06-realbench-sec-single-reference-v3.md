# RealBench 单次 SEC 复验：工具退出正常，结果收集失败

后续修复与新身份下的通过证据见 [SEC 资格记录](2026-09-07-realbench-sec-qualification.md)。
用户随后授权此类故障自主排障和有界验证，取代下文历史“逐次再批准”的下一步要求；
本次 v3 的 infrastructure failure 仍保持不变。

2026-09-06。**本次获准的一次 `aes_sbox` reference SEC 已执行，最终分类为
`infrastructure_failure`，不是 `proven`。** 两次综合和 SEC 进程均退出 0，但随后发生
`ValueError`，没有成功解析正式结果。没有重试、没有扩大任务集合、没有模型调用。

本文接续 [环境修复与先前尝试](2026-09-06-realbench-sec-site-attempt.md)。原 v2 的许可证
失败记录不变；本次为新的单候选 profile 和新的输出目录，不能改写任一旧结果。

## Evidence

以下文件位于操作者外部目录 `realbench-sec-sbox-envfix-v3`；复现商业调用需要显式授权、
私有站点配置和已审计候选。本报告只提供内容身份和状态，不分发配置、源码或原始工具日志。

| ID | 证据 | SHA-256 / 观察 |
| --- | --- | --- |
| E1 | `preflight.json` | `5b8aee60efa4bfdee07195e377b84da1d4878403a1d92adaf6095bdbb8578687`；一个 profile resolve 成功，调用前 reservation/scratch/process 都为 0 |
| E2 | `qualification.json` | `dc85d345156e754894c80f4ac38c41dbd54cd92c8cdb39d356e8a69efbc01320`；一次 reference，端到端 15.142 s，`sandbox_error` / `infrastructure_failure`，`candidate_failure=false`，无隐藏输出 |
| E3 | `final-site-status.json` | `359b5713964cd44a2b512ae5c247d0ce19c016f87407f87c09089fe22d7f75f9`；阶段回执、两个入口停用、scratch/process=0、reservation=1 |
| E4 | 安装包 `jasper_apps_userguide.pdf`，PDF 第 87、301 页；`jasper_command_reference.pdf`，PDF 第 870 页 | 只读提取显示会话日志位于 `sessionLogs/session_N`，项目目录 `jg.log` 为完整日志入口；文档未证明本次入口的实际文件类型 |
| E5 | [bounded_read](../../integrations/verigym-cadence/src/verigym_cadence/protocol.py) 的离线合成检查 | 普通 `JPW: proven` 文件可读；指向同一临时目录内该文件的链接触发 `ValueError`；临时目录清理完成，商业调用 0 |

E4 的外部摘录记录 `installed-pdf-log-layout.json` hash 为
`361f5bf9eb5ee1fc9a759b785f2b5ebee560656e812583aefb8937444a93457f`。
该记录及安装包文档不随公开代码分发。公开证据的 file hash 可由持有对应外部文件的
操作者使用 `sha256sum` 校验，不要求为核对报告重新执行商业作业。

### 实际阶段

| 阶段 | 耗时（秒） | 退出码 | 超时 / 输出截断 |
| --- | ---: | ---: | --- |
| 参考 Yosys 综合 | 0.318 | 0 | 均否 |
| 候选 Yosys 综合 | 0.267 | 0 | 均否 |
| JasperGold SEC 进程 | 7.430 | 0 | 均否 |

worker 回执确认 `CDS_LIC_FILE` 和 `LM_LICENSE_FILE` 都存在，未记录变量值。版本探测也
退出 0：JasperGold `2022.12p001`，Yosys `0.44+9`。SEC 退出后回执记录 `ValueError`，
没有生成 `sec_diagnostic` / `JPW` 解析记录；不能把退出码 0 解释为 formal proof。

### 冻结身份

- 修复代码 commit：`9210a3fbf077e429e0c95aecf9235ebc18854465`；本轮检查时其全部 CI 通过。
- Server release：`e16bc5771d8aca7cf4101d7f1bc387319e1a28dcdbad6e0a1c6476b258ca153e`。
- Profile ID：`realbench-aes_sbox-sec-envfix-v3`；仅允许一个参考候选，最大调用数 1。
- Server resolved hash：`a4da41fa3d82597db1907533e2eeaa38f1f00e85e140bd7663df00d72c60ac55`。
- Client resolved hash：`490cff3acbb3ab78a7a62e8c77bd6ffa10fed75e11923ff2e5ee1f51a634f4d8`。
- Task hash：`f2d4eed75125133dc9d7209ef5c583ad92ac802ffcfbd67a249e59cd17708da5`。
- Candidate bundle hash：`492a491775366b9c39bacd1ee03ace19536297c200a4fdb0eb66b52f122e2aa3`。
- Source lock 与派生 Tcl 保持先前冻结字节；仅改变明确命名的部署身份、单次限额和阶段回执。

## Findings

- F1（E2、E3）：环境修复确实进入了实际 worker；本次已越过版本探测和两次综合，SEC
  进程也退出 0。但没有可接受的 SEC 结果，因此既不能判 reference 错，也不能确认等价。
- F2（E2–E5）：异常位置与日志读取限制相符。当前 native worker 在读取 `jgproject/jg.log`
  后才调用结果解析，读取函数拒绝任何符号链接、非普通文件和超限文件。链接情形可以
  离线复现；本次回执没有保存实际文件类型、大小或异常消息，故具体触发条件仍未证实。
  安装包文档只能支持会话日志布局，不能代替本次文件状态证据。
- F3（E3）：本轮的一次调用额度已用完，两个临时入口已停用，运行目录和相关工作目录
  进程没有残留；保留的配置、私有资产与一次性 reservation 未删除。未证明异常断连或
  scheduler cancellation 行为，也未扩展到模型生成 RTL。

## Path 与下一步

新单候选配置 E1 → 有许可证环境的 worker E3 → 参考/候选综合 E2 → SEC 退出 0 E2 →
结果收集异常 F2 → 停用入口、保留证据 F3 → 安装包文档和离线读取检查 E4/E5。

下一步应定位并修复结果收集，而不是据当前结果继续推断站点缺许可证。新诊断需在日志
读取前保存**内容无关**的文件类型、大小、是否为链接及固定错误码；不得为诊断公开 raw log，
也不得直接放宽输入资产的 symlink 安全限制。修复后若要重做真实 SEC，应另行批准新
invocation 并冻结新身份。本轮不重复尝试，PR 继续保持 draft，suite-qualified 仍为 false。
