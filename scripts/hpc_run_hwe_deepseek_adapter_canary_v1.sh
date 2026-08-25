#!/usr/bin/env bash
set -euo pipefail

mode=${1:-execute}
case "$mode" in
  identity|preflight|execute) ;;
  *) echo "invalid adapter canary mode" >&2; exit 64 ;;
esac

stage=/hpc/home/connect.jzhu484/agent/.verigym-tmp/hwe-adapter-canary-v1
repository=$stage/source-snapshot
base=/hpc/home/connect.jzhu484/agent/.verigym-tmp/hwe-sft64k-v4
old_prereg=/hpc/home/connect.jzhu484/agent/experiments/cva6-hwe-deepseek-harness-v1/development-training-v1/canary-32step-s484-preregistration
old_execution=/hpc/home/connect.jzhu484/agent/experiments/cva6-hwe-deepseek-harness-v1/development-training-v1/canary-32step-s484-execution-v1
prereg=/hpc/home/connect.jzhu484/agent/experiments/cva6-hwe-deepseek-harness-v1/development-training-v1/adapter-native-canary-s484-preregistration-v4
execution=/hpc/home/connect.jzhu484/agent/experiments/cva6-hwe-deepseek-harness-v1/development-training-v1/adapter-native-canary-s484-execution-v1
qualification=/hpc/home/connect.jzhu484/agent/experiments/cva6-hwe-deepseek-harness-v1/optimizer-smoke-v1/checkpoint-resume-replay-v5
python=$base/venv/bin/python
rootfs=/hpc/home/connect.jzhu484/agent/deps/ubuntu-20.04-rootfs
nccl=/hpc/home/connect.jzhu484/agent/deps/nccl-build-cuda124-host-glibc217-v2.27.5-1/lib/libnccl.so.2.27.5
triton_cc=$base/triton-cc-launcher
triton_ptxas=$base/triton-ptxas-launcher
config=$repository/configs/training/qwen35_hwe_deepseek_harness_development_training_v1.json
receipt=$old_prereg/canary-preregistration-receipt.json
predecessor=$old_execution/development-canary-execution-report.json
authorization=$prereg/adapter-execution-authorization.json
checkpoint=$execution/temporary-fsdp2-checkpoints
evidence=$execution/canary-evidence
report=$execution/adapter-native-canary-report.json

unset LD_PRELOAD
export LD_LIBRARY_PATH="/hpc/home/connect.jzhu484/miniconda3/envs/agent/lib:/usr/lib64:/lib64"

test "${LSB_JOBID:-}" = 466876
test "$(hostname -s)" = gpu03
test "$(sha256sum "$python" | awk '{print $1}')" = ffa11dc20f5f7be4d7ce6591777ca2552ba31704e7662cdeb62d0629dd5b9b7e
test "$(sha256sum "$nccl" | awk '{print $1}')" = 1373b0e1daeffa33c03af204321a8927878e483957900b5cd6a52c6b50eaa6cd
test "$(sha256sum "$config" | awk '{print $1}')" = cd100345df85de8073fd7fd201ddec7bdcfd47811c18e9442b96306330c9b997
test "$(sha256sum "$receipt" | awk '{print $1}')" = 047304efef82c1d95bd4fffb74fb4c75f27374e7e31b4a4fb061df7bee395d95
test "$(sha256sum "$base/dataset/dataset-manifest.json" | awk '{print $1}')" = 60b1f2646c238efa2197d89c98875c1587a3be16e1c051f2227c3a22b8ae4fac
test "$(sha256sum "$base/dataset/train.jsonl" | awk '{print $1}')" = cab55d3cc7752b971904c88d8c11e93645c0b215af9beec40dd648bcfe7f1aa1
test "$(cat "$rootfs/.export-complete")" = sha256:f78909c2b360d866b3220655c0b079838258b8891a12ac25fc670f0cbb54229f
test ! -e "$execution"
test ! -e "$prereg/adapter-execution-started.json"

mkdir -p "$stage/nccl-overlay" "$stage/process-tmp" "$stage/process-scratch"
if test ! -e "$stage/nccl-overlay/libnccl.so.2"; then
  ln -s "$nccl" "$stage/nccl-overlay/libnccl.so.2"
fi
test "$(readlink -f "$stage/nccl-overlay/libnccl.so.2")" = "$nccl"

export CC="$triton_cc"
export PATH="${python%/*}:/usr/bin:/bin"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$repository/src:$repository/integrations/verigym-training-reference/src:$base/overlay3:$base/rllm-source:$base/transformers-source/src:$base/torch-overlay:$base/dependency-overlay"
export LD_LIBRARY_PATH="$stage/nccl-overlay:$base/runtime-base/conda/lib:/hpc/home/connect.jzhu484/miniconda3/envs/agent/lib:$rootfs/lib/x86_64-linux-gnu:$rootfs/usr/lib/x86_64-linux-gnu:/usr/lib64"
export TMPDIR="$stage/process-tmp"
export TEMP="$stage/process-tmp"
export TMP="$stage/process-tmp"
export TRITON_CACHE_DIR="$base/preflight-cache16/triton"
export TORCHINDUCTOR_CACHE_DIR="$base/preflight-cache16/inductor"
export TRITON_PTXAS_PATH="$triton_ptxas"
export CUDA_VISIBLE_DEVICES=0,1,2,3
export CUDA_DEVICE_MAX_CONNECTIONS=1
export TOKENIZERS_PARALLELISM=false
export NCCL_DEBUG=WARN
export TORCH_NCCL_ASYNC_ERROR_HANDLING=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

if test "$mode" = identity; then
  "$python" -c 'import torch, verigym, verigym_training_reference; print(torch.__version__); print(verigym.__file__); print(verigym_training_reference.__file__)'
  exit 0
fi

"$python" - <<PY
from pathlib import Path
from verigym.hwe.deepseek_harness_adapter_canary import load_adapter_canary_authorization, validate_adapter_canary_authorization
a = load_adapter_canary_authorization(Path("$authorization"))
validate_adapter_canary_authorization(
    a,
    config_path=Path("$config"),
    preregistration_receipt_path=Path("$receipt"),
    predecessor_execution_report_path=Path("$predecessor"),
    dataset_root=Path("$base/dataset"),
    model_root=Path("/hpc/home/connect.jzhu484/agent/datasets/Qwen3.5-9B"),
    repository_root=Path("$repository"),
    qualification_root=Path("$qualification"),
)
print(a.authorization_hash)
PY

if test "$mode" = preflight; then
  exit 0
fi

"$python" "$repository/scripts/run_hwe_deepseek_adapter_canary_v1.py" \
  --config "$config" \
  --preregistration-receipt "$receipt" \
  --predecessor-execution-report "$predecessor" \
  --authorization "$authorization" \
  --dataset-root "$base/dataset" \
  --model-root /hpc/home/connect.jzhu484/agent/datasets/Qwen3.5-9B \
  --repository-root "$repository" \
  --qualification-root "$qualification" \
  --scratch-root "$stage/process-scratch" \
  --checkpoint-root "$checkpoint" \
  --evidence-root "$evidence" \
  --report "$report" \
  --rllm-source "$base/rllm-source" \
  --verl-source "$base/verl-source" \
  --transformers-source "$base/transformers-source"
