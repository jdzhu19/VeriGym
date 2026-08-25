# HWE-Bench-Oriented SFT Trajectory Collection Guidelines — Fused Version

> 适用范围：VeriGym、HWE-Bench、RTL-Repo 等 repository-level hardware agent 的 trajectory 收集与 SFT 数据构建。
> 核心目标：借鉴 R2E-Gym、SWE-Gym、DeepSWE/rLLM 的 observation-control 思路，但根据 HWE-Bench 的长时程、多文件、异构 EDA 工具特征重新设定 steps、tokens、工具输出预算和 teacher execution contract。
>
> 本融合版特别解决两类容易混淆的问题：
>
> 1. **Teacher 能否完成任务** 与 **trajectory 能否直接进入 SFT** 是两个不同问题；
> 2. **bounded** 不应等价于 **MCP-only / 固定 typed tools**，真正需要约束的是 environment、runaway behavior、model-visible observation 和最终 SFT materialization。

---

## 1. 为什么不能直接照搬 R2E-Gym 的参数

R2E-Gym / SWE-Gym 提供了非常有价值的 repository-agent trajectory 收集经验，例如：

- 限制 rollout step 数；
- 对目录和文件读取做 progressive disclosure；
- mask tool observation；
- 限制 SFT sequence length；
- 成功轨迹中优先保留更高效的路径。

但是，**HWE-Bench 与典型 SWE repair task 的任务结构并不完全相同**。

HWE-Bench 中常见的 agent 行为不仅包括：

```text
search
→ read source
→ edit
→ run test
```

还可能包括：

```text
定位 RTL hierarchy
→ 检查配置 / generated collateral
→ 查找 signal / interface
→ 修改多个 RTL / config / DV 文件
→ compile / elaborate
→ simulation
→ 根据 assertion / cycle / hierarchy 继续修改
→ regression
```

因此 HWE-Bench 往往具有：

- 更长的探索 horizon；
- 更多跨文件依赖；
- RTL、配置、DV、生成文件之间的 cross-artifact coordination；
- 更重的 compile / simulation observation；
- 更高的单任务 wall-clock budget。

所以：

> **R2E-Gym 的 observation-control 方法可以直接借鉴，但 40 steps、20K–32K sequence 等具体 budget 不应直接复制。**

---

## 2. HWE-Bench 的实际 horizon 明显更长

HWE-Bench 的 reference agent recipe 使用了明显更宽松的 agent execution 上限，例如：

```text
Claude Code:
max_turns = 500

Kimi:
max_steps_per_turn = 500

OpenHands:
max_iterations = 500
```

OpenHands 还可以通过 history condenser 压缩长历史。

这说明 HWE-Bench 的基本设计思想更接近：

```text
允许长 horizon
+
限制 / 压缩 context accumulation
```

而不是：

```text
强行把所有任务限制在 40–50 steps
```

HWE-Bench 已公开分析中的不同 agent 平均 tool-call 数也可能落在几十次甚至更高。

因此：

> **一条 20–80 tool-call 的成功硬件 trajectory 本身并不异常。**

这也意味着，不能简单使用：

```text
tool calls 越少
→ trajectory 越好
```

作为 HWE SFT trajectory 的主要筛选规则。

---

# 3. 必须分离四种不同的“长度 / token”概念

这是整个 policy 中最重要的定义之一。

---

## 3.1 Agent Runtime Context

这是 agent 在 rollout / inference 时单次模型调用实际能够使用的 context。

例如：

```text
128K
256K
1M
```

取决于：

- 模型 context window；
- agent runtime；
- provider；
- condenser / summarizer；
- history management policy。

因此：

> **Teacher runtime context 可以远大于最终 SFT sequence。**

---

## 3.2 API Cumulative Token Usage

这是 provider / runtime 在多轮执行中累计统计的 token usage，例如：

```text
api_input_tokens_cumulative
api_output_tokens_cumulative
```

由于每一轮往往会重复发送已有 history：

```text
cumulative API input
```

可能远大于：

```text
unique trajectory tokens
```

例如一条 trajectory 的累计输入达到：

```text
500K
1M
3M+
```

并不意味着最终存在一个同样大小的独立 transcript。

因此：

> **API cumulative input usage 主要用于成本、效率和 runaway 分析，不能直接作为 32K / 64K SFT eligibility gate。**

---

## 3.3 Raw Unique Trajectory Length

Raw trajectory 是 teacher / agent 实际产生的完整 event stream：

