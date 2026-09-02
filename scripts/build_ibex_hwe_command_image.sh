#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 6 || $# -gt 7 ]]; then
  echo "usage: $0 ABSOLUTE_RG_BINARY ABSOLUTE_RG_RELEASE_ARCHIVE VERIFIER_IMAGE_ID TASK_ID IMAGE_TAG OUTPUT_JSON [iverilog|verilator]" >&2
  exit 2
fi

rg_binary=$1
rg_release_archive=$2
verifier_image_id=$3
task_id=$4
image_tag=$5
output_json=$6
ibex_toolchain_profile=${7:-iverilog}
repository_root=$(git rev-parse --show-toplevel)
dockerfile=$repository_root/docker/ibex-hwe-command/Dockerfile
sanitizer=$repository_root/scripts/sanitize_docker_image_environment.py
command_uid=$(id -u)
command_gid=$(id -g)
build_tag=${image_tag}-unsanitized
expected_rg_version='ripgrep 15.2.0 (rev e89fff89ac)'
expected_rg_sha256=e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849
expected_rg_release_archive_sha256=33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c
rg_release_member=ripgrep-15.2.0-x86_64-unknown-linux-musl/rg

if [[ $command_uid == 0 || $command_gid == 0 ]]; then
  echo "HWE command images require a non-root host UID:GID" >&2
  exit 1
