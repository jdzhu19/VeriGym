#!/usr/bin/env bash
set -euo pipefail

mode=${1:-execute}
case "$mode" in
  identity|preflight|execute) ;;
  *) echo "invalid heldout adapter recovery mode" >&2; exit 64 ;;
esac

stage=/hpc/home/connect.jzhu484/agent/.verigym-tmp/hwe-heldout-k1-v8
assets_stage=/hpc/home/connect.jzhu484/agent/.verigym-tmp/hwe-heldout-k1-v1
repository=$stage/source-snapshot
base=/hpc/home/connect.jzhu484/agent/.verigym-tmp/hwe-sft64k-v4
qualification=$assets_stage/qualification
image_lock=$assets_stage/image-locks/pr-2944.json
adapter_execution=/hpc/home/connect.jzhu484/agent/experiments/cva6-hwe-deepseek-harness-v1/development-training-v1/adapter-native-canary-s484-execution-v1
prior_execution=/hpc/home/connect.jzhu484/agent/experiments/cva6-hwe-deepseek-harness-v1/development-training-v1/adapter-native-canary-s484-heldout-k1-execution-v8
prereg=/hpc/home/connect.jzhu484/agent/experiments/cva6-hwe-deepseek-harness-v1/development-training-v1/adapter-native-canary-s484-heldout-adapter-recovery-preregistration-v4
execution=/hpc/home/connect.jzhu484/agent/experiments/cva6-hwe-deepseek-harness-v1/development-training-v1/adapter-native-canary-s484-heldout-adapter-recovery-execution-v1
python=$base/venv/bin/python
rootfs=/hpc/home/connect.jzhu484/agent/deps/ubuntu-20.04-rootfs
node_tmp=/tmp/466876.tmpdir/.verigym-tmp/hwe-heldout-k1-v8
wheel=/hpc/home/connect.jzhu484/agent/datasets/wheelhouse/hwe-heldout-k1-v1/tiktoken-0.7.0-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
tiktoken_overlay=$stage/tiktoken-overlay
authorization=$prereg/heldout-adapter-recovery-authorization.json
model=/hpc/home/connect.jzhu484/agent/datasets/Qwen3.5-9B
adapter=$adapter_execution/lora_adapter
adapter_report=$adapter_execution/adapter-native-canary-report.json
prior_report=$prior_execution/heldout-report.json

unset LD_PRELOAD
export LD_LIBRARY_PATH="/hpc/home/connect.jzhu484/miniconda3/envs/agent/lib:/usr/lib64:/lib64"

test "${LSB_JOBID:-}" = 466876
test "$(hostname -s)" = gpu03
test "$(sha256sum "$python" | awk '{print $1}')" = ffa11dc20f5f7be4d7ce6591777ca2552ba31704e7662cdeb62d0629dd5b9b7e
test "$(cat "$rootfs/.export-complete")" = sha256:f78909c2b360d866b3220655c0b079838258b8891a12ac25fc670f0cbb54229f
test -f "$authorization"
test -f "$prior_report"
test -f "$adapter/adapter_model.safetensors"
test "$(sha256sum "$wheel" | awk '{print $1}')" = 86b6e7dc2e7ad1b3757e8a24597415bafcfb454cebf9a33a01f2e6ba2e663992
test -f "$qualification/task-split.json"
test -f "$qualification/qualification-progress.json"
test -d "$qualification/sources/pr-2944"
test ! -e "$prereg/heldout-execution-started.json"
test ! -e "$execution"

mkdir -p "$stage/process-scratch" "$node_tmp"
chmod 700 "$node_tmp"
if test ! -d "$tiktoken_overlay/tiktoken"; then
  mkdir -p "$tiktoken_overlay"
  "$python" -m zipfile -e "$wheel" "$tiktoken_overlay"
fi
export PATH="${python%/*}:/usr/bin:/bin"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$tiktoken_overlay:$repository/scripts:$repository/src:$repository/integrations/verigym-training-reference/src:$repository/integrations/verigym-deepseek-harness/src:$repository/integrations/verigym-hwe-bench/src:$base/overlay3:$base/transformers-source/src:$base/torch-overlay:$base/dependency-overlay"
export LD_LIBRARY_PATH="$base/runtime-base/conda/lib:/hpc/home/connect.jzhu484/miniconda3/envs/agent/lib:$rootfs/lib/x86_64-linux-gnu:$rootfs/usr/lib/x86_64-linux-gnu:/usr/lib64"
export TMPDIR="$node_tmp"
export TEMP="$node_tmp"
export TMP="$node_tmp"
export TOKENIZERS_PARALLELISM=false
export CUDA_VISIBLE_DEVICES=0,1,2,3
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
test "$("$python" -c 'import importlib.metadata; print(importlib.metadata.version("tiktoken"))')" = 0.7.0

if test "$mode" = identity; then
  "$python" -c 'import torch, verigym, verigym_training_reference, verigym_deepseek_harness, verigym_hwe_bench; print(torch.__version__); print(verigym.__file__)'
  (unset LD_LIBRARY_PATH; /usr/bin/docker version --format '{{.Server.Version}}')
  exit 0
fi

"$python" - <<PY
from pathlib import Path
import importlib.util
p = Path("$repository/scripts/run_hwe_deepseek_heldout_adapter_recovery_v1.py")
spec = importlib.util.spec_from_file_location("heldout_recovery_runner", p)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
a = m._authorization(Path("$authorization"))
m.original._validate_sources(Path("$repository").resolve(strict=True), a)
print(a["authorization_hash"])
PY

if test "$mode" = preflight; then
  (unset LD_LIBRARY_PATH; /usr/bin/docker image inspect sha256:5b95472e7fbfa80eb0cf173099254ef5285fcd78f7c3c78b42678ae9181dd96e >/dev/null)
  (unset LD_LIBRARY_PATH; /usr/bin/docker image inspect sha256:d20ffcf6ba42570d225ec9fe0757f501f654c222250c83e3fd83ab70918834e3 >/dev/null)
  (unset LD_LIBRARY_PATH; /usr/bin/docker image inspect sha256:91a135852c3ab371c24e2f49fad382568ffb830167d3c26006c26f88fe190b6a >/dev/null)
  (unset LD_LIBRARY_PATH; nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader)
  exit 0
fi

"$python" "$repository/scripts/run_hwe_deepseek_heldout_adapter_recovery_v1.py" \
  --authorization "$authorization" \
  --adapter-report "$adapter_report" \
  --prior-heldout-report "$prior_report" \
  --qualification-root "$qualification" \
  --image-lock "$image_lock" \
  --model-root "$model" \
  --adapter-root "$adapter" \
  --repository-root "$repository" \
  --scratch-root "$stage/process-scratch" \
  --output "$execution" \
  --campaign-id cva6-hwe-qwen35-sft-heldout-adapter-recovery-v1
