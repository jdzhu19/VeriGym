#!/usr/bin/env bash
set -euo pipefail

if [[ ${VERIGYM_RUN_QWEN35_VLLM_SERVICE:-} != 1 ]]; then
  echo "VERIGYM_RUN_QWEN35_VLLM_SERVICE=1 is required" >&2
  exit 2
fi
if [[ $# -ne 9 ]]; then
  echo "usage: $0 IMAGE_ID MODEL_ROOT CACHE_ROOT EMPTY_HOME NETWORK PORT BASE_MODEL_ID ADAPTER_ROOT_OR_DASH SERVED_MODEL_ID" >&2
  exit 2
fi

image_id=$1
for path in "$2" "$3" "$4"; do
  if [[ -L $path ]]; then
    echo "service mounts cannot be symlinks" >&2
    exit 2
  fi
done
model_root=$(realpath "$2")
cache_root=$(realpath "$3")
empty_home=$(realpath "$4")
network_name=$5
port=$6
base_model_id=$7
adapter_input=$8
served_model_id=$9
gpu_devices=${VERIGYM_GPU_DEVICE_IDS:-}
seccomp_arguments=()
case ${VERIGYM_GPU_DOCKER_SECCOMP_PROFILE:-default} in
  default) ;;
  unconfined) seccomp_arguments=(--security-opt seccomp=unconfined) ;;
  *)
    echo "VERIGYM_GPU_DOCKER_SECCOMP_PROFILE must be 'default' or 'unconfined'" >&2
    exit 2
    ;;
esac

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
if [[ ! $base_model_id =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$ ]] || \
  [[ ! $served_model_id =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$ ]]; then
  echo "base or served model ID contains unsafe characters" >&2
  exit 2
fi
adapter_arguments=()
adapter_mount=()
if [[ $adapter_input == - ]]; then
  if [[ $served_model_id != "$base_model_id" ]]; then
    echo "base service must use the base model identity" >&2
    exit 2
  fi
else
  if [[ -L $adapter_input || ! -d $adapter_input ]]; then
    echo "adapter root must be a real directory or '-'" >&2
    exit 2
  fi
  adapter_root=$(realpath "$adapter_input")
  if [[ $served_model_id == "$base_model_id" ]]; then
    echo "adapter service identity must differ from the base model identity" >&2
    exit 2
  fi
  adapter_mount=(--volume "$adapter_root:/adapter:ro")
  adapter_arguments=(--enable-lora --lora-modules "$served_model_id=/adapter")
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
  "${seccomp_arguments[@]}" \
  --user "$(id -u):$(id -g)" \
  --env HOME=/work/home \
  --env HF_HUB_OFFLINE=1 \
  --env TRANSFORMERS_OFFLINE=1 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8g \
  --volume "$empty_home:/work/home" \
  --volume "$model_root:/model:ro" \
  --volume "$cache_root:/cache" \
  "${adapter_mount[@]}" \
  "$image_id" \
  python3 -m vllm.entrypoints.openai.api_server \
  --model /model \
  --served-model-name "$base_model_id" \
  "${adapter_arguments[@]}" \
  --tensor-parallel-size 4 \
  --host 0.0.0.0 \
  --port 8000