fi
if [[ $rg_binary != /* || ! -f $rg_binary || ! -x $rg_binary || -L $rg_binary ]]; then
  echo "ripgrep binary must be an executable absolute non-symlink path" >&2
  exit 2
fi
if [[ $rg_release_archive != /* || ! -f $rg_release_archive || -L $rg_release_archive ]]; then
  echo "ripgrep release archive must be an absolute regular non-symlink path" >&2
  exit 2
fi
case "$rg_binary:$rg_release_archive" in
  *'/@openai/codex/'*|*'/codex-path/'*)
    echo "ripgrep must come from an independently acquired release, not a Codex bundle" >&2
    exit 2
    ;;
esac
if [[ ! $verifier_image_id =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "Verifier image must be an immutable sha256 image ID" >&2
  exit 2
fi
if [[ ! $task_id =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$ ]]; then
  echo "Task ID is not portable" >&2
  exit 2
fi
if [[ $ibex_toolchain_profile != iverilog && $ibex_toolchain_profile != verilator ]]; then
  echo "Ibex toolchain profile must be iverilog or verilator" >&2
  exit 2
fi
if [[ $output_json != /* || -e $output_json ]]; then
  echo "Output JSON must be a new absolute path" >&2
  exit 2
fi
if docker image inspect "$image_tag" >/dev/null 2>&1 \
  || docker image inspect "$build_tag" >/dev/null 2>&1; then
  echo "Final or intermediate HWE command image tag already exists" >&2
  exit 2
fi
if [[ $("$rg_binary" --version | head -n 1) != "$expected_rg_version" ]]; then
  echo "ripgrep identity differs from the frozen official 15.2.0 release" >&2
  exit 1
fi
rg_sha256=$(sha256sum "$rg_binary" | awk '{print $1}')
if [[ $rg_sha256 != "$expected_rg_sha256" ]]; then
  echo "ripgrep binary SHA-256 differs from the frozen official release identity" >&2
  exit 1
fi
rg_release_archive_sha256=$(sha256sum "$rg_release_archive" | awk '{print $1}')
if [[ $rg_release_archive_sha256 != "$expected_rg_release_archive_sha256" ]]; then
  echo "ripgrep archive SHA-256 differs from the frozen official release identity" >&2
  exit 1
fi
archive_rg_sha256=$(tar -xOzf "$rg_release_archive" "$rg_release_member" | sha256sum \
  | awk '{print $1}')
if [[ $archive_rg_sha256 != "$rg_sha256" ]]; then
  echo "ripgrep binary differs from the binary inside the frozen release archive" >&2
  exit 1
fi

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
  echo "Verifier image has no local tag for offline BuildKit resolution" >&2
  exit 1
fi

scratch_parent=/data2/jiadongzhu/Agent/.verigym-tmp
mkdir -p "$scratch_parent"
build_context=$(mktemp -d "$scratch_parent/verigym-ibex-hwe-command.XXXXXXXX")
cleanup() {
  case "$build_context" in
    "$scratch_parent"/verigym-ibex-hwe-command.*) rm -rf -- "$build_context" ;;
    *) echo "refusing to remove unexpected command-image build context" >&2 ;;
  esac
}
trap cleanup EXIT
install -m 0755 "$rg_binary" "$build_context/rg"

DOCKER_BUILDKIT=1 docker build \
  --network none \
  --build-arg "IBEX_VERIFIER_BASE=$local_base_reference" \
  --build-arg "IBEX_VERIFIER_BASE_ID=$verifier_image_id" \
  --build-arg "RG_SHA256=$rg_sha256" \
  --build-arg "RG_RELEASE_ARCHIVE_SHA256=$rg_release_archive_sha256" \
  --build-arg "HWE_TASK_ID=$task_id" \
  --build-arg "IBEX_TOOLCHAIN_PROFILE=$ibex_toolchain_profile" \
  --build-arg "COMMAND_UID=$command_uid" \
  --build-arg "COMMAND_GID=$command_gid" \
  --file "$dockerfile" \
  --tag "$build_tag" \
  "$build_context"

unsanitized_image_id=$(docker image inspect "$build_tag" --format '{{.Id}}')
sanitized_result=$(
  python "$sanitizer" \
    --image-id "$unsanitized_image_id" \
    --output-tag "$image_tag" \
    --user "$command_uid:$command_gid" \
    --environment 'PATH=/usr/local/bin:/usr/bin:/bin' \
    --environment 'HOME=/tmp/verigym-home' \
    --environment 'LANG=C.UTF-8' \
    --environment 'LC_ALL=C.UTF-8' \
    --environment 'TMPDIR=/tmp'
)
derived_image_id=$(python -c 'import json,sys; print(json.loads(sys.argv[1])["image_id"])' \
  "$sanitized_result")
if [[ $(docker image inspect "$local_base_reference" --format '{{.Id}}') != "$verifier_image_id" ]]; then
  echo "Local verifier image tag changed during the HWE command-image build" >&2
  exit 1
fi
if [[ ! $derived_image_id =~ ^sha256:[0-9a-f]{64}$ \
  || $derived_image_id == "$verifier_image_id" ]]; then
  echo "Derived HWE command image identity is invalid" >&2
  exit 1
fi

mkdir -p "$(dirname "$output_json")"
sanitizer_sha256=$(sha256sum "$sanitizer" | awk '{print $1}')
python - "$output_json" "$task_id" "$verifier_image_id" "$derived_image_id" \
  "$unsanitized_image_id" "$rg_sha256" "$rg_release_archive_sha256" \
  "$sanitizer_sha256" "$ibex_toolchain_profile" <<'PY'
import json
import os
import sys
from pathlib import Path

(
    output,
    task_id,
    base_id,
    command_id,
    unsanitized_image_id,
    rg_sha256,
    rg_release_archive_sha256,
    sanitizer_sha256,
    ibex_toolchain_profile,
) = sys.argv[1:]
toolchain_profile_id = {
    "iverilog": "ibex-iverilog-container-native-v1",
    "verilator": "ibex-verilator-system-container-native-v1",
}[ibex_toolchain_profile]
payload = {
    "format_id": "verigym_hwe_command_image_build_receipt_v1",
    "task_id": task_id,
    "verifier_base_image_id": base_id,
    "derived_command_image_id": command_id,
    "unsanitized_command_image_id": unsanitized_image_id,
    "rg_version": "ripgrep 15.2.0 (rev e89fff89ac)",
    "rg_sha256": rg_sha256,
    "rg_release_archive_sha256": rg_release_archive_sha256,
    "rg_source": "github.com/BurntSushi/ripgrep/releases/15.2.0",
    "codex_present": False,
    "build_network": "none",
    "source_whiteout_path": "/home/ibex",
    "visible_workspace_path": "/workspace/repository",
    "collection_profile_id": "hwe_standard_v2",
    "tool_contract_id": "hwe_native_shell_v2",
    "toolchain_profile_id": toolchain_profile_id,
    "command_protocol": "hwe_command_image_v1",
    "configuration_sanitizer_sha256": sanitizer_sha256,
    "exact_image_environment": [
        "PATH=/usr/local/bin:/usr/bin:/bin",
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
