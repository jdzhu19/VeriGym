#!/usr/bin/env python3
"""Repair and qualify the PR-1816 open HWE toolchain without a provider."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
for _source_root in reversed(
    (
        _REPOSITORY,
        _REPOSITORY / "src",
        _REPOSITORY / "integrations/verigym-hwe-bench/src",
    )
):
    _source_text = str(_source_root.resolve(strict=True))
    sys.path[:] = [_source_text, *(entry for entry in sys.path if entry != _source_text)]

from scripts import materialize_hwe_deepseek_harness_v69 as v69  # noqa: E402
from scripts import materialize_hwe_deepseek_harness_v172_open_toolchain as v172  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_directory  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    inspect_offline_image_archive,
)
from verigym.hwe.open_toolchain import (  # noqa: E402
    OpenToolchainImageLock,
    OpenToolchainQualificationManifest,
    load_open_toolchain_manifest,
)
from verigym.hwe.open_toolchain_successor import (  # noqa: E402
    V174_IDENTITY,
    OpenToolchainV174SuccessorManifest,
    exact_repository_digest,
    load_v174_successor_manifest,
)

IDENTITY = V174_IDENTITY
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V174_OPEN_TOOLCHAIN_REPAIR"
SANITIZED_CHILD_ENV = "VERIGYM_V174_SANITIZED_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v174_open_toolchain_repair_v1.json"
)
UPSTREAM_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v172_open_toolchain_qualification_v1.json"
)
ARCHIVE_ROOT = Path("/data2/jiadongzhu/Agent/hwe-bench-public-images")
STOP_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v172-open-toolchain-qualification-pre-output-stop-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v174-open-toolchain-qualification-repair-v1"
)
SCRATCH_ROOT = Path(
    "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v174-open-toolchain-repair"
)
DATA_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v174/data")
SOCKET_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v174/socket")
FINAL_IMAGE_TAG = "verigym/open-rtl-tools:hwe-v174-pr1816"
OWNER = "deepseek-harness-hwe-v174-open-toolchain"
_DIND_TAG = "docker:23.0.6-dind"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v174_open_toolchain_repair_v1.json",
    "docker/open-rtl-tools-hwe/Dockerfile.v174",
    "docs/audits/2026-09-06_deepseek-harness-v173-v172-pre-output-stop.md",
    "docs/audits/2026-09-06_deepseek-harness-v174-open-toolchain-repair-authorization.md",
    "docs/hwe_deepseek_harness_collection.md",
    "integrations/verigym-deepseek-harness/tests/test_v174_open_toolchain_repair.py",
    "scripts/launch_hwe_deepseek_harness_v174_open_toolchain_repair.py",
    "scripts/materialize_hwe_deepseek_harness_v174_open_toolchain_repair.py",
    "src/verigym/hwe/open_toolchain_successor.py",
    "tests/unit/test_hwe_open_toolchain_successor.py",
)
_ALLOWED_UNTRACKED_PATHS = frozenset(
    {
        "configs/training/qwen35_hwe_openhands_v56_direct_oci_provisioning_v1.json",
        "integrations/verigym-openhands/src/verigym_openhands/hwe_v56_direct_oci_provisioning.py",
        "scripts/download_hwe_bench_public_images.txt",
        "src/verigym/hwe/oci_resumable.py",
        "src/verigym/hwe/public_ghcr.py",
        "tests/unit/test_hwe_oci_resumable.py",
        "tests/unit/test_hwe_public_ghcr.py",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the one authorized repair and publish no partial qualification contract."""

    successor = load_v174_successor_manifest(_exact_file(arguments.manifest, MANIFEST, "manifest"))
    upstream = _load_and_bind_upstream(successor)
    runtime = _runtime_manifest(successor, upstream)
    _require_execution_boundary(arguments, successor)
    source_commit = _require_clean_merged_main()
    archive_root = _exact_directory(arguments.archive_root, ARCHIVE_ROOT, "archive root")
    with _patched_v172_runtime():
        _preflight_inputs(successor, runtime, archive_root=archive_root)
        root = v172._new_output(arguments.output, runtime)  # noqa: SLF001
        scratch = v172._new_scratch(runtime)  # noqa: SLF001
        return _execute(
            arguments,
            successor=successor,
            manifest=runtime,
            archive_root=archive_root,
            root=root,
            scratch=scratch,
            source_commit=source_commit,
        )


