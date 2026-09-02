#!/usr/bin/env python3
"""Provision the v55 PR-2728 environment without qualifying a task or calling a provider."""

from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
_SOURCE_ROOTS = (
    _REPOSITORY,
    _REPOSITORY / "src",
    _REPOSITORY / "integrations/verigym-hwe-bench/src",
    _REPOSITORY / "integrations/verigym-openhands/src",
)
for _source_root in reversed(_SOURCE_ROOTS):
    if str(_source_root) not in sys.path:
        sys.path.insert(0, str(_source_root))

from verigym_openhands import hwe_v55_environment_provisioning as _v55  # noqa: E402

from scripts import materialize_cva6_openhands_v52_v23_canary as _v52_cli  # noqa: E402
from scripts import materialize_cva6_openhands_v53_v23_canary as _v53_cli  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_bytes  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.image_transfer import (  # noqa: E402
    ContentAddressedLayerCache,
    LayerTransferRetryPolicy,
    redacted_transfer_failure_v2,
)

_V54_FAILURE_PATH = Path(
    "/data/jzhu484/Agent/experiments/openhands-hwe-v54-v23-canary-materialization-v1.failure.json"
)
_OUTPUT_ROOT = Path("/data/jzhu484/Agent/experiments")
_OUTPUT_NAME = "openhands-hwe-v55-pr2728-environment-v1.json"
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_openhands_v55_environment_provisioning_v1.json",
    "docs/audits/2026-09-02_openhands-v55-environment-provisioning-authorization.md",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v55_environment_provisioning.py",
    "integrations/verigym-openhands/tests/test_hwe_v55_environment_provisioning.py",
    "integrations/verigym-openhands/tests/test_hwe_v55_environment_provisioning_cli.py",
    "scripts/provision_cva6_pr2728_environment_v55.py",
    "src/verigym/hwe/image_transfer.py",
    "tests/unit/test_hwe_image_transfer.py",
)


