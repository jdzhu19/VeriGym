# RealBench SEC 日志修复与三题控制资格检查

2026-09-06 至 09-07。**三题的 reference / function-negative 共六个 SEC 控制均符合预期。**
这是固定候选、固定站点路径的正负控制证据，不是全量 RealBench 支持、模型成绩或任意 RTL
执行的隔离资格。历史 [v3 结果收集失败](2026-09-06-realbench-sec-single-reference-v3.md)
和更早的许可证失败记录保持不变。

用户已明确授权此类启动、环境和结果收集故障的自主诊断、修复与有界后续验证。每次失败
仍停止所属批次，保留证据；不盲目重试、不重用 reservation、不改变已冻结身份。

## Evidence

外部文件可由持有者使用 `sha256sum` 核对。重现真实 SEC 需要已审计候选、私有站点配置和
新的有界调用授权；阅读报告或离线核对证据不需要再次运行商业工具。

| ID | 外部证据 | SHA-256 / 观察 |
| --- | --- | --- |
| E1 | `realbench-sec-sbox-logfix-v4/qualification.json` | `8e90bd3242616fc416e0da6ada012957e04f1194f8457983acf8691b533487fc`；一次 S-box reference，`proven`，13.041 s |
| E2 | `realbench-sec-remaining-controls-v5/qualification.json` | `444ad06e49badfb3ca14ab1c47c5f9e6a410a0c0ba18fa7be7a61d411b28a07c`；剩余五个控制全部符合预期 |
| E3 | 本地 `test_sec_contract.py` 日志链接回归 | 接入修复前 4 个模拟 native flow 失败，均为 `symlink asset is forbidden`；接入后 Cadence 与 shared verifier 共 57 passed |
| E4 | `realbench-scripted-sec-sbox-v1/progress.json` | `e92379901327a692812fec8cb243967e67d1611f7d184e0e781fa0c8c28524d6`；完整 orchestrator 返回 `proven`，无 infrastructure error |
| E5 | `realbench-scripted-sec-sbox-v1/post-run-check.json` | `a4e0c6f8b85a4e3e08e0cf9770882247c9c181a86dc343492342e1a0e1e5b774`；离线回放与真实事件顺序核对通过，新增 verifier 调用 0 |
| E6 | `realbench-sec-scripted-sbox-v6/final-site-status.json` | `9d7de2d09e9313cd2c9daa9b4f9407c2edf46209ada7f4d124ad2f9075159a08`；SEC 显式 `proven`，5.977 s，两个入口停用、scratch/process=0、reservation=1 |

### 实际 SEC 结果

| 模块 | Reference | Function-negative | 配置 |
| --- | --- | --- | --- |
| `aes_sbox` | `proven`，13.041 s | `counterexample`，12.739 s | reference 为 v4；负例为 v5 |
| `aes_rcon` | `proven`，12.748 s | `counterexample`，12.941 s | v5 |
| `aes_key_expand_128` | `proven`，24.923 s | `counterexample`，13.091 s | v5 |

耗时为端到端秒数。v4 与 v5 使用不同 profile/plan 身份，但相同插件 release、工具、源和
派生 Tcl；没有重跑 v4 已通过的 reference 来拼凑同一批次。所有负例均为 candidate failure，
没有把基础设施故障当成候选错误。客户端没有返回原始日志、counterexample 或隐藏资产。

- JasperGold：`2022.12p001`；Yosys：`0.44+9`。
- Source lock：`ae36fb99aebe9ea169abca1adc8e9486538fc4b615b03bb9066e9a002230cdef`。
- Cadence release：`fb83af4945771c4e758efeca78ad05b7115e37e554511db7d629408fbf802bb1`。
- 派生 Tcl：`4cd51087ad8114c2f81b72f1626164a02d97dc9d61693b37f04c74024bc28d0c`；未改变 formal 判定语义。
- v4/v5 最大调用数分别为 1/5，实际分别为 1/5；均零自动重试、零模型调用。
- 完成后 v4 两个入口、v5 四个入口均取消执行权限；各自 scratch/process=0，
  reservation 分别为 1/5。配置、私有资产和 reservation 保留，不删除历史证据。

## Findings

- F1（E1、E3）：实际 `jgproject/jg.log` 是项目内部符号链接；其目标为单链接普通文件，
  大小 12,657 bytes。旧输入资产读取器拒绝这种日志入口。新 reader 成功读取后，仅接受
  明确的 `JPW: proven`。v3 没有留下文件元数据，不能补写成当时已确认根因或取得 proof。
- F2（E1、E2）：许可证环境传递与工具日志读取已在真实任务路径上验证可用；三题正负
  控制确认当前工具/template 组合可判定预审候选。该结论不外推至其他 feature、版本或任务。
