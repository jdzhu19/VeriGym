#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 ABSOLUTE_CODEX_BINARY IMAGE_TAG" >&2
  exit 2
fi

codex_binary=$1
image_tag=$2
expected_sha256=a31ae9450a26216eb1e7c53102fd42123dd675974310b0e2ca3aa4cb622a2c15
source_date_epoch=1784712454
repository_root=$(git rev-parse --show-toplevel)
dockerfile=$repository_root/docker/codex-exec-server/Dockerfile

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

observed_sha256=$(sha256sum "$codex_binary" | awk '{print $1}')
if [[ $observed_sha256 != "$expected_sha256" ]]; then
  echo "Codex binary SHA-256 mismatch" >&2
  exit 1
fi

build_context=$(mktemp -d -t verigym-codex-image.XXXXXXXX)
cleanup() {
  case "$build_context" in
    /tmp/verigym-codex-image.*)
      rm -rf -- "$build_context"
      ;;
    *)
      echo "refusing to remove unexpected build context: $build_context" >&2
      ;;
  esac
}
trap cleanup EXIT

install -m 0755 "$codex_binary" "$build_context/codex"
touch --date="@$source_date_epoch" "$build_context/codex"

DOCKER_BUILDKIT=1 SOURCE_DATE_EPOCH=$source_date_epoch \
  docker build \
  --file "$dockerfile" \
  --tag "$image_tag" \
  "$build_context"

docker image inspect "$image_tag" --format '{{.Id}}'