```text
system
user
assistant action
tool observation
assistant action
tool observation
...
final answer
```

它应尽可能作为：

```text
audit
replay
provenance
debugging evidence
```

完整保存。

例如：

```text
raw_unique_transcript_tokens = 83K
```

本身不等于失败。

不应为了训练方便直接覆盖或修改 raw trajectory。

---

## 3.4 Compact SFT Materialized Sequence

真正用于 SFT trainer 的 sequence 则应经过：

```text
raw trajectory
      │
      ▼
normalization
      │
      ▼
observation compaction
      │
      ▼
causality validation
      │
      ▼
compact SFT transcript
```

推荐：

```text
<= 32K
→ preferred / primary SFT

32K–64K
→ acceptable long-context SFT

> 64K
→ compact again / inspect / optional long-context bucket / filter
```

因此：

> **Agent runtime context、API cumulative usage、raw unique trajectory 和 compact SFT sequence 不应该使用同一个上限。**

---

# 4. 当前 48.8K Trajectory 应该如何评价

当前轨迹：

```text
Total unique tokens:       48,815
Observation tokens:        46,266  (~94.8%)
Assistant tokens:           1,528  (~3.1%)

Tool calls:                    22
File reads:                     8
```

不应简单得出：

```text
48.8K
→ trajectory 太长
```

更准确的判断是：

- **22 tool calls** 对 HWE-Bench 来说完全正常；
- **48.8K raw unique tokens** 不应因为总长度直接判 invalid；
- 但它也**不应该未经 compaction 就直接被认定为一个合格的 32K–64K long-context SFT sample**；
- 真正需要优化的是 observation efficiency。

当前：

```text
46,266 observation tokens
/
1,528 assistant tokens
≈ 30.3
```

也就是每产生 1 个被监督的 assistant token，需要处理约 30 个 observation token。

进一步看 distribution：

```text
一次 recursive list_files
→ ~10K tokens

若干 full-file read
→ 数千 tokens / call
```

更准确的描述是：

> **这不是 horizon-too-long problem，而是 heavy-tail observation problem。**

因此推荐判断路径：

```text
48.8K raw trajectory
        │
        ▼
causality-preserving observation compaction
        │
        ├── <=32K
        │     → primary SFT
        │
        ├── 32K–64K
        │     → optional long-context SFT
        │
        └── >64K
              → inspect / compact again / filter
```

---

# 5. 最重要的架构原则：Execution Budget 与 SFT Budget 分离

Teacher 的任务是：

> **尽可能可靠地解决任务并产生可验证行为。**

SFT materializer 的任务是：

> **把成功行为转化成紧凑、因果完整、训练可承受的 sequence。**

因此不要使用：

```text
SFT max sequence = 32K
```

反向推导：

```text
Teacher execution 一旦累计超过 32K
→ 立即停止
```

这会把 training budget 错误地变成 capability limit。

更合理的是：

```text
Teacher execution
        │
        ├── wider horizon
        ├── richer debugging capability
        └── bounded environment
                 │
                 ▼
         raw immutable trace
                 │
                 ▼
      deterministic normalizer
                 │
                 ▼
       compact SFT transcript
```

---

# 6. `bounded` 的定义需要修改

不推荐继续定义：

```text
bounded
=
MCP-only
+
固定六个 typed tools
```

更准确的定义是：

```text
bounded
=
bounded workspace
+
bounded network
+
bounded credentials
+
bounded host exposure
+
bounded wall clock
+
bounded decision horizon
+
bounded model-visible observation
+
bounded final SFT materialization
+
explicit termination semantics
```

因此：

```text
native shell
```

本身并不等于：

```text
unbounded
```

例如在 container 内运行：

```text
rg
sed
grep
make
verilator
git
```

完全可以属于 bounded teacher。

真正需要控制的是：

```text
它能访问什么
它能运行多久
它能返回多少 observation
它是否暴露 secret / host path
它是否进入重复循环
最终 transcript 是否可规范化
```

---

# 7. 推荐三种 Teacher / Collection Mode

不要只保留：

```text
strict bounded
vs
host-direct
```

两种极端模式。

---

## 7.1 Mode A — Diagnostic Host-Direct

目标：

- 快速判断模型本身能否解决 task；
- 判断 MCP / broker / bridge 是否是主要失败源；
- agent harness smoke；
- tool availability diagnosis。

典型能力：

