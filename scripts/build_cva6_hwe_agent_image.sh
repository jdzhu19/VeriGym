#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 ABSOLUTE_CODEX_BINARY VERIFIER_IMAGE_ID TASK_ID IMAGE_TAG OUTPUT_JSON" >&2
  exit 2
fi

codex_binary=$1
verifier_image_id=$2
task_id=$3
image_tag=$4
output_json=$5
repository_root=$(git rev-parse --show-toplevel)
dockerfile=$repository_root/docker/codex-cva6-hwe-agent/Dockerfile
sanitizer=$repository_root/scripts/sanitize_docker_image_environment.py
expected_codex_sha256=cb0a15567e9a60a5820d54b0f6ae86d504dc3805c1eab21a47f70e3eb7b73a40
expected_rg_sha256=e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849
agent_uid=$(id -u)
agent_gid=$(id -g)
build_tag=${image_tag}-unsanitized

if [[ $agent_uid == 0 || $agent_gid == 0 ]]; then
  echo "HWE agent images require a non-root host UID:GID" >&2
  exit 1
fi

if [[ $codex_binary != /* || ! -f $codex_binary || ! -x $codex_binary || -L $codex_binary ]]; then
  echo "Codex binary must be an executable absolute non-symlink native-file path" >&2
  exit 2
fi
if [[ ! $verifier_image_id =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "Verifier image must be an immutable sha256 image ID" >&2
  exit 2
fi
if [[ ! $task_id =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$ ]]; then
  echo "Task ID is not portable" >&2
  exit 2
fi
if [[ $output_json != /* || -e $output_json ]]; then
  echo "Output JSON must be a new absolute path" >&2
  exit 2
fi
if docker image inspect "$image_tag" >/dev/null 2>&1 \
  || docker image inspect "$build_tag" >/dev/null 2>&1; then
  echo "Final or intermediate HWE agent image tag already exists" >&2
  exit 2
fi
if [[ $("$codex_binary" --version) != "codex-cli 0.147.0" ]]; then
  echo "Codex CLI identity differs from the frozen 0.147.0 collection identity" >&2
  exit 1
fi

# Inspect only: a missing local image fails closed and is never pulled.
observed_base_id=$(docker image inspect "$verifier_image_id" --format '{{.Id}}')
if [[ $observed_base_id != "$verifier_image_id" ]]; then
  echo "Local verifier image identity changed" >&2
  exit 1
fi
local_base_reference=$(
  docker image inspect "$verifier_image_id" --format '{{range .RepoTags}}{{println .}}{{end}}' \
    | awk 'NF && $0 != "<none>:<none>" {print; exit}'
)
if [[ -z $local_base_reference ]]; then
  echo "Verifier image has no existing local tag for offline BuildKit resolution" >&2
  exit 1
fi

codex_sha256=$(sha256sum "$codex_binary" | awk '{print $1}')
if [[ $codex_sha256 != "$expected_codex_sha256" ]]; then
  echo "Codex 0.147.0 native binary SHA-256 differs from the frozen campaign identity" >&2
  exit 1
fi
rg_binary=$(dirname "$codex_binary")/../codex-path/rg
rg_binary=$(realpath "$rg_binary")
if [[ ! -f $rg_binary || ! -x $rg_binary || -L $rg_binary ]]; then
  echo "Codex native bundle does not contain its sibling ripgrep executable" >&2
  exit 1
fi
rg_sha256=$(sha256sum "$rg_binary" | awk '{print $1}')
if [[ $rg_sha256 != "$expected_rg_sha256" ]]; then
  echo "Codex 0.147.0 ripgrep SHA-256 differs from the frozen campaign identity" >&2
  exit 1
fi
scratch_parent=/data/jzhu484/Agent/.verigym-tmp
mkdir -p "$scratch_parent"
build_context=$(mktemp -d "$scratch_parent/verigym-cva6-hwe-image.XXXXXXXX")
cleanup() {
  case "$build_context" in
    "$scratch_parent"/verigym-cva6-hwe-image.*) rm -rf -- "$build_context" ;;
    *) echo "refusing to remove unexpected build context" >&2 ;;
  esac
}
trap cleanup EXIT
install -m 0755 "$codex_binary" "$build_context/codex"
install -m 0755 "$rg_binary" "$build_context/rg"

DOCKER_BUILDKIT=1 docker build \
  --network none \
  --build-arg "CVA6_VERIFIER_BASE=$local_base_reference" \
  --build-arg "CVA6_VERIFIER_BASE_ID=$verifier_image_id" \
  --build-arg "CODEX_SHA256=$codex_sha256" \
  --build-arg "RG_SHA256=$rg_sha256" \
  --build-arg "HWE_TASK_ID=$task_id" \
  --build-arg "AGENT_UID=$agent_uid" \
  --build-arg "AGENT_GID=$agent_gid" \
  --file "$dockerfile" \
  --tag "$build_tag" \
  "$build_context"

unsanitized_image_id=$(docker image inspect "$build_tag" --format '{{.Id}}')
sanitized_result=$(
  python "$sanitizer" \
    --image-id "$unsanitized_image_id" \
    --output-tag "$image_tag" \
    --user "$agent_uid:$agent_gid" \
    --environment 'PATH=/tools/verilator/bin:/opt/iverilog/bin:/usr/local/bin:/usr/bin:/bin' \
    --environment 'HOME=/tmp/verigym-home' \
    --environment 'LANG=C.UTF-8' \
    --environment 'LC_ALL=C.UTF-8' \
    --environment 'TMPDIR=/tmp'
)
derived_image_id=$(python -c 'import json,sys; print(json.loads(sys.argv[1])["image_id"])' \
  "$sanitized_result")
if [[ $(docker image inspect "$local_base_reference" --format '{{.Id}}') != "$verifier_image_id" ]]; then
  echo "Local verifier image tag changed during the HWE agent build" >&2
  exit 1
fi
if [[ ! $derived_image_id =~ ^sha256:[0-9a-f]{64}$ || $derived_image_id == "$verifier_image_id" ]]; then
  echo "Derived HWE agent image identity is invalid" >&2
  exit 1
fi

mkdir -p "$(dirname "$output_json")"
sanitizer_sha256=$(sha256sum "$sanitizer" | awk '{print $1}')
python - "$output_json" "$task_id" "$verifier_image_id" "$derived_image_id" \
  "$unsanitized_image_id" "$codex_sha256" "$rg_sha256" "$sanitizer_sha256" <<'PY'
import json
import os
import sys
from pathlib import Path

(
    output,
    task_id,
    base_id,
    agent_id,
    unsanitized_image_id,
    codex_sha256,
    rg_sha256,
    sanitizer_sha256,
) = sys.argv[1:]
payload = {
    "format_id": "verigym_hwe_agent_image_build_receipt_v2",
    "task_id": task_id,
    "verifier_base_image_id": base_id,
    "derived_agent_image_id": agent_id,
    "unsanitized_agent_image_id": unsanitized_image_id,
    "codex_version": "codex-cli 0.147.0",
    "agent_codex_sha256": codex_sha256,
    "agent_rg_sha256": rg_sha256,
    "build_network": "none",
    "source_whiteout_path": "/home/cva6",
    "visible_workspace_path": "/workspace/repository",
    "collection_profile_id": "hwe_standard_v2",
    "tool_contract_id": "hwe_native_shell_v2",
    "container_read_scope": "isolated_agent_container",
    "configuration_sanitizer_sha256": sanitizer_sha256,
    "exact_image_environment": [
        "PATH=/tools/verilator/bin:/opt/iverilog/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME=/tmp/verigym-home",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "TMPDIR=/tmp",
    ],
}
target = Path(output)
temporary = target.with_name(f".{target.name}.tmp")
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    json.dump(payload, stream, sort_keys=True, indent=2)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, target)
PY
