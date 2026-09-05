#!/usr/bin/env python3
"""Build and qualify the v172 PR-1816 open HWE toolchain without a provider."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
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

from verigym_hwe_bench.adapter import HweBenchSuite  # noqa: E402
from verigym_hwe_bench.cva6_qualification import (  # noqa: E402
    run_zero_model_smoke,
    zero_model_fail_to_pass_eligible,
    zero_model_infrastructure_valid,
)
from verigym_hwe_bench.prepare import (  # noqa: E402
    load_selected_instances,
    prepare_source,
    reference_patch_compatibility,
)

from scripts import materialize_hwe_deepseek_harness_v69 as v69  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_bytes  # noqa: E402
from verigym.core.workspace import copy_tree_safely, normalize_relative_path  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    inspect_offline_image_archive,
    require_toolchain_verifier_binding,
)
from verigym.hwe.open_toolchain import (  # noqa: E402
    V172_AGENT_TOOLCHAIN_ID,
    V172_IDENTITY,
    OpenToolchainImageLock,
    OpenToolchainQualificationManifest,
    load_open_toolchain_manifest,
)
from verigym.schemas.suite import SuiteSourceConfig  # noqa: E402

IDENTITY = V172_IDENTITY
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V172_OPEN_TOOLCHAIN"
SANITIZED_CHILD_ENV = "VERIGYM_V172_SANITIZED_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v172_open_toolchain_qualification_v1.json"
)
ARCHIVE_ROOT = Path("/data2/jiadongzhu/Agent/hwe-bench-public-images")
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v172-open-toolchain-qualification-v1"
)
SCRATCH_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v172-open-toolchain")
DATA_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v172/data")
SOCKET_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v172/socket")
FINAL_IMAGE_TAG = "verigym/open-rtl-tools:hwe-v172-pr1816"
OWNER = "deepseek-harness-hwe-v172-open-toolchain"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_CONTROL_OUTPUT = 1024 * 1024
_MAX_TEST_OUTPUT = 32 * 1024 * 1024
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v172_open_toolchain_qualification_v1.json",
    "docker/open-rtl-tools/Dockerfile",
    "docker/open-rtl-tools-hwe/Dockerfile",
    "docker/open-rtl-tools-hwe/README.md",
    "docs/audits/2026-09-06_deepseek-harness-v172-open-toolchain-authorization.md",
    "docs/audits/2026-09-06_deepseek-harness-v171-v170-result.md",
    "docs/hwe_deepseek_harness_collection.md",
    "integrations/verigym-deepseek-harness/tests/test_v172_open_toolchain.py",
    "scripts/launch_hwe_deepseek_harness_v172_open_toolchain.py",
    "scripts/materialize_hwe_deepseek_harness_v172_open_toolchain.py",
    "src/verigym/hwe/open_toolchain.py",
    "tests/unit/test_hwe_open_toolchain.py",
)
_BINARY_PATHS = {
    "verilator": "/tools/verilator/bin/verilator",
    "verilator_bin": "/tools/verilator/bin/verilator_bin",
    "iverilog": "/opt/iverilog/bin/iverilog",
    "vvp": "/opt/iverilog/bin/vvp",
    "yosys": "/opt/yosys/bin/yosys",
    "rg": "/usr/local/bin/rg",
    "make": "/usr/bin/make",
    "g++": "/usr/bin/g++",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the one authorized offline build and publish no partial qualification contract."""

    manifest = load_open_toolchain_manifest(_exact_file(arguments.manifest, MANIFEST, "manifest"))
    _require_execution_boundary(arguments, manifest)
    source_commit = _require_clean_merged_main()
    archive_root = _exact_directory(arguments.archive_root, ARCHIVE_ROOT, "archive root")
    _preflight_inputs(manifest, archive_root=archive_root)
    root = _new_output(arguments.output, manifest)
    scratch = _new_scratch(manifest)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v172_progress_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
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
        headroom = _headroom_receipt()
        atomic_dump_json(root / "headroom.json", headroom)
        archive_receipt = inspect_offline_image_archive(manifest.task, archive_root=archive_root)
        atomic_dump_json(root / "archive-receipt.json", archive_receipt)
        patch_receipt, instance = _patch_receipt(manifest, archive_root=archive_root)
        atomic_dump_json(root / "reference-patch-compatibility.json", patch_receipt)

        progress["status"] = "offline_tool_builder"
        _write_progress(root, progress)
        builder_id = _materialize_host_builder(manifest)
        transfers = _save_transfer_images(manifest, builder_id=builder_id, scratch=scratch)
        _prepare_dind_backings(manifest)
        _create_bind_volume(manifest.dind_data_volume, DATA_BACKING)
        _create_bind_volume(manifest.dind_socket_volume, SOCKET_BACKING)
        dind_name = f"verigym-dind-v172-{secrets.token_hex(8)}"
        dind_receipt = _start_dind(dind_name, manifest, root=root, scratch=scratch)
        atomic_dump_json(root / "dind-runtime.json", dind_receipt)
        docker_host = f"unix://{SOCKET_BACKING / 'docker.sock'}"

        progress["status"] = "open_toolchain_build"
        _write_progress(root, progress)
        with _docker_host(docker_host):
            _load_transfer_images(
                manifest,
                builder_id=builder_id,
                transfers=transfers,
                docker_host=docker_host,
            )
            image_id = _build_open_image(
                manifest,
                builder_id=builder_id,
                scratch=scratch,
                docker_host=docker_host,
            )
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

            _load_official_image(manifest, archive_root=archive_root)
            source = root / "source"
            dataset = archive_root / manifest.task.dataset_relpath
            prepare_source(
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
            official = run_zero_model_smoke(
                source=source,
                output=root / "official-qualification",
                docker_control_timeout_s=120,
            )
            if not zero_model_infrastructure_valid(
                official
            ) or not zero_model_fail_to_pass_eligible(official):
                raise ConfigurationError("v172 official route is not base-FAIL/reference-PASS")
            open_comparison = _run_open_comparison(
                source=source,
                instance=instance,
                image_id=image_id,
                docker_host=docker_host,
                root=root,
            )
            atomic_dump_json(root / "open-comparison.json", open_comparison)
            binding = _binding_receipt(manifest, open_comparison=open_comparison, official=official)
            atomic_dump_json(root / "toolchain-verifier-binding.json", binding)
            inner_cleanup = _validate_inner_cleanup(docker_host)
            atomic_dump_json(root / "inner-cleanup.json", inner_cleanup)

        _stop_dind(dind_name)
        dind_name = None
        cleanup = _success_cleanup(manifest, scratch=scratch)
        data_retained = True
        atomic_dump_json(root / "cleanup.json", cleanup)
        contract = _qualification_contract(
            manifest,
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
        # This is deliberately the final authority-bearing artifact.
        atomic_dump_json(root / "qualification-contract.json", contract)
        progress.update(
            {
                "status": "completed_pending_independent_v173_audit",
                "qualification_contract_published": True,
                "qualification_contract_hash": contract["contract_hash"],
                "retained_dind_reopen_budget": 1,
                "v174_canary_authorized": False,
            }
        )
        report = _seal(progress)
        _write_progress(root, report)
        atomic_dump_json(root / "zero-provider-report.json", report)
        return report
    except (Exception, KeyboardInterrupt) as exc:
        if dind_name is not None:
            _stop_dind(dind_name, strict=False)
        cleanup = _failure_cleanup(manifest, scratch=scratch, preserve_output=root)
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
            _remove_host_builder_tag(manifest)


def _preflight_inputs(
    manifest: OpenToolchainQualificationManifest,
    *,
    archive_root: Path,
) -> None:
    expected = {
        _REPOSITORY / manifest.builder_source_dockerfile: manifest.builder_source_dockerfile_sha256,
        _REPOSITORY / manifest.final_dockerfile: manifest.final_dockerfile_sha256,
        Path(manifest.verilator_archive_path): manifest.verilator_archive_sha256,
        Path(manifest.ripgrep_archive_path): manifest.ripgrep_archive_sha256,
        _REPOSITORY / manifest.predecessor_audit_path: manifest.predecessor_audit_sha256,
    }
    for path, digest in expected.items():
        if path.is_symlink() or not path.is_file() or _hash_file(path) != digest:
            raise ConfigurationError("v172 frozen input identity changed")
    rg_binary = Path(manifest.ripgrep_archive_path).parent / (
        "ripgrep-15.2.0-x86_64-unknown-linux-musl/rg"
    )
    if (
        rg_binary.is_symlink()
        or not rg_binary.is_file()
        or _hash_file(rg_binary) != manifest.ripgrep_binary_sha256
    ):
        raise ConfigurationError("v172 ripgrep executable identity changed")
    if any(path.name.endswith(".partial") for path in expected):
        raise ConfigurationError("v172 refuses partial tool inputs")
    if _docker_image_id(manifest.accepted_open_tools_tag) != manifest.accepted_open_tools_image_id:
        raise ConfigurationError("v172 accepted open-tools image identity changed")
    dind = _inspect_image(manifest.dind_image_id)
    if manifest.dind_repository_digest not in (dind.get("RepoDigests") or []):
        raise ConfigurationError("v172 DinD repository digest changed")
    inspect_offline_image_archive(manifest.task, archive_root=archive_root)


def _patch_receipt(
    manifest: OpenToolchainQualificationManifest,
    *,
    archive_root: Path,
) -> tuple[dict[str, Any], Any]:
    dataset = archive_root / manifest.task.dataset_relpath
    if (
        dataset.is_symlink()
        or not dataset.is_file()
        or _hash_file(dataset) != manifest.task.dataset_sha256
    ):
        raise ConfigurationError("v172 official dataset identity changed")
    if (
        v69._selected_row_hash(dataset, manifest.task.instance_id)
        != manifest.task.selected_row_sha256
    ):  # noqa: SLF001
        raise ConfigurationError("v172 selected dataset row identity changed")
    selected = load_selected_instances(dataset, {manifest.task.instance_id})
    if len(selected) != 1 or selected[0].base_commit != manifest.task.source_commit:
        raise ConfigurationError("v172 source commit binding changed")
    compatibility = asdict(reference_patch_compatibility(selected[0]))
    if compatibility.get("compatible") is not True:
        raise ConfigurationError("v172 reference patch is incompatible")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_v172_reference_patch_compatibility_v1",
        "task_id": manifest.task.task_id,
        **compatibility,
        "completed_before_image_load": True,
    }
    return {**base, "receipt_hash": content_hash(base)}, selected[0]


def _materialize_host_builder(manifest: OpenToolchainQualificationManifest) -> str:
    if _docker_image_id(manifest.builder_tag, required=False) is not None:
        raise ConfigurationError("v172 builder tag must be fresh")
    _run_quiet(
        [
            "docker",
            "build",
            "--quiet",
            "--network",
            "none",
            "--pull=false",
            "--target",
            manifest.builder_target,
            "--tag",
            manifest.builder_tag,
            "--file",
            str(_REPOSITORY / manifest.builder_source_dockerfile),
            str((_REPOSITORY / "docker/open-rtl-tools").resolve(strict=True)),
        ],
        timeout=1800,
    )
    builder_id = _docker_image_id(manifest.builder_tag)
    builder = _inspect_image(builder_id)
    official = _inspect_image(manifest.official_verifier_image, required=False)
    if official is not None and _is_ancestor_layers(official, builder):
        raise ConfigurationError("v172 builder unexpectedly descends from the HWE task image")
    return builder_id


def _save_transfer_images(
    manifest: OpenToolchainQualificationManifest,
    *,
    builder_id: str,
    scratch: Path,
) -> dict[str, Path]:
    result = {
        "accepted": scratch / "accepted-open-tools.tar",
        "builder": scratch / "builder.tar",
    }
    for image_id, output in (
        (manifest.accepted_open_tools_image_id, result["accepted"]),
        (builder_id, result["builder"]),
    ):
        _run_quiet(["docker", "image", "save", "--output", str(output), image_id], timeout=1800)
        if (
            output.is_symlink()
            or not output.is_file()
            or not 0 < output.stat().st_size <= 8 * 1024**3
        ):
            raise ConfigurationError("v172 image transfer archive is unsafe")
    return result


def _prepare_dind_backings(manifest: OpenToolchainQualificationManifest) -> None:
    for path, expected in (
        (DATA_BACKING, Path(manifest.dind_data_backing)),
        (SOCKET_BACKING, Path(manifest.dind_socket_backing)),
    ):
        if path != expected or path.exists() or path.is_symlink():
            raise ConfigurationError("v172 DinD backing is not fresh")
        path.mkdir(parents=True, mode=0o700)
        path.chmod(0o700)
        metadata = path.stat()
        if (
            next(path.iterdir(), None) is not None
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.getuid()
            or metadata.st_gid != os.getgid()
        ):
            raise ConfigurationError("v172 DinD backing ownership changed")


def _create_bind_volume(name: str, backing: Path) -> None:
    if _volume_exists(name):
        raise ConfigurationError("v172 DinD volume is not fresh")
    output = (
        _run(
            [
                "docker",
                "volume",
                "create",
                "--driver",
                "local",
                "--label",
                f"verigym.owner={OWNER}",
                "--opt",
                "type=none",
                "--opt",
                "o=bind",
                "--opt",
                f"device={backing}",
                name,
            ],
            timeout=30,
        )
        .decode()
        .strip()
    )
    if output != name:
        raise ConfigurationError("v172 DinD volume creation output changed")


def _start_dind(
    name: str,
    manifest: OpenToolchainQualificationManifest,
    *,
    root: Path,
    scratch: Path,
) -> dict[str, Any]:
    empty_home = scratch / "empty-home"
    empty_home.mkdir(mode=0o700)
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        f"verigym.owner={OWNER}",
        "--label",
        "verigym.role=offline-daemon",
        "--privileged",
        "--network",
        "none",
        "--pids-limit",
        "32768",
        "--env",
        "DOCKER_TLS_CERTDIR=",
        "--volume",
        f"{manifest.dind_socket_volume}:/var/run:rw",
        "--volume",
        f"{manifest.dind_data_volume}:/var/lib/docker:rw",
        "--mount",
        f"type=bind,src={root},dst={root},rw",
        "--mount",
        f"type=bind,src={scratch},dst={scratch},rw",
        "--mount",
        f"type=bind,src={empty_home},dst=/verigym-host-sentinel,readonly",
        manifest.dind_image_id,
        "--storage-driver=vfs",
        f"--group={os.getgid()}",
    ]
    _run(command, timeout=60)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = _run_result(["docker", "exec", name, "docker", "info"], timeout=10)
        if result.returncode == 0:
            break
        time.sleep(0.25)
    else:
        raise ConfigurationError("v172 DinD daemon did not become ready")
    outer = _inspect_container(name)
    host = outer.get("HostConfig") or {}
    config = outer.get("Config") or {}
    mounts = outer.get("Mounts") or []
    destinations = {item.get("Destination") for item in mounts if isinstance(item, dict)}
    if (
        host.get("Privileged") is not True
        or host.get("NetworkMode") != "none"
        or config.get("Labels", {}).get("verigym.owner") != OWNER
        or "/var/run" not in destinations
        or "/var/lib/docker" not in destinations
        or str(root) not in destinations
        or str(scratch) not in destinations
        or any(item.get("Destination") == "/var/run/docker.sock" for item in mounts)
    ):
        raise ConfigurationError("v172 outer DinD isolation differs from policy")
    info = json.loads(
        _run(["docker", "exec", name, "docker", "info", "--format", "{{json .}}"], timeout=30)
    )
    version = (
        _run(
            ["docker", "exec", name, "docker", "version", "--format", "{{.Server.Version}}"],
            timeout=30,
        )
        .decode()
        .strip()
    )
    if (
        version != manifest.dind_server_version
        or info.get("Driver") != manifest.dind_storage_driver
        or info.get("DefaultRuntime") != manifest.dind_default_runtime
    ):
        raise ConfigurationError("v172 inner Docker identity changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v172_dind_runtime_v1",
        "image_id": manifest.dind_image_id,
        "repository_digest": manifest.dind_repository_digest,
        "server_version": version,
        "storage_driver": info["Driver"],
        "default_runtime": info["DefaultRuntime"],
        "outer_network": "none",
        "host_socket_mounted": False,
        "data_backing_role": "data2_campaign_owned",
    }
    return {**base, "receipt_hash": content_hash(base)}


