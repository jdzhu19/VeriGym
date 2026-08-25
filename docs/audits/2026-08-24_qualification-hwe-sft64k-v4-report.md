# HWE DeepSeek Harness 64K v4 loader 与 GPU 资格审计

日期：2026-08-24。范围仅为 exact SFT loader 和一次零 optimizer-step 的 GPU
forward/backward 资格验证。本轮没有开始训练、没有写 checkpoint/adapter、没有提交新 HPC
作业，也没有把资格 profile 注册为正式训练 recipe。

> **结论边界：** `loader_ready=true`、`gpu_probe_passed=true`、
> `development_training_ready=true`；`production_training_ready=false`、
> `training_started=false`、`optimizer_steps=0`、`adapter_written=false`。
> exact context 未压缩或 observation-masked，因此 `nap_required=false`，这不是 NAP pass。

## 结论

资格验证通过。冻结 v3 的 83 个 decision rows 被无损派生为独立 64K v4；实际
rLLM→parquet→veRL dataset 路径逐行保留 `messages`、六工具 schemas 和 exact token
receipts，并用冻结 Qwen3.5 tokenizer/chat template 重算全部 token IDs 与 decision-only
loss mask。83 行全部匹配，最长真实行 50,117 tokens，19 行超过 32,768，零行超过
65,536，未发生截断、压缩、删除或重排。

现有 LSF job `466876` 的 gpu03 allocation 上，GPU 0--3 以 BF16、FSDP2、LoRA
rank 8、Ulysses SP=4 对最长 50,117-token 行完成一次 forward/backward。四个 rank 的 loss
均为 `0.49397674202919006`，每个 rank 有 496 个有限 gradient tensors；trainable parameter
hash 前后相同，optimizer step 为 0。主 profile 通过，offload fallback 未使用。完成后七张
A30 均为 0 MiB，原 allocation 仍为 `RUN`，未被释放。

资格总表：
[qualification-summary.json](/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/decision-sft-64k-v4/qualification-summary.json:1)，
文件 SHA-256 为
`da521f3859e4d188c9ebd5d4f560300f896f394905ca864346666f5b9ce1d384`。

## 冻结数据与派生约束

源 v3 dataset hash 保持
`b362cc1df0969f1bad368c939110175502d8ff0d97aef62c93cccd18871e351a`；manifest 和
train JSONL 的 SHA-256 分别为
`a2605512edac128e66ac0afdf07a9245098f0bdd3b07ca485defc484b3b01c46` 与
`1b7522c3bae396aeed4464486a3c8ba60b9b4f3fde8defa2d4903ff852618cec`。派生器在读取
时强制验证这三个身份、83 个源 record hashes 及其顺序；v3 历史文件未修改。

独立 v4 dataset hash 为
`0acfe95a820d87310a87b6da104ba59e259ce754b19242f7c9b42937591c5139`；manifest 与
train JSONL 的 SHA-256 分别为
`60b1f2646c238efa2197d89c98875c1587a3be16e1c051f2227c3a22b8ae4fac` 与
`cab55d3cc7752b971904c88d8c11e93645c0b215af9beec40dd648bcfe7f1aa1`。v4 保留两条
verifier-pass trajectories、83 个 decisions 和 85 个 canonical tool actions；action
multiset 与 v3 完全一致。

每行新增 source-v3 binding、tool-schema hash、input-ID hash 和 loss-mask hash，并固定
`max_length=65_536`、`truncation=error`。派生器的 fail-closed 源身份与 payload 不变检查见
[deepseek_harness_sft_64k.py](../../src/verigym/hwe/deepseek_harness_sft_64k.py)，对应 schema
见 [hwe.py](../../src/verigym/schemas/hwe.py)。

## Loader 与 Qwen3.5 兼容层

专用边界不修改冻结 rLLM/veRL 安装目录：

- parquet writer 在落盘前后验证完整 `messages`、同一份六工具 schemas、record binding
  和 exact receipts；Arrow 物理编码不同只允许在语义完全相等时通过。本地 parquet
  SHA-256 为 `4603e10121b9f47add8e6c70f30434c3ef531c1598f9f484d894118c7c01084d`；HPC
  parquet 为 78,140 bytes，SHA-256
  `f1bcd1d88ee14d9628e36c7a2e8c6aa59dc2fc294b6c617cd0a393776ada323b`，两者语义相等。
- veRL dataset 对前缀和完整目标都调用
  `apply_chat_template(..., tools=tools)`，只监督最后一个完整 assistant decision。实际
  token IDs、loss mask、token counts、tokenizer hash
  `440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e` 和 chat-template
  hash `a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715` 必须逐项匹配。
  缺工具、字段变化、模板漂移或超过 64K 都会抛错。