def _execute(
    arguments: argparse.Namespace,
    *,
    successor: OpenToolchainV174SuccessorManifest,
    manifest: OpenToolchainQualificationManifest,
    archive_root: Path,
    root: Path,
    scratch: Path,
    source_commit: str,
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v174_progress_v1",
        "identity": IDENTITY,
        "manifest_hash": successor.manifest_hash,
        "upstream_manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": arguments.post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "offline_preflight",
        "provider_calls": 0,
        "model_process_count": 0,
        "qualification_contract_published": False,
        **_closed_flags(),
    }
    _write_progress(root, progress)
    dind_name: str | None = None
    data_retained = False
    try:
        headroom = v172._headroom_receipt()  # noqa: SLF001
        atomic_dump_json(root / "headroom.json", headroom)
        archive_receipt = inspect_offline_image_archive(manifest.task, archive_root=archive_root)
        atomic_dump_json(root / "archive-receipt.json", archive_receipt)
        patch_receipt, instance = v172._patch_receipt(  # noqa: SLF001
            manifest, archive_root=archive_root
        )
        atomic_dump_json(root / "reference-patch-compatibility.json", patch_receipt)

        progress["status"] = "offline_tool_builder"
        _write_progress(root, progress)
        builder_id = v172._materialize_host_builder(manifest)  # noqa: SLF001
        transfers = v172._save_transfer_images(  # noqa: SLF001
            manifest, builder_id=builder_id, scratch=scratch
        )
        v172._prepare_dind_backings(manifest)  # noqa: SLF001
        v172._create_bind_volume(manifest.dind_data_volume, DATA_BACKING)  # noqa: SLF001
        v172._create_bind_volume(manifest.dind_socket_volume, SOCKET_BACKING)  # noqa: SLF001
        dind_name = f"verigym-dind-v174-{secrets.token_hex(8)}"
        dind_receipt = v172._start_dind(  # noqa: SLF001
            dind_name, manifest, root=root, scratch=scratch
        )
        atomic_dump_json(root / "dind-runtime.json", dind_receipt)
        docker_host = f"unix://{SOCKET_BACKING / 'docker.sock'}"

        progress["status"] = "open_toolchain_build"
        _write_progress(root, progress)
        with v172._docker_host(docker_host):  # noqa: SLF001
            v172._load_transfer_images(  # noqa: SLF001
                manifest,
                builder_id=builder_id,
                transfers=transfers,
                docker_host=docker_host,
            )
            image_id = v172._build_open_image(  # noqa: SLF001
                manifest,
                builder_id=builder_id,
                scratch=scratch,
                docker_host=docker_host,
            )
            v172._load_official_image(manifest, archive_root=archive_root)  # noqa: SLF001
            scan, image_lock = _scan_and_lock_open_image(
                manifest,
                image_id=image_id,
                builder_id=builder_id,
                docker_host=docker_host,
            )
            atomic_dump_json(root / "open-toolchain-security-scan.json", scan)
            atomic_dump_json(
                root / "open-toolchain-image-lock.json", image_lock.model_dump(mode="json")
            )

            source = root / "source"
            dataset = archive_root / manifest.task.dataset_relpath
            v172.prepare_source(
                dataset=dataset,
                output=source,
                selected_tasks=[manifest.task.instance_id],
                pull=False,
                imported_image_bindings={
                    manifest.task.registry_reference: {
                        "image_id": manifest.official_verifier_image,
                        "manifest_digest": manifest.task.registry_manifest_digest,
                    }
                },
                docker_control_timeout_s=120,
            )
            source_binding = v69._source_binding(source, manifest.task)  # noqa: SLF001
            atomic_dump_json(root / "source-binding.json", source_binding)

            progress["status"] = "dual_route_qualification"
            _write_progress(root, progress)
            official = v172.run_zero_model_smoke(
                source=source,
                output=root / "official-qualification",
                docker_control_timeout_s=120,
            )
            if not v172.zero_model_infrastructure_valid(
                official
            ) or not v172.zero_model_fail_to_pass_eligible(official):
                raise ConfigurationError("v174 official route is not base-FAIL/reference-PASS")
            open_comparison = v172._run_open_comparison(  # noqa: SLF001
                source=source,
                instance=instance,
                image_id=image_id,
                docker_host=docker_host,
                root=root,
            )
            atomic_dump_json(root / "open-comparison.json", open_comparison)
            binding = v172._binding_receipt(  # noqa: SLF001
                manifest, open_comparison=open_comparison, official=official
            )
            atomic_dump_json(root / "toolchain-verifier-binding.json", binding)
            inner_cleanup = v172._validate_inner_cleanup(docker_host)  # noqa: SLF001
            atomic_dump_json(root / "inner-cleanup.json", inner_cleanup)

        v172._stop_dind(dind_name)  # noqa: SLF001
        dind_name = None
        cleanup = v172._success_cleanup(manifest, scratch=scratch)  # noqa: SLF001
        data_retained = True
        atomic_dump_json(root / "cleanup.json", cleanup)
        contract = _qualification_contract(
            successor,
            manifest=manifest,
            source_commit=source_commit,
            post_merge_main_run_id=arguments.post_merge_main_run_id,
            archive_receipt=archive_receipt,
            patch_receipt=patch_receipt,
            source_binding=source_binding,
            image_lock=image_lock,
            open_comparison=open_comparison,
            official=official,
            binding=binding,
            cleanup=cleanup,
        )
        atomic_dump_json(root / "qualification-contract.json", contract)
        progress.update(
            {
                "status": "completed_pending_independent_v175_audit",
                "qualification_contract_published": True,
                "qualification_contract_hash": contract["contract_hash"],
                "retained_dind_reopen_budget": 1,
                "v176_canary_authorized": False,
            }
        )
        report = _seal(progress)
        _write_progress(root, report)
        atomic_dump_json(root / "zero-provider-report.json", report)
        return report
    except (Exception, KeyboardInterrupt) as exc:
        if dind_name is not None:
            v172._stop_dind(dind_name, strict=False)  # noqa: SLF001
        cleanup = v172._failure_cleanup(  # noqa: SLF001
            manifest, scratch=scratch, preserve_output=root
        )
        stopped = _seal(
            {
                **progress,
                "status": "stopped_without_qualification_contract",
                "stop_reason": type(exc).__name__,
                "raw_exception_persisted": False,
                "qualification_contract_published": False,
                "provider_calls": 0,
                "cleanup_complete": cleanup,
            }
        )
        _write_progress(root, stopped)
        atomic_dump_json(root / "zero-provider-report.json", stopped)
        raise
    finally:
        if not data_retained:
            v172._remove_host_builder_tag(manifest)  # noqa: SLF001


