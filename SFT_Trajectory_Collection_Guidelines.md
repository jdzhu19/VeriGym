# SFT Trajectory Collection Guidelines for Repository-Level Agents

> 适用范围：VeriGym / HWE-Bench / RTL-Repo 等 repository-level agent 任务
> 目标：在不破坏行为因果链的前提下，降低 tool observation 对 SFT 上下文、显存和训练吞吐的占用。

---

## 1. 背景与问题定义

Repository-level repair agent 的轨迹通常包含：

- `system` / `user` 指令；
- assistant 的工具调用；
- 工具 observation；
- assistant 最终回答或 patch；
- 可选 verifier / reward 信息。

在实际轨迹中，tool observation 往往占绝大多数 token。例如：

- 工具 observation：46,266 / 48,815，约 **94.8%**
- assistant tool-call + final answer：1,528，约 **3.1%**
- system / user：约 **2.1%**
- 共 22 次工具调用、8 次文件读取

这种分布本身并不意味着轨迹错误。Repository repair 本来就要求模型读取源码、目录、diff 和测试结果；同时 private reasoning 不应导出。

真正需要解决的问题是：

> **被 mask 的 observation 虽然不计算 SFT loss，但仍然参与 Transformer forward，继续占用上下文长度、显存和计算量。**

因此，优化重点不应只是 loss masking，而应从 **trajectory collection / tool design 阶段主动控制 observation 大小**。

---

## 2. 参考工作中的共同做法

### 2.1 R2E-Gym

R2E-Gym 对 repository agent 的工具输出进行了明显的 context-saving 设计：

- rollout 默认限制最大 step 数；
- 目录浏览限制深度，而不是一次递归输出整个仓库；
- 长 Python 文件自动进入 concise view；
- 支持按 `view_range` 精确读取局部代码；
- 单次工具输出有硬长度上限；
- SFT 配置使用约 20K token 的 cutoff。

最值得借鉴的是其基本交互模式：

```text
search / shallow tree
        ↓
locate relevant file
        ↓
concise file view
        ↓
targeted ranged read
        ↓
edit / test
```

而不是：

```text
recursive repo dump
        ↓
full-file dump
        ↓
LLM 自己从海量文本中寻找信息
```

---

### 2.2 SWE-Gym

SWE-Gym 的公开设置体现了几个重要原则：

- SFT 使用固定最大 sequence length；
- input / observation 不参与监督 loss；
- 使用 packing 减少 padding 浪费；
- 成功 trajectory 之间倾向保留更短、更少 response rounds 的轨迹；
- repository-level 成功轨迹通常远短于 50K raw tokens。

因此：

> **成功轨迹不应被等价保留。成功且更短的行为路径通常更适合作为 SFT demonstration。**

---

### 2.3 DeepSWE / rLLM

DeepSWE / rLLM 采用 observation masking，但同时强调：

- long observation 会持续膨胀 prompt；
- trajectory 需要受 max prompt / response / turns 等限制；
- overlong、timeout、max-turn 等 termination 可以作为 filtering 条件；
- 训练 context 和推理 context 不必相同。

这说明：

> **Observation masking 是必要条件，但不是 trajectory compression 的替代品。**

---

### 2.4 ChipSeek

ChipSeek 的公开 SFT 数据更接近 reasoning cold-start / instruction-output 数据，而不是 repository-level multi-turn tool trajectory。

因此它对本问题的直接参考价值有限。对于 repo-agent 的 observation 膨胀问题，应优先参考 R2E-Gym、SWE-Gym 和 DeepSWE / rLLM。

---

# 3. 推荐的 VeriGym Trajectory Collection Policy

## 3.1 总体原则

推荐采用以下流水线：

```text
Teacher / Agent rollout
        ↓
Verifier validation
        ↓
Success trajectory
        ↓
Observation-aware normalization
        ↓
Length / quality filtering
        ↓
Assistant-only loss masking
        ↓
SFT dataset
```

核心原则：

1. **保留真实行为因果链**
2. **不导出 private reasoning**
3. **工具 observation 默认有界**
4. **优先 progressive disclosure，而不是一次返回完整上下文**
5. **成功轨迹中优先保留短路径**
6. **训练 context 与 inference context 可以不同**

