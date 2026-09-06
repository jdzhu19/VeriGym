# EDA 主线整合检查

本次整合保留历史实验身份；没有重跑商业矩阵，也没有产生新的 benchmark score。
RealBench/JasperGold 的安装探测不等于 suite 或许可证资格化。

## Evidence

2026-09-06，在独立 scratch worktree 中更新远端引用并执行无冲突合并：

- 主线父提交：`642053bd38574f3baae52e61c09caf12dd6d29bc`。
- EDA 父提交：`4d6c48f2127add0db04f28c94ba328209f904957`。
- 合并基点：`c292325bad58d184537cc91a1673486df63eff95`。
- `agent/rtl-agenteval-v1` 是 EDA 父提交的祖先，没有重复合并或选择性移植。
- 原工作树、原虚拟环境和未跟踪 HWE 文件未变更。

本地检查使用 Python 3.12.13，所有商业、外部 benchmark 和 Docker opt-in 均未启用：

| 检查 | 结果 |
| --- | --- |
| `ruff check .` | 通过 |
| `ruff format --check .` | 1,448 个文件通过 |
| `mypy src` | 232 个源文件通过 |
| `python scripts/export_schemas.py --check` | 无 schema 漂移 |
| `pytest -q` | 1,798 passed、1 skipped、54 deselected；另一个测试经环境修复后通过 |
| RTLLM credential-free tests | 125 passed、29 deselected |
| RTLLM mypy | 6 个源文件通过 |
| Synopsys credential-free tests | 47 passed、1 skipped，含环境修复后的定向复测 |
| Synopsys mypy | 27 个源文件通过 |
| `verigym doctor` | 插件可发现；未配置的商业 profile 不作健康或资格化声明 |
| `git diff --cached --check` | 通过，无冲突标记 |

复现插件检查使用各自的 pytest/mypy 配置，例如：

```bash
pytest -c integrations/verigym-synopsys/pyproject.toml \
  integrations/verigym-synopsys/tests -m 'not commercial'
mypy --config-file integrations/verigym-synopsys/pyproject.toml \
  integrations/verigym-synopsys/src
```

## Findings

上述检查覆盖完整 EDA superset 与更新后主线的普通测试、类型及 schema 交界；没有修改
冻结 suite、tool、profile 或 campaign identity。历史商业资格化仍以各自审计为准。
此记录不替代远端 CI 状态。

首次远端 ordinary Python 3.11/3.12/3.13 检查发现旧测试写死了本站 scratch 路径。
仅将该单元测试改为使用 `tempfile` 的默认目录（本站可通过 `TMPDIR` 指定），保留
Unix socket 长度限制和实际目录创建/复用断言。生产 launcher 与冻结身份均未修改。
package、quality、reproducible-build、OpenHands 与 Docker zero-model security 检查已通过。

三类本地环境问题已排除，没有为它们修改已资格化实现：

- 长 scratch 路径超过 Unix socket 长度限制：用短名称的独立 `--basetemp` 定向复测。
- 子进程依赖虚拟环境：将环境的 `bin` 放在 `PATH` 首位，并使用 `venv --copies`
  保证解析 Python 可执行文件后仍使用正确的 site-packages。
- 旧宿主不能安装 CI 的部分 manylinux wheels：本地选用 numpy 2.2.6、pyarrow 20.0.0；
  不修改 Ubuntu CI 的依赖约定。本地结果不是所有支持 Python 版本的覆盖声明。

## Path 与后续边界

更新主线引用 → 独立 worktree 合并完整 superset → 安装该 worktree 的 integrations →
无凭据检查及失败定向复测 → 远端 CI。以上步骤对应本节 Evidence，不涉及商业重试。

RealBench 外部 checkout 尚未提供；远端仅完成 JasperGold 2022.12 的安装/version 探测。
后续必须分别验证固定 profile、负对照、SEC、候选身份、隐藏资产隔离和多轮 finish/replay，
不能从“安装存在”推导“真实 suite 已通过”。
