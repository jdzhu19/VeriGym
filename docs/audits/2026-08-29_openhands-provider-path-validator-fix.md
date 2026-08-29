# OpenHands provider path validator 误报修复审计

日期：2026-08-29。范围仅限 provider tool arguments 的 pre-dispatch host-path validator；本次
不恢复已 fail-closed 的 v17 campaign，不重跑 PR-2468，不启动 provider、GPU、SFT 或 held-out。

## 根因

历史 validator 先用 `json.loads()` 得到工具参数，再对每个值执行 `json.dumps()`，最后用同时
匹配 POSIX host roots 与 Windows drive paths 的表达式扫描序列化文本。合法 patch 中的 RTL
case label：

```systemverilog
riscv::CSR_MCOUNTINHIBIT:
```

在重新序列化后以 `T:\n` 结尾，Windows 分支 `[A-Za-z]:\\` 将标签末尾的 `T:` 与 newline
escape 的起始反斜杠误判为 drive prefix。PR-2468 的可见任务要求修改 `mcountinhibit` 读写
行为，且 `core/csr_regfile.sv` 的两个目标 case 均使用该标签；失败 receipt 也将
`apply_patch.patch` 标记为 `raw_host_path`。由于
rejected arguments 按冻结安全策略未持久化，不能还原历史补丁正文，但相同检测表达式对最小
PR-2468 patch 的误报可本地确定性复现。

## 修复

- 有效 JSON 递归扫描 decoded string leaves，不再扫描重新序列化的转义文本。
- 无法解析的 raw JSON 使用独立 escape-aware 表达式；Windows 路径必须在 JSON 文本中包含
  两个反斜杠，因此普通 `T:\n` newline escape 不再误报。
- Provider-visible JSON Schema 仍约束 decoded strings；`additionalProperties=false` 和 exact
  six-tool contract 不变。
- `/home`、`/data`、`/hpc` 与 `C:\\...` 的 pre-dispatch fail-closed 拒绝行为不变。

回归覆盖普通 completion 与一次 required-tool path recovery，使用 PR-2468 形状的
`CSR_MCOUNTINHIBIT:` patch，并分别验证四类真实 host paths 仍被拒绝。该修复不重写 provider
输出、不合成 action，也不改变历史 agent/campaign identity；任何后续采集必须建立新的冻结
身份并重新通过 canary 与数据容量门禁。

## 本地验证

- 定向 tool-schema、普通 completion、path-recovery 与 malformed-JSON 回归：74 passed。
- OpenHands plugin 全量 credential-free、zero-model suite：229 passed。
- Ruff format/check：42 files already formatted，all checks passed。
- strict mypy：24 source files，no issues。

验证未使用 provider credential、Docker、GPU 或 benchmark verifier，也没有写入或修改历史
experiment output。