def _load_and_bind_upstream(
    successor: OpenToolchainV174SuccessorManifest,
) -> OpenToolchainQualificationManifest:
    path = _REPOSITORY / successor.upstream_manifest_path
    if path != UPSTREAM_MANIFEST or _hash_file(path) != successor.upstream_manifest_sha256:
        raise ConfigurationError("v174 frozen upstream manifest file changed")
    manifest = load_open_toolchain_manifest(path)
    if manifest.manifest_hash != successor.upstream_manifest_hash:
        raise ConfigurationError("v174 frozen upstream manifest identity changed")
    return manifest


def _runtime_manifest(
    successor: OpenToolchainV174SuccessorManifest,
    upstream: OpenToolchainQualificationManifest,
) -> OpenToolchainQualificationManifest:
    """Apply only successor-reviewed resource identities to the frozen v172 inputs."""

    return upstream.model_copy(
        update={
            "builder_tag": successor.builder_tag,
            "final_dockerfile": successor.final_dockerfile,
            "final_dockerfile_sha256": successor.final_dockerfile_sha256,
            "dind_data_volume": successor.dind_data_volume,
            "dind_socket_volume": successor.dind_socket_volume,
            "dind_data_backing": successor.dind_data_backing,
            "dind_socket_backing": successor.dind_socket_backing,
            "output_root": successor.output_root,
            "scratch_root": successor.scratch_root,
        }
    )