def _load_transfer_images(
    manifest: OpenToolchainQualificationManifest,
    *,
    builder_id: str,
    transfers: dict[str, Path],
    docker_host: str,
) -> None:
    for path in transfers.values():
        _run(["docker", "--host", docker_host, "load", "--input", str(path)], timeout=1800)
    _tag_inner(docker_host, manifest.accepted_open_tools_image_id, manifest.accepted_open_tools_tag)
    _tag_inner(docker_host, builder_id, manifest.builder_tag)
    if (
        _docker_image_id(manifest.accepted_open_tools_tag, host=docker_host)
        != manifest.accepted_open_tools_image_id
        or _docker_image_id(manifest.builder_tag, host=docker_host) != builder_id
    ):
        raise ConfigurationError("v172 transferred image identity changed")


def _build_open_image(
    manifest: OpenToolchainQualificationManifest,
    *,
    builder_id: str,
    scratch: Path,
    docker_host: str,
) -> str:
    context = scratch / "build-context"
    context.mkdir(mode=0o700)
    shutil.copy2(manifest.verilator_archive_path, context / "verilator-v5.008.tar.gz")
    shutil.copy2(
        manifest.ripgrep_archive_path,
        context / "ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz",
    )
    command = [
        "docker",
        "--host",
        docker_host,
        "build",
        "--quiet",
        "--network",
        "none",
        "--pull=false",
        "--tag",
        FINAL_IMAGE_TAG,
        "--build-arg",
        f"VERILATOR_ARCHIVE_SHA256={manifest.verilator_archive_sha256}",
        "--build-arg",
        f"VERILATOR_COMMIT={manifest.verilator_commit}",
        "--build-arg",
        f"RIPGREP_ARCHIVE_SHA256={manifest.ripgrep_archive_sha256}",
        "--build-arg",
        f"RIPGREP_BINARY_SHA256={manifest.ripgrep_binary_sha256}",
        "--build-arg",
        f"HOST_UID={os.getuid()}",
        "--build-arg",
        f"HOST_GID={os.getgid()}",
        "--file",
        str(_REPOSITORY / manifest.final_dockerfile),
        str(context),
    ]
    _run_quiet(command, timeout=3600)
    image_id = _docker_image_id(FINAL_IMAGE_TAG, host=docker_host)
    if image_id in {
        manifest.accepted_open_tools_image_id,
        manifest.official_verifier_image,
        builder_id,
    }:
        raise ConfigurationError("v172 derived open-toolchain image identity is invalid")
    return image_id