```text
host-local workspace
native shell
rg / sed / grep
make
verilator
git
editor
```

可以采用较宽 context / tool policy。

但是：

```yaml
trajectory_class: diagnostic
sft_eligible: false
```

原因：

- host path / credential isolation 较弱；
- observation 不一定 bounded；
- raw CLI JSONL 不是规范化 v2 transcript；
- training / inference action semantics 未必一致；
- API cumulative usage 可能极高。

因此：

> **Host-direct 适合作为 capability diagnostic，不适合作为默认 SFT data-production mode。**

---

## 7.2 Mode B — Strict Typed-Tool Teacher

即传统：

```text
Docker runtime bridge
+
MCP broker
+
typed list/read/search/patch/test tools
+
bounded observation
```

优点：

- schema 清晰；
- isolation 强；
- observation policy 容易固定；
- transcript 易验证；
- training contract 易控制。

缺点：

- broker / event protocol 可能成为额外 failure source；
- patch state machine 可能限制真实调试流程；
- 很难自然覆盖：
  - rg
  - sed
  - make
  - verilator
  - project-specific scripts
- 硬件 repo 中 native tooling 本身往往是任务的一部分。

因此：

> **Strict typed-tool teacher 很适合 conformance，但不应该被定义成唯一合法 SFT teacher。**

---

## 7.3 Mode C — Recommended: Containerized Native-Shell Teacher + Bounded Collector

这是推荐增加的 HWE-oriented production mode。

```text
containerized workspace
        │
        ├── native shell
        ├── rg / grep
        ├── sed
        ├── git
        ├── make
        ├── verilator
        ├── simulator/compiler
        └── editor
                 │
                 ▼
        bounded collector
                 │
        ├── stdout/stderr cap
        ├── log summarization
        ├── structural file view
        ├── explicit omission marker
        ├── path sanitization
        ├── secret scanning
        ├── event normalization
        └── token accounting
                 │
                 ▼
         normalized v2 transcript
```

核心思想：

> **Bound the data and environment, not the legitimate debugging capability of the teacher.**

这个模式既保留 host-direct 的主要能力优势，又恢复：

- isolation；
- bounded observation；
- transcript normalization；
- SFT eligibility；
- reproducibility；
- student-facing tool semantics。

---

# 8. Teacher Backend 与 Student Backend 不要求完全相同

原来的：

> training 和 inference 应使用完全相同的 tool contract

需要稍微放宽。

更准确的原则是：

> **Training transcript 与 student inference 应保持兼容的 action / observation semantics；teacher 的具体 backend 不要求与 student 完全相同。**

例如：

```text
Teacher backend:
native shell

assistant:
rg "flush" rtl/
```

可以 normalization 成：

```text
tool: shell
command: rg "flush" rtl/

observation:
<bounded search-like output>
```

Student inference 可能使用：

```text
typed search tool
```

或者：

```text
typed shell tool
```

二者仍然可以兼容，只要模型看到的是稳定的：

```text
action
→ bounded evidence
→ next action
```

真正应该避免的是：

```text
Training:
read_file 永远返回完整 1000 行

Inference:
read_file 只返回 structural view
```

这种 observation semantics 的明显 distribution shift。

因此：

> **要求的是 student-facing semantics compatibility，而不是 teacher implementation identity。**

---

# 9. 推荐的 Step Policy

原先类似：

```yaml
trajectory:
  max_steps: 40-50
```

不适合作为 HWE-Bench / VeriGym 的统一默认值。

推荐：

```yaml
trajectory:
  # SFT data-production efficiency soft limit
  soft_max_steps: 80

  # runaway guardrail
  hard_max_steps: 200

  # benchmark-faithful reference execution
  benchmark_max_steps: 500
```

注意：

> `80 / 200` 是建议的 VeriGym data-production baseline，不是 HWE-Bench 官方标准。

含义：

```text
0–80
→ 正常

80–200
→ 允许继续
→ 标记 long_horizon=true
→ 检查是否存在无效循环

>200
→ 默认终止生产型 teacher
→ 或进入特殊 long-horizon profile

benchmark-faithful evaluation
→ 可按照 benchmark/reference recipe 使用更宽上限
```

---

# 10. Step 的定义必须统一

不同 harness 中：

```text
turn
step
tool call
event
shell command
```

可能不是同一个概念。

推荐定义：

> **decision step = 一次 assistant/model decision**

例如：

```bash
rg "flush" rtl && sed -n '100,180p' rtl/core.sv
```