- F3（E1–E3）：修复只影响 verifier-owned 输出；候选/site asset 的 `bounded_read` 未改变。
  日志目标必须留在本次非 symlink 项目内，拒绝越界、悬空、循环、硬链接、特殊文件和超限。
  单独 reader 使用有界读取及非阻塞、禁止最终 symlink 跟随的打开方式。native worker
  仍为 trusted-fixture-only，不是生成 RTL 的安全沙箱。
- F4（E4–E6）：共享 orchestrator 的 scripted 正式提交路径已闭合。公开数学生成器只生成
  一个 256-entry case 表模块，审计确认无系统调用、directive 或其他模块，且字节与先前
  functional 修复候选一致。新 v6 profile 仅批准该确切哈希，不批准其他模型生成 RTL。

### 完整 scripted orchestrator

使用 [独立 opt-in 脚本](../../scripts/realbench_scripted_sec_slice.py)，固定 seed=0、sample=1、
model calls=0、最大 SEC=1；本次实际 SEC=1，加上 E1/E2，本轮总计七次新商业调用。
agent `realbench-scripted-sbox-sec-v1` / `1.0.0` 不使用模型，repair 从公开 GF(256) 定义计算。

- 执行脚本 hash：`fb624299531c103f424145321524970297198ccae14e8cd01c83c673d72b9a46`。
- 候选 file hash：`c476d345bb9dcd1179f053dbd5a52dfa47a37fe1646f528fd689987bbe886f46`。
- 候选 bundle hash：`6e1cb6d3155f1d4c1825e06cb143a800eca7b156afd55bcabb0c6983a4d4d8fa`。
- SEC client resolved：`4098579d75fe98f6fd8c266261b5ad5249cc49b5dcb65630fda262d25611d0a7`。
- Public profile resolved：`5b96ee9cc3d30f0ebcb1b61605c3f0092a5fe8bb331a80b6cd5c3cfca27096b3`。
- 基础 task hash 保持 E1 的身份；绑定最终 verifier 后 task hash 为
  `f2a4742e7c901bc830fe067ec7506019d834d4ee5a9658009b2d7478032916e1`，没有覆盖原 task。

E5 核对 trace：序号 16 功能 `test_failed` → 28 功能 `success` → 37 `final_submission`
→ 39 `repository_candidate_frozen` → 41 `verifier_started` → 最终 SEC `proven`。
`repository_public_tests` 旧字段在 profile-backed 路由中为空，不能据此断言没有 public
checks；实际两次结果来自 ordinary `tool_result` 事件。冻结 run 没有修改，补充检查单独保存。

完整 trace hash：`482662bd48b95a734ec9a2818e7af4c97254473a69c3095aacdfaa6d0839ef7a`；
scorecard hash：`fa2ac0b4ba06d13a082c6928bf435d1dced30201fd70a213fb3eb55fbcb65a65`。
`replay_run(..., verify=False)` 验证 artifact integrity 和候选重放，不启动 agent/model/SEC。
冻结候选与审计字节一致，完整隐藏资产字节泄漏扫描通过；formal `ToolResult` 的
stdout/stderr/artifacts/diagnostics 均空。core 正常生成的 request/result JSON 和零字节 log
文件不等同于返回了原始商业工具日志。Docker 与远端成功路径清理均通过。

## Path 与复现检查

历史失败 → 离线日志链接回归 E3 → 仅修复固定日志入口 → 新 v4 reference E1 →
确认实际日志布局 F1 和显式 proof → 原三题剩余五个控制 E2 → 清理并停用临时入口。

从仓库根目录、已安装插件的开发环境运行，无需商业资产或凭据：

```bash
pytest integrations/verigym-cadence/tests tests/unit/test_verifier_profiles.py -q
pytest integrations/verigym-realbench/tests -q
ruff check integrations/verigym-cadence integrations/verigym-realbench scripts/realbench_scripted_sec_slice.py
ruff format --check integrations/verigym-cadence integrations/verigym-realbench scripts/realbench_scripted_sec_slice.py
mypy integrations/verigym-cadence/src integrations/verigym-realbench/src scripts/realbench_scripted_sec_slice.py
```

当前检查：57 passed；RealBench 42 passed / 1 个 opt-in Docker test skipped；lint、format、
15 个 source files typing 通过。Cadence wheel/sdist 内容审计通过，未分发商业资产。
原 functional 九例不受日志修改影响，复用原冻结证据，不重复执行。

剩余资格边界：生成 RTL 隔离及远端异常取消、
真实模型读取图片、全 60-module/4-system 扩展和原生指标聚合；PR 保持 draft。