---

# 4. Tool Observation Contract

## 4.1 `list_files`

### 不推荐

```text
list_files(path=".", recursive=true)
```

直接递归整个 repository。

这种行为很容易一次产生数千到上万 token，而且大量内容对当前决策无关。

### 推荐

默认：

```text
list_files(
    path=".",
    max_depth=2,
    max_entries=200
)
```

建议默认忽略：

```text
.git/
node_modules/
build/
dist/
target/
__pycache__/
.cache/
vendor/
third_party/
generated/
```

具体是否忽略 `third_party/`、`generated/` 应由 benchmark contract 决定。

如果结果超过限制：

```text
<truncated>
423 additional entries omitted.
Inspect a specific subdirectory with list_files(path=...).
```

### 目标

让模型学习：

```text
先定位目录
→ 再展开目标子目录
```

而不是依赖完整 repo tree。

---

## 4.2 `read_file`

### 小文件

对于较短文件，可以直接返回全文。

例如：

```text
<= 150–250 lines
```

阈值可以按语言调整。

---

### 大文件

大文件默认不应直接返回全文。

推荐：

```text
read_file(path="rtl/core.sv")
```

返回 concise view：

```text
1   module core #(
2       parameter WIDTH = 32
3   ) (
4       input logic clk,
5       ...
6   );

20  // declarations
...
42  always_ff @(posedge clk) begin
    <35 lines omitted>
76  end

90  always_comb begin
    <48 lines omitted>
139 end

160 assign ready = ...

181 endmodule
```

然后允许：

```text
read_file(
    path="rtl/core.sv",
    start_line=40,
    end_line=100
)
```

定点展开。

---

## 4.3 RTL / Hardware 文件的 concise view

对 Verilog / SystemVerilog 建议保留：

- `module` / `interface` / `package`
- parameter / localparam
- port declarations
- typedef / struct / enum
- signal declarations
- instance names及模块类型
- `always_ff`
- `always_comb`
- `always_latch`
- continuous `assign`
- function / task signature
- generate block
- assertion / property 位置
- 原始 line number

长 block body 可以折叠：

```text
always_ff @(posedge clk) begin
    <37 lines omitted; use read_file(..., start_line=84, end_line=125)>
end
```

建议优先使用：

- Tree-sitter
- Slang
- Surelog/UHDM
- lightweight parser

来实现结构感知的 concise view。

---

# 5. Search Contract

搜索结果必须有界。

例如：

```text
search_code(
    query="state_q",
    top_k=20
)
```

建议返回：

- 文件路径；
- 行号；
- 命中行；
- 少量上下文。

不推荐一次返回：

- 所有命中；
- 每个命中几十行上下文；
- 整个文件。

推荐流程：

```text
search
→ identify candidate
→ ranged read
```

---

# 6. Shell / Test Observation

测试日志同样容易造成 trajectory 膨胀。

建议默认保留：

- command；
- exit code；
- failure summary；
- failing test names；
- relevant stack trace；
- stderr tail；
- verifier result。

例如：

```text
pytest: 214 passed, 3 failed

FAILED tests/test_decode.py::test_branch
FAILED tests/test_decode.py::test_jump
FAILED tests/test_pipeline.py::test_flush

Relevant traceback:
...
```

不要默认保存数千行成功测试日志。

如果日志被截断，应显式标记：

```text
<output truncated>
Original output: 18,432 lines
Showing failure-focused summary.
```

---

# 7. Diff Observation

Diff 通常对 repair 轨迹非常关键，因此不能简单删除。

推荐：

1. 小 diff 全量保留；
2. 大 diff 按文件拆分；
3. 优先显示 modified hunks；
4. 对 generated file / lock file 设置特殊策略；
5. 超限时保留文件列表 + hunks 摘要，并允许进一步请求单个文件 diff。

---

# 8. Tool Output Hard Limit

所有 observation 建议设置硬上限。

推荐初始值：