- dispatcher 只允许 materialize 或 qualification probe；`fit()` 和 `train()` 均 fail fast。
  resolved profile 固定 BF16、FSDP2、LoRA 8/16/0.05、gradient checkpointing、
  remove-padding、global/micro batch 1、16,384 token/GPU、SP=4、workers 0、torch compile
  disabled，且 checkpoint save contents 为空。
- Qwen3.5 层显式选择官方 `Qwen3_5ForCausalLM`，固定
  `trust_remote_code=false`，通过 bounded fused vocabulary head 避免构造完整
  50K×248,320 logits。SP>1 时强制使用 veRL 从全局序列得到的 `shift_labels`，不在 shard
  内重复 roll/slice；LoRA adapter 保持 BF16，避免 FSDP2 mixed original dtype。

实现入口分别是
[hwe_decision_sft_64k.py](../../integrations/verigym-training-reference/src/verigym_training_reference/hwe_decision_sft_64k.py)、
[hwe_decision_sft_64k_backend.py](../../integrations/verigym-training-reference/src/verigym_training_reference/hwe_decision_sft_64k_backend.py)、
[qwen35_verl_compat.py](../../integrations/verigym-training-reference/src/verigym_training_reference/qwen35_verl_compat.py)
和
[verl_lora_dropout.py](../../integrations/verigym-training-reference/src/verigym_training_reference/verl_lora_dropout.py)。

## GPU 资格结果

| 项目 | 实际值 |
| --- | --- |
| LSF / host | existing job `466876` / `gpu03` |
| GPU | A30 0--3，world size 4，Ulysses SP=4 |
| 最长真实样本 | row 61，50,117 tokens |
| loss | 四个 rank 均为 `0.49397674202919006`，finite |
| gradients | 每 rank 496 tensors，全部 finite |
| 参数变化 | trainable parameter hashes 前后相同 |
| 峰值 allocated | 18,934,681,600 bytes（17.634 GiB） |
| 峰值 reserved | 21,791,506,432 bytes（20.295 GiB） |
| probe / 总 wall time | 81.7302 s / 111.2903 s |
| GPU seconds | 445.1613 |
| fallback | offload 未使用 |
| mutation | 0 optimizer steps；0 checkpoint；0 adapter |

GPU 报告：
[gpu-qualification-primary.json](/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/decision-sft-64k-v4/gpu-qualification-primary.json:1)，
SHA-256
`c44b7068284f4e02d6e0ec44a9e89f56e886debbbc32a06525a4312388d14a62`。clean launch log
SHA-256 为 `f43b5780015dd9e6ab2343fcf7dd6f7e213acf49f01a5847b3e3fea4762b7bc4`。

launch9 已完成 probe，但对象释放阶段发生 NCCL OOM，因此没有被当作最终通过；它的报告
和日志仍保留。修复后的 launch10 在 `finally` 中先清梯度和对象引用，再进行 GC、CUDA
synchronize/empty-cache、barrier 和 process-group teardown，干净退出。资格 primitive、
optimizer/checkpoint guards 与清理顺序见
[hwe_decision_sft_64k_entry.py](../../integrations/verigym-training-reference/src/verigym_training_reference/hwe_decision_sft_64k_entry.py)。

## 冻结运行时

- rLLM commit `1d1109a655e291b3001d8526d7c9ecc5b9328226`；
- veRL release `0.8.0`，source commit
  `7aed6b230776f963fa09509c10d9c3a767d1102c`，package metadata `0.8.0.dev0`；
- Transformers checkout `e8ea728a3eeeb903e77c7d1bd29267c80a1be71f`；
- PyTorch `2.6.0+cu124`、CUDA `12.4`、NCCL `2.21.5+cuda12.4`、FlashAttention
  `2.7.4.post1`；
- qualification wheels：VeriGym
  `a9c667123b0fdc603c1ceeab295424c0541c43ce46688133d91edfefa4693c57`、training-reference
  `acdf1e49d15e5983277045dd503cfaa6b608d1ce6df8c49c1f8ab53d7a00b2e5`、veRL
  `29dcf0b913d6374233c3c680a96171a0005b4468e6a58b3a80e13dff90011070`、FlashAttention
  `58853b28a5a926cae14402bfd8d4d93a45ebf8f9e79533f37ab09d0d77a99c05`。