def _preflight_inputs(
    successor: OpenToolchainV174SuccessorManifest,
    manifest: OpenToolchainQualificationManifest,
    *,
    archive_root: Path,
) -> None:
    _validate_predecessor_evidence(successor)
    expected = {
        _REPOSITORY / manifest.builder_source_dockerfile: manifest.builder_source_dockerfile_sha256,
        _REPOSITORY / manifest.final_dockerfile: manifest.final_dockerfile_sha256,
        Path(manifest.verilator_archive_path): manifest.verilator_archive_sha256,
        Path(manifest.ripgrep_archive_path): manifest.ripgrep_archive_sha256,
        _REPOSITORY / manifest.predecessor_audit_path: manifest.predecessor_audit_sha256,
    }
    for path, digest in expected.items():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.name.endswith(".partial")
            or _hash_file(path) != digest
        ):
            raise ConfigurationError("v174 frozen input identity changed")
    rg_binary = Path(manifest.ripgrep_archive_path).parent / (
        "ripgrep-15.2.0-x86_64-unknown-linux-musl/rg"
    )
    if (
        rg_binary.is_symlink()
        or not rg_binary.is_file()
        or _hash_file(rg_binary) != manifest.ripgrep_binary_sha256
    ):
        raise ConfigurationError("v174 ripgrep executable identity changed")
    if v172._docker_image_id(manifest.accepted_open_tools_tag) != (  # noqa: SLF001
        manifest.accepted_open_tools_image_id
    ):
        raise ConfigurationError("v174 accepted open-tools image identity changed")
    if v172._docker_image_id(_DIND_TAG) != manifest.dind_image_id:  # noqa: SLF001
        raise ConfigurationError("v174 DinD tag identity changed")
    dind = v172._inspect_image(_DIND_TAG)  # noqa: SLF001
    exact_repository_digest(
        dind.get("RepoDigests"),
        expected_repository=successor.dind_repository_name,
        expected_digest=successor.dind_repository_digest,
    )
    if dind.get("Id") != manifest.dind_image_id or (dind.get("Os"), dind.get("Architecture")) != (
        "linux",
        "amd64",
    ):
        raise ConfigurationError("v174 DinD immutable identity or platform changed")
    for path in (OUTPUT_ROOT, SCRATCH_ROOT, DATA_BACKING, SOCKET_BACKING):
        if path.exists() or path.is_symlink():
            raise ConfigurationError("v174 resource path must be fresh")
    if (
        v172._volume_exists(manifest.dind_data_volume)  # noqa: SLF001
        or v172._volume_exists(manifest.dind_socket_volume)  # noqa: SLF001
        or v172._docker_image_id(manifest.builder_tag, required=False) is not None  # noqa: SLF001
        or v172._docker_image_id(FINAL_IMAGE_TAG, required=False) is not None  # noqa: SLF001
        or v172._owned_containers()  # noqa: SLF001
    ):
        raise ConfigurationError("v174 campaign resource identity is not fresh")
    inspect_offline_image_archive(manifest.task, archive_root=archive_root)


def _scan_and_lock_open_image(
    manifest: OpenToolchainQualificationManifest,
    *,
    image_id: str,
    builder_id: str,
    docker_host: str,
) -> tuple[dict[str, Any], OpenToolchainImageLock]:
    scan, image_lock = v172._scan_and_lock_open_image(  # noqa: SLF001
        manifest,
        image_id=image_id,
        builder_id=builder_id,
        docker_host=docker_host,
    )
    scan_base = dict(scan)
    scan_base.pop("scan_hash")
    scan_base["scan_id"] = "v174-open-toolchain-scan-v1"
    scan = {**scan_base, "scan_hash": content_hash(scan_base)}
    lock_base = image_lock.model_dump(mode="json", exclude={"lock_hash"})
    lock_base["security_scan_id"] = scan["scan_id"]
    image_lock = OpenToolchainImageLock.model_validate(
        {**lock_base, "lock_hash": content_hash(lock_base)}
    )
    return scan, image_lock


