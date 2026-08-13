#!/usr/bin/env bash
set -euo pipefail

if [[ ${VERIGYM_RUN_QWEN35_RLLM_MULTITURN_SMOKE:-} != 1 ]]; then
  echo "VERIGYM_RUN_QWEN35_RLLM_MULTITURN_SMOKE=1 is required" >&2
  exit 2
fi
if [[ $# -ne 9 ]]; then
  echo "usage: $0 IMAGE_ID TASK BROKER_ROOT MODEL_ROOT OUTPUT_PARENT CACHE_ROOT EMPTY_HOME NETWORK MODEL_ID" >&2
  exit 2
fi

image_id=$1
for path in "$2" "$3" "$4" "$5" "$6" "$7"; do
  if [[ -L $path ]]; then
    echo "rLLM smoke inputs and mounts cannot be symlinks" >&2
    exit 2
  fi
done
task=$(realpath "$2")
broker_root=$(realpath "$3")
model_root=$(realpath "$4")
output_parent=$(realpath "$5")
cache_root=$(realpath "$6")
empty_home=$(realpath "$7")
network_name=$8
model_id=$9
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
  echo "rLLM smoke image must be an exact local Docker image ID" >&2
  exit 2
fi
if [[ -L $task || ! -f $task ]]; then
  echo "rLLM smoke task must be a regular non-symlink file" >&2
  exit 2
fi
for path in "$broker_root" "$model_root" "$output_parent" "$cache_root" "$empty_home"; do
  if [[ -L $path || ! -d $path ]]; then
    echo "all rLLM smoke mounts must be existing non-symlink directories" >&2
    exit 2
  fi
done
if [[ -n $(find "$empty_home" -mindepth 1 -maxdepth 1 -print -quit) ]]; then
  echo "rLLM smoke synthetic home must be empty" >&2
  exit 2
fi
mkdir -p "$cache_root/tmp"
if [[ -L $cache_root/tmp || ! -d $cache_root/tmp ]]; then
  echo "rLLM smoke cache temporary directory is unsafe" >&2
  exit 2
fi
if [[ -e "$output_parent/native-smoke" || -L "$output_parent/native-smoke" ]]; then
  echo "rLLM native smoke output already exists" >&2
  exit 2
fi
if [[ ! $network_name =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$ ]] || \
  [[ $network_name == bridge || $network_name == host || $network_name == none ]] || \
  [[ $(docker network inspect "$network_name" --format '{{.Driver}}') != bridge ]]; then
  echo "rLLM smoke requires the vLLM service user-defined bridge" >&2
  exit 2
fi
if [[ ! $model_id =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$ ]]; then
  echo "model ID contains unsafe characters" >&2
  exit 2
fi

docker run --rm \
  --network "$network_name" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  ${seccomp_arguments[@]+"${seccomp_arguments[@]}"} \
  --pids-limit 2048 \
  --user "$(id -u):$(id -g)" \
  --env HOME=/work/home \
  --env LOGNAME=verigym \
  --env USER=verigym \
  --env TMPDIR=/cache/tmp \
  --env OPENBLAS_NUM_THREADS=1 \
  --env OMP_NUM_THREADS=1 \
  --env MKL_NUM_THREADS=1 \
  --env NUMEXPR_NUM_THREADS=1 \
  --env VERIGYM_RUN_QWEN35_RLLM_MULTITURN_SMOKE=1 \
  --env VERIGYM_MODEL_BASE_URL=http://verigym-qwen35-vllm:8000/v1 \
  --env VERIGYM_MODEL_API_KEY=local-verigym-no-auth \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=1g \
  --volume "$empty_home:/work/home" \
  --volume "$task:/input/task.json:ro" \
  --volume "$broker_root:/broker" \
  --volume "$model_root:/model:ro" \
  --volume "$output_parent:/output" \
  --volume "$cache_root:/cache" \
  "$image_id" \
  python3 /opt/verigym/bin/smoke_qwen35_rllm_multiturn.py \
  --task /input/task.json \
  --broker-root /broker \
  --model-root /model \
  --model-id "$model_id" \
  --rllm-source /opt/rllm \
  --output /output/native-smoke
