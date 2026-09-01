#!/usr/bin/env python3
"""Qualify public CVA6 PR-2728 exactly once without a model or provider."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from verigym_hwe_bench.cva6_qualification import (
    run_zero_model_smoke,
    zero_model_fail_to_pass_eligible,
    zero_model_infrastructure_valid,
)
from verigym_hwe_bench.models import HweInstance, repository_profile
from verigym_hwe_bench.prepare import (
    prepare_source,
    reference_patch_compatibility,
)

from scripts.qualify_cva6_openhands_v19_public_tasks import (
    _completed_outcome,
    _source_binding,
)
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json

OPENHANDS_V51_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V51_PR2728_QUALIFICATION"
OPENHANDS_V51_APPROVAL_FORMAT = (
    "verigym_openhands_hwe_v51_pr2728_public_qualification_authorization_v1"
)
OPENHANDS_V51_PROGRESS_FORMAT = "verigym_openhands_hwe_v51_pr2728_public_qualification_progress_v1"
OPENHANDS_V51_APPROVAL_HASH = "fe0be8fe67180851a2f507559822f2baf4c50939b9bc2487e0145e783520a8b3"
OPENHANDS_V51_IDENTITY = "openhands-hwe-v51-pr2728-public-qualification-v1"
OPENHANDS_V51_NETWORK = "verigym-hwe-net"
OPENHANDS_V51_TOOL_CACHE = Path(
    "/data/jzhu484/Agent/.verigym-tmp/openhands-v24-crane-v0.22.0-slsa-v2.7.1"
)
OPENHANDS_V51_SCRATCH = Path(
    "/data/jzhu484/Agent/.verigym-tmp/openhands-v51-pr2728-public-qualification-v1"
)
OPENHANDS_V51_CANDIDATE_NUMBER = 2728
OPENHANDS_V51_CANDIDATE_TASK_ID = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2728"
OPENHANDS_V51_CANDIDATE_INSTANCE_ID = "openhwgroup/cva6:pr-2728"
OPENHANDS_V51_CANDIDATE_REFERENCE = "ghcr.io/pku-liang/openhwgroup_m_cva6:pr-2728"
OPENHANDS_V51_CANDIDATE_REFERENCES = (OPENHANDS_V51_CANDIDATE_REFERENCE,)
OPENHANDS_V51_PATCH_COMPATIBILITY_HASH = (
    "cccec1b44901f1e3cd7d6694a5a825cd9716536e445a7678ff408cedcf6fe0d2"
)
OPENHANDS_V51_CANDIDATE_RECORD_SHA256 = (
    "42f3040a91af4e735e1107dd2536691c9fa3286b4e9441cc8ebb039e3d3c1a16"
)

_V50_FAILURE_AUDIT_MERGE = "6177cfa5d9566bdebbd3feef9be54e7329349a37"
_V50_FAILURE_AUDIT_SHA256 = "5ff1ac06b007c16cf47634a85d544c7388d86e74ea82bee910c6a1136977680e"
_V50_MAIN_RUN_ID = 33513250028
_V50_EVIDENCE_TREE_HASH = "ac49a3f79ea7b1e025280a822057f8c7f370a6cc328e7f7bec8be057adace418"
_V50_REPORT_HASH = "11a6cc828708e6a2fa48214e5c241436e8ba55c599e210c43f78846b4e32075f"
_V50_ATTEMPT_RUN_HASH = "a95c81161ccbc8ac8e3d8ce3f52393d524c05e5876e980df6461d93b0a90d42c"
_V50_SCORECARD_HASH = "9d630fb264b6909b08836be16e911536916282dab8b48e1a5bdc497bdbecc848"
_DATASET_SHA256 = "732c5dac910815c1c7ac72c8ccca88f66dbb7ed5d097806a5ddea611102f60f1"
_DATASET_REVISION = "1403afb57ce056c659c82b35e39c38c6a21ee635"
_DATASET_SOURCE_COMMIT = "10c78a87e1f92695d78d15b1464a6107dcac8837"
_MIN_DOCKER_AVAILABLE_BYTES = 64 * 1024 * 1024 * 1024
_MIN_DOCKER_AVAILABLE_INODES = 1_000_000
_DOCKER_ROOT = Path("/data/docker")
_SCRATCH_PARENT = Path("/data/jzhu484/Agent/.verigym-tmp")
_HELDOUT_CVA6_NUMBERS = frozenset({2374, 2945, 3107, 3171})
_EXCLUDED_PUBLIC_NUMBERS = frozenset(
    {
        1482,
        2032,
        2170,
        2248,
        2282,
        2330,
        2374,
        2468,
        2469,
        2549,
        2589,
        2802,
        2844,
        2916,
        2944,
        2945,
        2989,
        3059,
        3107,
        3168,
        3171,
        3191,
        3204,
        3226,
        3231,
    }
)
_REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_openhands_v51_pr2728_public_qualification_v1.json",
    "docs/audits/2026-09-01_openhands-v50-provider-canary-failed-closed.md",
    "docs/audits/2026-09-01_openhands-v51-pr2728-public-qualification-authorization.md",
    "integrations/verigym-openhands/tests/test_hwe_v51_pr2728_public_qualification.py",
    "scripts/qualify_cva6_openhands_v51_pr2728_public_qualification.py",
)

_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_DATASET_LINE_BYTES = 16 * 1024 * 1024
_MAX_DIAGNOSTIC_BYTES = 16 * 1024
_MAX_CONFIG_BYTES = 16 * 1024 * 1024
_MAX_TARBALL_BYTES = 64 * 1024 * 1024 * 1024
_MAX_TARBALL_MEMBERS = 8_192
_MEMORY_BYTES = 1024 * 1024 * 1024
_PIDS_LIMIT = 128
_TMPFS = "rw,noexec,nosuid,nodev,size=67108864,mode=1777"
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CRANE_SHA256 = "771ced475a87b8b2314b9f9de267264789b3297f34a6d5d8ab601e8482db4d94"
_EXECUTION_IMAGE_ENVIRONMENT = (
    "PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG=C.UTF-8",
    "GPG_KEY=A035C8C19219BA821ECEA86B64E628F8D684696D",
    "PYTHON_VERSION=3.11.9",
    "PYTHON_PIP_VERSION=24.0",
    "PYTHON_SETUPTOOLS_VERSION=65.5.1",
    "PYTHON_GET_PIP_URL=https://github.com/pypa/get-pip/raw/"
    "def4aec84b261b939137dd1c69eff0aabb4a7bf4/public/get-pip.py",
    "PYTHON_GET_PIP_SHA256=bc37786ec99618416cc0a0ca32833da447f4d91ab51d2c138dd15b7af21e8e9a",
    "HOME=/nonexistent",
)


class _StageFailure(ConfigurationError):
    def __init__(self, message: str, *, diagnostic: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostic = copy.deepcopy(diagnostic)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _top_level_number(raw: bytes) -> int | None:
    """Extract only the top-level PR number without decoding unselected record values."""

    depth = 0
    index = 0
    while index < len(raw):
        character = raw[index]
        if character in b"[{":
            depth += 1
            index += 1
            continue
        if character in b"]}":
            depth -= 1
            if depth < 0:
                raise ConfigurationError("OpenHands v51 dataset envelope is malformed")
            index += 1
            continue
        if character != ord('"'):
            index += 1
            continue
        start = index
        index += 1
        while index < len(raw):
            if raw[index] == ord("\\"):
                index += 2
                continue
            if raw[index] == ord('"'):
                break
            index += 1
        if index >= len(raw):
            raise ConfigurationError("OpenHands v51 dataset envelope has an unterminated string")
        end = index
        index += 1
        if depth != 1:
            continue
        cursor = index
        while cursor < len(raw) and raw[cursor] in b" \t\r\n":
            cursor += 1
        if cursor >= len(raw) or raw[cursor] != ord(":"):
            continue
        try:
            key = json.loads(raw[start : end + 1])
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError("OpenHands v51 dataset key is malformed") from exc
        if key != "number":
            continue
        cursor += 1
        while cursor < len(raw) and raw[cursor] in b" \t\r\n":
            cursor += 1
        match = re.match(rb"-?\d+", raw[cursor:])
        if match is None:
            raise ConfigurationError("OpenHands v51 top-level PR number is malformed")
        terminator = cursor + len(match.group())
        while terminator < len(raw) and raw[terminator] in b" \t\r\n":
            terminator += 1
        if terminator >= len(raw) or raw[terminator] not in b",}":
            raise ConfigurationError("OpenHands v51 top-level PR number is not an integer")
        return int(match.group())
    if depth != 0:
        raise ConfigurationError("OpenHands v51 dataset envelope is unbalanced")
    return None


def _selected_candidate(
    dataset: Path, approved: dict[str, Any]
) -> tuple[dict[str, Any], HweInstance, bytes, dict[str, Any]]:
    """Decode only PR-2728 and expose content-free qualification metadata."""

    selected: list[bytes] = []
    with dataset.open("rb") as stream:
        for raw in stream:
            if not raw or len(raw) > _MAX_DATASET_LINE_BYTES:
                raise ConfigurationError("OpenHands v51 dataset line is unbounded")
            number = _top_level_number(raw)
            if number == OPENHANDS_V51_CANDIDATE_NUMBER:
                selected.append(raw)
            elif number in _HELDOUT_CVA6_NUMBERS:
                # The record envelope is inspected, but held-out JSON values are never decoded.
                continue
    if len(selected) != 1:
        raise ConfigurationError("OpenHands v51 selected public record is not unique")
    raw = selected[0]
    if hashlib.sha256(raw).hexdigest() != OPENHANDS_V51_CANDIDATE_RECORD_SHA256:
        raise ConfigurationError("OpenHands v51 selected public record identity changed")
    try:
        row = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("OpenHands v51 selected public record is malformed") from exc
    if not isinstance(row, dict):
        raise ConfigurationError("OpenHands v51 selected public record is not an object")
    base = row.get("base")
    f2p = row.get("f2p_tests")
    fix_result = row.get("fix_patch_result")
    test_result = row.get("test_patch_result")
    modified_files = row.get("modified_files")
    if (
        row.get("org") != "openhwgroup"
        or row.get("repo") != "cva6"
        or row.get("number") != OPENHANDS_V51_CANDIDATE_NUMBER
        or not isinstance(base, dict)
        or not isinstance(base.get("sha"), str)
        or re.fullmatch(r"[0-9a-f]{40}", base["sha"]) is None
        or not isinstance(f2p, dict)
        or not f2p
        or not isinstance(fix_result, dict)
        or fix_result.get("failed_count") != 0
        or fix_result.get("skipped_count") != 0
        or fix_result.get("passed_count", 0) < 1
        or not isinstance(test_result, dict)
        or test_result.get("failed_count", 0) < 1
        or not isinstance(row.get("fix_patch"), str)
        or not isinstance(row.get("test_patch"), str)
        or not isinstance(modified_files, list)
        or any(not isinstance(item, str) for item in modified_files)
    ):
        raise ConfigurationError("OpenHands v51 public F2P task identity changed")
    profile = repository_profile("openhwgroup/cva6")
    instance = HweInstance(
        org="openhwgroup",
        repo="cva6",
        number=OPENHANDS_V51_CANDIDATE_NUMBER,
        title=str(row.get("title") or OPENHANDS_V51_CANDIDATE_INSTANCE_ID),
        problem_statement=str(row.get("problem_statement") or ""),
        base_commit=base["sha"],
        fix_patch=row["fix_patch"],
        test_patch=row["test_patch"],
        tb_script=str(row.get("tb_script") or ""),
        modified_files=list(modified_files),
        expected_test_ids=sorted(str(value) for value in f2p),
        language=profile.language,
        license_id=profile.license_expression,
    )
    changed_lines = sum(
        1
        for line in instance.fix_patch.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )
    candidate = {
        "number": OPENHANDS_V51_CANDIDATE_NUMBER,
        "task_id": OPENHANDS_V51_CANDIDATE_TASK_ID,
        "instance_id": OPENHANDS_V51_CANDIDATE_INSTANCE_ID,
        "changed_line_count": changed_lines,
        "modified_file_count": len(set(instance.modified_files)),
    }
    compatibility = asdict(reference_patch_compatibility(instance, temporary_root=_SCRATCH_PARENT))
    receipt_hash = content_hash(compatibility)
    receipt = {**compatibility, "receipt_hash": receipt_hash}
    if (
        OPENHANDS_V51_CANDIDATE_NUMBER in _EXCLUDED_PUBLIC_NUMBERS
        or OPENHANDS_V51_CANDIDATE_NUMBER in _HELDOUT_CVA6_NUMBERS
        or candidate != approved.get("candidate")
        or changed_lines != 25
        or candidate["modified_file_count"] != 1
        or receipt_hash != OPENHANDS_V51_PATCH_COMPATIBILITY_HASH
        or approved.get("reference_patch_compatibility") != receipt
        or compatibility
        != {
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
        }
    ):
        raise ConfigurationError("OpenHands v51 public-task selection changed")
    return candidate, instance, raw, receipt


def _write_selected_dataset(scratch: Path, raw: bytes) -> Path:
    path = scratch / "public-pr-2728.jsonl"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != (
        OPENHANDS_V51_CANDIDATE_RECORD_SHA256
    ):
        raise ConfigurationError("OpenHands v51 selected dataset materialization changed")
    return path


def qualify_v51_streamed_public_tasks(
    *, approval_path: Path, dataset: Path, output: Path
) -> dict[str, Any]:
    """Transfer and qualify only never-attempted public PR-2728, with no retry."""

    if os.environ.get(OPENHANDS_V51_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V51_OPT_IN_ENV}=1 is required")
    approved = _validated_authorization(_load_json(approval_path))
    resolved_dataset = _validated_dataset(dataset, approved=approved)
    candidate, _instance, raw_candidate, compatibility = _selected_candidate(
        resolved_dataset, approved
    )
    source_commit = _merged_source_commit()
    _validate_network()
    execution_image = _validate_local_image(approved["execution_image"])
    tool_cache = _validated_tool_cache(approved["tool_cache"])
    headroom = _validate_headroom()
    if (
        _count_host_candidate_images() != 0
        or _inspect_host_image(_sentinel_reference()) is not None
    ):
        raise ConfigurationError(
            "OpenHands v51 qualification requires an empty candidate inventory"
        )
    scratch = _new_scratch_directory()
    try:
        root = _new_directory(output)
        selected_dataset = _write_selected_dataset(scratch, raw_candidate)
    except BaseException:
        _cleanup_scratch(scratch)
        raise
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V51_PROGRESS_FORMAT,
        "status": "running",
        "identity": OPENHANDS_V51_IDENTITY,
        "authorization_hash": approved["authorization_hash"],
        "merged_source_commit": source_commit,
        "predecessor_v50_status": approved["predecessor_v50"]["status"],
        "predecessor_v50_evidence_tree_hash": approved["predecessor_v50"]["evidence_tree_hash"],
        "official_dataset_sha256": approved["dataset"]["sha256"],
        "official_dataset_revision": approved["dataset"]["revision"],
        "official_source_commit": approved["dataset"]["source_commit"],
        "candidate": candidate,
        "candidate_record_sha256": OPENHANDS_V51_CANDIDATE_RECORD_SHA256,
        "reference_patch_compatibility": compatibility,
        "reference_patch_preflight_completed_before_image_access": True,
        "network": OPENHANDS_V51_NETWORK,
        "verifier_network": "none",
        "headroom_preflight": headroom,
        "implicit_image_pulls_allowed": False,
        "streamed_transfer_and_qualification": True,
        "shared_layer_cache_enabled": True,
        "bounded_pull_stderr_allowed": True,
        "model_process_count": 0,
        "provider_calls": 0,
        "heldout_task_ids_loaded": [],
        "heldout_record_values_decoded": False,
        "historical_attempts_retried": False,
        "automatic_retry": False,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "active_task_id": None,
        "active_pull_receipt": None,
        "outcomes": [],
        "qualified_bindings": {},
        "image_transfers": {},
        "failure_diagnostic": None,
    }
    _write_progress(root, progress)
    failure: BaseException | None = None
    try:
        ca_output, ca_control, ca_receipt = _run_controlled_container(
            image_id=execution_image["image_id"],
            tool_cache=tool_cache,
            scratch=scratch,
            network="none",
            path="/usr/bin/test",
            arguments=["-s", "/etc/ssl/certs/ca-certificates.crt"],
            label_role="ca-bundle-precheck",
            timeout=300,
            output_bound=_MAX_DIAGNOSTIC_BYTES,
        )
        if ca_output or ca_receipt["stderr_bytes"] != 0:
            raise _StageFailure(
                "OpenHands v51 CA precheck emitted output",
                diagnostic={**ca_receipt, "failure_stage": "ca_bundle_precheck_output"},
            )
        progress["ca_bundle_precheck_passed"] = True
        progress["ca_bundle_control_hash"] = ca_control["control_hash"]
        progress["ca_bundle_command_receipt"] = ca_receipt
        _write_progress(root, progress)

        for scheduled, reference in zip(
            (candidate,), OPENHANDS_V51_CANDIDATE_REFERENCES, strict=True
        ):
            if scheduled != candidate or progress["outcomes"]:
                raise ConfigurationError("OpenHands v51 one-task schedule changed")
            task_id = str(candidate["task_id"])
            if task_id != OPENHANDS_V51_CANDIDATE_TASK_ID:
                raise ConfigurationError("OpenHands v51 qualification schedule changed")
            progress["active_task_id"] = task_id
            _write_progress(root, progress)

            def persist_pull_receipt(receipt: dict[str, Any]) -> None:
                progress["active_pull_receipt"] = copy.deepcopy(receipt)
                _write_progress(root, progress)

            transfer = _transfer_candidate(
                reference=reference,
                image_id=execution_image["image_id"],
                tool_cache=tool_cache,
                scratch=scratch,
                pull_receipt_sink=persist_pull_receipt,
            )
            progress["image_transfers"][task_id] = transfer
            progress["active_pull_receipt"] = None
            _write_progress(root, progress)

            source_relative = f"sources/pr-{candidate['number']}"
            smoke_relative = f"smokes/pr-{candidate['number']}"
            source = root / source_relative
            smoke = root / smoke_relative
            binding: dict[str, str] | None = None
            report: dict[str, Any] | None = None
            task_failure: Exception | None = None
            try:
                prepare_source(
                    dataset=selected_dataset,
                    output=source,
                    selected_tasks=[str(candidate["instance_id"])],
                    pull=False,
                    official_dataset_revision=approved["dataset"]["revision"],
                    official_source_commit=approved["dataset"]["source_commit"],
                    imported_image_bindings={
                        reference: {
                            "image_id": transfer["image_id"],
                            "manifest_digest": transfer["manifest_digest"],
                        }
                    },
                )
                binding = _source_binding(source, expected_task_id=task_id)
                if (
                    binding["verifier_image"] != transfer["image_id"]
                    or binding["verifier_manifest_digest"] != transfer["manifest_digest"]
                ):
                    raise ConfigurationError(
                        "OpenHands v51 prepared source transfer binding changed"
                    )
                report = run_zero_model_smoke(source=source, output=smoke)
            except Exception as exc:
                task_failure = exc
                report = _load_optional_report(smoke / "smoke-report.json")

            if report is not None and zero_model_infrastructure_valid(report):
                if binding is None:
                    try:
                        binding = _source_binding(source, expected_task_id=task_id)
                    except Exception as exc:
                        task_failure = exc
                if binding is not None:
                    outcome = _completed_outcome(
                        candidate=candidate,
                        binding=binding,
                        report=report,
                    )
                    progress["outcomes"].append(outcome)
                    if zero_model_fail_to_pass_eligible(report):
                        progress["qualified_bindings"][task_id] = {
                            **binding,
                            "source": source_relative,
                            "smoke": smoke_relative,
                            "transfer_receipt_hash": transfer["transfer_receipt_hash"],
                        }
                    progress["active_task_id"] = None
                    _write_progress(root, progress)
                    continue

            progress["outcomes"].append(
                {
                    "task_id": task_id,
                    "instance_id": candidate["instance_id"],
                    "changed_line_count": candidate["changed_line_count"],
                    "modified_file_count": candidate["modified_file_count"],
                    "infrastructure_valid": False,
                    "verifier_network": "none",
                    "verifier_image": transfer["image_id"],
                    "model_process_count": 0,
                    "base_failed": False,
                    "reference_passed": False,
                    "status": "infrastructure_invalid",
                    "failure_type": (
                        type(task_failure).__name__ if task_failure is not None else "UnknownError"
                    ),
                }
            )
            progress["active_task_id"] = None
            progress["status"] = "stopped_infrastructure_invalid"
            _write_progress(root, progress)
            raise ConfigurationError(
                f"OpenHands v51 qualification stopped on infrastructure-invalid {task_id}"
            ) from task_failure

        progress["active_task_id"] = None
        qualified = list(progress["qualified_bindings"])
        progress["qualified_task_ids"] = qualified
        progress["training_candidate_task_ids"] = qualified
        if qualified == [OPENHANDS_V51_CANDIDATE_TASK_ID]:
            progress["status"] = "qualified_pending_command_image"
        elif progress["status"] == "running":
            progress["status"] = "not_qualified"
            progress["stop_reason"] = "ordinary_base_or_reference_mismatch"
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc
        if progress["status"] == "running":
            progress["status"] = "stopped_security_or_infrastructure_invalid"
        diagnostic = getattr(exc, "diagnostic", None)
        progress["failure_diagnostic"] = (
            diagnostic
            if isinstance(diagnostic, dict)
            else {
                "failure_stage": "qualification_orchestration",
                "failure_type": type(exc).__name__,
            }
        )
    finally:
        try:
            _cleanup_scratch(scratch)
            progress["temporary_transfer_scratch_removed"] = True
        except (Exception, KeyboardInterrupt) as exc:
            if failure is None:
                failure = exc
            progress["temporary_transfer_scratch_removed"] = False
            progress["status"] = "stopped_security_or_infrastructure_invalid"
            progress["failure_diagnostic"] = {
                "failure_stage": "transfer_scratch_cleanup",
                "failure_type": type(exc).__name__,
            }
        progress["host_candidate_images_present"] = _count_host_candidate_images()
        progress["temporary_containers_removed"] = _count_temporary_containers() == 0
        progress["docker_socket_mounted"] = False
        progress["privileged_container_used"] = False
        progress["tcp_api_listener_present"] = False
        _write_progress(root, progress)
    if failure is not None:
        raise ConfigurationError("OpenHands v51 streamed qualification failed") from failure
    return _sealed(progress)


def _transfer_candidate(
    *,
    reference: str,
    image_id: str,
    tool_cache: Path,
    scratch: Path,
    pull_receipt_sink: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    if reference not in OPENHANDS_V51_CANDIDATE_REFERENCES:
        raise ConfigurationError("OpenHands v51 transfer reference is not frozen")
    if _inspect_host_image(reference) is not None:
        raise ConfigurationError("OpenHands v51 candidate appeared before its transfer")
    digest_output, digest_control, digest_receipt = _run_controlled_container(
        image_id=image_id,
        tool_cache=tool_cache,
        scratch=scratch,
        network=OPENHANDS_V51_NETWORK,
        path="/tools/crane",
        arguments=["digest", reference],
        label_role="candidate-digest",
        timeout=300,
        output_bound=_MAX_DIAGNOSTIC_BYTES,
    )
    try:
        manifest_digest = digest_output.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise ConfigurationError("OpenHands v51 candidate digest is not ASCII") from exc
    if not _SHA256_DIGEST.fullmatch(manifest_digest):
        raise ConfigurationError("OpenHands v51 candidate digest is malformed")
    immutable_reference = f"{reference.rsplit(':', 1)[0]}@{manifest_digest}"
    config_output, config_control, config_receipt = _run_controlled_container(
        image_id=image_id,
        tool_cache=tool_cache,
        scratch=scratch,
        network=OPENHANDS_V51_NETWORK,
        path="/tools/crane",
        arguments=["config", immutable_reference],
        label_role="candidate-config",
        timeout=300,
        output_bound=_MAX_CONFIG_BYTES,
    )
    if not config_output:
        raise ConfigurationError("OpenHands v51 candidate config is empty")
    expected_image_id = f"sha256:{hashlib.sha256(config_output).hexdigest()}"
    archive = scratch / "candidate-image.tar"
    if archive.exists() or archive.is_symlink():
        raise ConfigurationError("OpenHands v51 candidate archive path is not empty")
    pull_output, pull_control, pull_receipt = _run_controlled_container(
        image_id=image_id,
        tool_cache=tool_cache,
        scratch=scratch,
        network=OPENHANDS_V51_NETWORK,
        path="/tools/crane",
        arguments=[
            "pull",
            immutable_reference,
            "/transfer/candidate-image.tar",
            "--format=tarball",
            "--cache_path=/transfer/layer-cache",
        ],
        label_role="candidate-pull",
        timeout=3_600,
        output_bound=_MAX_DIAGNOSTIC_BYTES,
    )
    stderr_bytes = pull_receipt.get("stderr_bytes")
    pull_observation = {
        **pull_receipt,
        "stdout_empty": not pull_output,
        "stderr_bounded": (
            isinstance(stderr_bytes, int) and 0 <= stderr_bytes <= _MAX_DIAGNOSTIC_BYTES
        ),
        "raw_output_persisted": False,
    }
    pull_receipt_sink(pull_observation)
    if not pull_observation["stderr_bounded"] or pull_output:
        raise _StageFailure(
            "OpenHands v51 crane pull output policy failed",
            diagnostic={**pull_observation, "failure_stage": "candidate_pull_output_policy"},
        )
    archive_receipt = _validated_crane_tarball(
        archive,
        expected_image_id=expected_image_id,
        expected_sentinel=_sentinel_reference(),
    )
    loaded = subprocess.run(
        ["docker", "image", "load", "--input", str(archive)],
        check=False,
        capture_output=True,
        timeout=3_600,
    )
    load_receipt = {
        "exit_code": loaded.returncode,
        "stdout_bytes": len(loaded.stdout),
        "stderr_bytes": len(loaded.stderr),
        "stdout_sha256": hashlib.sha256(loaded.stdout).hexdigest(),
        "stderr_present": bool(loaded.stderr),
    }
    if (
        loaded.returncode != 0
        or len(loaded.stdout) > _MAX_DIAGNOSTIC_BYTES
        or len(loaded.stderr) > _MAX_DIAGNOSTIC_BYTES
    ):
        raise _StageFailure(
            "OpenHands v51 Docker image load failed",
            diagnostic={**load_receipt, "failure_stage": "candidate_image_load"},
        )
    sentinel = _inspect_host_image(_sentinel_reference())
    if sentinel is None or sentinel.get("Id") != expected_image_id:
        raise ConfigurationError("OpenHands v51 loaded image config identity changed")
    tagged = subprocess.run(
        ["docker", "image", "tag", expected_image_id, reference],
        check=False,
        capture_output=True,
        timeout=60,
    )
    if tagged.returncode != 0 or tagged.stdout or tagged.stderr:
        raise ConfigurationError("OpenHands v51 candidate image tag failed")
    imported = _inspect_host_image(reference)
    if imported is None or imported.get("Id") != expected_image_id:
        raise ConfigurationError("OpenHands v51 candidate image import identity changed")
    removed = subprocess.run(
        ["docker", "image", "rm", _sentinel_reference()],
        check=False,
        capture_output=True,
        timeout=60,
    )
    if removed.returncode != 0 or _inspect_host_image(_sentinel_reference()) is not None:
        raise ConfigurationError("OpenHands v51 digest sentinel cleanup failed")
    archive.unlink()
    base = {
        "reference": reference,
        "manifest_digest": manifest_digest,
        "image_id": expected_image_id,
        "config_bytes": len(config_output),
        "config_sha256": hashlib.sha256(config_output).hexdigest(),
        "archive": archive_receipt,
        "digest_control_hash": digest_control["control_hash"],
        "config_control_hash": config_control["control_hash"],
        "pull_control_hash": pull_control["control_hash"],
        "command_receipts": {
            "digest": digest_receipt,
            "config": config_receipt,
            "pull": pull_receipt,
            "load": load_receipt,
        },
        "digest_qualified_pull": True,
        "shared_layer_cache_used": True,
        "pull_stdout_empty": True,
        "bounded_pull_stderr_allowed": True,
        "temporary_archive_removed": True,
        "sentinel_tag_removed": True,
    }
    return {**base, "transfer_receipt_hash": content_hash(base)}


def _run_controlled_container(
    *,
    image_id: str,
    tool_cache: Path,
    scratch: Path,
    network: str,
    path: str,
    arguments: list[str],
    label_role: str,
    timeout: int,
    output_bound: int,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    resolved_tools = tool_cache.resolve(strict=True)
    resolved_scratch = scratch.resolve(strict=True)
    container_name = f"verigym-hwe-v51-{label_role}-{os.getpid()}-{secrets.token_hex(4)}"
    command = [
        "docker",
        "create",
        "--pull",
        "never",
        "--name",
        container_name,
        "--label",
        f"org.verigym.owner={OPENHANDS_V51_IDENTITY}",
        "--label",
        f"org.verigym.role={label_role}",
        "--network",
        network,
        "--ipc",
        "none",
        "--read-only",
        "--tmpfs",
        f"/tmp:{_TMPFS}",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        str(_MEMORY_BYTES),
        "--memory-swap",
        str(_MEMORY_BYTES),
        "--cpus",
        "2",
        "--pids-limit",
        str(_PIDS_LIMIT),
        "--workdir",
        "/transfer",
        "--env",
        "HOME=/nonexistent",
        "--mount",
        f"type=bind,src={resolved_tools},dst=/tools,readonly",
        "--mount",
        f"type=bind,src={resolved_scratch},dst=/transfer",
        "--entrypoint",
        path,
        image_id,
        *arguments,
    ]
    diagnostic: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v51_command_receipt_v1",
        "role": label_role,
        "network": network,
        "create_exit_code": None,
        "create_stdout_bytes": 0,
        "create_stderr_bytes": 0,
        "exit_code": None,
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "stderr_present": False,
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "temporary_container_removed": False,
    }
    result: tuple[bytes, dict[str, Any]] | None = None
    failure: BaseException | None = None
    try:
        created = subprocess.run(command, check=False, capture_output=True, timeout=60)
        diagnostic.update(
            {
                "create_exit_code": created.returncode,
                "create_stdout_bytes": len(created.stdout),
                "create_stderr_bytes": len(created.stderr),
            }
        )
        if (
            created.returncode != 0
            or len(created.stdout) > _MAX_DIAGNOSTIC_BYTES
            or len(created.stderr) > _MAX_DIAGNOSTIC_BYTES
        ):
            raise ConfigurationError("OpenHands v51 Docker create failed or exceeded its bound")
        container_id = created.stdout.decode("ascii", errors="strict").strip()
        values = _docker_json(["docker", "container", "inspect", container_id])
        if not container_id or len(values) != 1:
            raise ConfigurationError("OpenHands v51 container inspection is malformed")
        control = _validate_container_inspection(
            values[0],
            image_id=image_id,
            tool_cache=resolved_tools,
            scratch=resolved_scratch,
            network=network,
            path=path,
            arguments=arguments,
            label_role=label_role,
        )
        started = subprocess.run(
            ["docker", "start", "--attach", container_id],
            check=False,
            capture_output=True,
            timeout=timeout,
        )
        diagnostic.update(
            {
                "exit_code": started.returncode,
                "stdout_bytes": len(started.stdout),
                "stderr_bytes": len(started.stderr),
                "stderr_present": bool(started.stderr),
                "stdout_sha256": hashlib.sha256(started.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(started.stderr).hexdigest(),
                "control_hash": control["control_hash"],
            }
        )
        if (
            started.returncode != 0
            or len(started.stdout) > output_bound
            or len(started.stderr) > _MAX_DIAGNOSTIC_BYTES
        ):
            raise ConfigurationError(
                "OpenHands v51 controlled command failed or exceeded its bound"
            )
        result = started.stdout, control
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc
    try:
        _remove_container(container_name)
        diagnostic["temporary_container_removed"] = True
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc
        diagnostic["failure_stage"] = "temporary_container_cleanup"
    if failure is not None:
        diagnostic.setdefault("failure_stage", label_role)
        diagnostic["failure_type"] = type(failure).__name__
        raise _StageFailure(
            "OpenHands v51 controlled container stage failed", diagnostic=diagnostic
        ) from failure
    if result is None:
        raise _StageFailure(
            "OpenHands v51 controlled container returned no result", diagnostic=diagnostic
        )
    return result[0], result[1], diagnostic


def _validate_container_inspection(
    container: dict[str, Any],
    *,
    image_id: str,
    tool_cache: Path,
    scratch: Path,
    network: str,
    path: str,
    arguments: list[str],
    label_role: str,
) -> dict[str, Any]:
    host = container.get("HostConfig")
    config = container.get("Config")
    mounts = container.get("Mounts")
    network_settings = container.get("NetworkSettings")
    if (
        not isinstance(host, dict)
        or not isinstance(config, dict)
        or not isinstance(network_settings, dict)
        or not isinstance(mounts, list)
    ):
        raise ConfigurationError("OpenHands v51 effective controls are malformed")
    mount_map = {str(item.get("Destination")): item for item in mounts if isinstance(item, dict)}
    environment = _environment_map(config.get("Env"))
    expected_environment = _environment_map(list(_EXECUTION_IMAGE_ENVIRONMENT))
    security_options = host.get("SecurityOpt") or []
    tmpfs = host.get("Tmpfs") or {}
    labels = config.get("Labels") or {}
    tools_mount = mount_map.get("/tools")
    scratch_mount = mount_map.get("/transfer")
    valid = (
        container.get("Image") == image_id
        and container.get("Path") == path
        and container.get("Args") == arguments
        and host.get("NetworkMode") == network
        and host.get("IpcMode") == "none"
        and host.get("PidMode") in {"", None}
        and host.get("ReadonlyRootfs") is True
        and host.get("Privileged") is False
        and not (host.get("CapAdd") or [])
        and (host.get("CapDrop") or []) == ["ALL"]
        and not (host.get("Devices") or [])
        and any(str(value).startswith("no-new-privileges") for value in security_options)
        and host.get("Memory") == _MEMORY_BYTES
        and host.get("MemorySwap") == _MEMORY_BYTES
        and host.get("NanoCpus") == 2_000_000_000
        and host.get("PidsLimit") == _PIDS_LIMIT
        and host.get("PublishAllPorts") is False
        and host.get("PortBindings") in (None, {})
        and host.get("RestartPolicy", {}).get("Name") in {"", "no"}
        and host.get("AutoRemove") is False
        and isinstance(tmpfs, dict)
        and tmpfs.get("/tmp") == _TMPFS
        and len(mounts) == 2
        and isinstance(tools_mount, dict)
        and tools_mount.get("Source") == str(tool_cache)
        and tools_mount.get("RW") is False
        and isinstance(scratch_mount, dict)
        and scratch_mount.get("Source") == str(scratch)
        and scratch_mount.get("RW") is True
        and config.get("User") == f"{os.getuid()}:{os.getgid()}"
        and config.get("WorkingDir") == "/transfer"
        and config.get("ExposedPorts") in (None, {})
        and config.get("Volumes") in (None, {})
        and environment == expected_environment
        and labels.get("org.verigym.owner") == OPENHANDS_V51_IDENTITY
        and labels.get("org.verigym.role") == label_role
        and network_settings.get("Ports") in (None, {})
    )
    if not valid:
        raise ConfigurationError("OpenHands v51 effective container controls changed")
    base = {
        "network": network,
        "path": path,
        "arguments": arguments,
        "privileged": False,
        "read_only_rootfs": True,
        "non_root_user": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "ipc_mode": "none",
        "private_pid_namespace": True,
        "bounded_resources": True,
        "tool_cache_mount_read_only": True,
        "transfer_scratch_mount_read_write": True,
        "docker_socket_mounted": False,
        "published_ports": False,
        "environment_names": sorted(environment),
    }
    return {**base, "control_hash": content_hash(base)}


def _validated_crane_tarball(
    path: Path, *, expected_image_id: str, expected_sentinel: str
) -> dict[str, Any]:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= _MAX_TARBALL_BYTES
    ):
        raise ConfigurationError("OpenHands v51 candidate tarball is unsafe")
    with tarfile.open(path, mode="r:") as archive:
        members = archive.getmembers()
        if not 1 <= len(members) <= _MAX_TARBALL_MEMBERS:
            raise ConfigurationError("OpenHands v51 candidate tarball inventory is unbounded")
        names = [member.name for member in members]
        if len(names) != len(set(names)) or any(
            not member.isfile() or member.name.startswith(("/", "../")) or "/../" in member.name
            for member in members
        ):
            raise ConfigurationError("OpenHands v51 candidate tarball entries are unsafe")
        manifests = [member for member in members if member.name == "manifest.json"]
        if len(manifests) != 1 or not 1 <= manifests[0].size <= _MAX_JSON_BYTES:
            raise ConfigurationError("OpenHands v51 candidate tarball manifest is malformed")
        stream = archive.extractfile(manifests[0])
        if stream is None:
            raise ConfigurationError("OpenHands v51 candidate tarball manifest is unreadable")
        try:
            value = json.loads(stream.read())
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError("OpenHands v51 candidate tarball manifest is invalid") from exc
    if (
        not isinstance(value, list)
        or len(value) != 1
        or not isinstance(value[0], dict)
        or value[0].get("Config") != expected_image_id
        or value[0].get("RepoTags") != [expected_sentinel]
        or expected_image_id not in names
    ):
        raise ConfigurationError("OpenHands v51 candidate tarball identity changed")
    return {
        "size_bytes": metadata.st_size,
        "sha256": _sha256_file(path),
        "member_count": len(members),
        "config_image_id": expected_image_id,
        "sentinel_reference": expected_sentinel,
    }


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    observed_hash = value.pop("authorization_hash", None)
    if (
        observed_hash != OPENHANDS_V51_APPROVAL_HASH
        or content_hash(value) != OPENHANDS_V51_APPROVAL_HASH
    ):
        raise ConfigurationError("OpenHands v51 authorization identity changed")
    value["authorization_hash"] = observed_hash
    predecessor = value.get("predecessor_v50")
    dataset = value.get("dataset")
    tool_cache = value.get("tool_cache")
    controls = value.get("required_controls")
    actions = value.get("authorized_actions")
    if (
        value.get("schema_version") != "1.0"
        or value.get("format_id") != OPENHANDS_V51_APPROVAL_FORMAT
        or value.get("status") != "authorized_pending_qualification"
        or value.get("identity") != OPENHANDS_V51_IDENTITY
        or value.get("network") != OPENHANDS_V51_NETWORK
        or value.get("candidate") != _expected_candidate()
        or value.get("candidate_record_sha256") != OPENHANDS_V51_CANDIDATE_RECORD_SHA256
        or value.get("reference_patch_compatibility") != _expected_patch_compatibility()
        or value.get("qualification_target") != 1
        or value.get("candidate_role") != "training"
        or value.get("failure_policy") != "stop_immediately_no_retry"
        or value.get("formal_collection_allowed") is not False
        or value.get("formal_collection_started") is not False
        or value.get("collection_started") is not False
        or value.get("training_started") is not False
        or value.get("production_training_ready") is not False
        or value.get("benchmark_score_claimed") is not False
        or not isinstance(predecessor, dict)
        or predecessor
        != {
            "identity": "openhands-hwe-v50-v22-required-tool-canary-v1",
            "status": "canary_failed_closed",
            "authorization_merge_commit": "90bb1833cf55921a0631d1000ea57f45b736da02",
            "failure_audit_merge_commit": _V50_FAILURE_AUDIT_MERGE,
            "post_merge_main_run_id": _V50_MAIN_RUN_ID,
            "post_merge_main_all_eight_classes_passed": True,
            "evidence_tree_hash": _V50_EVIDENCE_TREE_HASH,
            "report_hash": _V50_REPORT_HASH,
            "attempt_run_hash": _V50_ATTEMPT_RUN_HASH,
            "scorecard_hash": _V50_SCORECARD_HASH,
            "failed_training_task_id": ("hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2916"),
            "failed_training_task_retried": False,
            "validation_task_started": False,
        }
        or not isinstance(dataset, dict)
        or dataset
        != {
            "sha256": _DATASET_SHA256,
            "revision": _DATASET_REVISION,
            "source_commit": _DATASET_SOURCE_COMMIT,
        }
        or not isinstance(tool_cache, dict)
        or tool_cache.get("source_identity") != "openhands-hwe-v24-daemonless-prewarm-preflight-v1"
        or tool_cache.get("crane_release_tag") != "v0.22.0"
        or tool_cache.get("crane_sha256") != _CRANE_SHA256
        or tool_cache.get("bootstrap_receipt_hash")
        != "b44ecb1ceb8d750d6fb2b8ea32c82a1efc3aa437e274b022f660b332ca51407a"
        or tool_cache.get("bootstrap_progress_hash")
        != "1ae3817dc084d06330dac5402ac8c64c8a5d27f33c8e5bea338eeb4e719cd8f6"
        or controls != _required_controls()
        or actions != _authorized_actions()
    ):
        raise ConfigurationError("OpenHands v51 authorization scope changed")
    return value


def _expected_candidate() -> dict[str, Any]:
    return {
        "number": OPENHANDS_V51_CANDIDATE_NUMBER,
        "task_id": OPENHANDS_V51_CANDIDATE_TASK_ID,
        "instance_id": OPENHANDS_V51_CANDIDATE_INSTANCE_ID,
        "changed_line_count": 25,
        "modified_file_count": 1,
    }


def _expected_patch_compatibility() -> dict[str, Any]:
    return {
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
        "receipt_hash": OPENHANDS_V51_PATCH_COMPATIBILITY_HASH,
    }


def _required_controls() -> dict[str, bool]:
    return {
        "clean_merged_origin_main": True,
        "exact_v50_failure_evidence": True,
        "distinct_v51_identity": True,
        "candidate_never_attempted": True,
        "candidate_not_heldout": True,
        "heldout_record_values_decoded": False,
        "reference_patch_preflight_before_image_access": True,
        "reference_patch_raw_output_persisted": False,
        "docker_root_headroom_rechecked": True,
        "privileged": False,
        "docker_socket_mount": False,
        "docker_daemon_process": False,
        "tcp_api_listener": False,
        "read_only_rootfs": True,
        "non_root_user": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "two_exact_mounts": True,
        "default_bridge_used": False,
        "provider_or_registry_credentials_present": False,
        "proxy_values_forwarded": False,
        "tls_verification_disabled": False,
        "networkless_verifier": True,
        "digest_qualified_candidate_pull": True,
        "remote_config_to_local_image_id_binding": True,
        "tarball_inventory_validation": True,
        "atomic_progress": True,
        "shared_content_addressed_layer_cache": True,
        "single_task_schedule_rechecked": True,
        "pull_stdout_must_be_empty": True,
        "bounded_pull_stderr_allowed": True,
        "content_free_pull_receipt_persisted_before_policy": True,
        "automatic_retry": False,
    }


def _authorized_actions() -> dict[str, bool]:
    return {
        "select_public_pr_2728": True,
        "classify_reference_patch_metadata": True,
        "resolve_candidate_digests": True,
        "download_candidate_images": True,
        "load_candidate_images": True,
        "run_zero_model_qualification": True,
        "invoke_provider": False,
        "build_command_image": False,
        "materialize_canary_contract": False,
        "start_collection": False,
        "start_training": False,
        "load_heldout_tasks": False,
    }


def _validated_dataset(path: Path, *, approved: dict[str, Any]) -> Path:
    expanded = path.expanduser()
    if (
        expanded.is_symlink()
        or not expanded.is_file()
        or expanded.stat().st_size > 512 * 1024 * 1024
    ):
        raise ConfigurationError("OpenHands v51 dataset is unsafe")
    resolved = expanded.resolve(strict=True)
    if _sha256_file(resolved) != approved["dataset"]["sha256"]:
        raise ConfigurationError("OpenHands v51 dataset identity changed")
    return resolved


def _validated_tool_cache(binding: dict[str, Any]) -> Path:
    resolved = OPENHANDS_V51_TOOL_CACHE.resolve(strict=True)
    if (
        OPENHANDS_V51_TOOL_CACHE.is_symlink()
        or not resolved.is_dir()
        or not resolved.is_relative_to(Path("/data/jzhu484/Agent/.verigym-tmp"))
    ):
        raise ConfigurationError("OpenHands v51 tool cache path is unsafe")
    files = binding.get("files")
    if not isinstance(files, dict) or set(files) != {path.name for path in resolved.iterdir()}:
        raise ConfigurationError("OpenHands v51 tool cache inventory changed")
    for name, expected in files.items():
        path = resolved / name
        metadata = path.lstat()
        if (
            not isinstance(expected, dict)
            or path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size != expected.get("size")
            or _sha256_file(path) != expected.get("sha256")
        ):
            raise ConfigurationError("OpenHands v51 tool cache file identity changed")
    crane = resolved / "crane"
    if _sha256_file(crane) != _CRANE_SHA256 or not os.access(crane, os.X_OK):
        raise ConfigurationError("OpenHands v51 crane executable identity changed")
    receipt = _load_json(resolved / "bootstrap-receipt.json")
    receipt_hash = receipt.pop("receipt_hash", None)
    if (
        receipt_hash != binding.get("bootstrap_receipt_hash")
        or content_hash(receipt) != receipt_hash
        or receipt.get("format_id") != "verigym_openhands_hwe_v24_crane_bootstrap_receipt_v1"
        or receipt.get("release_tag") != binding.get("crane_release_tag")
        or receipt.get("crane_sha256") != _CRANE_SHA256
        or receipt.get("slsa_verification_passed") is not True
    ):
        raise ConfigurationError("OpenHands v51 bootstrap receipt identity changed")
    progress = _load_json(resolved / "bootstrap-progress.json")
    progress_hash = progress.pop("progress_hash", None)
    if (
        progress_hash != binding.get("bootstrap_progress_hash")
        or content_hash(progress) != progress_hash
        or progress.get("status") != "passed"
        or progress.get("current_stage") is not None
    ):
        raise ConfigurationError("OpenHands v51 bootstrap progress identity changed")
    return resolved


def _validate_local_image(binding: Any) -> dict[str, str]:
    if not isinstance(binding, dict):
        raise ConfigurationError("OpenHands v51 execution image binding is malformed")
    reference = binding.get("reference")
    image_id = binding.get("image_id")
    manifest = binding.get("manifest_digest")
    if not all(isinstance(item, str) for item in (reference, image_id, manifest)):
        raise ConfigurationError("OpenHands v51 execution image binding is incomplete")
    values = _docker_json(["docker", "image", "inspect", str(reference)])
    digests = values[0].get("RepoDigests") if len(values) == 1 else None
    observed = {
        value.rsplit("@", 1)[1]
        for value in digests or []
        if isinstance(value, str) and "@sha256:" in value
    }
    if len(values) != 1 or values[0].get("Id") != image_id or observed != {manifest}:
        raise ConfigurationError("OpenHands v51 execution image identity changed")
    config = values[0].get("Config")
    if not isinstance(config, dict) or config.get("ExposedPorts") not in (None, {}):
        raise ConfigurationError("OpenHands v51 execution image exposes a port")
    return {
        "reference": str(reference),
        "image_id": str(image_id),
        "manifest_digest": str(manifest),
    }


def _validate_network() -> None:
    values = _docker_json(["docker", "network", "inspect", OPENHANDS_V51_NETWORK])
    if len(values) != 1:
        raise ConfigurationError("OpenHands v51 network inspection is malformed")
    network = values[0]
    if (
        network.get("Name") != OPENHANDS_V51_NETWORK
        or network.get("Driver") != "bridge"
        or network.get("Internal") is not False
        or network.get("Scope") != "local"
    ):
        raise ConfigurationError("OpenHands v51 dedicated download network is unavailable")


def _merged_source_commit() -> str:
    repository = Path(__file__).resolve().parents[1]
    for relative in _REQUIRED_MERGED_PATHS:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if tracked != relative:
            raise ConfigurationError("OpenHands v51 required merged path changed")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=repository, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    upstream = subprocess.run(
        ["git", "rev-parse", "origin/main"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", _V50_FAILURE_AUDIT_MERGE, head],
        cwd=repository,
        check=True,
    )
    audit = repository / "docs/audits/2026-09-01_openhands-v50-provider-canary-failed-closed.md"
    if (
        head != upstream
        or re.fullmatch(r"[0-9a-f]{40}", head) is None
        or _sha256_file(audit) != _V50_FAILURE_AUDIT_SHA256
    ):
        raise ConfigurationError("OpenHands v51 qualification requires clean merged origin/main")
    return head


def _validate_headroom() -> dict[str, Any]:
    try:
        raw_root = subprocess.run(
            ["docker", "info", "--format", "{{json .DockerRootDir}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        docker_root = Path(json.loads(raw_root)).resolve(strict=True)
        filesystem = os.statvfs(docker_root)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError) as exc:
        raise ConfigurationError("OpenHands v51 Docker-root headroom check failed") from exc
    available_bytes = filesystem.f_bavail * filesystem.f_frsize
    available_inodes = filesystem.f_favail
    if (
        docker_root != _DOCKER_ROOT
        or available_bytes < _MIN_DOCKER_AVAILABLE_BYTES
        or available_inodes < _MIN_DOCKER_AVAILABLE_INODES
    ):
        raise ConfigurationError("OpenHands v51 Docker-root headroom is insufficient")
    return {
        "docker_root": str(docker_root),
        "available_bytes": available_bytes,
        "available_inodes": available_inodes,
        "minimum_available_bytes": _MIN_DOCKER_AVAILABLE_BYTES,
        "minimum_available_inodes": _MIN_DOCKER_AVAILABLE_INODES,
        "passed": True,
    }


def _sentinel_reference() -> str:
    return "ghcr.io/pku-liang/openhwgroup_m_cva6:i-was-a-digest"


def _inspect_host_image(reference: str) -> dict[str, Any] | None:
    result = subprocess.run(
        ["docker", "image", "inspect", reference],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("OpenHands v51 image inspection is malformed") from exc
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ConfigurationError("OpenHands v51 image inspection is malformed")
    return values[0]


def _count_host_candidate_images() -> int:
    return sum(
        _inspect_host_image(reference) is not None
        for reference in OPENHANDS_V51_CANDIDATE_REFERENCES
    )


def _count_temporary_containers() -> int:
    result = subprocess.run(
        ["docker", "container", "ls", "--all", "--quiet", "--filter", "name=verigym-hwe-v51-"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return len(result.stdout.splitlines())


def _remove_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "container", "rm", "--force", container_name],
        check=False,
        capture_output=True,
        timeout=60,
    )
    remaining = subprocess.run(
        ["docker", "container", "ls", "--all", "--quiet", "--filter", f"name={container_name}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if remaining.stdout.strip():
        raise ConfigurationError("OpenHands v51 temporary container cleanup failed")


def _load_optional_report(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _new_scratch_directory() -> Path:
    if OPENHANDS_V51_SCRATCH.exists() or OPENHANDS_V51_SCRATCH.is_symlink():
        raise ConfigurationError("OpenHands v51 transfer scratch must be new")
    OPENHANDS_V51_SCRATCH.mkdir(parents=True)
    return OPENHANDS_V51_SCRATCH.resolve(strict=True)


def _cleanup_scratch(path: Path) -> None:
    resolved_parent = _SCRATCH_PARENT.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if resolved != OPENHANDS_V51_SCRATCH or not resolved.is_relative_to(resolved_parent):
        raise ConfigurationError("OpenHands v51 scratch cleanup path changed")
    shutil.rmtree(resolved)


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists() or expanded.is_symlink():
        raise ConfigurationError("OpenHands v51 output must not already exist")
    expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _environment_map(values: Any) -> dict[str, str]:
    if not isinstance(values, list):
        return {}
    result: dict[str, str] = {}
    for value in values:
        name, separator, content = str(value).partition("=")
        if not separator or name in result:
            return {}
        result[name] = content
    return result


def _docker_json(arguments: list[str]) -> list[dict[str, Any]]:
    try:
        value = json.loads(
            subprocess.run(
                arguments,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        )
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ConfigurationError("OpenHands v51 Docker inspection failed") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ConfigurationError("OpenHands v51 Docker inspection returned malformed data")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ConfigurationError("OpenHands v51 JSON input contains a duplicate key")
        value[key] = item
    return value


def _load_json(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file() or expanded.stat().st_size > _MAX_JSON_BYTES:
        raise ConfigurationError(f"unsafe OpenHands v51 JSON input: {expanded.name}")
    try:
        value = json.loads(expanded.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"malformed OpenHands v51 JSON input: {expanded.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v51 JSON input is not an object: {expanded.name}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sealed(progress: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(progress)
    base.pop("progress_hash", None)
    return {**base, "progress_hash": content_hash(base)}


def _write_progress(root: Path, progress: dict[str, Any]) -> None:
    atomic_dump_json(root / "qualification-progress.json", _sealed(progress))


def main() -> int:
    arguments = _parser().parse_args()
    progress = qualify_v51_streamed_public_tasks(
        approval_path=arguments.authorization,
        dataset=arguments.dataset,
        output=arguments.output,
    )
    print(
        json.dumps(
            {
                "status": progress["status"],
                "qualified_task_ids": progress.get("qualified_task_ids", []),
                "progress_hash": progress["progress_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if progress["status"] == "qualified_pending_command_image" else 2


if __name__ == "__main__":
    raise SystemExit(main())
