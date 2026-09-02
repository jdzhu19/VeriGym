#!/usr/bin/env python3
"""Materialize the fixed OpenHands v23 canary contract without a provider."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from collections.abc import Callable
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
    _source_text = str(_source_root.resolve(strict=True))
    sys.path[:] = [_source_text, *(entry for entry in sys.path if entry != _source_text)]

from verigym_hwe_bench.cva6_qualification import (  # noqa: E402
    run_zero_model_smoke,
    zero_model_fail_to_pass_eligible,
    zero_model_infrastructure_valid,
)
from verigym_hwe_bench.prepare import prepare_source  # noqa: E402
from verigym_openhands.hwe_v52_materialization import (  # noqa: E402
    OPENHANDS_V52_IDENTITY,
    OPENHANDS_V52_OPT_IN_ENV,
    OPENHANDS_V52_PERSISTENT_LAYER_CACHE,
    V52Stages,
    run_v52_zero_provider,
    validate_v52_authorization,
)

from scripts import qualify_cva6_openhands_v51_pr2728_public_qualification as _v51  # noqa: E402
from scripts import scan_and_lock_cva6_hwe_command_image as _command_scanner  # noqa: E402
from scripts.qualify_cva6_openhands_v19_public_tasks import _source_binding  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_bytes  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.image_lock import (  # noqa: E402
    HweAgentImageLock,
    HweCommandImageLock,
    HweCommandSourceLock,
    build_hwe_command_source_lock,
)
from verigym.hwe.image_transfer import (  # noqa: E402
    ContentAddressedLayerCache,
    SingleCleanupArchive,
    redacted_transfer_failure,
)

_TASK_ID = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2728"
_INSTANCE_ID = "openhwgroup/cva6:pr-2728"
_REFERENCE = "ghcr.io/pku-liang/openhwgroup_m_cva6:pr-2728"
_NETWORK = "verigym-hwe-net"
_DATASET_SHA256 = "732c5dac910815c1c7ac72c8ccca88f66dbb7ed5d097806a5ddea611102f60f1"
_DATASET_REVISION = "1403afb57ce056c659c82b35e39c38c6a21ee635"
_DATASET_SOURCE_COMMIT = "10c78a87e1f92695d78d15b1464a6107dcac8837"
_CANDIDATE_RECORD_SHA256 = "42f3040a91af4e735e1107dd2536691c9fa3286b4e9441cc8ebb039e3d3c1a16"
_PATCH_COMPATIBILITY_HASH = "cccec1b44901f1e3cd7d6694a5a825cd9716536e445a7678ff408cedcf6fe0d2"
_EXECUTION_IMAGE = {
    "reference": "python:3.11.9-slim-bookworm",
    "image_id": "sha256:65a6ce634d975b67ee77c8d0f59248cbcb9d8b8f229d584c3cf5d624038bf963",
    "manifest_digest": "sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317",
}
_TOOL_CACHE = Path("/data/jzhu484/Agent/.verigym-tmp/openhands-v24-crane-v0.22.0-slsa-v2.7.1")
_CRANE_SHA256 = "771ced475a87b8b2314b9f9de267264789b3297f34a6d5d8ab601e8482db4d94"
_RG_SHA256 = "e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849"
_RG_ARCHIVE_SHA256 = "33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c"
_V33_FILES = {
    "image-locks/pr-3204.json": "a3a29f4ad2515c9502b3716e8644806154c7f9a74d388f9cd9c741d81458dc22",
    "security-scans/pr-3204.json": (
        "6357976446539e526c15cf22a8e9616df650e4ac30117934898b7a40eb339ed1"
    ),
}
_V33_SOURCE_LOCK_FILE_SHA256 = "55ff6b4efb9675a0a6d512b32d0b33d7778d93d81159086c7485b9f3ebe92a6b"
_V33_SOURCE_LOCK_HASH = "b3fe6732fe4d9b52a6444cda90b25add311665af537acf6b389ad1fdafa1933b"
_V33_LOCK_HASH = "4e6bcb561d1c631955dcf9b4a2475a0b09d5bb6bb6b98441cd20101f893400d7"
_V33_SECURITY_SCAN_ID = "55e94ec5fd12482534238867e109f920779685d0ef9f18b0db03e99f88be62cf"
_V33_COMMAND_IMAGE = "sha256:ed935e093a8f5df4f081ee94d7fb3696335350053dd74fbbd5178b23c2fd1784"
_V33_VERIFIER_IMAGE = "sha256:459deab1a9b65a25be4583087238308dd12e773b818e720299cc8cafe55f4f64"
_V33_TASK_HASH = "9322fa0b8455126e5c5f2e68ae02c47484935d5ea84bf69b9e6494658e229e86"
_V33_SOURCE_HASH = "15861c5f52071656a4ac8dbe7f96df49c974d24c2e3f53f9e449eba12794f02f"
_VALIDATION_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204"
_MAX_OUTPUT_BYTES = 32 * 1024 * 1024
_HASH = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_openhands_v52_v23_canary_materialization_v1.json",
    "docs/audits/2026-09-02_openhands-v23-v52-collection-readiness-authorization.md",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v23.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v23_protocol.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v52_materialization.py",
    "integrations/verigym-openhands/tests/test_hwe_v52_materialization_cli.py",
    "scripts/materialize_cva6_openhands_v52_v23_canary.py",
    "scripts/scan_and_lock_cva6_hwe_command_image.py",
    "src/verigym/hwe/image_lock.py",
    "src/verigym/hwe/image_transfer.py",
)
_CREDENTIAL_ENV_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
    }
)


class _CommandFailure(ConfigurationError):
    def __init__(self, stage: str, raw_stderr: bytes) -> None:
        super().__init__(f"OpenHands v52 controlled command failed at {stage}")
        self.stage = stage
        self.raw_stderr = raw_stderr


@dataclass
class _RunContext:
    authorization: dict[str, Any]
    dataset: Path
    v33_root: Path
    v33_source_lock: Path
    rg_binary: Path
    rg_archive: Path
    transfer: dict[str, Any] | None = None
    qualification: dict[str, Any] | None = None
    source_lock: HweCommandSourceLock | None = None
    security_scan: dict[str, Any] | None = None
    command_lock: HweCommandImageLock | None = None
    active_stage: str | None = None
    verified_layer_inventory: list[dict[str, str | int | bool]] | None = None
    layer_transfer_attempts: list[dict[str, Any]] | None = None


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
    """Execute the one-shot, zero-provider v52 materialization."""

    if os.environ.get(OPENHANDS_V52_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V52_OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("OpenHands v52 requires a non-root host identity")
    if any(name in os.environ for name in _CREDENTIAL_ENV_NAMES):
        raise ConfigurationError("OpenHands v52 refuses a provider credential environment")
    _require_clean_merged_main()
    authorization = validate_v52_authorization(_load_json(_safe_file(arguments.authorization)))
    context = _RunContext(
        authorization=authorization,
        dataset=_validated_dataset(arguments.dataset),
        v33_root=_safe_directory(arguments.v33_root),
        v33_source_lock=_safe_file(arguments.v33_source_lock),
        rg_binary=_validated_rg(arguments.rg_binary, executable=True, expected=_RG_SHA256),
        rg_archive=_validated_rg(
            arguments.rg_release_archive,
            executable=False,
            expected=_RG_ARCHIVE_SHA256,
        ),
    )
    output = arguments.output.expanduser()
    _safe_directory(output.parent)
    failure_path = output.with_name(f"{output.name}.failure.json")
    if failure_path.exists() or failure_path.is_symlink():
        raise ConfigurationError("OpenHands v52 identity is already frozen by a failure receipt")

    def stage(
        name: str,
        function: Callable[[_RunContext, Path], dict[str, Any]],
    ) -> Callable[[Path], dict[str, Any]]:
        def wrapped(root: Path) -> dict[str, Any]:
            context.active_stage = name
            return function(context, root)

        return wrapped

    stages = V52Stages(
        pr2728_image_transfer=stage("pr2728_image_transfer", _transfer_stage),
        pr2728_public_qualification=stage("pr2728_public_qualification", _qualification_stage),
        pr2728_v2_security_scan=stage("pr2728_v2_security_scan", _security_scan_stage),
        pr2728_command_image_lock=stage("pr2728_command_image_lock", _command_lock_stage),
        pr3204_v33_lock_revalidation=stage("pr3204_v33_lock_revalidation", _v33_revalidation_stage),
    )
    try:
        return run_v52_zero_provider(
            authorization=authorization,
            stages=stages,
            output=output,
        )
    except BaseException as exc:
        _publish_failure(failure_path, context=context, exc=exc)
        raise


def _transfer_stage(context: _RunContext, root: Path) -> dict[str, Any]:
    _v51._validate_network()
    _v51._validate_headroom()
    execution = _v51._validate_local_image(_EXECUTION_IMAGE)
    tool_cache = _safe_directory(_TOOL_CACHE)
    crane = _safe_file(tool_cache / "crane")
    if not os.access(crane, os.X_OK) or hash_bytes(crane.read_bytes()) != _CRANE_SHA256:
        raise ConfigurationError("OpenHands v52 crane identity changed")
    if _v51._inspect_host_image(_REFERENCE) is not None:
        raise ConfigurationError("OpenHands v52 PR-2728 tag already exists")
    sentinel = _v51._sentinel_reference()
    if _v51._inspect_host_image(sentinel) is not None:
        raise ConfigurationError("OpenHands v52 transfer sentinel already exists")

    cache = ContentAddressedLayerCache(OPENHANDS_V52_PERSISTENT_LAYER_CACHE)
    cache_staging = cache.task_staging(f"v52-pr2728-{os.getpid()}-{secrets.token_hex(4)}")
    work = root / "private-transfer"
    work.mkdir(mode=0o700)
    archive = work / "candidate-image.tar"
    owner = SingleCleanupArchive(archive)
    inventory: list[dict[str, Any]] = []
    try:
        cache.seed_task_staging(cache_staging)
        digest_stdout, _ = _run_controlled_container(
            image_id=execution["image_id"],
            tool_cache=tool_cache,
            work=work,
            cache_staging=None,
            network=_NETWORK,
            path="/tools/crane",
            arguments=["digest", _REFERENCE],
            role="candidate_digest",
            timeout=300,
        )
        manifest_digest = digest_stdout.decode("ascii", errors="strict").strip()
        if not _DIGEST.fullmatch(manifest_digest):
            raise ConfigurationError("OpenHands v52 candidate manifest digest is malformed")
        immutable = f"{_REFERENCE.rsplit(':', 1)[0]}@{manifest_digest}"
        config_stdout, _ = _run_controlled_container(
            image_id=execution["image_id"],
            tool_cache=tool_cache,
            work=work,
            cache_staging=None,
            network=_NETWORK,
            path="/tools/crane",
            arguments=["config", immutable],
            role="candidate_config",
            timeout=300,
        )
        if not config_stdout:
            raise ConfigurationError("OpenHands v52 candidate config is empty")
        image_id = f"sha256:{hashlib.sha256(config_stdout).hexdigest()}"
        with owner:
            pull_stdout, _ = _run_controlled_container(
                image_id=execution["image_id"],
                tool_cache=tool_cache,
                work=work,
                cache_staging=cache_staging,
                network=_NETWORK,
                path="/tools/crane",
                arguments=[
                    "pull",
                    immutable,
                    "/transfer/candidate-image.tar",
                    "--format=tarball",
                    "--cache_path=/cache",
                ],
                role="candidate_pull",
                timeout=3_600,
            )
            if pull_stdout:
                raise ConfigurationError("OpenHands v52 crane pull emitted stdout")
            inventory = [
                receipt.safe_dict() for receipt in cache.promote_task_staging(cache_staging)
            ]
            if not inventory:
                raise ConfigurationError("OpenHands v52 crane layer inventory is empty")
            _v51._validated_crane_tarball(
                archive,
                expected_image_id=image_id,
                expected_sentinel=sentinel,
            )
            loaded = _bounded_run(
                ["docker", "image", "load", "--input", str(archive)], timeout=3_600
            )
            if loaded.returncode != 0:
                raise _CommandFailure("candidate_load", loaded.stderr)
            observed_sentinel = _v51._inspect_host_image(sentinel)
            if observed_sentinel is None or observed_sentinel.get("Id") != image_id:
                raise ConfigurationError("OpenHands v52 loaded image identity changed")
            tagged = _bounded_run(["docker", "image", "tag", image_id, _REFERENCE], timeout=60)
            if tagged.returncode != 0 or tagged.stdout or tagged.stderr:
                raise _CommandFailure("candidate_tag", tagged.stderr)
            imported = _v51._inspect_host_image(_REFERENCE)
            if imported is None or imported.get("Id") != image_id:
                raise ConfigurationError("OpenHands v52 candidate tag identity changed")
            removed = _bounded_run(["docker", "image", "rm", sentinel], timeout=60)
            if removed.returncode != 0 or _v51._inspect_host_image(sentinel) is not None:
                raise _CommandFailure("sentinel_cleanup", removed.stderr)
    finally:
        _cleanup_directories(cache_staging, work)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v52_pr2728_image_transfer_v1",
        "task_id": _TASK_ID,
        "verifier_image": image_id,
        "manifest_digest": manifest_digest,
        "layer_inventory": inventory,
        "temporary_archive_cleanup_count": owner.cleanup_count,
        "raw_stderr_persisted": False,
        "provider_calls": 0,
        "model_process_count": 0,
    }
    context.transfer = _sealed(base)
    return context.transfer


def _qualification_stage(context: _RunContext, root: Path) -> dict[str, Any]:
    transfer = _required(context.transfer, "transfer")
    candidate, _instance, raw_candidate, compatibility = _v51._selected_candidate(
        context.dataset,
        {
            "candidate": {
                "number": 2728,
                "task_id": _TASK_ID,
                "instance_id": _INSTANCE_ID,
                "changed_line_count": 25,
                "modified_file_count": 1,
            },
            "reference_patch_compatibility": {
                "classifier": "git-apply-metadata-v1",
                "compatible": True,
                "reason": "compatible",
                "patch_file_count": 1,
                "created_file_count": 0,
                "deleted_file_count": 0,
                "renamed_file_count": 0,
                "copied_file_count": 0,
                "mode_changed_file_count": 0,
                "binary_file_count": 0,
                "raw_output_persisted": False,
                "network_accessed": False,
                "docker_accessed": False,
                "receipt_hash": _PATCH_COMPATIBILITY_HASH,
            },
        },
    )
    if compatibility["receipt_hash"] != _PATCH_COMPATIBILITY_HASH:
        raise ConfigurationError("OpenHands v52 reference-patch compatibility changed")
    selected_root = root / "selected-input"
    selected_root.mkdir(mode=0o700)
    selected_dataset = _v51._write_selected_dataset(selected_root, raw_candidate)
    source = root / "sources/pr-2728"
    smoke = root / "smokes/pr-2728"
    try:
        prepare_source(
            dataset=selected_dataset,
            output=source,
            selected_tasks=[_INSTANCE_ID],
            pull=False,
            official_dataset_revision=_DATASET_REVISION,
            official_source_commit=_DATASET_SOURCE_COMMIT,
            imported_image_bindings={
                _REFERENCE: {
                    "image_id": str(transfer["verifier_image"]),
                    "manifest_digest": str(transfer["manifest_digest"]),
                }
            },
        )
    finally:
        shutil.rmtree(selected_root)
    binding = _source_binding(source, expected_task_id=_TASK_ID)
    report = run_zero_model_smoke(source=source, output=smoke)
    if not zero_model_infrastructure_valid(report) or not zero_model_fail_to_pass_eligible(report):
        raise ConfigurationError("OpenHands v52 PR-2728 public qualification did not pass")
    if (
        binding["verifier_image"] != transfer["verifier_image"]
        or binding["verifier_manifest_digest"] != transfer["manifest_digest"]
    ):
        raise ConfigurationError("OpenHands v52 qualification image binding changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v52_pr2728_public_qualification_v1",
        "task_id": _TASK_ID,
        "task_hash": binding["task_hash"],
        "source_hash": binding["source_hash"],
        "prepared_source_image_lock_sha256": binding["source_image_lock_sha256"],
        "verifier_image": binding["verifier_image"],
        "transfer_receipt_hash": transfer["receipt_hash"],
        "infrastructure_valid": True,
        "base_failed": report.get("base_failed") is True,
        "reference_passed": report.get("reference_passed") is True,
        "verifier_network": "none",
        "provider_calls": 0,
        "model_process_count": 0,
    }
    context.qualification = _sealed(base)
    return context.qualification


def _security_scan_stage(
    context: _RunContext,
    root: Path,
    *,
    image_tag: str = "verigym/cva6-openhands-v52-command-pr-2728:rg-15.2.0-v1",
    format_id: str = "verigym_openhands_hwe_v52_pr2728_v2_security_scan_v1",
    owner_identity: str = OPENHANDS_V52_IDENTITY,
    name_version: str = "v52",
) -> dict[str, Any]:
    qualification = _required(context.qualification, "qualification")
    artifacts = _inventory_toolchain(
        str(qualification["verifier_image"]),
        owner_identity=owner_identity,
        name_version=name_version,
    )
    source_lock = build_hwe_command_source_lock(
        task_id=_TASK_ID,
        task_hash=qualification["task_hash"],
        source_hash=qualification["source_hash"],
        prepared_source_image_lock_sha256=qualification["prepared_source_image_lock_sha256"],
        verifier_base_image_id=qualification["verifier_image"],
        toolchain_profile_id="cva6-verilator-5.008-container-native-v2",
        allowlisted_artifacts=artifacts,
    )
    source_lock_path = root / "source-image-locks/pr-2728.json"
    receipt_path = root / "image-receipts/pr-2728.json"
    scan_path = root / "security-scans/pr-2728.json"
    lock_path = root / "image-locks/pr-2728.json"
    for parent in (
        source_lock_path.parent,
        receipt_path.parent,
        scan_path.parent,
        lock_path.parent,
    ):
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_dump_json(source_lock_path, source_lock.model_dump(mode="json"))
    built = _bounded_run(
        [
            str(_REPOSITORY / "scripts/build_cva6_hwe_command_image.sh"),
            str(context.rg_binary),
            str(context.rg_archive),
            str(qualification["verifier_image"]),
            _TASK_ID,
            image_tag,
            str(receipt_path),
        ],
        cwd=_REPOSITORY,
        timeout=1_800,
    )
    if built.returncode != 0:
        raise ConfigurationError("OpenHands v52 command-image build failed")
    scan, lock = _command_scanner.scan_and_lock(
        receipt_path=receipt_path,
        identity_lock_path=source_lock_path,
        security_output=scan_path,
        lock_output=lock_path,
    )
    if not scan.get("scan_passed") or not lock.security_scan_passed:
        raise ConfigurationError("OpenHands v52 command-image v2 scan failed")
    context.source_lock = source_lock
    context.security_scan = scan
    context.command_lock = lock
    base = {
        "schema_version": "1.0",
        "format_id": format_id,
        "task_id": lock.task_id,
        "task_hash": lock.task_hash,
        "source_hash": lock.source_hash,
        "verifier_image": lock.verifier_base_image_id,
        "command_image": lock.derived_command_image_id,
        "security_scan_file_sha256": hash_bytes(scan_path.read_bytes()),
        "security_scan_id": lock.security_scan_id,
        "scanner_profile_id": scan["scanner_profile_id"],
        "scan_passed": True,
        "codex_present": False,
        "provider_credentials_present": False,
        "hidden_assets_present": False,
        "network_available": False,
        "provider_calls": 0,
        "model_process_count": 0,
    }
    return _sealed(base)


def _command_lock_stage(context: _RunContext, root: Path) -> dict[str, Any]:
    source_lock = context.source_lock
    lock = context.command_lock
    scan = context.security_scan
    if source_lock is None or lock is None or scan is None:
        raise ConfigurationError("OpenHands v52 command-image scan outputs are missing")
    source_lock_path = root / "source-image-locks/pr-2728.json"
    lock_path = root / "image-locks/pr-2728.json"
    scan_path = root / "security-scans/pr-2728.json"
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v52_pr2728_command_image_lock_v1",
        "task_id": lock.task_id,
        "task_hash": lock.task_hash,
        "source_hash": lock.source_hash,
        "source_image_lock_file_sha256": hash_bytes(source_lock_path.read_bytes()),
        "source_image_lock_hash": source_lock.lock_hash,
        "verifier_image": lock.verifier_base_image_id,
        "command_image": lock.derived_command_image_id,
        "lock_file_sha256": hash_bytes(lock_path.read_bytes()),
        "lock_hash": lock.lock_hash,
        "security_scan_file_sha256": hash_bytes(scan_path.read_bytes()),
        "security_scan_id": lock.security_scan_id,
        "scanner_profile_id": scan["scanner_profile_id"],
        "security_scan_passed": True,
        "codex_present": False,
        "provider_credentials_present": False,
        "hidden_assets_present": False,
        "build_network": "none",
        "runtime_network": "none",
        "provider_calls": 0,
        "model_process_count": 0,
    }
    return _sealed(base)


def _v33_revalidation_stage(context: _RunContext, root: Path) -> dict[str, Any]:
    lock_path = _safe_file(context.v33_root / "image-locks/pr-3204.json")
    scan_path = _safe_file(context.v33_root / "security-scans/pr-3204.json")
    if (
        hash_bytes(lock_path.read_bytes()) != _V33_FILES["image-locks/pr-3204.json"]
        or hash_bytes(scan_path.read_bytes()) != _V33_FILES["security-scans/pr-3204.json"]
        or hash_bytes(context.v33_source_lock.read_bytes()) != _V33_SOURCE_LOCK_FILE_SHA256
    ):
        raise ConfigurationError("OpenHands v52 sealed PR-3204 evidence bytes changed")
    source_lock = HweAgentImageLock.model_validate(_load_json(context.v33_source_lock))
    lock = HweCommandImageLock.model_validate(_load_json(lock_path))
    scan = _load_json(scan_path)
    if (
        source_lock.lock_hash != _V33_SOURCE_LOCK_HASH
        or source_lock.task_id != _VALIDATION_TASK
        or source_lock.task_hash != _V33_TASK_HASH
        or source_lock.source_hash != _V33_SOURCE_HASH
        or source_lock.verifier_base_image_id != _V33_VERIFIER_IMAGE
        or lock.lock_hash != _V33_LOCK_HASH
        or lock.security_scan_id != _V33_SECURITY_SCAN_ID
        or scan.get("security_scan_id") != _V33_SECURITY_SCAN_ID
        or scan.get("scan_passed") is not True
        or scan.get("scanner_profile_id") != "cva6-hwe-command-container-native-offline-v2"
        or content_hash({k: v for k, v in scan.items() if k != "security_scan_id"})
        != _V33_SECURITY_SCAN_ID
        or lock.task_id != _VALIDATION_TASK
        or lock.task_hash != _V33_TASK_HASH
        or lock.source_hash != _V33_SOURCE_HASH
        or lock.verifier_base_image_id != _V33_VERIFIER_IMAGE
        or lock.derived_command_image_id != _V33_COMMAND_IMAGE
    ):
        raise ConfigurationError("OpenHands v52 sealed PR-3204 lock binding changed")
    image = _v51._inspect_host_image(_V33_COMMAND_IMAGE)
    if image is None or image.get("Id") != _V33_COMMAND_IMAGE:
        raise ConfigurationError("OpenHands v52 PR-3204 command image is not local")
    checks, diagnostic = _command_scanner._container_scan(
        _V33_COMMAND_IMAGE,
        user=f"{os.getuid()}:{os.getgid()}",
        rg_sha256=lock.rg_sha256,
        artifacts=[item.model_dump(mode="json") for item in lock.allowlisted_artifacts],
    )
    if not checks or not all(checks.values()) or diagnostic.get("status") != "passed":
        raise ConfigurationError("OpenHands v52 current v2 PR-3204 rescan failed")
    destination = root / "validation-v33"
    destination.mkdir(mode=0o700)
    shutil.copyfile(lock_path, destination / "pr-3204-command-lock.json")
    shutil.copyfile(scan_path, destination / "pr-3204-security-scan.json")
    shutil.copyfile(context.v33_source_lock, destination / "pr-3204-source-lock.json")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v52_pr3204_v33_lock_revalidation_v1",
        "task_id": _VALIDATION_TASK,
        "task_hash": _V33_TASK_HASH,
        "source_hash": _V33_SOURCE_HASH,
        "source_image_lock_file_sha256": _V33_SOURCE_LOCK_FILE_SHA256,
        "source_image_lock_hash": _V33_SOURCE_LOCK_HASH,
        "verifier_image": _V33_VERIFIER_IMAGE,
        "command_image": _V33_COMMAND_IMAGE,
        "lock_file_sha256": _V33_FILES["image-locks/pr-3204.json"],
        "lock_hash": _V33_LOCK_HASH,
        "security_scan_file_sha256": _V33_FILES["security-scans/pr-3204.json"],
        "security_scan_id": _V33_SECURITY_SCAN_ID,
        "scanner_profile_id": "cva6-hwe-command-container-native-offline-v2",
        "security_scan_passed": True,
        "codex_present": False,
        "provider_credentials_present": False,
        "hidden_assets_present": False,
        "build_network": "none",
        "runtime_network": "none",
        "source": "sealed_v33_revalidated",
        "provider_calls": 0,
        "model_process_count": 0,
    }
    return _sealed(base)


def _inventory_toolchain(
    image_id: str,
    *,
    owner_identity: str = OPENHANDS_V52_IDENTITY,
    name_version: str = "v52",
) -> list[dict[str, str]]:
    paths = (
        ("/usr/bin/make", "build_tool"),
        ("/tools/verilator/bin/verilator", "simulator"),
        ("/tools/verilator/bin/verilator_bin", "simulator"),
    )
    command = "sha256sum -- " + " ".join(path for path, _role in paths)
    stdout, stderr = _run_controlled_container(
        image_id=image_id,
        tool_cache=None,
        work=None,
        cache_staging=None,
        network="none",
        path="/bin/sh",
        arguments=["-c", command],
        role="toolchain_inventory",
        timeout=120,
        owner_identity=owner_identity,
        name_version=name_version,
    )
    if stderr:
        raise ConfigurationError("OpenHands v52 toolchain inventory emitted stderr")
    observed: dict[str, str] = {}
    for line in stdout.decode("ascii", errors="strict").splitlines():
        digest, separator, path = line.partition("  ")
        if not separator or not _HASH.fullmatch(digest) or path in observed:
            raise ConfigurationError("OpenHands v52 toolchain inventory is malformed")
        observed[path] = digest
    if set(observed) != {path for path, _role in paths}:
        raise ConfigurationError("OpenHands v52 toolchain inventory paths changed")
    return [{"path": path, "sha256": observed[path], "role": role} for path, role in paths]


def _run_controlled_container(
    *,
    image_id: str,
    tool_cache: Path | None,
    work: Path | None,
    cache_staging: Path | None,
    network: str,
    path: str,
    arguments: list[str],
    role: str,
    timeout: int,
    owner_identity: str = OPENHANDS_V52_IDENTITY,
    name_version: str = "v52",
) -> tuple[bytes, bytes]:
    if not re.fullmatch(r"v[0-9]+", name_version):
        raise ConfigurationError("OpenHands controlled-container version is invalid")
    name = f"verigym-hwe-{name_version}-{role}-{os.getpid()}-{secrets.token_hex(4)}"
    command = [
        "docker",
        "create",
        "--pull",
        "never",
        "--name",
        name,
        "--label",
        f"org.verigym.owner={owner_identity}",
        "--label",
        f"org.verigym.role={role}",
        "--network",
        network,
        "--ipc",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        str(1024**3),
        "--memory-swap",
        str(1024**3),
        "--cpus",
        "2",
        "--pids-limit",
        "128",
        "--env",
        "HOME=/nonexistent",
    ]
    expected_mounts: dict[str, tuple[Path, bool]] = {}
    if tool_cache is not None:
        expected_mounts["/tools"] = (tool_cache.resolve(strict=True), False)
    if work is not None:
        expected_mounts["/transfer"] = (work.resolve(strict=True), True)
        command.extend(("--workdir", "/transfer"))
    if cache_staging is not None:
        expected_mounts["/cache"] = (cache_staging.resolve(strict=True), True)
    for destination, (source, writable) in expected_mounts.items():
        suffix = "" if writable else ",readonly"
        command.extend(("--mount", f"type=bind,src={source},dst={destination}{suffix}"))
    command.extend(("--entrypoint", path, image_id, *arguments))
    container_id: str | None = None
    failure: BaseException | None = None
    raw_stderr = b""
    result: tuple[bytes, bytes] | None = None
    try:
        created = _bounded_run(command, timeout=60)
        raw_stderr = created.stderr
        if created.returncode != 0:
            raise _CommandFailure(role, raw_stderr)
        container_id = created.stdout.decode("ascii", errors="strict").strip()
        inspection = _docker_json(["docker", "container", "inspect", container_id])
        if len(inspection) != 1:
            raise ConfigurationError("OpenHands v52 container inspection is malformed")
        _validate_container(inspection[0], image_id, network, path, arguments, expected_mounts)
        started = _bounded_run(["docker", "start", "--attach", container_id], timeout=timeout)
        raw_stderr = started.stderr
        if started.returncode != 0:
            raise _CommandFailure(role, raw_stderr)
        result = started.stdout, started.stderr
    except BaseException as exc:
        failure = exc
    if container_id is not None:
        removed = _bounded_run(["docker", "container", "rm", "--force", container_id], timeout=60)
        if removed.returncode != 0:
            failure = _CommandFailure("container_cleanup", removed.stderr)
    if failure is not None:
        if isinstance(failure, _CommandFailure):
            raise failure
        raise _CommandFailure(role, raw_stderr) from failure
    if result is None:
        raise _CommandFailure(role, raw_stderr)
    return result


def _validate_container(
    value: dict[str, Any],
    image_id: str,
    network: str,
    path: str,
    arguments: list[str],
    mounts: dict[str, tuple[Path, bool]],
) -> None:
    host = value.get("HostConfig")
    config = value.get("Config")
    observed_mounts = value.get("Mounts")
    if (
        not isinstance(host, dict)
        or not isinstance(config, dict)
        or not isinstance(observed_mounts, list)
    ):
        raise ConfigurationError("OpenHands v52 container controls are malformed")
    environment: dict[str, str] = {}
    for entry in config.get("Env") or []:
        name, separator, value_text = str(entry).partition("=")
        if not separator or name in environment:
            raise ConfigurationError("OpenHands v52 container environment is malformed")
        environment[name] = value_text
    forbidden_environment = {
        *_CREDENTIAL_ENV_NAMES,
        "ALL_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "all_proxy",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
    mount_map = {
        str(item.get("Destination")): (
            Path(str(item.get("Source"))).resolve(strict=True),
            item.get("RW") is True,
        )
        for item in observed_mounts
        if isinstance(item, dict) and item.get("Type") == "bind"
    }
    if (
        value.get("Image") != image_id
        or value.get("Path") != path
        or value.get("Args") != arguments
        or host.get("NetworkMode") != network
        or host.get("IpcMode") != "none"
        or host.get("PidMode") not in (None, "")
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or "ALL" not in (host.get("CapDrop") or [])
        or not any(
            str(item).startswith("no-new-privileges") for item in (host.get("SecurityOpt") or [])
        )
        or host.get("Memory") != 1024**3
        or host.get("MemorySwap") != 1024**3
        or host.get("NanoCpus") != 2_000_000_000
        or host.get("PidsLimit") != 128
        or config.get("User") != f"{os.getuid()}:{os.getgid()}"
        or environment.get("HOME") != "/nonexistent"
        or forbidden_environment.intersection(environment)
        or mount_map != mounts
        or any(destination == "/var/run/docker.sock" for destination in mount_map)
    ):
        raise ConfigurationError("OpenHands v52 container controls changed")


def _publish_failure(path: Path, *, context: _RunContext, exc: BaseException) -> None:
    if path.exists() or path.is_symlink():
        return
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v52_materialization_failure_v1",
        "identity": OPENHANDS_V52_IDENTITY,
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
    command_failure = _find_command_failure(exc)
    if command_failure is not None and context.active_stage == "pr2728_image_transfer":
        base["transfer_error"] = redacted_transfer_failure(
            command_failure,
            raw_stderr=command_failure.raw_stderr,
            stage=command_failure.stage,
        )
    atomic_dump_json(path, {**base, "receipt_hash": content_hash(base)})


def _find_command_failure(exc: BaseException) -> _CommandFailure | None:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, _CommandFailure):
            return current
        current = current.__cause__
    return None


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
            raise ConfigurationError("OpenHands v52 required merged path changed")
    subprocess.run(["git", "diff", "--quiet", "--"], cwd=_REPOSITORY, check=True)
    subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=_REPOSITORY, check=True)
    head = _git_output("rev-parse", "HEAD")
    upstream = _git_output("rev-parse", "origin/main")
    if head != upstream or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ConfigurationError("OpenHands v52 requires the clean merged origin/main commit")
    return head


def _validated_dataset(path: Path) -> Path:
    resolved = _safe_file(path)
    if hash_bytes(resolved.read_bytes()) != _DATASET_SHA256:
        raise ConfigurationError("OpenHands v52 official dataset identity changed")
    return resolved


def _validated_rg(path: Path, *, executable: bool, expected: str) -> Path:
    resolved = _safe_file(path)
    if (executable and not os.access(resolved, os.X_OK)) or hash_bytes(
        resolved.read_bytes()
    ) != expected:
        raise ConfigurationError("OpenHands v52 ripgrep input identity changed")
    if "/@openai/codex/" in str(resolved) or "/codex-path/" in str(resolved):
        raise ConfigurationError("OpenHands v52 refuses a Codex-bundled ripgrep")
    return resolved


def _safe_file(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise ConfigurationError("OpenHands v52 input file is unsafe")
    return expanded.resolve(strict=True)


def _safe_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_dir():
        raise ConfigurationError("OpenHands v52 input directory is unsafe")
    return expanded.resolve(strict=True)


def _cleanup_directories(*paths: Path) -> None:
    failure: OSError | None = None
    for path in paths:
        try:
            shutil.rmtree(path)
        except OSError as exc:
            failure = exc
    if failure is not None:
        raise ConfigurationError("OpenHands v52 private staging cleanup failed") from failure


def _load_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ConfigurationError("OpenHands v52 JSON input is unbounded")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("OpenHands v52 JSON input is malformed") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("OpenHands v52 JSON input is not an object")
    return value


def _bounded_run(
    arguments: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
        raise _CommandFailure("timeout", stderr) from exc
    if len(result.stdout) > _MAX_OUTPUT_BYTES or len(result.stderr) > _MAX_OUTPUT_BYTES:
        raise _CommandFailure("output_bound", result.stderr[:_MAX_OUTPUT_BYTES])
    return result


def _docker_json(arguments: list[str]) -> list[dict[str, Any]]:
    result = _bounded_run(arguments, timeout=30)
    if result.returncode != 0:
        raise _CommandFailure("docker_inspect", result.stderr)
    try:
        value = json.loads(result.stdout)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("OpenHands v52 Docker JSON is malformed") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ConfigurationError("OpenHands v52 Docker JSON is not an object list")
    return value


def _git_output(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _required(value: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if value is None:
        raise ConfigurationError(f"OpenHands v52 {label} receipt is missing")
    return copy.deepcopy(value)


def _sealed(base: dict[str, Any]) -> dict[str, Any]:
    return {**base, "receipt_hash": content_hash(base)}


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
