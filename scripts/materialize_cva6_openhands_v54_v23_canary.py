#!/usr/bin/env python3
"""Materialize the v54 OpenHands v23 canary contract without calling a provider."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
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

from verigym_openhands import hwe_v54_materialization as _v54  # noqa: E402

from scripts import materialize_cva6_openhands_v52_v23_canary as _v52_cli  # noqa: E402
from scripts import materialize_cva6_openhands_v53_v23_canary as _v53_cli  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_bytes  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.image_transfer import (  # noqa: E402
    ContentAddressedLayerCache,
    redacted_transfer_failure,
)

_V53_FAILURE_PATH = Path(
    "/data/jzhu484/Agent/experiments/openhands-hwe-v53-v23-canary-materialization-v1.failure.json"
)
_REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_openhands_v54_v23_canary_materialization_v1.json",
    "docs/audits/2026-09-02_openhands-v53-v23-materialization-stopped.md",
    "docs/audits/2026-09-02_openhands-v54-v23-materialization-authorization.md",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v54_materialization.py",
    "integrations/verigym-openhands/tests/test_hwe_v54_materialization.py",
    "integrations/verigym-openhands/tests/test_hwe_v54_materialization_cli.py",
    "scripts/materialize_cva6_openhands_v54_v23_canary.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--v33-root", type=Path, required=True)
    parser.add_argument("--v33-source-lock", type=Path, required=True)
    parser.add_argument("--rg-binary", type=Path, required=True)
    parser.add_argument("--rg-release-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the one-shot, zero-provider v54 successor materialization."""

    if os.environ.get(_v54.OPENHANDS_V54_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{_v54.OPENHANDS_V54_OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("OpenHands v54 requires a non-root host identity")
    if any(name in os.environ for name in _v52_cli._CREDENTIAL_ENV_NAMES):
        raise ConfigurationError("OpenHands v54 refuses a provider credential environment")
    _require_clean_merged_main()
    authorization = _v54.validate_v54_authorization(
        _v52_cli._load_json(_v52_cli._safe_file(arguments.authorization))
    )
    _validate_v53_failure_receipt_and_cache()
    context = _v52_cli._RunContext(
        authorization=authorization,
        dataset=_v52_cli._validated_dataset(arguments.dataset),
        v33_root=_v52_cli._safe_directory(arguments.v33_root),
        v33_source_lock=_v52_cli._safe_file(arguments.v33_source_lock),
        rg_binary=_v52_cli._validated_rg(
            arguments.rg_binary,
            executable=True,
            expected=_v52_cli._RG_SHA256,
        ),
        rg_archive=_v52_cli._validated_rg(
            arguments.rg_release_archive,
            executable=False,
            expected=_v52_cli._RG_ARCHIVE_SHA256,
        ),
    )
    output = arguments.output.expanduser()
    if output.parent.resolve(strict=True) != Path("/data/jzhu484/Agent/experiments"):
        raise ConfigurationError("OpenHands v54 output root changed")
    failure_path = output.with_name(f"{output.name}.failure.json")
    if failure_path.exists() or failure_path.is_symlink():
        raise ConfigurationError("OpenHands v54 identity is already frozen by a failure receipt")

    def wrap(
        stage: str,
        function: Callable[[_v52_cli._RunContext, Path], dict[str, Any]],
    ) -> Callable[[Path], dict[str, Any]]:
        def wrapped(root: Path) -> dict[str, Any]:
            context.active_stage = stage
            return function(context, root)

        return wrapped

    stages = _v54.V54Stages(
        pr2728_image_transfer=wrap("pr2728_image_transfer", _transfer_stage),
        pr2728_public_qualification=wrap("pr2728_public_qualification", _qualification_stage),
        pr2728_v2_security_scan=wrap("pr2728_v2_security_scan", _security_scan_stage),
        pr2728_command_image_lock=wrap("pr2728_command_image_lock", _command_lock_stage),
        pr3204_v33_lock_revalidation=wrap("pr3204_v33_lock_revalidation", _v33_revalidation_stage),
    )
    try:
        return _v54.run_v54_zero_provider(
            authorization=authorization,
            stages=stages,
            output=output,
        )
    except BaseException as exc:
        _publish_failure(failure_path, context=context, exc=exc)
        raise


def _transfer_stage(context: _v52_cli._RunContext, root: Path) -> dict[str, Any]:
    return _v53_cli._transfer_stage_for_identity(
        context,
        root,
        identity=_v54.OPENHANDS_V54_IDENTITY,
        version="v54",
        cache_root=_v54.OPENHANDS_V54_PERSISTENT_LAYER_CACHE,
    )


def _qualification_stage(context: _v52_cli._RunContext, root: Path) -> dict[str, Any]:
    return _v53_cli._qualification_stage_for_version(context, root, version="v54")


def _security_scan_stage(context: _v52_cli._RunContext, root: Path) -> dict[str, Any]:
    return _v53_cli._security_scan_stage_for_identity(
        context,
        root,
        identity=_v54.OPENHANDS_V54_IDENTITY,
        version="v54",
    )


def _command_lock_stage(context: _v52_cli._RunContext, root: Path) -> dict[str, Any]:
    return _v53_cli._command_lock_stage_for_version(context, root, version="v54")


def _v33_revalidation_stage(context: _v52_cli._RunContext, root: Path) -> dict[str, Any]:
    return _v53_cli._v33_revalidation_stage_for_version(context, root, version="v54")


def _validate_v53_failure_receipt_and_cache() -> None:
    path = _v52_cli._safe_file(_V53_FAILURE_PATH)
    expected = _v54._V53_FAILURE_BINDING
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
            not isinstance(item, dict) or item.get("cache_hit") is not False for item in inventory
        )
        or value.get("output_published") is not False
        or value.get("provider_calls") != 0
        or value.get("model_process_count") != 0
    ):
        raise ConfigurationError("OpenHands v53 frozen failure evidence changed")
    base = {key: item for key, item in value.items() if key != "receipt_hash"}
    if content_hash(base) != expected["failure_receipt_hash"]:
        raise ConfigurationError("OpenHands v53 frozen failure receipt hash changed")
    assert isinstance(inventory, list)
    digests = [str(item["digest"]) for item in inventory]
    cache = ContentAddressedLayerCache(_v54.OPENHANDS_V54_PERSISTENT_LAYER_CACHE)
    observed = cache.bounded_inventory(digests)
    expected_sizes = {str(item["digest"]): item["size"] for item in inventory}
    if any(
        item["cache_hit"] is not True or item["size"] != expected_sizes[item["digest"]]
        for item in observed
    ):
        raise ConfigurationError("OpenHands v53 verified layer cache identity changed")


