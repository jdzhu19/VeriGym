#!/usr/bin/env python3
"""Seal the zero-provider PR-166 command image for the Harness v4 successor."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from verigym_hwe_bench.adapter import HweBenchSuite

from scripts.scan_and_lock_cva6_hwe_command_image import scan_and_lock
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import build_hwe_command_source_lock
from verigym.schemas.suite import SuiteSourceConfig

TASK_ID = "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-166"
SOURCE_ROOT = Path("/data2/jiadongzhu/Agent/datasets/hwe-ibex-pr166-harness-v66-fresh-v1")
SMOKE_ROOT = Path("/data2/jiadongzhu/Agent/experiments/hwe-ibex-pr166-harness-v66-smoke-v1")
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v66-ibex-pr166-command-image-v1"
)
RG_ROOT = Path(
    "/data2/jiadongzhu/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl"
)
RG_BINARY = RG_ROOT / "rg"
RG_ARCHIVE = RG_ROOT.parent / "ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz"
IMAGE_TAG = "verigym/ibex-hwe-command:harness-v66-pr166"
VERIFIER_IMAGE = "sha256:b7894597216546304802a6470aab76b0db297854704854b21fa32de3fd80a240"
EXPECTED_TASK_HASH = "d3c05fdf9be2c8c9dae301f702de207c0986dc222625a0c573e1745b14b45d24"
EXPECTED_SOURCE_HASH = "205b4e61416e4bca5bd7ef8a52167637845b1817e09e960e746b572c7814f18a"
EXPECTED_SOURCE_LOCK_SHA256 = "aabe5a6bb353f4836e4a69e4a6bf6e922ae0a4a49f8eef40a950b79409b1971b"
EXPECTED_SMOKE_SHA256 = "8082b21ef140411f573737e4a7f28a0807f4346de4339d01b2bf670f2ba465c2"
TOOLCHAIN = (
    {
        "path": "/usr/bin/make",
        "sha256": "92f646030615cd98490a68a94c0aefd87b552be3158b941c02e43b0bfdb576db",
        "role": "build_tool",
    },
    {
        "path": "/usr/bin/verilator",
        "sha256": "ebe0a4ad8d1995ffcf1f9972f2e2614998ffc73f3fc94003ec7b689d5432f463",
        "role": "simulator",
    },
    {
        "path": "/usr/bin/verilator_bin",
        "sha256": "3ee693fd5cad46bd7b4fd51aa7ba9a8def53f3c9e6a3f703716cdc52e026f8aa",
        "role": "simulator",
    },
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--smoke-root", type=Path, default=SMOKE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    return parser


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ConfigurationError(f"unsafe v66 input: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError(f"v66 input is not an object: {path.name}")
    return value


def _new_root(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ConfigurationError("v66 output must not already exist")
    path.mkdir(mode=0o700, parents=True)
    return path.resolve(strict=True)


def _run(command: list[str], *, timeout: int) -> None:
    result = subprocess.run(command, check=False, cwd=Path(__file__).parents[1], timeout=timeout)
    if result.returncode != 0:
        raise ConfigurationError("v66 command-image build failed")


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    source = arguments.source.resolve(strict=True)
    smoke_root = arguments.smoke_root.resolve(strict=True)
    if source != SOURCE_ROOT or smoke_root != SMOKE_ROOT:
        raise ConfigurationError("v66 source or smoke identity changed")
    if hash_bytes((source / "image-lock.json").read_bytes()) != EXPECTED_SOURCE_LOCK_SHA256:
        raise ConfigurationError("v66 prepared-source image lock changed")
    smoke_path = smoke_root / "smoke-report.json"
    if hash_bytes(smoke_path.read_bytes()) != EXPECTED_SMOKE_SHA256:
        raise ConfigurationError("v66 smoke receipt changed")
    smoke = _load_json(smoke_path)
    if (
        smoke.get("task_id") != TASK_ID
        or smoke.get("base_resolved") is not False
        or smoke.get("base_infrastructure_error") is not False
        or smoke.get("reference_passed") is not True
        or smoke.get("model_process_count") != 0
    ):
        raise ConfigurationError("v66 base-FAIL/reference-PASS qualification changed")

    suite = HweBenchSuite().with_source(
        SuiteSourceConfig(source_root=source, variant="repo-repair-v1")
    )
    references = list(suite.discover())
    if len(references) != 1 or references[0].id != TASK_ID:
        raise ConfigurationError("v66 prepared source exposed a different task")
    task = suite.load_task(references[0])
    if content_hash(task) != EXPECTED_TASK_HASH or task.source.content_hash != EXPECTED_SOURCE_HASH:
        raise ConfigurationError("v66 task or source hash changed")
    image_lock = _load_json(source / "image-lock.json")
    entries = image_lock.get("entries")
    if not isinstance(entries, list) or len(entries) != 1:
        raise ConfigurationError("v66 prepared source image inventory changed")
    entry = entries[0]
    if not isinstance(entry, dict) or entry.get("image_id") != VERIFIER_IMAGE:
        raise ConfigurationError("v66 verifier image binding changed")
    observed_image = subprocess.run(
        ["docker", "image", "inspect", VERIFIER_IMAGE, "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    if observed_image != VERIFIER_IMAGE:
        raise ConfigurationError("v66 verifier image is unavailable")

    root = _new_root(arguments.output)
    for name in ("source-image-locks", "image-receipts", "security-scans", "image-locks"):
        (root / name).mkdir(mode=0o700)
    source_lock_path = root / "source-image-locks/pr-166.json"
    receipt_path = root / "image-receipts/pr-166.json"
    scan_path = root / "security-scans/pr-166.json"
    lock_path = root / "image-locks/pr-166.json"
    source_lock = build_hwe_command_source_lock(
        task_id=TASK_ID,
        task_hash=EXPECTED_TASK_HASH,
        source_hash=EXPECTED_SOURCE_HASH,
        prepared_source_image_lock_sha256=EXPECTED_SOURCE_LOCK_SHA256,
        verifier_base_image_id=VERIFIER_IMAGE,
        toolchain_profile_id="ibex-verilator-system-container-native-v1",
        allowlisted_artifacts=list(TOOLCHAIN),
    )
    atomic_dump_json(source_lock_path, source_lock.model_dump(mode="json"))
    _run(
        [
            str(Path(__file__).with_name("build_ibex_hwe_command_image.sh")),
            str(RG_BINARY),
            str(RG_ARCHIVE),
            VERIFIER_IMAGE,
            TASK_ID,
            IMAGE_TAG,
            str(receipt_path),
            "verilator",
        ],
        timeout=1800,
    )
    scan, lock = scan_and_lock(
        receipt_path=receipt_path,
        identity_lock_path=source_lock_path,
        security_output=scan_path,
        lock_output=lock_path,
        repository_profile="ibex-verilator",
    )
    if scan.get("scan_passed") is not True or lock.security_scan_passed is not True:
        raise ConfigurationError("v66 command-image security scan did not pass")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v66_ibex_pr166_zero_provider_result_v1",
        "task_id": TASK_ID,
        "task_hash": EXPECTED_TASK_HASH,
        "source_hash": EXPECTED_SOURCE_HASH,
        "prepared_source_image_lock_sha256": EXPECTED_SOURCE_LOCK_SHA256,
        "smoke_report_sha256": EXPECTED_SMOKE_SHA256,
        "verifier_image": VERIFIER_IMAGE,
        "command_image": lock.derived_command_image_id,
        "command_image_lock_hash": lock.lock_hash,
        "security_scan_id": lock.security_scan_id,
        "toolchain_profile_id": lock.toolchain_profile_id,
        "base_failed": True,
        "base_infrastructure_error": False,
        "reference_passed": True,
        "bridge_regression": "host_control_plane_with_episode_command_image_accepted_v1",
        "verifier_network": "none",
        "command_image_runtime_network": "none",
        "provider_calls": 0,
        "model_process_count": 0,
        "formal_collection_allowed": False,
        "collection_started": False,
        "training_started": False,
    }
    result = {**base, "result_hash": content_hash(base)}
    atomic_dump_json(root / "zero-provider-result.json", result)
    return result


def main() -> int:
    result = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "task_id": result["task_id"],
                "command_image": result["command_image"],
                "command_image_lock_hash": result["command_image_lock_hash"],
                "security_scan_id": result["security_scan_id"],
                "result_hash": result["result_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