如果由一次 assistant action 发出：

```text
decision_steps += 1
```

而不是按 shell 中包含两个 Unix command 算两步。

推荐分别统计：

```text
model_decision_steps
tool_invocations
shell_subcommands        # optional
provider_events          # optional
```

避免直接比较不同 harness 的原生 `turn` 数。

---

# 11. Step 上限最终应通过成功轨迹分布校准

`80 / 200` 是合理的工程起点，但不应该永久固定。

对较宽约束下的 successful teacher trajectories 统计：

```text
P50 decision steps
P75
P90
P95
P99
```

推荐：

```text
soft_limit
≈ successful P90

hard_limit
≈ successful P95/P99 + safety margin
```

还应按 task family / repo family 分开分析。

例如：

```text
small RTL repair
large SoC RTL repair
Chisel hierarchy repair
RTL + DV
RTL + config
```

如果不同类别分布差异明显，应使用 profile，而不是全局常量。

---

# 12. Patch Budget：从固定小上限改为 soft/hard + churn detection

Hardware repair 常见：

```text
patch
→ compile
→ error
→ patch
→ simulate
→ assertion failure
→ patch
→ pass
```

这属于有价值的 verification loop。

因此不推荐使用很小的：

```text
max_patch_calls = 8
```

作为主要 hard limit。

可以使用初始 baseline：

```yaml
patch:
  soft_actions: 16
  hard_actions: 32
```

但更重要的是监控：

```text
unique_modified_files
total_diff_lines
repeated_same_hunk_edits
no_op_patch_count
patch_revert_count
patch_churn_ratio
```

例如：

```text
edit A
→ revert A
→ edit A
→ revert A
→ edit A
```

即使只有 5 次 patch，也可能比 12 次有根据的修复更低效。

因此：

> **Patch quality / churn 比 patch count 本身更重要。**

---

# 13. SFT Token Policy

不建议使用：

```text
20K–32K hard cutoff
```

作为 HWE trajectory 的统一标准。

推荐：

### Preferred / Primary

```text
<= 32K compact tokens
```

最适合作为主训练集。

### Acceptable Long-Context

```text
32K–64K compact tokens
```

适合：

- multi-file RTL repair；
- RTL + config；
- RTL + DV；
- Chisel hierarchy；
- 多轮 compile / simulation / regression；
- 经过合理 compaction 后仍然保留较多必要上下文的 hard task。

### Expensive / Inspect

```text
> 64K compact tokens
```

优先：

```text
compact again
→ inspect causality
→ optional long-context bucket
→ safe segmentation
→ filter
```

推荐配置：

```yaml
sft:
  preferred_max_tokens: 32768
  allowed_max_tokens: 65536
  overlong_policy: compact_then_filter
```

如果当前训练资源只支持 32K：

```yaml
enable_long_context_bucket: false
```

即可。

---

# 14. 为什么仍然建议 32K 作为 Primary Bucket

即使 teacher runtime 可以使用：

```text
128K
256K
1M
```

也不意味着主 SFT dataset 应使用同样长度。

原因：

- observation token 即使 loss-masked，也参与 Transformer forward；
- 32K 本身已经具有较高计算 / 显存成本；
- 很多 raw observation 可以安全压缩；
- dataset throughput 和 sample diversity 往往比保留少量极长 raw history 更重要。

因此：

> **Teacher 可以长；主 SFT sample 应尽量短。**

但“尽量短”不意味着：

```text
为了 <=32K
→ 删除必要 evidence
```

---

# 15. 优先修 Observation，而不是砍 Steps

对于当前：

```text
22 tool calls
48.8K raw unique tokens
```

不推荐：

```text
22 tool calls
↓
强行压成 10–15 calls
```

更合理的是：

```text
list_files
10K
↓
1–2K

full-file read
8K
↓
structural view 2–4K
↓
targeted range 2–4K

simulator output
15K
↓
error-focused 3–8K
```

这样可能在不删除关键 action 的情况下，把 48.8K raw trajectory 压缩到更适合训练的区间。

---

# 16. `list_files`：禁止 Unbounded Recursive，而不是禁止 Recursive

R2E-Gym 式：

```text
initial tree depth = 2
```

仍然非常适合 HWE。

推荐：

```yaml
list_files:
  initial_max_depth: 2
  max_entries: 200
  max_output_tokens: 2000
  allow_scoped_recursive: true
```

初始：

