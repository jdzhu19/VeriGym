#!/usr/bin/env python3
"""Re-seal an HWE v2 image with the exact image-level environment allowlist."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from sanitize_docker_image_environment import sanitize

from verigym.experiments.state import atomic_dump_json

_IMAGE_ENVIRONMENT = [
    "PATH=/tools/verilator/bin:/opt/iverilog/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME=/tmp/verigym-home",
    "LANG=C.UTF-8",
    "LC_ALL=C.UTF-8",
    "TMPDIR=/tmp",
]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output-tag", required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    return parser


def _load_receipt(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("unsafe HWE v2 receipt")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("format_id") != "verigym_hwe_agent_image_build_receipt_v2"
        or value.get("collection_profile_id") != "hwe_standard_v2"
        or value.get("tool_contract_id") != "hwe_native_shell_v2"
    ):
        raise ValueError("input is not a frozen HWE v2 build receipt")
    return value


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.output_receipt.exists():
        raise ValueError("re-sanitized HWE receipt output must be new")
    receipt = _load_receipt(arguments.receipt)
    source_image_id = receipt.get("derived_agent_image_id")
    if not isinstance(source_image_id, str):
        raise ValueError("HWE v2 receipt has no derived image ID")
    image_id = sanitize(
        image_id=source_image_id,
        output_tag=arguments.output_tag,
        environment=_IMAGE_ENVIRONMENT,
        user=f"{os.getuid()}:{os.getgid()}",
    )
    output = {
        **receipt,
        "derived_agent_image_id": image_id,
        "unsanitized_agent_image_id": source_image_id,
        "exact_image_environment": _IMAGE_ENVIRONMENT,
        "configuration_revision": "baseline_image_environment_v2",
    }
    arguments.output_receipt.parent.mkdir(parents=True, exist_ok=True)
    atomic_dump_json(arguments.output_receipt, output)
    print(json.dumps({"image_id": image_id, "task_id": output["task_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