def _publish_failure(
    path: Path,
    *,
    context: _v52_cli._RunContext,
    exc: BaseException,
) -> None:
    if path.exists() or path.is_symlink():
        return
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v54_materialization_failure_v1",
        "identity": _v54.OPENHANDS_V54_IDENTITY,
        "status": "frozen_zero_provider_materialization_failed",
        "authorization_hash": context.authorization["authorization_hash"],
        "failure_stage": context.active_stage or "preflight",
        "failure_type": type(exc).__name__,
        "output_published": False,
        "canary_contract_published": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "raw_output_persisted": False,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    command_failure = _v52_cli._find_command_failure(exc)
    if command_failure is not None and context.active_stage == "pr2728_image_transfer":
        base["transfer_error"] = redacted_transfer_failure(
            command_failure,
            raw_stderr=command_failure.raw_stderr,
            stage=command_failure.stage,
        )
    inventory = context.verified_layer_inventory
    if context.active_stage == "pr2728_image_transfer" and inventory is not None:
        if len(inventory) > 512:
            raise ConfigurationError("OpenHands v54 failure inventory is unbounded")
        base["verified_layer_inventory"] = copy.deepcopy(inventory)
    atomic_dump_json(path, {**base, "receipt_hash": content_hash(base)})


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
            raise ConfigurationError("OpenHands v54 required merged path changed")
    subprocess.run(["git", "diff", "--quiet", "--"], cwd=_REPOSITORY, check=True)
    subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=_REPOSITORY, check=True)
    head = _v52_cli._git_output("rev-parse", "HEAD")
    upstream = _v52_cli._git_output("rev-parse", "origin/main")
    if head != upstream or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ConfigurationError("OpenHands v54 requires the clean merged origin/main commit")
    return head


def main() -> int:
    result = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "identity": result["identity"],
                "status": result["status"],
                "canary_contract_hash": result["canary_contract_hash"],
                "provider_calls": result["provider_calls"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