```text
list_files(".")
```

只展示浅层。

模型定位到：

```text
hw/ip/uart/
```

之后允许：

```text
list_files(
    path="hw/ip/uart",
    recursive=true,
    max_entries=200
)
```

原则：

> **禁止 repository-wide unbounded dump，但允许 scoped recursive discovery。**

---

# 17. Generated / Vendor / Third-Party 文件：Deprioritized but Searchable

对于 hardware repo，不应简单定义：

```text
generated/
vendor/
third_party/
= inaccessible
```

因为 bug 可能涉及：

- generated RTL；
- HJSON / JSON；
- register description；
- templates；
- DV infrastructure；
- config；
- Scala / Chisel；
- generated collateral；
- build metadata；
- IP metadata。

推荐：

### Normally hidden from initial tree

```text
.git/
__pycache__/
.cache/
temporary runtime outputs
```

### Deprioritized but searchable

```text
build/
generated/
vendor/
third_party/
```

也就是说：

> **不在初始 tree 中完整展开，不等于 agent 不能搜索和读取。**

---

# 18. `read_file` 应使用 HWE-aware Structural View

R2E-Gym 的 Python concise view 思想仍然适用，但 HWE 需要不同 parser contract。

---

## 18.1 Verilog / SystemVerilog 建议保留

```text
`include
`define
`ifdef / `ifndef

module
interface
package

parameter
localparam

ports
signal declarations

typedef
struct
enum

instance
parameter binding
port connection

generate

always_ff
always_comb
always_latch

assign

function
task

assert
property
bind
```

长 block 可以折叠：

```text
84  always_ff @(posedge clk) begin
        <37 lines omitted>
121 end
```

并明确提示：

```text
Use read_file(path=..., start_line=84, end_line=121)
```

---

## 18.2 Chisel / Scala 建议保留

至少包括：

```text
Module
RawModule
LazyModule
LazyModuleImp

IO
Bundle

Config
Parameters

Reg
Wire
when
switch

Diplomacy nodes

trait
mixin

module instantiation
relevant imports
```

如果 parser / structural summarizer 不可靠：

> **宁可返回 bounded line range，也不要生成可能错误的结构摘要。**

---

# 19. `read_file` Token Budget

建议：

```yaml
read_file:
  small_file_full_view: true
  default_large_file_mode: structural
  allow_line_range: true

  preferred_output_tokens: 4000
  max_output_tokens: 8000
```

推荐流程：

```text
small file
→ full view

large file
→ structural view

specific region
→ ranged full-detail view
```

重点不是单纯增加 hard cap，而是：

> **减少无意义的 full-file dump。**

---

# 20. Native Shell 可以存在，但 Model-visible stdout 必须 Bounded

Host-direct 更容易成功的重要原因之一是 agent 可以直接运行：

```text
rg
sed
grep
make
verilator
git diff
```

不建议因为 raw CLI observation 很大，就直接禁止 native shell。

应该限制的是：

```text
what the model sees
```

例如：

```bash
rg "state_q" .
```

产生 137 个匹配。

collector 可以返回：

```text
137 matches found.
Showing 40 most relevant matches.

rtl/core.sv:112: ...
rtl/core.sv:184: ...
...

<97 matches omitted>
Refine the query or restrict the path.
```

而不是完整返回所有命中。

---

# 21. Shell / Compile / Simulation Observation

HWE 常见：

```text
Verilator
VCS
Mill
SBT
RISC-V GCC
UVM
custom simulation
difftest
```

重要信息可能包括：

```text
command
exit code
compile error
elaboration hierarchy
assertion
simulation cycle
timestamp
seed
expected / actual
first mismatch
fatal
stack / elaboration chain
```

推荐：

```yaml
shell:
  preferred_output_tokens: 4000
  max_output_tokens: 8000
  summarize_success_noise: true

  preserve:
    - command
    - exit_code
    - simulator
    - test_name
    - seed
    - first_error
    - assertion
    - cycle_or_time
    - hierarchy
    - expected_actual
    - traceback_or_elaboration_chain
    - stderr_tail
```

不推荐简单：

```text
只保留最后 100 行
```

因为真正的 first failure 可能出现在中间。

---

# 22. EDA Timeout 不应简单复制 Software Agent 的 90 秒

对 hardware：

```text
Verilator compile
Chisel elaboration
Mill/SBT
simulation
full regression
commercial simulator startup
```

可能天然更慢。

因此建议：