def _scan_and_lock_open_image(
    manifest: OpenToolchainQualificationManifest,
    *,
    image_id: str,
    builder_id: str,
    docker_host: str,
) -> tuple[dict[str, Any], OpenToolchainImageLock]:
    image = _inspect_image(image_id, host=docker_host)
    official = _inspect_image(manifest.official_verifier_image, host=docker_host)
    config = image.get("Config") or {}
    environment = config.get("Env") or []
    env_names = {item.partition("=")[0] for item in environment if isinstance(item, str)}
    labels = config.get("Labels") or {}
    expected_user = f"{os.getuid()}:{os.getgid()}"
    checks: dict[str, bool] = {
        "image_id_resolved": image.get("Id") == image_id,
        "linux_amd64": image.get("Os") == "linux" and image.get("Architecture") == "amd64",
        "non_root_user": config.get("User") == expected_user,
        "working_directory": config.get("WorkingDir") == "/workspace/repository",
        "inert_command": config.get("Cmd") == ["tail", "-f", "/dev/null"],
        "entrypoint_absent": config.get("Entrypoint") in (None, []),
        "ports_absent": config.get("ExposedPorts") in (None, {}),
        "volumes_absent": config.get("Volumes") in (None, {}),
        "agent_toolchain_label": labels.get("org.verigym.agent-toolchain-id")
        == manifest.agent_toolchain_id,
        "non_authoritative_label": labels.get("org.verigym.role") == "agent-only-non-authoritative",
        "official_verifier_label": labels.get("org.verigym.official-verifier-included") == "false",
        "provider_environment_absent": not env_names.intersection(
            ZERO_PROVIDER_CONFIGURATION_ENV_NAMES
        ),
        "proxy_environment_absent": not env_names.intersection(
            {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"}
        ),
        "official_image_not_equal": image_id != manifest.official_verifier_image,
        "accepted_parent_not_equal": image_id != manifest.accepted_open_tools_image_id,
        "builder_not_equal": image_id != builder_id,
        "official_not_ancestor": not _is_ancestor_layers(official, image),
        "build_network_none": manifest.build_network == "none",
        "runtime_network_none": manifest.agent_command_network == "none",
        "provider_clients_unavailable": manifest.provider_clients_available is False,
        "registry_access_disallowed": manifest.registry_access_allowed is False,
        "partial_archives_disallowed": manifest.partial_archive_allowed is False,
        "local_runtime_disallowed": manifest.local_runtime_allowed is False,
        "formal_collection_closed": manifest.formal_collection_allowed is False,
    }
    probe_script = "set -eu; " + "; ".join(
        [f"sha256sum {_BINARY_PATHS[name]}" for name in _BINARY_PATHS]
        + [
            "verigym-open-toolchain-identity",
            "verilator --version",
            "iverilog -V 2>&1 | head -n 1",
            "vvp -V 2>&1 | head -n 1",
            "yosys -V",
            "rg --version | head -n 1",
            "make --version | head -n 1",
            "g++ --version | head -n 1",
            "! command -v codex",
            "test ! -e /root/.codex",
            "test ! -e /home/verigym/.codex",
        ]
    )
    probe = _run_secure_container(
        docker_host=docker_host,
        image_id=image_id,
        role="security-scan",
        command=["/bin/bash", "-c", probe_script],
        mounts=[],
        timeout=300,
        output_limit=_MAX_CONTROL_OUTPUT,
    )
    text = probe["output"].decode("utf-8", errors="strict")
    binary_hashes: dict[str, str] = {}
    for line in text.splitlines():
        digest, separator, path = line.partition("  ")
        for name, expected_path in _BINARY_PATHS.items():
            if separator and path == expected_path and _HASH.fullmatch(digest):
                binary_hashes[name] = digest
    checks.update(
        {
            "binary_inventory_complete": set(binary_hashes) == set(_BINARY_PATHS),
            "identity_command": "agent_toolchain_id=verigym-open-rtl-tools-v1" in text,
            "verilator_version": "Verilator 5.008" in text,
            "iverilog_version": "Icarus Verilog version 12.0" in text,
            "vvp_version": "Icarus Verilog runtime version 12.0" in text,
            "yosys_version": "Yosys 0.67" in text,
            "ripgrep_version": "ripgrep 15.2.0" in text,
            "make_present": "GNU Make" in text,
            "compiler_present": "g++" in text,
            "runtime_read_only": probe["read_only_root"] is True,
            "runtime_cap_drop_all": probe["cap_drop_all"] is True,
            "runtime_no_new_privileges": probe["no_new_privileges"] is True,
            "runtime_no_mounts": probe["mount_count"] == 0,
            "runtime_cleanup": probe["container_removed"] is True,
            "codex_absent": probe["returncode"] == 0,
        }
    )
    passed = all(checks.values())
    scan_base = {
        "schema_version": "1.0",
        "format_id": "verigym_open_hwe_toolchain_security_scan_v1",
        "scan_id": "v172-open-toolchain-scan-v1",
        "image_id": image_id,
        "check_count": len(checks),
        "checks": checks,
        "scan_passed": passed,
        "probe_output_sha256": hash_bytes(probe["output"]),
        "probe_output_bytes": len(probe["output"]),
        "raw_probe_output_persisted": False,
    }
    scan = {**scan_base, "scan_hash": content_hash(scan_base)}
    if not passed:
        raise ConfigurationError("v172 open-toolchain security scan failed")
    versions = {
        "verilator": "5.008",
        "iverilog": "12.0",
        "vvp": "12.0",
        "yosys": "0.67",
        "rg": "15.2.0",
    }
    lock_base = {
        "schema_version": "1.0",
        "format_id": "verigym_open_hwe_toolchain_image_lock_v1",
        "identity": IDENTITY,
        "agent_toolchain_id": V172_AGENT_TOOLCHAIN_ID,
        "image_id": image_id,
        "accepted_open_tools_image_id": manifest.accepted_open_tools_image_id,
        "builder_image_id": builder_id,
        "official_verifier_image": manifest.official_verifier_image,
        "binary_sha256": binary_hashes,
        "binary_versions": versions,
        "build_network": "none",
        "runtime_network": "none",
        "effective_user": expected_user,
        "read_only_root": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "single_workspace_mount": True,
        "provider_credentials_present": False,
        "codex_present": False,
        "hwe_task_image_ancestor": False,
        "official_verifier_included": False,
        "security_scan_id": scan["scan_id"],
        "security_check_count": len(checks),
        "security_scan_passed": True,
    }
    lock = OpenToolchainImageLock.model_validate(
        {**lock_base, "lock_hash": content_hash(lock_base)}
    )
    return scan, lock


def _load_official_image(
    manifest: OpenToolchainQualificationManifest,
    *,
    archive_root: Path,
) -> None:
    v69._load_completed_archive(manifest.task, archive_root=archive_root)  # noqa: SLF001
    if _docker_image_id(manifest.task.registry_reference) != manifest.official_verifier_image:
        raise ConfigurationError("v172 official verifier image binding changed")


def _run_open_comparison(
    *,
    source: Path,
    instance: Any,
    image_id: str,
    docker_host: str,
    root: Path,
) -> dict[str, Any]:
    suite = HweBenchSuite(docker_control_timeout_s=120).with_source(
        SuiteSourceConfig(source_root=source, variant="repo-repair-v1")
    )
    references = list(suite.discover())
    if len(references) != 1:
        raise ConfigurationError("v172 source did not expose exactly one task")
    task = suite.load_task(references[0])
    reference = suite.reference_solution(task)
    if reference is None:
        raise ConfigurationError("v172 PR-1816 reference solution is unavailable")
    visible_repository = source / "workspaces" / references[0].native_id / "repository"
    workspaces = root / "open-workspaces"
    workspaces.mkdir(mode=0o700)
    base_repository = workspaces / "base"
    reference_repository = workspaces / "reference"
    copy_tree_safely(visible_repository, base_repository, preserve_safe_file_modes=True)
    copy_tree_safely(visible_repository, reference_repository, preserve_safe_file_modes=True)
    for relative, content in reference.files.items():
        destination = reference_repository / normalize_relative_path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    results: dict[str, dict[str, Any]] = {}
    for role, repository in (("base", base_repository), ("reference", reference_repository)):
        script = repository / ".verigym_public_test.sh"
        script.write_text(instance.tb_script, encoding="utf-8")
        script.chmod(0o700)
        try:
            results[role] = _run_open_public_test(
                docker_host=docker_host,
                image_id=image_id,
                repository=repository,
                role=role,
            )
        finally:
            script.unlink(missing_ok=True)
            generated = repository / ".tb_debug_cause_haltreq"
            if generated.exists() and not generated.is_symlink():
                shutil.rmtree(generated)
    base_failed = results["base"]["returncode"] != 0 and results["base"]["fail_sentinel"] is True
    reference_passed = (
        results["reference"]["returncode"] == 0 and results["reference"]["pass_sentinel"] is True
    )
    report_base = {
        "schema_version": "1.0",
        "format_id": "verigym_open_hwe_pr1816_comparison_v1",
        "task_id": task.id,
        "agent_toolchain_id": V172_AGENT_TOOLCHAIN_ID,
        "result_role": "agent_only_non_authoritative",
        "test_name": "debug_cause_haltreq",
        "public_tb_script_sha256": hashlib.sha256(instance.tb_script.encode()).hexdigest(),
        "base_failed": base_failed,
        "base_infrastructure_error": False,
        "reference_passed": reference_passed,
        "network": "none",
        "read_only_root": True,
        "non_root": True,
        "single_workspace_mount": True,
        "provider_calls": 0,
        "results": results,
    }
    report = {**report_base, "receipt_hash": content_hash(report_base)}
    if not base_failed or not reference_passed:
        raise ConfigurationError("v172 open route is not base-FAIL/reference-PASS")
    return report


def _run_open_public_test(
    *,
    docker_host: str,
    image_id: str,
    repository: Path,
    role: str,
) -> dict[str, Any]:
    probe = _run_secure_container(
        docker_host=docker_host,
        image_id=image_id,
        role=f"open-{role}",
        command=["/bin/bash", "/home/ibex/.verigym_public_test.sh"],
        mounts=[(repository, "/home/ibex")],
        timeout=900,
        output_limit=_MAX_TEST_OUTPUT,
        cpus="4",
        memory="8g",
        pids="4096",
        tmpfs_size="512m",
    )
    output = probe.pop("output")
    return {
        **probe,
        "output_sha256": hash_bytes(output),
        "output_bytes": len(output),
        "pass_sentinel": b"TEST: debug_cause_haltreq ... PASS" in output,
        "fail_sentinel": b"TEST: debug_cause_haltreq ... FAIL" in output,
        "raw_output_persisted": False,
    }


def _run_secure_container(
    *,
    docker_host: str,
    image_id: str,
    role: str,
    command: list[str],
    mounts: list[tuple[Path, str]],
    timeout: int,
    output_limit: int,
    cpus: str = "1",
    memory: str = "1g",
    pids: str = "256",
    tmpfs_size: str = "64m",
) -> dict[str, Any]:
    name = f"verigym-v172-{role}-{secrets.token_hex(6)}"
    create = [
        "docker",
        "--host",
        docker_host,
        "container",
        "create",
        "--name",
        name,
        "--label",
        f"verigym.owner={OWNER}",
        "--label",
        f"verigym.role={role}",
        "--network",
        "none",
        "--read-only",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        pids,
        "--memory",
        memory,
        "--memory-swap",
        memory,
        "--cpus",
        cpus,
        "--ipc",
        "none",
        "--init",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={tmpfs_size}",
    ]
    for source, destination in mounts:
        create.extend(["--mount", f"type=bind,src={source},dst={destination},rw"])
    create.extend(
        ["--workdir", mounts[0][1] if mounts else "/workspace/repository", image_id, *command]
    )
    container_id = _run(create, timeout=60).decode().strip()
    try:
        inspection = _inspect_container(container_id, host=docker_host)
        host = inspection.get("HostConfig") or {}
        config = inspection.get("Config") or {}
        observed_mounts = inspection.get("Mounts") or []
        if (
            host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or host.get("CapAdd") not in (None, [])
            or host.get("CapDrop") != ["ALL"]
            or "no-new-privileges" not in (host.get("SecurityOpt") or [])
            or config.get("User") != f"{os.getuid()}:{os.getgid()}"
            or len(observed_mounts) != len(mounts)
        ):
            raise ConfigurationError("v172 secure container isolation changed")
        result = _run_result(
            ["docker", "--host", docker_host, "start", "--attach", container_id],
            timeout=timeout,
            maximum=output_limit,
        )
        output = result.stdout + result.stderr
        if len(output) > output_limit:
            raise ConfigurationError("v172 secure container output exceeded its bound")
        return {
            "returncode": result.returncode,
            "output": output,
            "network": "none",
            "read_only_root": True,
            "cap_drop_all": True,
            "no_new_privileges": True,
            "effective_user": f"{os.getuid()}:{os.getgid()}",
            "mount_count": len(observed_mounts),
            "container_removed": True,
        }
    except subprocess.TimeoutExpired as exc:
        _run_result(["docker", "--host", docker_host, "kill", container_id], timeout=30)
        raise ConfigurationError("v172 secure container timed out") from exc
    finally:
        removed = _run_result(
            ["docker", "--host", docker_host, "container", "rm", "--force", container_id],
            timeout=60,
        )
        if removed.returncode != 0:
            raise ConfigurationError("v172 secure container cleanup failed")


def _binding_receipt(
    manifest: OpenToolchainQualificationManifest,
    *,
    open_comparison: dict[str, Any],
    official: dict[str, Any],
) -> dict[str, Any]:
    official_hash = content_hash(official)
    attempt = {
        "task_id": manifest.task.task_id,
        "agent_toolchain_id": manifest.agent_toolchain_id,
        "official_verifier_image": manifest.official_verifier_image,
        "official_verifier_executed": True,
        "agent_diagnostic_result_role": "agent_only_non_authoritative",
        "official_verifier_result_role": "benchmark_authoritative",
        "agent_diagnostic_receipt_hash": open_comparison["receipt_hash"],
        "official_verifier_receipt_hash": official_hash,
    }
    require_toolchain_verifier_binding(
        attempt=attempt,
        expected_agent_toolchain_id=manifest.agent_toolchain_id,
        expected_official_verifier_image=manifest.official_verifier_image,
    )
    return {**attempt, "binding_hash": content_hash(attempt)}


def _qualification_contract(
    manifest: OpenToolchainQualificationManifest,
    *,
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
        and image_lock.security_scan_passed is True
        and cleanup.get("cleanup_complete") is True
    )
    if not eligible:
        raise ConfigurationError("v172 refuses a partial qualification contract")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v172_qualification_contract_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
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
        "all_networks": "none",
        "provider_calls": 0,
        "model_process_count": 0,
        "partial_authorization_published": False,
        "requires_independent_v173_audit": True,
        "v174_canary_authorized": False,
        "retained_dind_reopen_budget": 1,
        **_closed_flags(),
    }
    return {**base, "contract_hash": content_hash(base)}


