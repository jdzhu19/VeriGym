#!/usr/bin/env bash
set -euo pipefail

if [[ ${VERIGYM_RUN_QWEN35_VLLM_SERVICE:-} != 1 ]]; then
  echo "VERIGYM_RUN_QWEN35_VLLM_SERVICE=1 is required" >&2
  exit 2
fi
if [[ $# -ne 7 ]]; then
  echo "usage: $0 IMAGE_ID MODEL_ROOT CACHE_ROOT EMPTY_HOME NETWORK PORT MODEL_ID" >&2
  exit 2
fi

image_id=$1
model_root=$(realpath "$2")
cache_root=$(realpath "$3")
empty_home=$(realpath "$4")
network_name=$5
port=$6
model_id=$7
gpu_devices=${VERIGYM_GPU_DEVICE_IDS:-}

if [[ ! $image_id =~ ^sha256:[0-9a-f]{64}$ ]] || \
  [[ $(docker image inspect "$image_id" --format '{{.Id}}') != "$image_id" ]]; then
  echo "vLLM service image must be an exact local Docker image ID" >&2
  exit 2
fi
if [[ ! $gpu_devices =~ ^[0-9]+,[0-9]+,[0-9]+,[0-9]+$ ]] || \
  [[ $(tr ',' '\n' <<<"$gpu_devices" | sort -u | wc -l) -ne 4 ]]; then
  echo "VERIGYM_GPU_DEVICE_IDS must name four distinct assigned GPU indices" >&2
  exit 2
fi
if [[ -z ${CUDA_VISIBLE_DEVICES:-} ]] || [[ $CUDA_VISIBLE_DEVICES != "$gpu_devices" ]]; then
  echo "explicit service GPU IDs must match the LSF CUDA_VISIBLE_DEVICES allocation" >&2
  exit 2
fi
for path in "$model_root" "$cache_root" "$empty_home"; do
  if [[ -L $path || ! -d $path ]]; then
    echo "all service mounts must be existing non-symlink directories" >&2
    exit 2
  fi
done
if [[ -n $(find "$empty_home" -mindepth 1 -maxdepth 1 -print -quit) ]]; then
  echo "vLLM service synthetic home must be empty" >&2
  exit 2
fi
if [[ ! $network_name =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$ ]] || \
  [[ $network_name == bridge || $network_name == host || $network_name == none ]] || \
  [[ $(docker network inspect "$network_name" --format '{{.Driver}}') != bridge ]]; then
  echo "service requires an existing dedicated user-defined bridge" >&2
  exit 2
fi
if [[ ! $port =~ ^[0-9]{2,5}$ ]] || ((port < 1024 || port > 65535)); then
  echo "service port must be between 1024 and 65535" >&2
  exit 2
fi
if [[ ! $model_id =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$ ]]; then
  echo "model ID contains unsafe characters" >&2
  exit 2
fi

docker run --rm \
  --name verigym-qwen35-vllm \
  --network "$network_name" \
  --publish "127.0.0.1:$port:8000" \
  --gpus "\"device=$gpu_devices\"" \
  --shm-size 16g \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --env HOME=/work/home \
  --env HF_HUB_OFFLINE=1 \
  --env TRANSFORMERS_OFFLINE=1 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8g \
  --volume "$empty_home:/work/home" \
  --volume "$model_root:/model:ro" \
  --volume "$cache_root:/cache" \
  "$image_id" \
  python3 -m vllm.entrypoints.openai.api_server \
  --model /model \
  --served-model-name "$model_id" \
  --tensor-parallel-size 4 \
  --host 0.0.0.0 \
  --port 8000