```yaml
timeouts:
  ordinary_shell: bounded

  compile:
    policy: repo_specific

  simulation:
    policy: repo_specific

  regression:
    policy: verifier_specific
```

具体值应通过真实 runtime 分布校准。

例如：

```text
普通 rg / sed
```

和：

```text
完整 Verilator build
```

不应该共享同一个 timeout。

---

# 23. Full Raw Log 与 Model Observation 必须分离

推荐：

```text
command execution
      │
      ├── raw stdout/stderr
      │       ↓
      │   immutable artifact
      │
      └── observation collector
              ↓
         compact diagnostic view
              ↓
             model
```

例如：

```yaml
observation:
  compact_tokens: 3200
  raw_bytes: 1842281
  raw_sha256: ...
  truncated_for_model: true
```

这样：

- audit evidence 不丢；
- replay 可验证；
- 模型不会吃完整巨量 log；
- SFT transcript 保持 compact。

---

# 24. Diff Budget

Hardware patch 可能跨多个 artifact。

推荐：

```yaml
diff:
  preferred_output_tokens: 8000
  max_output_tokens: 16000
```

处理：

```text
small diff
→ full diff

large diff
→ file summary
→ relevant hunks
→ per-file diff on demand
```

Diff 是 repair causality 中的重要 evidence，不应简单因为长就删除。

---

# 25. Search Budget

推荐：

```yaml
search:
  top_k: 20
  max_output_tokens: 3000
```

返回：

- path；
- line number；
- matched line；
- 少量上下文。

保持：

```text
search
→ locate
→ ranged read
```

而不是：

```text
search
→ dump all matches and files
```

---

# 26. 从 “Prefer Short Success” 改成 “Prefer Information-Efficient Success”

HWE 不应简单定义：

```text
越短越好
```

因为有效 hardware debugging 可能需要：

```text
rg
→ hierarchy inspection
→ build probing
→ config inspection
→ edit
→ compile
→ simulation
→ refine
→ regression
```

真正应惩罚的是：

```text
redundant rereads
repeated identical search
same command with same output
unbounded logs
useless build spam
patch thrashing
```

因此：

> **Prefer information-efficient successful trajectories, not merely shorter trajectories.**

---

# 27. 推荐的 Curation Ranking

同一 task 有多条成功 trajectory 时：

```text
1. verifier passed
2. policy compliant
3. causally complete
4. no infrastructure failure
5. no secret / host leakage
6. no runaway / pathological loop
7. evidence of useful verification
8. information-efficient exploration
9. lower patch churn
10. lower redundant observation volume
11. lower repeated tool-call ratio
12. reasonable total compact tokens
```

不建议：

```text
success
→ sort only by total steps
```

也不建议：

```text
最短
→ 一定最好
```

---

# 28. Productive Iteration 与 Redundant Iteration 应分开

例如：

```text
patch
→ compile
→ new error
→ patch
→ targeted simulation
→ new assertion
→ patch
→ pass
```

属于：

```text
productive iteration
```

而：

```text
same grep
→ same result
→ same grep
→ same result
```

属于：

```text
redundant iteration
```

HWE trajectory 允许较长 horizon，但需要控制：

```text
thrashing
looping
repeated exploration
```

而不是控制一切合法调试回合。

---

# 29. 推荐增加的 Metrics

至少记录：

```text
model_decision_steps
tool_invocations
file_reads
search_calls
shell_calls

api_input_tokens_cumulative
api_output_tokens_cumulative

raw_unique_transcript_tokens
compact_sft_transcript_tokens

assistant_tokens
observation_tokens

max_single_observation_tokens
mean_observation_tokens_per_call
observation_to_assistant_ratio

duplicate_read_ratio
repeated_search_ratio

compile_log_tokens
file_view_tokens
directory_listing_tokens
diff_tokens

compile_attempts
simulation_attempts
useful_verification_calls

unique_files_read
unique_files_modified

patch_churn_ratio

raw_log_bytes
raw_to_compact_ratio

tokens_per_success
```

特别关注：

```text
max_single_observation_tokens
```

因为当前 trajectory 的问题明显具有 heavy-tail 特征：

```text
average 不一定离谱
但单个 list_files / log 极大
```

---

# 30. Raw 与 Compact Trajectory 必须同时保留

推荐：

```text
raw trajectory
        │
        ├── immutable archive
        │
        ▼
deterministic observation compactor
        │
        ▼
compact normalized trajectory
        │
        ▼
causality validation
        │
        ▼
SFT materialization
```

