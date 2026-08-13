#!/usr/bin/env bash
set -euo pipefail

if [[ ${VERIGYM_RUN_QWEN35_MULTITURN_SFT:-} != 1 ]]; then
  echo "VERIGYM_RUN_QWEN35_MULTITURN_SFT=1 is required" >&2
  exit 2
fi
if [[ $# -ne 6 ]]; then
  echo "usage: $0 IMAGE_ID MODEL_ROOT DATASET_ROOT OUTPUT_ROOT CACHE_ROOT EMPTY_HOME" >&2
  exit 2
fi

image_id=$1
for path in "$2" "$3" "$4" "$5" "$6"; do
  if [[ -L $path ]]; then
    echo "trainer mounts cannot be symlinks" >&2
    exit 2
  fi
done
model_root=$(realpath "$2")
dataset_root=$(realpath "$3")
output_root=$(realpath "$4")
cache_root=$(realpath "$5")
empty_home=$(realpath "$6")
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
  echo "trainer image must be an exact local Docker image ID" >&2
  exit 2
fi
if [[ ! $gpu_devices =~ ^[0-9]+,[0-9]+,[0-9]+,[0-9]+$ ]] || \
  [[ $(tr ',' '\n' <<<"$gpu_devices" | sort -u | wc -l) -ne 4 ]]; then
  echo "VERIGYM_GPU_DEVICE_IDS must name four distinct assigned GPU indices" >&2
  exit 2
fi
if [[ -z ${CUDA_VISIBLE_DEVICES:-} ]] || [[ $CUDA_VISIBLE_DEVICES != "$gpu_devices" ]]; then
  echo "explicit container GPU IDs must match the LSF CUDA_VISIBLE_DEVICES allocation" >&2
  exit 2
fi
for path in "$model_root" "$dataset_root" "$output_root" "$cache_root" "$empty_home"; do
  if [[ -L $path || ! -d $path ]]; then
    echo "all trainer mounts must be existing non-symlink directories" >&2
    exit 2
  fi
done
if [[ -n $(find "$empty_home" -mindepth 1 -maxdepth 1 -print -quit) ]]; then
  echo "trainer synthetic home must be empty" >&2
  exit 2
fi
mkdir -p "$cache_root/tmp"
if [[ -L $cache_root/tmp || ! -d $cache_root/tmp ]]; then
  echo "trainer cache temporary directory is unsafe" >&2
  exit 2
fi

docker run --rm \
  --network none \
  --gpus "\"device=$gpu_devices\"" \
  --shm-size 16g \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  ${seccomp_arguments[@]+"${seccomp_arguments[@]}"} \
  --pids-limit 8192 \
  --user "$(id -u):$(id -g)" \
  --env HOME=/work/home \
  --env LOGNAME=verigym \
  --env USER=verigym \
  --env TMPDIR=/cache/tmp \
  --env VERIGYM_RUN_QWEN35_MULTITURN_SFT=1 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=1g \
  --volume "$empty_home:/work/home" \
  --volume "$model_root:/model:ro" \
  --volume "$dataset_root:/dataset:ro" \
  --volume "$output_root:/output" \
  --volume "$cache_root:/cache" \
  "$image_id" \
  python3 /opt/verigym/bin/train_qwen35_multiturn_sft.py \
  --dataset /dataset \
  --model-root /model \
  --output /output \
  --rllm-source /opt/rllm
