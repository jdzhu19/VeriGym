#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 OUTPUT_DIRECTORY" >&2
  exit 2
fi

inventory_root=$1
if [[ -e "$inventory_root" ]]; then
  echo "inventory output already exists" >&2
  exit 2
fi
mkdir -p "$inventory_root"

conda_executable=${CONDA_EXE:-$(command -v conda || true)}
if [[ -z "$conda_executable" && -x /hpc/home/connect.jzhu484/miniconda3/bin/conda ]]; then
  conda_executable=/hpc/home/connect.jzhu484/miniconda3/bin/conda
fi
if [[ -z "$conda_executable" || ! -x "$conda_executable" ]]; then
  echo "Conda executable is unavailable" >&2
  exit 2
fi

"$conda_executable" list --explicit -n agent | \
  "$conda_executable" run --no-capture-output -n agent \
    python "$(dirname "$0")/sanitize_conda_explicit_manifest.py" \
  >"$inventory_root/conda-agent-explicit.sanitized.txt"
"$conda_executable" run -n agent python -m pip list --format=json \
  >"$inventory_root/pip-agent.json"
"$conda_executable" run --no-capture-output -n agent python - \
  >"$inventory_root/key-versions.json" <<'PY'
import importlib.metadata
import json
import platform

packages = {}
for name in ("rllm", "verl", "vllm", "torch", "transformers", "peft"):
    try:
        packages[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        packages[name] = None
print(json.dumps({"python": platform.python_version(), "packages": packages}, sort_keys=True))
PY
"$conda_executable" run -n agent python -c \
  'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' \
  "$inventory_root/key-versions.json"

sha256sum \
  "$inventory_root/conda-agent-explicit.sanitized.txt" \
  "$inventory_root/pip-agent.json" \
  "$inventory_root/key-versions.json" \
  >"$inventory_root/SHA256SUMS"

echo "wrote content-safe package inventory to $inventory_root"
