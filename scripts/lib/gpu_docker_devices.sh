#!/usr/bin/env bash

# Resolve scheduler-visible GPU indices to stable UUIDs before crossing the host Docker daemon.
# LSF may cgroup-filter and renumber devices inside an allocation while Docker interprets numeric
# --gpus device IDs in the daemon's host-global namespace.
resolve_docker_gpu_device_ids() {
  if [[ $# -ne 1 || ! $1 =~ ^[0-9]+(,[0-9]+)*$ ]]; then
    echo "scheduler GPU IDs must be a comma-separated numeric list" >&2
    return 2
  fi
  local requested=$1
  local query
  if ! query=$(nvidia-smi --query-gpu=index,uuid --format=csv,noheader,nounits); then
    echo "cannot query scheduler-visible GPU UUIDs" >&2
    return 2
  fi
  local resolved=
  local remaining=$requested
  local requested_id
  local index
  local uuid
  local candidate_uuid
  local line
  while :; do
    requested_id=${remaining%%,*}
    if [[ $remaining == *,* ]]; then
      remaining=${remaining#*,}
    else
      remaining=
    fi
    uuid=
    while IFS= read -r line; do
      IFS=',' read -r index candidate_uuid <<<"$line"
      index=${index//[[:space:]]/}
      candidate_uuid=${candidate_uuid//[[:space:]]/}
      if [[ $index == "$requested_id" ]]; then
        uuid=$candidate_uuid
        break
      fi
    done <<<"$query"
    if [[ ! $uuid =~ ^GPU-[0-9A-Fa-f-]{32,64}$ ]]; then
      echo "scheduler GPU index has no canonical visible UUID" >&2
      return 2
    fi
    if [[ ,$resolved, == *,$uuid,* ]]; then
      echo "scheduler GPU indices resolve to duplicate UUIDs" >&2
      return 2
    fi
    if [[ -n $resolved ]]; then
      resolved+=,
    fi
    resolved+=$uuid
    if [[ -z $remaining ]]; then
      break
    fi
  done
  printf '%s\n' "$resolved"
}