def _validate_predecessor_evidence(successor: OpenToolchainV174SuccessorManifest) -> None:
    if Path(successor.predecessor_stop_root) != STOP_ROOT:
        raise ConfigurationError("v174 predecessor stop root changed")
    receipt = STOP_ROOT / "stop-receipt.json"
    entries = list(STOP_ROOT.iterdir()) if STOP_ROOT.is_dir() and not STOP_ROOT.is_symlink() else []
    root_stat = STOP_ROOT.stat() if entries else None
    receipt_stat = receipt.stat() if receipt.is_file() and not receipt.is_symlink() else None
    if (
        entries != [receipt]
        or root_stat is None
        or receipt_stat is None
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or stat.S_IMODE(receipt_stat.st_mode) != 0o600
        or root_stat.st_uid != os.getuid()
        or root_stat.st_gid != os.getgid()
        or receipt_stat.st_uid != os.getuid()
        or receipt_stat.st_gid != os.getgid()
        or _hash_file(receipt) != successor.predecessor_stop_receipt_sha256
        or hash_directory(STOP_ROOT) != successor.predecessor_stop_tree_hash
    ):
        raise ConfigurationError("v174 predecessor stop evidence changed")
    try:
        value = json.loads(receipt.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v174 predecessor stop receipt is malformed") from exc
    base = dict(value) if isinstance(value, dict) else {}
    receipt_hash = base.pop("receipt_hash", None)
    required = {
        "identity": successor.upstream_identity,
        "status": "infrastructure_invalid",
        "failure_category": "repository_digest_representation_mismatch",
        "provider_calls": 0,
        "qualification_contract_published": False,
        "in_place_retry_allowed": False,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    if (
        receipt_hash != successor.predecessor_stop_receipt_hash
        or content_hash(base) != receipt_hash
        or any(base.get(key) != expected for key, expected in required.items())
    ):
        raise ConfigurationError("v174 predecessor stop receipt binding changed")
    audit = _REPOSITORY / successor.predecessor_audit_path
    if (
        audit.is_symlink()
        or not audit.is_file()
        or _hash_file(audit) != successor.predecessor_audit_sha256
    ):
        raise ConfigurationError("v174 predecessor audit changed")


def _qualification_contract(
    successor: OpenToolchainV174SuccessorManifest,
    *,
    manifest: OpenToolchainQualificationManifest,
    source_commit: str,
    post_merge_main_run_id: int,
    archive_receipt: dict[str, Any],
    patch_receipt: dict[str, Any],
    source_binding: dict[str, str],
    image_lock: OpenToolchainImageLock,
    open_comparison: dict[str, Any],
    official: dict[str, Any],
    binding: dict[str, Any],
    cleanup: dict[str, Any],
) -> dict[str, Any]:
    eligible = (
        open_comparison.get("base_failed") is True
        and open_comparison.get("reference_passed") is True
        and official.get("base_failed") is True
        and official.get("reference_passed") is True
        and image_lock.identity == IDENTITY
        and image_lock.security_scan_passed is True
        and cleanup.get("cleanup_complete") is True
    )
    if not eligible:
        raise ConfigurationError("v174 refuses a partial qualification contract")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v174_qualification_contract_v1",
        "identity": IDENTITY,
        "manifest_hash": successor.manifest_hash,
        "upstream_manifest_hash": manifest.manifest_hash,
        "predecessor_stop_receipt_hash": successor.predecessor_stop_receipt_hash,
        "predecessor_stop_tree_hash": successor.predecessor_stop_tree_hash,
        "predecessor_audit_commit": successor.predecessor_audit_commit,
        "predecessor_merge_commit": successor.predecessor_merge_commit,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "task_id": manifest.task.task_id,
        "archive_receipt_hash": archive_receipt["receipt_hash"],
        "patch_compatibility_receipt_hash": patch_receipt["receipt_hash"],
        "task_hash": source_binding["task_hash"],
        "source_hash": source_binding["source_hash"],
        "agent_toolchain_id": manifest.agent_toolchain_id,
        "agent_command_image": image_lock.image_id,
        "agent_command_image_lock_hash": image_lock.lock_hash,
        "agent_result_role": "agent_only_non_authoritative",
        "agent_base_failed": True,
        "agent_reference_passed": True,
        "official_verifier_image": manifest.official_verifier_image,
        "official_result_role": "benchmark_authoritative",
        "official_base_failed": True,
        "official_reference_passed": True,
        "toolchain_verifier_binding_hash": binding["binding_hash"],
        "repository_digest_parser": successor.repository_digest_parser,
        "dind_repository_digest": (
            f"{successor.dind_repository_name}@{successor.dind_repository_digest}"
        ),
        "all_networks": "none",
        "provider_calls": 0,
        "model_process_count": 0,
        "partial_authorization_published": False,
        "requires_independent_v175_audit": True,
        "v176_canary_authorized": False,
        "retained_dind_reopen_budget": 1,
        **_closed_flags(),
    }
    return {**base, "contract_hash": content_hash(base)}


@contextmanager
def _patched_v172_runtime() -> Iterator[None]:
    replacements = {
        "IDENTITY": IDENTITY,
        "OPT_IN_ENV": OPT_IN_ENV,
        "SANITIZED_CHILD_ENV": SANITIZED_CHILD_ENV,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "SCRATCH_ROOT": SCRATCH_ROOT,
        "DATA_BACKING": DATA_BACKING,
        "SOCKET_BACKING": SOCKET_BACKING,
        "FINAL_IMAGE_TAG": FINAL_IMAGE_TAG,
        "OWNER": OWNER,
        "_REQUIRED_MERGED_PATHS": _REQUIRED_MERGED_PATHS,
    }
    previous = {name: getattr(v172, name) for name in replacements}
    for name, value in replacements.items():
        setattr(v172, name, value)
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(v172, name, value)


def _require_execution_boundary(
    arguments: argparse.Namespace,
    manifest: OpenToolchainV174SuccessorManifest,
) -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(SANITIZED_CHILD_ENV) != "1":
        raise ConfigurationError("v174 exact opt-in launcher boundary is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v174 requires a non-root host identity")
    if any(name in os.environ for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES):
        raise ConfigurationError("v174 refuses provider configuration")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v174 requires the default host Docker endpoint")
    if arguments.post_merge_main_run_id <= manifest.predecessor_post_merge_main_run_id:
        raise ConfigurationError("v174 requires a new post-merge main run identity")


def _require_clean_merged_main() -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=_REPOSITORY,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or result.stdout.strip() != relative:
            raise ConfigurationError("v174 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        if subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=False).returncode != 0:
            raise ConfigurationError("v174 tracked repository state is dirty")
    if set(_git("ls-files", "--others", "--exclude-standard").splitlines()) != set(
        _ALLOWED_UNTRACKED_PATHS
    ):
        raise ConfigurationError("v174 untracked repository inventory changed")
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    upstream = _git("rev-parse", "origin/main")
    if branch != "main" or head != upstream or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ConfigurationError("v174 requires clean merged origin/main")
    return head


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _hash_file(path: Path) -> str:
    return v172._hash_file(path)  # noqa: SLF001


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink() or not path.is_file():
        raise ConfigurationError(f"v174 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v174 {label} identity changed")
    return resolved


def _exact_directory(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink() or not path.is_dir():
        raise ConfigurationError(f"v174 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v174 {label} identity changed")
    return resolved


def _closed_flags() -> dict[str, bool]:
    return {
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    base = dict(value)
    base.pop("report_hash", None)
    return {**base, "report_hash": content_hash(base)}


def _write_progress(root: Path, value: dict[str, Any]) -> None:
    atomic_dump_json(root / "materialization-progress.json", _seal(value))


def main() -> int:
    report = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "qualification_contract_published": report["qualification_contract_published"],
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
