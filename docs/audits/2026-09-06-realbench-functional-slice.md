# RealBench 真实数据与 functional slice 执行记录

2026-09-06。**数据已准备，三个 module 的 functional 控制已通过；最终 JasperGold SEC
仍未执行，不能宣称 suite-qualified 或原生 benchmark 分数。** 本文接续
[初版状态](2026-09-06-realbench-jasper-draft-status.md)，不改写该初版和失败 invocation 的证据。

## Evidence

| ID | 证据与复现入口 | 已观察结果 |
| --- | --- | --- |
| E1 | 官方 checkout 固定到 `9bc9a6ac058b3a3acb09b9e7623526737bbf8312`；在该 checkout 执行 `git rev-parse HEAD`、`git diff --quiet` | 用户明确授权后下载并解密；72/72 文档已生成，明文合计 1,046,952 bytes；所有 tracked 上游文件不变，加密原件保留 |
| E2 | [prepare.py](../../integrations/verigym-realbench/src/verigym_realbench/prepare.py)；按 [README](../../integrations/verigym-realbench/README.md) 显式准备 | source lock `ae36fb99aebe9ea169abca1adc8e9486538fc4b615b03bb9066e9a002230cdef`；全量资产 inventory `bbc7bf1c80518f9b45ee4a96bb3150f1cb1da03af274b5f6490addebcf0f11e0`，60 module / 4 system 仅作资产盘点 |
| E3 | [独立功能镜像](../../docker/realbench-verilator/README.md)、[opt-in Docker test](../../integrations/verigym-realbench/tests/test_docker_functional.py) | 新镜像补充 C++/make；真实合成 Docker regression 通过；运行使用 network-none 和匹配的非 root UID/GID，旧 lint 镜像未改 |
| E4 | [qualify_public.py](../../integrations/verigym-realbench/src/verigym_realbench/qualify_public.py)；外部 `realbench-functional-slice-v3/qualification.json` | 三题各 reference/function-negative/syntax-negative，共 9/9 符合预期，清理成功；结果文件 SHA-256 `89ecbbaab250049d6e13d460a8b000e1a309060ceb602ba0a5d333e3e0a7dd36` |
| E5 | [scripted public component](../../scripts/realbench_scripted_functional_slice.py)；外部 `realbench-scripted-functional-sbox-v1/progress.json` | 公开规格 → 错误实现 → 真实 functional rejection → 基于公开 GF(256) 数学修复 → pass → diff → typed finish → freeze/offline candidate replay；清理和隐藏资产内容扫描通过 |
| E6 | `pytest -c integrations/verigym-realbench/pyproject.toml integrations/verigym-realbench/tests`；Cadence/shared verifier/repository 回归 | RealBench 37 passed、1 个真实 Docker 测试默认 skip；另有 58 passed、3 个无关 opt-in deselected；core mypy 232 files、Cadence 5 files、RealBench 9 files 通过；schema 0 changed |
| E7 | `uv build --offline` 构建两个 plugin，再执行 `scripts/audit_optional_plugin_distribution.py` 的 `realbench`/`cadence` policy | 四个 wheel/sdist 通过扫描；工具与 console entry point 已纳入打包契约，无 dataset/商业资产随包分发 |

E1–E5 的数据、原始运行目录和 site/client/server profiles 只保留在外部。公开文件只有代码、
可复现入口和内容身份。E4/E5 是零模型组件验证，不是 full orchestrator scorecard；尤其没有
伪造 SEC success 来满足最终 DAG。E5 初次完成记录 SHA-256 为
`3913ed6a7aa28b6c0591bf4d7b98f4f905e6d4346161efc3b3e6ce28b9a25f0c`。

### 三题可见性核对

| Task | 类别 | Agent 可见 | Verifier 私有 |
| --- | --- | --- | --- |
| `aes/aes_sbox` | 组合 | 原规格、2 张图、独立空接口 stub | target/reference RTL、stimulus、checker、SEC template |
| `aes/aes_rcon` | 时序 | 原规格、2 张图、独立空接口 stub | 同上 |
| `aes/aes_key_expand_128` | 层次 | 原规格（含子模块接口）、2 张图、独立空接口 stub | 同上，另含 `aes_sbox`/`aes_rcon` 子模块 RTL |

每题 4 个公开 source assets；没有公开 target solution 或任一其他 slice target 的 golden
实现。层次化 module 沿用上游“生成目标模块、验证器提供依赖”的 contract，不把官方完整
verification 目录挂给模型。图片 bytes 和只读布局已检查；尚未证明真实模型能消费图片。