| Observation 类型 | 建议默认上限 |
|---|---:|
| directory listing | 1K–2K tokens |
| code search | 1K–2K tokens |
| file view | 2K–4K tokens |
| test / shell | 2K–4K tokens |
| diff | 4K–8K tokens |

这些不是 benchmark 标准，而是建议的工程初始值。

如果达到上限：

```text
<truncated>
Use a narrower query or line range to inspect the omitted content.
```

禁止 silent truncation。

---

# 9. SFT Sequence Length

建议将 repository-level SFT 的目标 sequence length 首先控制在：

```text
20K–32K tokens
```

理由：

- R2E-Gym SFT 使用约 20K cutoff；
- SWE-Gym 使用 32K 级别配置；
- repo agent 的 inference context 可以明显高于训练 context；
- 超长 raw trajectory 会显著降低训练吞吐。

注意：

> 不要直接从右侧粗暴 truncate。

因为右侧通常包含：

- patch；
- final answer；
- verifier conclusion；

这些往往是最重要的监督信号。

---

# 10. Loss Masking

推荐：

```text
system           mask
user             mask
tool observation mask
assistant action train
assistant final  train
```

即：

```text
loss only on model-generated assistant tokens
```

但是必须明确：

> **mask 只决定哪些 token 计算 loss，不会让 observation token 从 Transformer context 中消失。**

因此 observation compression 仍然必须在数据生成阶段完成。

---

# 11. 成功轨迹筛选

同一 task 有多条成功 rollout 时，不应随机等价采样。

推荐排序优先级：

```text
1. verifier passed
2. policy compliant
3. no infrastructure error
4. no overlong termination
5. fewer tool calls
6. fewer assistant rounds
7. fewer total tokens
8. smaller observation / assistant token ratio
```

例如：

```text
A: success, 21 tool calls, 43K tokens
B: success, 12 tool calls, 24K tokens
C: success, 35 tool calls, 61K tokens
```

优先：

```text
B > A > C
```

但不能只以长度作为唯一指标，因为某些复杂任务本身需要更多探索。

---

# 12. Observation Efficiency Metrics

建议在数据集统计中新增：

```text
total_tokens
assistant_tokens
observation_tokens
tool_calls
file_reads
search_calls
shell_calls
max_single_observation_tokens
observation_to_assistant_ratio
tokens_per_success
```

其中：

```text
observation_to_assistant_ratio
    = observation_tokens / assistant_tokens
```

例如当前轨迹：

```text
46,266 / 1,528 ≈ 30.3
```

意味着：

> 每产生 1 个被监督的 assistant token，需要处理约 30 个 observation token。

这个指标非常适合用于发现异常臃肿轨迹。

---

# 13. 对现有 48K Trajectory 的处理

不建议直接删除原始 observation。

例如原始轨迹：

```text
read_file(...)
→ observation 中出现第 812 行 bug
→ assistant 修改第 812 行
```

如果后处理成：

```text
read_file(...)
→ [observation removed]
→ assistant 修改第 812 行
```

就破坏了行为因果关系。

---

## 推荐方式

保留：

```text
raw trajectory
```

另外生成：

```text
normalized / compact trajectory
```

流程：

```text
raw trajectory
        ↓
deterministic observation compactor
        ↓
compact trajectory
        ↓
quality validation
        ↓
SFT
```

### 示例

#### Repository tree

```text
10K-token recursive tree
```

压缩成：

```text
depth-2 tree
<truncated: 423 additional entries>
```

---

#### 大 RTL 文件

```text
900-line SystemVerilog file
```

压缩成：

```text
module skeleton
+ declarations
+ relevant always blocks
+ line-number-preserving omitted regions
```

---

#### 测试输出

```text
8,000-line pytest / simulator log
```

压缩成：

```text
exit code
+ failing tests
+ relevant error
+ stack trace
+ short tail
```

---

# 14. Training / Inference Consistency

最理想的情况是：

> **训练时使用的 observation policy 与未来 inference 时 agent 实际看到的工具 contract 一致。**

例如训练时：

```text
large file
→ concise
→ ranged read
```

那么推理时也应该这样。

否则可能出现 distribution shift：

```text
训练：
模型习惯一次看到完整文件

推理：
工具只给 concise view
```

或者反过来。

