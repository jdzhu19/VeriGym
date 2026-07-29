#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 ABSOLUTE_CODEX_BINARY IVERILOG12_IMAGE IMAGE_TAG" >&2
  exit 2
fi

codex_binary=$1
iverilog_image=$2
image_tag=$3
expected_codex_sha256=a31ae9450a26216eb1e7c53102fd42123dd675974310b0e2ca3aa4cb622a2c15
source_date_epoch=1784712454
repository_root=$(git rev-parse --show-toplevel)
dockerfile=$repository_root/docker/codex-repository-agent/Dockerfile
launcher=$repository_root/src/verigym/public_test_launcher.py

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
iverilog_image_id=$(docker image inspect "$iverilog_image" --format '{{.Id}}')
if [[ ! $iverilog_image_id =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "Icarus verifier image has no immutable image ID" >&2
  exit 1
fi
iverilog_version_output=$(docker run --rm --network none "$iverilog_image_id" iverilog -V 2>&1)
iverilog_version=$(awk '/Icarus Verilog version/ && !found {print; found=1}' <<<"$iverilog_version_output")
if [[ $iverilog_version != *"version 12."* ]]; then
  echo "repository-agent base is not the required Icarus Verilog 12 image" >&2
  exit 1
fi

build_context_parent=$(realpath "${TMPDIR:-/tmp}")
if [[ ! -d $build_context_parent || ! -w $build_context_parent ]]; then
  echo "TMPDIR must resolve to an existing writable directory" >&2
  exit 2
fi
build_context=$(mktemp -d "$build_context_parent/verigym-codex-repository-image.XXXXXXXX")
cleanup() {
  case "$build_context" in
    "$build_context_parent"/verigym-codex-repository-image.*)
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

DOCKER_BUILDKIT=1 SOURCE_DATE_EPOCH=$source_date_epoch \
  docker build \
  --build-arg "IVERILOG_BASE=$iverilog_image" \
  --build-arg "IVERILOG_BASE_ID=$iverilog_image_id" \
  --build-arg "CODEX_SHA256=$observed_codex_sha256" \
  --build-arg "LAUNCHER_SHA256=$launcher_sha256" \
  --file "$dockerfile" \
  --tag "$image_tag" \
  "$build_context"

if [[ $(docker image inspect "$iverilog_image" --format '{{.Id}}') != "$iverilog_image_id" ]]; then
  echo "Icarus base image identity changed during repository-agent build" >&2
  exit 1
fi
docker image inspect "$image_tag" --format '{{.Id}}'
