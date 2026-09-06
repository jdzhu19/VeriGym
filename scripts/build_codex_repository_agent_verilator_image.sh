#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 ABSOLUTE_NATIVE_CODEX_BINARY VERILATOR_ICARUS_IMAGE IMAGE_TAG" >&2
  exit 2
fi

codex_binary=$1
rtl_image=$2
image_tag=$3
expected_codex_sha256=cb0a15567e9a60a5820d54b0f6ae86d504dc3805c1eab21a47f70e3eb7b73a40
source_date_epoch=1788710400
repository_root=$(git rev-parse --show-toplevel)
dockerfile=$repository_root/docker/codex-repository-agent-verilator/Dockerfile
launcher=$repository_root/src/verigym/public_test_launcher_v2.py

if [[ $codex_binary != /* || ! -f $codex_binary || ! -x $codex_binary ]]; then
  echo "Codex binary must be an executable absolute regular-file path" >&2
  exit 2
fi
case "$codex_binary" in
  */.codex/*|*/auth.json|*/credentials.json)
    echo "credential/config paths are forbidden as image build inputs" >&2
    exit 2
    ;;
esac
if [[ ! -f $launcher ]]; then
  echo "trusted public-test launcher source is missing" >&2
  exit 2
fi

observed_codex_sha256=$(sha256sum "$codex_binary" | awk '{print $1}')
if [[ $observed_codex_sha256 != "$expected_codex_sha256" ]]; then
  echo "Codex binary SHA-256 mismatch" >&2
  exit 1
fi
launcher_sha256=$(sha256sum "$launcher" | awk '{print $1}')
rtl_image_id=$(docker image inspect "$rtl_image" --format '{{.Id}}')
if [[ ! $rtl_image_id =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "RTL base image has no immutable image ID" >&2
  exit 1
fi
tool_versions=$(docker run --rm --network none "$rtl_image_id" sh -eu -c \
  'iverilog -V 2>&1; verilator --version 2>&1')
if [[ $tool_versions != *"Icarus Verilog version 12."* \
      || $tool_versions != *"Verilator 5.052"* ]]; then
  echo "repository-agent base lacks the qualified Icarus 12 and Verilator 5.052 tools" >&2
  exit 1
fi

build_context_parent=$(realpath "${TMPDIR:-/tmp}")
if [[ ! -d $build_context_parent || ! -w $build_context_parent ]]; then
  echo "TMPDIR must resolve to an existing writable directory" >&2
  exit 2
fi
build_context=$(mktemp -d "$build_context_parent/verigym-codex-verilator-image.XXXXXXXX")
cleanup() {
  case "$build_context" in
    "$build_context_parent"/verigym-codex-verilator-image.*)
      rm -rf -- "$build_context"
      ;;
    *)
      echo "refusing to remove unexpected build context: $build_context" >&2
      ;;
  esac
}
trap cleanup EXIT

install -m 0755 "$codex_binary" "$build_context/codex"
install -m 0755 "$launcher" "$build_context/verigym-public-test"
touch --date="@$source_date_epoch" \
  "$build_context/codex" \
  "$build_context/verigym-public-test"

DOCKER_BUILDKIT=0 SOURCE_DATE_EPOCH=$source_date_epoch \
  docker build \
  --build-arg "RTL_BASE=$rtl_image" \
  --build-arg "RTL_BASE_ID=$rtl_image_id" \
  --build-arg "CODEX_SHA256=$observed_codex_sha256" \
  --build-arg "LAUNCHER_SHA256=$launcher_sha256" \
  --file "$dockerfile" \
  --tag "$image_tag" \
  "$build_context"

if [[ $(docker image inspect "$rtl_image" --format '{{.Id}}') != "$rtl_image_id" ]]; then
  echo "RTL base image identity changed during repository-agent build" >&2
  exit 1
fi
docker image inspect "$image_tag" --format '{{.Id}}'