@dataclass
class _ProvisionContext:
    authorization: dict[str, Any]
    transfer: dict[str, Any] | None = None
    active_stage: str | None = None
    verified_layer_inventory: list[dict[str, str | int | bool]] | None = None
    layer_transfer_attempts: list[dict[str, Any]] | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--session-index", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def provision(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run one bounded provisioning session under an append-only session journal."""

    if os.environ.get(_v55.OPENHANDS_V55_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{_v55.OPENHANDS_V55_OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("OpenHands v55 requires a non-root host identity")
    if any(name in os.environ for name in _v52_cli._CREDENTIAL_ENV_NAMES):
        raise ConfigurationError("OpenHands v55 refuses a provider credential environment")
    main_commit = _require_clean_merged_main()
    authorization = _v55.validate_v55_authorization(
        _v52_cli._load_json(_v52_cli._safe_file(arguments.authorization))
    )
    _validate_v54_failure_receipt_and_cache()
    output = arguments.output.expanduser()
    if output.name != _OUTPUT_NAME or output.parent.resolve(strict=True) != _OUTPUT_ROOT:
        raise ConfigurationError("OpenHands v55 environment output identity changed")
    journal = output.with_name(f"{output.stem}.attempts")
    lock_path = output.with_name(f".{output.stem}.lock")
    descriptor = os.open(
        lock_path,
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ConfigurationError("OpenHands v55 provisioning lock identity changed")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _validate_session_journal(journal, arguments.session_index)
        context = _ProvisionContext(authorization=authorization)

        def transfer(root: Path) -> dict[str, Any]:
            context.active_stage = "pr2728_image_transfer"
            return _v53_cli._transfer_stage_for_identity(
                context,
                root,
                identity=_v55.OPENHANDS_V55_IDENTITY,
                version="v55",
                cache_root=_v55.OPENHANDS_V55_PERSISTENT_LAYER_CACHE,
                layer_retry_policy=LayerTransferRetryPolicy(
                    _v55.OPENHANDS_V55_LAYER_MAXIMUM_ATTEMPTS
                ),
            )

        try:
            return _v55.run_v55_environment_provisioning(
                authorization=authorization,
                session_index=arguments.session_index,
                main_commit=main_commit,
                provision=transfer,
                output=output,
            )
        except BaseException as exc:
            _publish_session_failure(
                journal,
                session_index=arguments.session_index,
                context=context,
                exc=exc,
            )
            raise
    finally:
        os.close(descriptor)


def _validate_v54_failure_receipt_and_cache() -> None:
    path = _v52_cli._safe_file(_V54_FAILURE_PATH)
    expected = _v55._V54_FAILURE_BINDING
    value = _v52_cli._load_json(path)
    transfer_error = value.get("transfer_error")
    inventory = value.get("verified_layer_inventory")
    if (
        hash_bytes(path.read_bytes()) != expected["failure_file_sha256"]
        or value.get("identity") != expected["identity"]
        or value.get("status") != expected["status"]
        or value.get("failure_stage") != expected["failure_stage"]
        or value.get("failure_type") != expected["failure_type"]
        or value.get("receipt_hash") != expected["failure_receipt_hash"]
        or not isinstance(transfer_error, dict)
        or transfer_error.get("error_family") != expected["transfer_error_family"]
        or transfer_error.get("stderr_bytes") != expected["transfer_stderr_bytes"]
        or transfer_error.get("stderr_sha256") != expected["transfer_stderr_sha256"]
        or not isinstance(inventory, list)
        or len(inventory) != expected["verified_layer_count"]
        or sum(item.get("size", -1) for item in inventory if isinstance(item, dict))
        != expected["verified_layer_bytes"]
        or any(
            not isinstance(item, dict) or item.get("cache_hit") is not True for item in inventory
        )
        or value.get("output_published") is not False
        or value.get("provider_calls") != 0
        or value.get("model_process_count") != 0
    ):
        raise ConfigurationError("OpenHands v54 frozen failure evidence changed")
    base = {key: item for key, item in value.items() if key != "receipt_hash"}
    if content_hash(base) != expected["failure_receipt_hash"]:
        raise ConfigurationError("OpenHands v54 frozen failure receipt hash changed")
    assert isinstance(inventory, list)
    digests = [str(item["digest"]) for item in inventory]
    cache = ContentAddressedLayerCache(_v55.OPENHANDS_V55_PERSISTENT_LAYER_CACHE)
    observed = cache.bounded_inventory(digests)
    expected_sizes = {str(item["digest"]): item["size"] for item in inventory}
    if any(
        item["cache_hit"] is not True or item["size"] != expected_sizes[item["digest"]]
        for item in observed
    ):
        raise ConfigurationError("OpenHands v54 verified layer cache identity changed")


def _validate_session_journal(journal: Path, requested_index: int) -> None:
    if (
        isinstance(requested_index, bool)
        or not 1 <= requested_index <= _v55.OPENHANDS_V55_MAXIMUM_SESSIONS
    ):
        raise ConfigurationError("OpenHands v55 provisioning session index is invalid")
    if journal.is_symlink():
        raise ConfigurationError("OpenHands v55 session journal cannot be a symlink")
    if not journal.exists():
        if requested_index != 1:
            raise ConfigurationError("OpenHands v55 provisioning session sequence changed")
        return
    root = journal.resolve(strict=True)
    if not root.is_dir() or root.parent != _OUTPUT_ROOT:
        raise ConfigurationError("OpenHands v55 session journal boundary changed")
    entries = sorted(root.iterdir())
    if len(entries) >= _v55.OPENHANDS_V55_MAXIMUM_SESSIONS:
        raise ConfigurationError("OpenHands v55 provisioning session budget is exhausted")
    expected_names = [f"session-{index:02d}.failure.json" for index in range(1, len(entries) + 1)]
    if [entry.name for entry in entries] != expected_names:
        raise ConfigurationError("OpenHands v55 provisioning session journal changed")
    for index, entry in enumerate(entries, 1):
        value = _v52_cli._load_json(_v52_cli._safe_file(entry))
        observed_hash = value.pop("receipt_hash", None)
        if (
            observed_hash != content_hash(value)
            or value.get("identity") != _v55.OPENHANDS_V55_IDENTITY
            or value.get("session_index") != index
            or value.get("environment_manifest_published") is not False
            or value.get("provider_task_identity_allocated") is not False
            or value.get("benchmark_task_consumed") is not False
            or value.get("provider_calls") != 0
            or value.get("session_resumable") is not True
        ):
            raise ConfigurationError("OpenHands v55 provisioning session evidence changed")
    if requested_index != len(entries) + 1:
        raise ConfigurationError("OpenHands v55 provisioning session sequence changed")


def _publish_session_failure(
    journal: Path,
    *,
    session_index: int,
    context: _ProvisionContext,
    exc: BaseException,
) -> None:
    journal.mkdir(mode=0o700, exist_ok=True)
    if journal.is_symlink() or journal.resolve(strict=True).parent != _OUTPUT_ROOT:
        raise ConfigurationError("OpenHands v55 session journal boundary changed")
    target = journal / f"session-{session_index:02d}.failure.json"
    if target.exists() or target.is_symlink():
        raise ConfigurationError("OpenHands v55 session failure already exists")
    command_failure = _v52_cli._find_command_failure(exc)
    if command_failure is not None:
        diagnostic = redacted_transfer_failure_v2(
            command_failure,
            raw_stderr=command_failure.raw_stderr,
            stage=command_failure.stage,
        )
    else:
        diagnostic = redacted_transfer_failure_v2(
            exc,
            raw_stderr=b"",
            stage="provisioning",
        )
    resumable = (
        diagnostic["retryable"] is True and session_index < _v55.OPENHANDS_V55_MAXIMUM_SESSIONS
    )
    attempts = copy.deepcopy(context.layer_transfer_attempts or [])
    inventory = copy.deepcopy(context.verified_layer_inventory or [])
    if len(attempts) > 512 or len(inventory) > 512:
        raise ConfigurationError("OpenHands v55 failure evidence is unbounded")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v55_environment_provisioning_failure_v1",
        "identity": _v55.OPENHANDS_V55_IDENTITY,
        "environment_id": _v55.OPENHANDS_V55_ENVIRONMENT_ID,
        "status": "provisioning_session_failed",
        "authorization_hash": context.authorization["authorization_hash"],
        "session_index": session_index,
        "failure_stage": context.active_stage or "preflight",
        "failure_type": type(exc).__name__,
        "transfer_error": diagnostic,
        "layer_transfer_attempts": attempts,
        "verified_layer_inventory": inventory,
        "session_resumable": resumable,
        "environment_manifest_published": False,
        "provider_task_identity_allocated": False,
        "benchmark_task_consumed": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "raw_output_persisted": False,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    atomic_dump_json(target, {**base, "receipt_hash": content_hash(base)})


def _require_clean_merged_main() -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=_REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() != relative:
            raise ConfigurationError("OpenHands v55 required merged path changed")
    subprocess.run(["git", "diff", "--quiet", "--"], cwd=_REPOSITORY, check=True)
    subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=_REPOSITORY, check=True)
    head = _v52_cli._git_output("rev-parse", "HEAD")
    upstream = _v52_cli._git_output("rev-parse", "origin/main")
    if head != upstream or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ConfigurationError("OpenHands v55 requires the clean merged origin/main commit")
    return head


def main() -> int:
    result = provision(_parser().parse_args())
    print(
        json.dumps(
            {
                "identity": result["identity"],
                "status": result["status"],
                "environment_id": result["environment_id"],
                "manifest_hash": result["manifest_hash"],
                "provider_calls": result["provider_calls"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