不要：

```text
直接修改 raw event log
```

也不要：

```text
删除 observation 后假装 assistant 原本就没看到
```

---

# 31. Compaction 必须保留 Causality

例如：

```text
read_file
→ observation 中第 812 行出现 bug
→ assistant 修改第 812 行
```

不能压成：

```text
read_file
→ [content removed]
→ assistant 修改第 812 行
```

推荐：

```text
structural summary
+
relevant lines
+
explicit omission marker
+
recoverable range metadata
```

确保后续 action 仍然可以从 compact observation 合理推出。

---

# 32. 建议增加 Compaction Manifest

每个被压缩 observation 留下：

```yaml
event_id: obs-0018

source:
  type: shell_stdout
  raw_sha256: ...
  raw_bytes: 1842281

compaction:
  method: error_focused_log
  original_tokens: 18342
  compact_tokens: 3120
  omission_marker: true

causality:
  later_action_depends_on_preserved_evidence: true
```

这样可以审计：

> SFT compactor 是否删除了 teacher 实际依赖的信息。

---

# 33. 推荐的 HWE-Oriented VeriGym Baseline

```yaml
teacher:
  production_mode: container_native_shell

trajectory:
  # VeriGym data-production policy, not HWE-Bench official limit.
  soft_max_decision_steps: 80
  hard_max_decision_steps: 200

  # Benchmark-faithful raw evaluation profile may use a wider ceiling.
  benchmark_max_steps: 500

patch:
  soft_actions: 16
  hard_actions: 32
  track_churn: true

workspace:
  containerized: true
  host_direct: false

network:
  external_web: false

tools:
  list_files:
    initial_max_depth: 2
    allow_scoped_recursive: true
    max_entries: 200
    max_output_tokens: 2000

  search:
    top_k: 20
    max_output_tokens: 3000

  read_file:
    small_file_full_view: true
    default_large_file_mode: structural
    allow_line_range: true
    preferred_output_tokens: 4000
    max_output_tokens: 8000

  shell:
    native_commands_allowed: true
    preferred_output_tokens: 4000
    max_output_tokens: 8000
    failure_focused: true
    preserve_hardware_diagnostics: true
    preserve_raw_artifact: true

  diff:
    preferred_output_tokens: 8000
    max_output_tokens: 16000

sft:
  preferred_max_tokens: 32768
  allowed_max_tokens: 65536
  overlong_policy: compact_then_filter

  train_on_system: false
  train_on_user: false
  train_on_observation: false
  train_on_assistant: true

eligibility:
  require_verifier_pass: true
  require_isolated_execution: true
  require_normalized_transcript: true

  reject_secret_exposure: true
  reject_host_path_exposure: true
  reject_pathological_loop: true

  # Important:
  # do not reject merely because cumulative API input usage exceeds 32K/64K.
  length_gate_metric: compact_sft_transcript_tokens

curation:
  prefer_information_efficient_success: true
  do_not_rank_by_length_alone: true

  preserve_raw_trajectory: true
  materialize_compact_trajectory: true
  preserve_compaction_manifest: true
```

其中：

```text
80 / 200
16 / 32
32K / 64K
```

均应视为 **VeriGym 的初始工程 baseline**，而不是 HWE-Bench 官方规则。

后续应通过 successful rollout distribution 校准。

---

# 34. 推荐使用多个 Profile，而不是一个全局常量

例如：

```text
r2e_like
hwe_standard
hwe_long
benchmark_faithful
diagnostic_host_direct
```

### `r2e_like`

适合：

- SWE-like repair；
- methodology alignment；
- 小型 repo task。

可使用较紧 step / context budget。

### `hwe_standard`

建议从：

```text
soft steps = 80
hard steps = 200
primary SFT = 32K
optional SFT = 64K
```

开始。

### `hwe_long`

用于：

- SoC-level；
- multi-artifact；
- Chisel；
- 多轮 compile/simulation；
- 明显超过 standard horizon 的 hard task。

可以提高 teacher horizon，但不意味着直接放宽 SFT sample。

### `benchmark_faithful`

尽量遵循 benchmark/reference agent 的 evaluation recipe。

主要用于：

```text
fair evaluation
```

而不是：

```text
直接构造 SFT sample
```

### `diagnostic_host_direct`

```yaml
sft_eligible: false
```

用于 capability diagnosis 和 harness isolation。