## Findings

- F1（E1、E2）：数据准备已解除之前的 source blocker。下载命令单独绕过代理，路由检查
  确认为物理网卡；没有关闭 VPN、修改 Docker daemon 或打印/保存代理值。
- F2（E3、E4）：suite-specific public functional MCP 已实现并经过真实小切片控制。
  复用原 public-test controller；保留 test ID `compile`，该 backend 实际同时做 syntax 和
  function。server 固定 image/assets/source order/timeout，候选不指定 shell、flags 或私有路径。
- F3（E2、E4）：上游 hierarchy testbench 的失败行是 `wo_N has …`，而上游 Python 只寻找
  `Hint: Output … mismatches`。本适配显式接受这两种已核对的报告格式，拒绝缺失、重复或
  不一致的 output verdict。它还限制有副作用的 RTL 并隐藏 raw diagnostics，因此属于独立
  VeriGym-derived 设置，不能冒充原生指标。
- F4（E5）：共用环境中的 typed finish、candidate freeze、patch exact reapply、只读资产
  和离线候选证明已通过真实 public 功能反馈链路。脚本修复独立计算 S-box，不把 golden
  交给 agent。离线候选证明不是“离线重做 formal”，没有商业工具或 source checkout 依赖。
- F5（E6）：真实资产暴露出两个初版 runtime 使用错误，已修正并加入 Docker regression：
  session role 必须为现有 `verifier`；容器生成构建目录的 UID/GID 必须允许宿主正常清理。
  C++ 生成/仿真只写 `.verigym_internal`，private sources 保持只读。

### 保留的失败与身份边界

- `realbench-functional-slice-v1` 在 profile/toolchain 预检阶段停止，未派发 candidate；
  原记录 hash `cc3cda33affcda529aa9281fad6b62e403aa8bd2114bff5559f5f058c40efc9b`。
- `realbench-functional-slice-v2` 的第一个 reference 是 infrastructure-invalid，随即停止；
  原记录 hash `9b6600b6ec10aa4b17244ad11c8bc5468a11d8792937c195fc70c178e201f1d3`。
  该记录的 cleanup 字段指外层 candidate staging，不能拿它证明内层 worker 清理成功。
  随后的纯合成 Docker 检查复现 UID 导致的 cleanup failure；定位后仅清理本次两个临时
  staging 残留，未删除失败记录或原始数据。
- v3 使用修正后的非 root 映射完成 9 个控制。没有重写 v1/v2 或自动续跑失败 invocation。
- 完成 E5 后修正了 `PUBLIC_TESTS.md` 遗留的“仅语法检查”文案，并在 task metadata 绑定
  notice hash。新投影会改变 task/server release identity；v3 硬件控制保留原 resolved hashes，
  不把它们改标成新身份，也不因提示文案变化重复整套硬件控制。受影响的 scripted 流程单独
  使用新 profile bundle 和新 output 检查。

提示修正后的 `realbench-scripted-functional-sbox-v2` 也已完成全部七步、candidate replay、
隐藏内容扫描与清理。progress 文件 SHA-256 为
`8906afeac857bcaae8f3b95e1c8b4d66593ca9687034c5b1c19403b0c1b06a88`。新 task hash 为
`f2d4eed75125133dc9d7209ef5c583ad92ac802ffcfbd67a249e59cd17708da5`，S-box resolved public
profile hash 为 `5b96ee9cc3d30f0ebcb1b61605c3f0092a5fe8bb331a80b6cd5c3cfca27096b3`。
这次仅复查受投影修改影响的两个 public calls；E4 的九个硬件控制仍保留在原 v3 身份下。

## Path 与剩余输入

E1 下载/解密 → E2 source/可见性冻结 → E3 隔离工具链 → E4 真实 public functional 控制
→ E5 public multi-turn/typed finish → E5 candidate freeze/offline proof → **待批准的远端
SEC 部署与 reference/negative 验证**。

继续需要操作者确认 HPC 临时固定 worker 的执行边界或提供现有隔离入口。当前 Cadence
仍要求预审 candidate hash；不得移除该限制去执行任意模型 RTL。当前轮没有商业作业、
真实模型调用、全 60/4 扩展、原生 metric aggregation 或历史 Codex episode 重跑。

复现 E4/E5 时，按 integration README 设置已准备 source、独立 bundle、digest-locked image
和新的输出位置；真实 Docker 必须显式 opt in。不要覆盖本文命名的既有 evidence roots。