def _headroom_receipt() -> dict[str, Any]:
    root = os.statvfs("/")
    data2 = os.statvfs("/data2")
    root_bytes = root.f_bavail * root.f_frsize
    data2_bytes = data2.f_bavail * data2.f_frsize
    root_inodes = root.f_favail
    data2_inodes = data2.f_favail
    passed = (
        root_bytes >= 8 * 1024**3
        and data2_bytes >= 20 * 1024**3
        and root_inodes >= 100_000
        and data2_inodes >= 100_000
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v172_headroom_v1",
        "control_root_available_bytes": root_bytes,
        "data2_available_bytes": data2_bytes,
        "control_root_available_inodes": root_inodes,
        "data2_available_inodes": data2_inodes,
        "capacity_satisfied": passed,
    }
    receipt = {**base, "receipt_hash": content_hash(base)}
    if not passed:
        raise ConfigurationError("v172 absolute headroom gate failed")
    return receipt


def _success_cleanup(
    manifest: OpenToolchainQualificationManifest,
    *,
    scratch: Path,
) -> dict[str, Any]:
    _remove_volume(manifest.dind_socket_volume, strict=True)
    if SOCKET_BACKING.exists():
        shutil.rmtree(SOCKET_BACKING)
    _remove_host_builder_tag(manifest)
    shutil.rmtree(scratch)
    if (
        not _volume_exists(manifest.dind_data_volume)
        or not DATA_BACKING.is_dir()
        or _volume_exists(manifest.dind_socket_volume)
        or SOCKET_BACKING.exists()
        or _owned_containers()
    ):
        raise ConfigurationError("v172 retained-runtime cleanup failed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v172_cleanup_v1",
        "cleanup_complete": True,
        "outer_dind_removed": True,
        "socket_volume_removed": True,
        "socket_backing_removed": True,
        "host_builder_tag_removed": True,
        "transfer_archives_removed": True,
        "owned_containers_remaining": 0,
        "data_volume_retained": True,
        "data_backing_retained": True,
        "retained_dind_reopen_budget": 1,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _validate_inner_cleanup(docker_host: str) -> dict[str, Any]:
    containers = (
        _run(
            [
                "docker",
                "--host",
                docker_host,
                "container",
                "ls",
                "--all",
                "--quiet",
            ],
            timeout=30,
        )
        .decode()
        .splitlines()
    )
    volumes = (
        _run(["docker", "--host", docker_host, "volume", "ls", "--quiet"], timeout=30)
        .decode()
        .splitlines()
    )
    if containers or volumes:
        raise ConfigurationError("v172 inner runtime cleanup inventory is not empty")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v172_inner_cleanup_v1",
        "containers_remaining": 0,
        "volumes_remaining": 0,
        "cleanup_complete": True,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _failure_cleanup(
    manifest: OpenToolchainQualificationManifest,
    *,
    scratch: Path,
    preserve_output: Path,
) -> bool:
    del preserve_output
    for container in _owned_containers():
        _run_result(["docker", "container", "rm", "--force", container], timeout=60)
    for name in (manifest.dind_socket_volume, manifest.dind_data_volume):
        _remove_volume(name, strict=False)
    for path in (SOCKET_BACKING.parent, scratch):
        if path.exists() and not path.is_symlink():
            shutil.rmtree(path)
    _remove_host_builder_tag(manifest)
    return (
        not _owned_containers()
        and not _volume_exists(manifest.dind_socket_volume)
        and not _volume_exists(manifest.dind_data_volume)
        and not SOCKET_BACKING.exists()
        and not DATA_BACKING.exists()
        and not scratch.exists()
    )


def _stop_dind(name: str, *, strict: bool = True) -> None:
    result = _run_result(["docker", "container", "rm", "--force", name], timeout=60)
    if strict and result.returncode != 0:
        raise ConfigurationError("v172 outer DinD cleanup failed")


def _remove_host_builder_tag(manifest: OpenToolchainQualificationManifest) -> None:
    if _docker_image_id(manifest.builder_tag, required=False) is not None:
        _run_result(["docker", "image", "rm", manifest.builder_tag], timeout=60)


def _remove_volume(name: str, *, strict: bool) -> None:
    if not _volume_exists(name):
        return
    result = _run_result(["docker", "volume", "rm", name], timeout=60)
    if strict and result.returncode != 0:
        raise ConfigurationError("v172 volume cleanup failed")


def _tag_inner(docker_host: str, image_id: str, tag: str) -> None:
    _run(["docker", "--host", docker_host, "image", "tag", image_id, tag], timeout=30)


@contextmanager
def _docker_host(value: str) -> Iterator[None]:
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v172 nested Docker environment is contaminated")
    os.environ["DOCKER_HOST"] = value
    try:
        yield
    finally:
        os.environ.pop("DOCKER_HOST", None)


def _require_execution_boundary(
    arguments: argparse.Namespace,
    manifest: OpenToolchainQualificationManifest,
) -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(SANITIZED_CHILD_ENV) != "1":
        raise ConfigurationError("v172 exact opt-in launcher boundary is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v172 requires a non-root host identity")
    if any(name in os.environ for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES):
        raise ConfigurationError("v172 refuses provider configuration")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v172 requires the default host Docker endpoint")
    if arguments.post_merge_main_run_id <= manifest.predecessor_post_merge_main_run_id:
        raise ConfigurationError("v172 requires a new positive post-merge main run identity")


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
            raise ConfigurationError("v172 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        if subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=False).returncode != 0:
            raise ConfigurationError("v172 tracked repository state is dirty")
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    upstream = _git("rev-parse", "origin/main")
    if branch != "main" or head != upstream or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ConfigurationError("v172 requires clean merged origin/main")
    return head


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _docker_image_id(
    reference: str,
    *,
    host: str | None = None,
    required: bool = True,
) -> str | None:
    command = ["docker"]
    if host is not None:
        command.extend(["--host", host])
    result = _run_result(
        [*command, "image", "inspect", reference, "--format", "{{.Id}}"], timeout=30
    )
    if result.returncode != 0:
        if required:
            raise ConfigurationError("v172 required image is unavailable")
        return None
    value = result.stdout.decode("ascii", errors="strict").strip()
    if result.stderr or _IMAGE_ID.fullmatch(value) is None:
        raise ConfigurationError("v172 image identity is malformed")
    return value


def _inspect_image(
    reference: str,
    *,
    host: str | None = None,
    required: bool = True,
) -> dict[str, Any] | None:
    command = ["docker"]
    if host is not None:
        command.extend(["--host", host])
    result = _run_result([*command, "image", "inspect", reference], timeout=30)
    if result.returncode != 0:
        if required:
            raise ConfigurationError("v172 image inspection failed")
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("v172 image inspection is malformed") from exc
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ConfigurationError("v172 image inspection shape changed")
    return value[0]


def _inspect_container(reference: str, *, host: str | None = None) -> dict[str, Any]:
    command = ["docker"]
    if host is not None:
        command.extend(["--host", host])
    value = json.loads(_run([*command, "container", "inspect", reference], timeout=30))
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ConfigurationError("v172 container inspection shape changed")
    return value[0]


def _is_ancestor_layers(parent: dict[str, Any], child: dict[str, Any]) -> bool:
    parent_layers = (parent.get("RootFS") or {}).get("Layers") or []
    child_layers = (child.get("RootFS") or {}).get("Layers") or []
    return bool(parent_layers) and child_layers[: len(parent_layers)] == parent_layers


def _volume_exists(name: str) -> bool:
    return _run_result(["docker", "volume", "inspect", name], timeout=30).returncode == 0


def _owned_containers() -> list[str]:
    result = _run_result(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--filter",
            f"label=verigym.owner={OWNER}",
            "--format",
            "{{.ID}}",
        ],
        timeout=30,
    )
    if result.returncode != 0:
        return ["inventory-error"]
    return [line for line in result.stdout.decode().splitlines() if line]


def _run(command: list[str], *, timeout: int) -> bytes:
    result = _run_result(command, timeout=timeout)
    if result.returncode != 0 or result.stderr:
        raise ConfigurationError("v172 bounded command failed")
    return result.stdout


def _run_result(
    command: list[str],
    *,
    timeout: int,
    maximum: int = _MAX_CONTROL_OUTPUT,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        command,
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    if len(result.stdout) > maximum or len(result.stderr) > maximum:
        raise ConfigurationError("v172 command output exceeded its bound")
    return result


def _run_quiet(command: list[str], *, timeout: int) -> None:
    result = subprocess.run(
        command,
        cwd=_REPOSITORY,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ConfigurationError("v172 quiet offline build command failed")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink() or not path.is_file():
        raise ConfigurationError(f"v172 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v172 {label} identity changed")
    return resolved


def _exact_directory(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink() or not path.is_dir():
        raise ConfigurationError(f"v172 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v172 {label} identity changed")
    return resolved


def _new_output(path: Path, manifest: OpenToolchainQualificationManifest) -> Path:
    if (
        path != OUTPUT_ROOT
        or str(path) != manifest.output_root
        or path.exists()
        or path.is_symlink()
    ):
        raise ConfigurationError("v172 output identity must be fresh and exact")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _new_scratch(manifest: OpenToolchainQualificationManifest) -> Path:
    if (
        SCRATCH_ROOT.as_posix() != manifest.scratch_root
        or SCRATCH_ROOT.exists()
        or SCRATCH_ROOT.is_symlink()
    ):
        raise ConfigurationError("v172 scratch identity must be fresh and exact")
    SCRATCH_ROOT.mkdir(parents=True, mode=0o700)
    return SCRATCH_ROOT.resolve(strict=True)


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