---

# 35. 当前 Strict-Bounded vs Host-Direct 结果应如何解释

如果出现：

```text
strict bounded teacher
→ 很低 eligible / solve rate

host-direct
→ 明显更高 solve rate
```

不能直接得出：

```text
bounded collection 不适合 HWE
```

因为两者同时改变了：

```text
tool freedom
tool protocol
patch state machine
workspace isolation
observation size
context policy
shell availability
```

更合理的结论是：

> **Host-direct 证明了模型在更自由工具环境下具有解决能力；它同时暴露出 strict MCP/broker policy 可能引入了额外 failure modes。**

真正值得验证的是第三种模式：

```text
containerized native-shell
+
bounded collector
```

---

# 36. 推荐三路 Ablation

对同一批 task、同一模型：

| Mode | Tool freedom | Isolation | Observation bound | SFT eligible |
|---|---|---|---|---|
| Strict MCP / typed tools | Lower | Strong | Strong | Yes |
| Native-shell bounded | High | Strong | Strong | **Yes** |
| Host-direct diagnostic | High | Weak | Weak | No |

重点比较：

```text
solve rate
verifier pass rate
SFT eligible rate

tool protocol failures
policy failures

raw unique tokens
compact SFT tokens
max observation size

patch churn
productive verification loops
```

关键问题是：

> **Native-shell bounded 能否保留 host-direct 的 solve rate，同时恢复 SFT eligibility？**

如果可以，则说明之前的问题更可能来自：

```text
MCP broker / tool-state-machine overconstraint
```

而不是：

```text
bounded data production 本身
```

---

# 37. 对原 Guideline 最重要的融合修改

## 修改 1：`40–50 steps`

改成：

```text
soft 80
hard 200
benchmark/reference execution up to 500 when appropriate
```

并通过成功轨迹的 P90/P95/P99 再校准。

---

## 修改 2：`20K–32K hard limit`

改成：

```text
compact <=32K
→ preferred

compact 32K–64K
→ acceptable long-context

compact >64K
→ compact / inspect / optional bucket / filter
```

同时强调：

```text
API cumulative usage
raw trajectory
compact SFT sequence
```

是三种不同 token metric。

---

## 修改 3：`bounded == MCP-only`

改成：

```text
bounded
=
controlled environment
+
bounded observation
+
bounded runaway behavior
+
normalized SFT materialization
```

允许：

```text
containerized native shell
```

作为 production teacher。

---

## 修改 4：Training / Inference Tool Contract

从：

```text
Teacher 与 student 必须使用同一 tool backend
```

改成：

```text
Teacher backend 可以不同
但 normalization 后的 action / observation semantics
必须与 student inference 兼容
```

---

## 修改 5：`generated/` 默认 ignore

改成：

```text
deprioritized but searchable
```

---

## 修改 6：`prefer shorter success`

改成：

```text
prefer information-efficient success
```

---

## 修改 7：`max patch calls = small fixed number`

改成：

```text
soft/hard patch budget
+
patch churn detection
```

---

## 修改 8：固定软件式 action timeout

改成：

```text
ordinary shell
compile
simulation
regression
```

分别使用 repo/tool-specific timeout profile。

---

# 38. 最终原则

对于 HWE-Bench / VeriGym：

> **不要把 SWE agent 的具体 trajectory budget 直接复制到 hardware agent。**

应该分别控制：

```text
Teacher capability
Agent horizon
Environment isolation
Observation size
Raw evidence retention
SFT materialization length
```

最终目标不是：

```text
最短 trajectory
```

也不是：

```text
最严格的工具限制
```

而是：

```text
成功
+
可验证
+
因果完整
+
工具探索有针对性
+
observation 有界
+
环境受控
+
训练成本合理
```

对于当前 48.8K-token、22-tool-call 的案例，最优先修复的是：

```text
recursive list_files
full-file read
large shell / EDA output
```

而不是首先减少 tool-call 数量。

对于当前 host-direct 与 strict bounded 的差异，下一步最值得实现的是：

```text
Containerized Native-Shell Teacher
+
Bounded Observation Collector
+
Normalized v2 Transcript
```

一句话总结：

> **R2E-Gym 提供 observation-control 方法论；HWE-Bench 需要更长的 teacher horizon 和更丰富的合法调试能力；VeriGym 则应通过 container isolation、bounded observations、causality-preserving compaction 和 compact SFT gating，把两者结合起来。**