因此建议将：

```text
Observation Policy
```

视为 agent/environment contract 的一部分，而不是单纯的数据清洗逻辑。

---

# 15. 推荐的 VeriGym 默认配置

可以先使用以下基线：

```yaml
trajectory:
  max_steps: 40-50
  target_max_tokens: 32768

tools:
  list_files:
    max_depth: 2
    max_entries: 200
    max_output_tokens: 1500

  search:
    top_k: 20
    max_output_tokens: 2000

  read_file:
    full_file_max_lines: 200
    default_mode_for_large_files: concise
    max_output_tokens: 4000
    allow_line_range: true

  shell:
    max_output_tokens: 4000
    failure_focused_summary: true

  diff:
    max_output_tokens: 8000

sft:
  train_on_system: false
  train_on_user: false
  train_on_observation: false
  train_on_assistant: true

filter:
  require_verifier_pass: true
  reject_overlong: true
  prefer_short_success: true
```

以上数值应先作为 baseline，再根据 HWE-Bench / RTL-Repo 的实际 token 分布调整。

---

# 16. 建议的验收指标

优化工具 contract 后，不应只看平均 token 数下降，还应同时验证任务性能。

建议比较：

| 指标 | Before | After |
|---|---:|---:|
| success rate |  |  |
| verifier pass rate |  |  |
| mean total tokens |  |  |
| median total tokens |  |  |
| P95 total tokens |  |  |
| mean observation tokens |  |  |
| observation / assistant ratio |  |  |
| mean tool calls |  |  |
| mean file reads |  |  |
| overlong rate |  |  |
| SFT tokens/sec |  |  |
| GPU memory |  |  |

核心验收条件：

```text
trajectory token 显著下降
AND
success / verifier performance 不显著下降
```

如果 token 大幅下降但成功率明显降低，则说明 compression policy 过于激进。

---

# 17. 当前问题的建议优先级

对于当前约 48.8K-token 的轨迹，建议按以下顺序修改：

### P0：立即修改

1. 禁止默认 recursive `list_files`
2. `list_files` 默认 depth=2
3. `read_file` 支持 line range
4. 所有工具 observation 设置硬上限
5. silent truncation 改为 explicit truncation

### P1：下一步

6. 实现 RTL-aware concise file view
7. 测试日志 failure-focused summarization
8. search top-k
9. diff bounded view
10. 收集 observation efficiency metrics

### P2：SFT 数据筛选

11. target max sequence 20K–32K
12. successful trajectories 中优先短路径
13. reject overlong / timeout / max-turn trajectories
14. raw trajectory 与 compact trajectory 同时保留

---

# 18. 最终原则

对于 repository-level SFT：

> **不要把“完整环境输出”误认为“高质量训练数据”。**

高质量 trajectory 应满足：

```text
足够的信息
+
真实的行为因果链
+
有界的 observation
+
清晰的工具使用策略
+
成功的 verifier 结果
```

最终目标不是简单降低 observation 比例，而是让模型学会：

```text
先搜索
→ 再定位
→ 局部读取
→ 修改
→ 验证
```

而不是：

```text
让环境一次性把整个仓库塞进上下文。
```

---

# 19. References

- ChipSeek: *Optimizing Verilog Generation via EDA-Integrated Reinforcement Learning*
  https://aclanthology.org/2026.acl-long.1154/

- ChipSeek GitHub
  https://github.com/rong-hash/chipseek

- R2E-Gym GitHub
  https://github.com/R2E-Gym/R2E-Gym

- R2E-Gym `file_editor.py`
  https://github.com/R2E-Gym/R2E-Gym/blob/main/src/r2egym/agenthub/tools/file_editor.py

- R2E-Gym SFT configuration
  https://github.com/R2E-Gym/R2E-Gym/blob/main/train/train_r2egym_32B_agent.yaml

- SWE-Gym GitHub
  https://github.com/SWE-Gym/SWE-Gym

- SWE-Gym paper
  https://arxiv.org/abs/2412.21139

- rLLM / DeepSWE
  https://github.com/agentica-project/rllm

- rLLM documentation
  https://rllm-project.readthedocs.io/