源快照、overlay、Triton cache 和临时进程文件均位于远端 `.verigym-tmp`，未覆盖 dirty
VeriGym checkout或共享 `agent` 环境。兼容 runtime 的 Python、NCCL、rootfs、GCC 与
Triton launcher identities 已记录在资格总表中。

## 证据、发现与验证路径

### Evidence

- **E-001 / frozen-source identity：** v3 manifest/train 文件 SHA-256、dataset hash 和全部
  record hashes；v4 manifest 中保存一对一 source binding。
- **E-002 / exact loader：**
  [loader-dry-run.json](/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/decision-sft-64k-v4/dataset/loader-dry-run.json:1)
  与 [train.parquet](/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/decision-sft-64k-v4/loader/train.parquet)
  证明 83 行由实际 tool-aware 路径逐行重算并匹配。
- **E-003 / GPU primitive：** final GPU JSON 与 clean launch log 记录四个 rank 的 loss、
  gradients、参数前后 hashes、资源峰值和 wall time。
- **E-004 / no mutation：** probe 报告显示 `optimizer_steps=0`、参数 hash 不变、
  checkpoint/adapter 均未写；代码把 optimizer step 和 checkpoint save 替换为 fail-fast
  guard。
- **E-005 / artifact security：**
  [security-scan.json](/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/decision-sft-64k-v4/security-scan.json:1)
  扫描 11 个原始资格文件、6,148,433 bytes，gate 为 pass，hard leak 与 scanner error 均为
  0。加入扫描报告本身后复扫 12 个文件、6,187,378 bytes，结果仍为 0/0。

### Findings

- **F-001 / exact loader ready：** 由 E-001、E-002 支持；六工具、完整 messages、receipts
  和最后 decision loss mask 已在 83 行真实 veRL dataset access 中一致。
- **F-002 / development GPU qualification passed：** 由 E-003、E-004 支持；最长真实行在
  冻结 primary profile 上完成有限 forward/backward，未使用 offload fallback。
- **F-003 / historical and security boundaries preserved：** 由 E-001、E-004、E-005 支持；
  v3 未改，资格目录无 secret/artifact gate failure，训练和生产状态均保持 false。
- **F-004 / build-source scan caveat：** core 与 training-reference 的 sdist/wheel 已离线构建、
  解包并无依赖安装成功。另对整个安装源码做通用 secret scan 时，仓库既有安全测试和扫描器
  源码中的私钥/赋值模式样例产生 55 个 hard-pattern findings；这些副本只在本轮
  `.verigym-tmp`，不属于资格交付目录，也未被用作 E-005 的 pass 依据。

### Paths

- **P-001 / 数据到 loader：** E-001 → v4 source binding → parquet semantic round-trip →
  Qwen tool-aware template 双渲染 → receipt/hash 比对 → F-001。
- **P-002 / loader 到 GPU：** F-001 → 83 行实际 veRL dataset access → 选取 row 61 →
  FSDP2+SP4 bounded-head forward/backward → finite loss/gradients → F-002。
- **P-003 / 零训练副作用：** optimizer/checkpoint guards → 参数前后 hash → clean teardown →
  allocation 保持 RUN 且所有 GPU 归零 → F-003。

## 验证清单

- `ruff check . && ruff format --check .`：通过，531 files formatted；
- `mypy src`：通过，203 source files；training-reference `mypy src`：通过，32 files；
- ordinary `pytest`：949 passed、1 skipped、52 deselected；
- training-reference：105 passed、1 skipped；HWE focused：78 passed；新增聚焦测试：28 passed；
- schema export/check：0 changed；
- core 与 training-reference：`python -m build --no-isolation` 成功，wheel 解包、无依赖安装
  和 sdist tar 校验成功。隔离构建最初因代理 502 无法下载临时 setuptools；本机
  setuptools `78.1.1` 满足两个 build-system 约束，故改用离线 no-isolation 验证；
- qualification artifact/secret scan：pass；
- existing job `466876`：probe 后仍为 `RUN`，`new_hpc_jobs_submitted=false`，
  `allocation_released=false`。

## 允许的后续结论

本轮只解除“exact 64K loader 是否完整”和“最长真实样本能否在现有四卡 A30 profile 上完成
有限反向传播”两个开发阻塞。它不提供 optimizer 数值稳定性、长程训练稳定性、checkpoint
恢复、adapter 质量、held-out 泛化、benchmark score 或 production readiness 证据。若要
启动训练，必须另行冻结正式 recipe/campaign identity、样本计划和 checkpoint policy；不得
沿用本报告把资格 probe 重标为 pilot adapter 或 production training。
