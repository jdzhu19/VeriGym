#!/usr/bin/env python3
"""Run the one-use, zero-provider v152 host-headroom and DinD lifecycle scaffold."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
for _source_root in reversed((_REPOSITORY, _REPOSITORY / "src")):
    _source_text = str(_source_root.resolve(strict=True))
    sys.path[:] = [_source_text, *(item for item in sys.path if item != _source_text)]

from scripts import (  # noqa: E402
    run_hwe_deepseek_harness_v125_bounded_dind_readiness_probe as v125,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    DeepSeekHarnessV152HostHeadroomScaffoldManifest,
    load_v150_official_matrix_manifest,
    load_v152_host_headroom_scaffold_manifest,
)
from verigym.runtimes.docker.engine import DockerCliEngine, EngineResult  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v152-host-headroom-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V152_HOST_HEADROOM_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v152_host_headroom_scaffold_v1.json"
)
V150_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v150_official_matrix_v1.json"
)
V150_RUNNER = _REPOSITORY / "scripts/collect_hwe_deepseek_harness_v150_official_matrix.py"
V150_LAUNCHER = _REPOSITORY / "scripts/launch_hwe_deepseek_harness_v150_official_matrix.py"
V150_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-05_deepseek-harness-v150-official-matrix-authorization.md"
)
V151_AUDIT = _REPOSITORY / "docs/audits/2026-09-05_deepseek-harness-v151-v150-result.md"
V150_ROOT = Path("/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v150-official-matrix-v1")
V150_REPORT = V150_ROOT / "matrix-report.json"
V150_PROGRESS = V150_ROOT / "matrix-progress.json"
V150_ATTEMPT = V150_ROOT / "attempts/pr-465.json"
V150_RECOVERY = V150_ROOT / "cleanup-recovery-receipt.json"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v152-host-headroom-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v152")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v152-control")
DIAGNOSTIC_SCRATCH = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v152-scratch")
_CLOSED_FLAGS = (
    "formal_collection_allowed",
    "formal_collection_started",
    "collection_started",
    "training_started",
    "production_training_ready",
)
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v152_host_headroom_scaffold_v1.json",
    "docs/audits/2026-09-05_deepseek-harness-v151-v150-result.md",
    "docs/audits/2026-09-05_deepseek-harness-v152-host-headroom-scaffold-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v152_host_headroom_scaffold.py",
    "scripts/run_hwe_deepseek_harness_v152_host_headroom_scaffold.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)


class _ScaffoldFailure(Exception):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
        raise ConfigurationError("v152 predecessor JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v152 predecessor JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v152 predecessor JSON must be an object")
    return value


def _canonical_hash(value: Mapping[str, Any], field: str) -> str:
    base = dict(value)
    claimed = base.pop(field, None)
    observed = content_hash(base)
    if claimed != observed:
        raise ConfigurationError("v152 predecessor canonical hash changed")
    return observed


def _git_text(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_execution_boundary(arguments: argparse.Namespace) -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v152 requires a non-root host identity")
    if tuple(sorted(ZERO_PROVIDER_CONFIGURATION_ENV_NAMES)) != (
        ZERO_PROVIDER_CONFIGURATION_ENV_NAMES
    ):
        raise ConfigurationError("v152 provider environment-name set is not canonical")
    if any(name in os.environ for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES):
        raise ConfigurationError("v152 refuses a provider configuration environment")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v152 requires the default local Docker endpoint")
    if arguments.manifest != MANIFEST or arguments.output != OUTPUT_ROOT:
        raise ConfigurationError("v152 manifest and output identities are exact")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v152 requires a positive post-merge main run ID")


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest,
) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        if _git_text("ls-files", "--error-unmatch", "--", relative) != relative:
            raise ConfigurationError("v152 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git_text("branch", "--show-current")
    head = _git_text("rev-parse", "HEAD")
    upstream = _git_text("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v151_audit_merge, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if (
        branch != "main"
        or head != upstream
        or len(head) != 40
        or ancestor.returncode != 0
        or ancestor.stdout
        or ancestor.stderr
    ):
        raise ConfigurationError("v152 requires clean merged origin/main after v151")
    return head


def _validate_static_predecessor(
    manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest,
) -> dict[str, Any]:
    v150 = load_v150_official_matrix_manifest(V150_MANIFEST)
    report = _load_json(V150_REPORT)
    progress = _load_json(V150_PROGRESS)
    attempt = _load_json(V150_ATTEMPT)
    recovery = _load_json(V150_RECOVERY)
    if (
        _hash_file(V150_MANIFEST) != manifest.v150_manifest_sha256
        or v150.manifest_hash != manifest.v150_manifest_hash
        or _hash_file(V150_RUNNER) != manifest.v150_runner_sha256
        or _hash_file(V150_LAUNCHER) != manifest.v150_launcher_sha256
        or _hash_file(V150_AUTHORIZATION) != manifest.v150_authorization_sha256
        or _hash_file(V151_AUDIT) != manifest.v151_audit_sha256
        or _hash_file(V150_REPORT) != manifest.v150_report_sha256
        or _hash_file(V150_PROGRESS) != manifest.v150_report_sha256
        or V150_REPORT.read_bytes() != V150_PROGRESS.read_bytes()
        or _canonical_hash(report, "report_hash") != manifest.v150_report_hash
        or _canonical_hash(progress, "report_hash") != manifest.v150_report_hash
        or _hash_file(V150_ATTEMPT) != manifest.v150_attempt_sha256
        or _canonical_hash(attempt, "attempt_hash") != manifest.v150_attempt_hash
        or _hash_file(V150_RECOVERY) != manifest.v150_cleanup_recovery_sha256
        or _canonical_hash(recovery, "receipt_hash") != manifest.v150_cleanup_recovery_hash
    ):
        raise ConfigurationError("v152 frozen predecessor bytes or hashes changed")
    if (
        report.get("status") != "stopped_pending_independent_v151_audit"
        or report.get("stop_reason") != "pre_provider_infrastructure_failure"
        or report.get("provider_call_count") != 0
        or report.get("provider_total_tokens") != 0
        or report.get("v148_data_volume_reopen_count") != 0
        or attempt.get("provider_marker") != "not_started"
        or attempt.get("provider_call_count") != 0
        or attempt.get("provider_total_tokens") != 0
        or recovery.get("failure_classification") != "host_containerd_no_space_before_dind_start"
        or recovery.get("failed_container_removed") is not True
        or recovery.get("socket_volume_removed") is not True
        or recovery.get("predecessor_data_volume_mutated") is not False
    ):
        raise ConfigurationError("v152 predecessor outcome no longer matches the v151 audit")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v152_predecessor_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "v150_manifest_hash": manifest.v150_manifest_hash,
        "v150_report_hash": manifest.v150_report_hash,
        "v150_attempt_hash": manifest.v150_attempt_hash,
        "v150_cleanup_recovery_hash": manifest.v150_cleanup_recovery_hash,
        "v151_audit_commit": manifest.v151_audit_commit,
        "v151_audit_merge": manifest.v151_audit_merge,
        "v151_post_merge_main_run_id": manifest.v151_post_merge_main_run_id,
        "v150_provider_calls": 0,
        "v150_provider_tokens": 0,
        "v150_v148_data_volume_reopen_count": 0,
        "v148_volumes_inspected": False,
        "v148_volumes_mounted": False,
        "v148_volumes_mutated": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _new_output(path: Path) -> Path:
    if path != OUTPUT_ROOT or path.exists() or path.is_symlink():
        raise ConfigurationError("v152 output identity must be new and exact")
    parent = path.parent.resolve(strict=True)
    if path.parent.is_symlink() or not parent.is_dir():
        raise ConfigurationError("v152 output parent is unsafe")
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path.resolve(strict=True)


def _create_runtime_paths(manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest) -> None:
    expected = {
        DIND_DATA_BACKING: manifest.dind_data_backing,
        DIND_SOCKET_BACKING: manifest.dind_socket_backing,
        CONTROL_ROOT: manifest.control_headroom_root,
        DIAGNOSTIC_SCRATCH: manifest.diagnostic_scratch_root,
    }
    if manifest.output_root != str(OUTPUT_ROOT) or DIND_PARENT.exists() or DIND_PARENT.is_symlink():
        raise ConfigurationError("v152 writable identities must be fresh and exact")
    if CONTROL_ROOT.exists() or CONTROL_ROOT.is_symlink():
        raise ConfigurationError("v152 control root must be fresh")
    if DIAGNOSTIC_SCRATCH.exists() or DIAGNOSTIC_SCRATCH.is_symlink():
        raise ConfigurationError("v152 diagnostic scratch root must be fresh")
    DIND_DATA_BACKING.mkdir(parents=True, mode=0o700)
    DIND_SOCKET_BACKING.mkdir(mode=0o700)
    CONTROL_ROOT.mkdir(parents=True, mode=0o700)
    DIAGNOSTIC_SCRATCH.mkdir(parents=True, mode=0o700)
    for path, frozen in expected.items():
        if str(path) != frozen or path.is_symlink() or not path.is_dir():
            raise ConfigurationError("v152 runtime path differs from the manifest")
        path.chmod(0o700)
        if next(path.iterdir(), None) is not None:
            raise ConfigurationError("v152 runtime path must start empty")


def _host_headroom_receipt(
    manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest,
    *,
    phase: str,
) -> dict[str, Any]:
    if manifest.host_runtime_state_root != "/" or phase not in {"before", "after"}:
        raise ConfigurationError("v152 host headroom identity changed")
    values = os.statvfs(manifest.host_runtime_state_root)
    block_size = values.f_frsize or values.f_bsize
    free_bytes = values.f_bavail * block_size
    free_inodes = values.f_favail
    passed = (
        free_bytes >= manifest.minimum_host_root_free_bytes
        and free_inodes >= manifest.minimum_host_root_free_inodes
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v152_host_root_headroom_v1",
        "identity": IDENTITY,
        "phase": phase,
        "status": "passed" if passed else "rejected_insufficient_headroom",
        "host_runtime_state_root": "/",
        "minimum_free_bytes": manifest.minimum_host_root_free_bytes,
        "observed_free_bytes": free_bytes,
        "minimum_free_inodes": manifest.minimum_host_root_free_inodes,
        "observed_free_inodes": free_inodes,
        "bytes_satisfied": free_bytes >= manifest.minimum_host_root_free_bytes,
        "inodes_satisfied": free_inodes >= manifest.minimum_host_root_free_inodes,
        "absolute_thresholds": True,
        "percentage_thresholds": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "raw_command_output_persisted": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


@contextmanager
def _v152_legacy_bindings() -> Iterator[None]:
    replacements = {
        "IDENTITY": IDENTITY,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "DIND_PARENT": DIND_PARENT,
        "DIND_DATA_BACKING": DIND_DATA_BACKING,
        "DIND_SOCKET_BACKING": DIND_SOCKET_BACKING,
        "CONTROL_ROOT": CONTROL_ROOT,
        "DIAGNOSTIC_SCRATCH": DIAGNOSTIC_SCRATCH,
    }
    previous = {name: getattr(v125, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v125, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v125, name, value)


def _reseal(value: Mapping[str, Any], *, field: str, format_id: str) -> dict[str, Any]:
    base = dict(value)
    base.pop(field, None)
    base["format_id"] = format_id
    base["identity"] = IDENTITY
    return {**base, field: content_hash(base)}


def _host_image_receipt(
    manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest,
    engine: DockerCliEngine,
) -> dict[str, Any]:
    try:
        with _v152_legacy_bindings():
            value = v125._host_image_receipt(manifest, engine)  # type: ignore[arg-type]  # noqa: SLF001
    except v125._ProbeFailure as exc:  # noqa: SLF001
        raise _ScaffoldFailure(exc.category) from exc
    return _reseal(
        value,
        field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v152_host_image_identity_v1",
    )


def _create_volume(
    manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest,
    engine: DockerCliEngine,
    *,
    name: str,
    role: str,
    backing: Path,
) -> None:
    try:
        with _v152_legacy_bindings():
            v125._create_volume(  # noqa: SLF001
                manifest,
                engine,
                name=name,
                role=role,
                backing=backing,  # type: ignore[arg-type]
            )
    except v125._ProbeFailure as exc:  # noqa: SLF001
        raise _ScaffoldFailure(exc.category) from exc


def _volume_setup_receipt(
    manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest,
) -> dict[str, Any]:
    with _v152_legacy_bindings():
        value = v125._volume_setup_receipt(manifest)  # type: ignore[arg-type]  # noqa: SLF001
    value = _reseal(
        value,
        field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v152_volume_setup_v1",
    )
    value["v148_volumes_inspected"] = False
    value["v148_volumes_reused"] = False
    value["receipt_hash"] = content_hash({k: v for k, v in value.items() if k != "receipt_hash"})
    return value


def _run_readiness_probe(
    manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest,
    engine: DockerCliEngine,
    name: str,
) -> dict[str, Any]:
    with _v152_legacy_bindings():
        value = v125._run_readiness_probe(manifest, engine, name)  # type: ignore[arg-type]  # noqa: SLF001
    return _reseal(
        value,
        field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v152_readiness_probe_v1",
    )


def _docker_call(
    engine: DockerCliEngine,
    arguments: list[str],
    *,
    timeout_s: int,
    maximum_bytes: int,
) -> EngineResult:
    return engine._invoke(  # noqa: SLF001
        arguments,
        timeout_s=timeout_s,
        max_output_bytes=maximum_bytes,
    )


def _inventory_receipt(
    manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest,
    engine: DockerCliEngine,
    name: str,
) -> dict[str, Any]:
    commands = {
        "container": ["docker", "container", "ls", "--all", "--quiet"],
        "image": ["docker", "image", "ls", "--all", "--quiet"],
        "volume": ["docker", "volume", "ls", "--quiet"],
        "custom_network": ["docker", "network", "ls", "--quiet", "--filter", "type=custom"],
    }
    summaries: dict[str, dict[str, Any]] = {}
    passed = True
    for role, command in commands.items():
        result = _docker_call(
            engine,
            ["exec", name, *command],
            timeout_s=manifest.inventory_command_timeout_seconds,
            maximum_bytes=manifest.maximum_diagnostic_output_bytes,
        )
        count = len([line for line in result.stdout.splitlines() if line.strip()])
        valid = (
            result.exit_code == 0
            and not result.timed_out
            and not result.output_truncated
            and not result.stderr
            and count == 0
        )
        summaries[role] = {
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "output_truncated": result.output_truncated,
            "stdout_bytes": len(result.stdout.encode()),
            "stderr_bytes": len(result.stderr.encode()),
            "observed_count": count,
            "empty": valid,
        }
        passed = passed and valid
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v152_inner_inventory_v1",
        "identity": IDENTITY,
        "status": "passed" if passed else "inventory_failed",
        "inventories": summaries,
        "mutable_inventory_empty": passed,
        "docker_network_created": False,
        "raw_stdout_persisted": False,
        "raw_stderr_persisted": False,
        "raw_output_hashed": False,
        "container_identity_persisted": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _cleanup(
    manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest,
    engine: DockerCliEngine,
    *,
    main_name: str,
    data_attempted: bool,
    socket_attempted: bool,
) -> dict[str, Any]:
    with _v152_legacy_bindings(), v125._v125_legacy_bindings():  # noqa: SLF001
        legacy = v125._v123  # noqa: SLF001
        main_removed, main_category = legacy._remove_container(  # noqa: SLF001
            manifest, engine, main_name, role="identity-probe-daemon"
        )
        owned = {
            "data": data_attempted
            and legacy._inspect_volume(  # noqa: SLF001
                manifest,
                engine,
                name=manifest.dind_data_volume,
                role="data",
                backing=DIND_DATA_BACKING,
            ),
            "socket": socket_attempted
            and legacy._inspect_volume(  # noqa: SLF001
                manifest,
                engine,
                name=manifest.dind_socket_volume,
                role="socket",
                backing=DIND_SOCKET_BACKING,
            ),
        }
        helper_attempted = any(owned.values())
        helper_status = "not_required"
        helper_exit_code: int | None = None
        helper_removed = True
        if helper_attempted:
            helper_name = f"verigym-dind-v152-cleanup-{secrets.token_hex(10)}"
            mounts: list[str] = []
            scripts: list[str] = []
            for role, volume, target in (
                ("data", manifest.dind_data_volume, "/verigym-data"),
                ("socket", manifest.dind_socket_volume, "/verigym-socket"),
            ):
                if owned[role]:
                    mounts.extend(["--mount", f"type=volume,src={volume},dst={target}"])
                    scripts.extend(
                        [
                            f"rm -rf -- {target}/* {target}/.[!.]* {target}/..?*",
                            f"chown {os.getuid()}:{os.getgid()} {target}",
                            f"chmod 0700 {target}",
                        ]
                    )
            helper = _docker_call(
                engine,
                [
                    "run",
                    "--rm",
                    "--name",
                    helper_name,
                    "--label",
                    f"verigym.owner={IDENTITY}",
                    "--label",
                    "verigym.role=host-headroom-cleanup",
                    "--network",
                    "none",
                    "--read-only",
                    "--user",
                    "0:0",
                    "--cap-drop",
                    "ALL",
                    "--cap-add",
                    "CHOWN",
                    "--cap-add",
                    "DAC_OVERRIDE",
                    "--cap-add",
                    "FOWNER",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "64",
                    "--memory",
                    "128m",
                    "--memory-swap",
                    "128m",
                    "--cpus",
                    "0.25",
                    *mounts,
                    "--entrypoint",
                    "/bin/sh",
                    manifest.dind_image_id,
                    "-euc",
                    "; ".join(scripts),
                ],
                timeout_s=manifest.cleanup_command_timeout_seconds,
                maximum_bytes=manifest.maximum_diagnostic_output_bytes,
            )
            helper_exit_code = helper.exit_code
            helper_status = (
                "passed"
                if helper.exit_code == 0
                and not helper.timed_out
                and not helper.output_truncated
                and not helper.stdout
                and not helper.stderr
                else legacy._classify_failure("cleanup_helper", helper)  # noqa: SLF001
            )
            helper_removed, helper_remove_category = legacy._remove_container(  # noqa: SLF001
                manifest, engine, helper_name, role="host-headroom-cleanup"
            )
            if not helper_removed:
                helper_status = helper_remove_category
        data_removed, data_category = legacy._remove_volume(  # noqa: SLF001
            manifest,
            engine,
            name=manifest.dind_data_volume,
            role="data",
            backing=DIND_DATA_BACKING,
            attempted=data_attempted,
        )
        socket_removed, socket_category = legacy._remove_volume(  # noqa: SLF001
            manifest,
            engine,
            name=manifest.dind_socket_volume,
            role="socket",
            backing=DIND_SOCKET_BACKING,
            attempted=socket_attempted,
        )
        data_restored = legacy._backing_restored(DIND_DATA_BACKING)  # noqa: SLF001
        socket_restored = legacy._backing_restored(DIND_SOCKET_BACKING)  # noqa: SLF001
    passed = all(
        (
            main_removed,
            helper_removed,
            helper_status in {"passed", "not_required"},
            data_removed,
            socket_removed,
            data_restored,
            socket_restored,
        )
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v152_cleanup_v1",
        "identity": IDENTITY,
        "status": "passed" if passed else "cleanup_unconfirmed",
        "main_container_removed": main_removed,
        "main_container_cleanup_category": main_category,
        "cleanup_helper_attempted": helper_attempted,
        "cleanup_helper_exit_code": helper_exit_code,
        "cleanup_helper_status": helper_status,
        "cleanup_helper_required_empty_output": True,
        "cleanup_helper_container_removed": helper_removed,
        "data_volume_removed": data_removed,
        "data_volume_cleanup_category": data_category,
        "socket_volume_removed": socket_removed,
        "socket_volume_cleanup_category": socket_category,
        "data_backing_empty_and_ownership_restored": data_restored,
        "socket_backing_empty_and_ownership_restored": socket_restored,
        "v148_volumes_inspected": False,
        "v148_volumes_mounted": False,
        "v148_volumes_mutated": False,
        "raw_stdout_persisted": False,
        "raw_stderr_persisted": False,
        "raw_output_hashed": False,
        "raw_exception_persisted": False,
        "container_identity_persisted": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _base_report(
    manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest,
    *,
    source_commit: str,
    post_merge_main_run_id: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v152_host_headroom_scaffold_result_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "stop_reason": None,
        "scaffold_complete": False,
        "scaffold_contract_published": False,
        "startup_attempt_limit": 1,
        "startup_attempt_count": 0,
        "dind_identity_qualified": False,
        "inner_mutable_inventory_empty": False,
        "cleanup_confirmed": False,
        "host_root_headroom_before_hash": None,
        "host_root_headroom_after_hash": None,
        "predecessor_preflight_hash": None,
        "host_image_identity_hash": None,
        "volume_setup_receipt_hash": None,
        "readiness_probe_receipt_hash": None,
        "inventory_receipt_hash": None,
        "cleanup_receipt_hash": None,
        "scaffold_contract_hash": None,
        "v148_volumes_inspected": False,
        "v148_volumes_mounted": False,
        "v148_volumes_mutated": False,
        "task_archives_read": False,
        "tasks_materialized": False,
        "base_reference_verification_started": False,
        "harness_controller_started": False,
        "docker_networks_created": False,
        "registry_accessed": False,
        "provider_credentials_available": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "provider_tokens": 0,
        "model_process_count": 0,
        "raw_docker_output_persisted": False,
        "raw_docker_output_hashed": False,
        "raw_exception_persisted": False,
        "container_identity_persisted": False,
        "requires_independent_v153_audit": True,
        **{name: False for name in _CLOSED_FLAGS},
    }


def _write_report(root: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(report)
    base.pop("report_hash", None)
    value = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(root / "scaffold-progress.json", value)
    atomic_dump_json(root / "scaffold-report.json", value)
    return value


def _scaffold_contract(
    manifest: DeepSeekHarnessV152HostHeadroomScaffoldManifest,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    required = (
        "predecessor_preflight_hash",
        "host_root_headroom_before_hash",
        "host_image_identity_hash",
        "volume_setup_receipt_hash",
        "readiness_probe_receipt_hash",
        "inventory_receipt_hash",
        "cleanup_receipt_hash",
        "host_root_headroom_after_hash",
    )
    if any(not isinstance(report.get(field), str) for field in required):
        raise ConfigurationError("v152 refuses a partial scaffold contract")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v152_host_runtime_scaffold_contract_v1",
        "identity": IDENTITY,
        "status": "passed_pending_independent_v153_audit",
        "manifest_hash": manifest.manifest_hash,
        **{field: report[field] for field in required},
        "host_root_minimum_free_bytes": manifest.minimum_host_root_free_bytes,
        "host_root_minimum_free_inodes": manifest.minimum_host_root_free_inodes,
        "dind_server_version": manifest.dind_server_version,
        "dind_storage_driver": manifest.dind_storage_driver,
        "dind_default_runtime": manifest.dind_default_runtime,
        "inner_mutable_inventory_empty": True,
        "cleanup_confirmed": True,
        "v148_volumes_inspected": False,
        "v148_volumes_mounted": False,
        "v148_volumes_mutated": False,
        "provider_execution_authorized": False,
        "provider_calls": 0,
        "provider_tokens": 0,
        "requires_independent_v153_audit": True,
        **{name: False for name in _CLOSED_FLAGS},
    }
    return {**base, "contract_hash": content_hash(base)}


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    _require_execution_boundary(arguments)
    manifest = load_v152_host_headroom_scaffold_manifest(arguments.manifest)
    if tuple(
        manifest.provider_environment_names
    ) != ZERO_PROVIDER_CONFIGURATION_ENV_NAMES or manifest.provider_environment_name_count != len(
        ZERO_PROVIDER_CONFIGURATION_ENV_NAMES
    ):
        raise ConfigurationError("v152 manifest provider environment boundary changed")
    source_commit = _require_clean_merged_main(manifest)
    predecessor = _validate_static_predecessor(manifest)
    root = _new_output(arguments.output)
    report = _base_report(
        manifest,
        source_commit=source_commit,
        post_merge_main_run_id=arguments.post_merge_main_run_id,
    )
    atomic_dump_json(root / "predecessor-preflight.json", predecessor)
    report["predecessor_preflight_hash"] = predecessor["receipt_hash"]
    _write_report(root, report)
    engine = DockerCliEngine()
    data_attempted = False
    socket_attempted = False
    main_name = f"verigym-dind-v152-{secrets.token_hex(10)}"
    failure_category: str | None = None
    readiness: dict[str, Any] | None = None
    inventory: dict[str, Any] | None = None
    cleanup: dict[str, Any]
    try:
        _create_runtime_paths(manifest)
        before = _host_headroom_receipt(manifest, phase="before")
        atomic_dump_json(root / "host-root-headroom-before.json", before)
        report["host_root_headroom_before_hash"] = before["receipt_hash"]
        if before["status"] != "passed":
            raise _ScaffoldFailure("insufficient_host_root_headroom")
        image = _host_image_receipt(manifest, engine)
        atomic_dump_json(root / "host-image-identity.json", image)
        report["host_image_identity_hash"] = image["receipt_hash"]
        data_attempted = True
        _create_volume(
            manifest,
            engine,
            name=manifest.dind_data_volume,
            role="data",
            backing=DIND_DATA_BACKING,
        )
        socket_attempted = True
        _create_volume(
            manifest,
            engine,
            name=manifest.dind_socket_volume,
            role="socket",
            backing=DIND_SOCKET_BACKING,
        )
        volume_setup = _volume_setup_receipt(manifest)
        atomic_dump_json(root / "volume-setup-receipt.json", volume_setup)
        report["volume_setup_receipt_hash"] = volume_setup["receipt_hash"]
        report["status"] = "bounded_dind_lifecycle"
        _write_report(root, report)
        readiness = _run_readiness_probe(manifest, engine, main_name)
        atomic_dump_json(root / "readiness-probe-receipt.json", readiness)
        report.update(
            startup_attempt_count=1,
            readiness_probe_receipt_hash=readiness["receipt_hash"],
            dind_identity_qualified=readiness["status"] == "passed",
        )
        if readiness["status"] != "passed":
            raise _ScaffoldFailure(str(readiness["diagnostic_category"]))
        inventory = _inventory_receipt(manifest, engine, main_name)
        atomic_dump_json(root / "inner-inventory-receipt.json", inventory)
        report.update(
            inventory_receipt_hash=inventory["receipt_hash"],
            inner_mutable_inventory_empty=inventory["status"] == "passed",
        )
        if inventory["status"] != "passed":
            raise _ScaffoldFailure("inner_inventory_failed")
    except _ScaffoldFailure as exc:
        failure_category = exc.category
    except Exception:
        failure_category = "unexpected_controller_failure"
    finally:
        try:
            cleanup = _cleanup(
                manifest,
                engine,
                main_name=main_name,
                data_attempted=data_attempted,
                socket_attempted=socket_attempted,
            )
        except Exception:
            cleanup = {
                "schema_version": "1.0",
                "format_id": "verigym_deepseek_harness_hwe_v152_cleanup_v1",
                "identity": IDENTITY,
                "status": "cleanup_unconfirmed",
                "cleanup_controller_failure": True,
                "raw_exception_persisted": False,
                "v148_volumes_inspected": False,
                "v148_volumes_mounted": False,
                "v148_volumes_mutated": False,
                "provider_calls": 0,
            }
            cleanup["receipt_hash"] = content_hash(cleanup)
        atomic_dump_json(root / "cleanup-receipt.json", cleanup)
        engine.close()
    report["cleanup_receipt_hash"] = cleanup["receipt_hash"]
    report["cleanup_confirmed"] = cleanup["status"] == "passed"
    after = _host_headroom_receipt(manifest, phase="after")
    atomic_dump_json(root / "host-root-headroom-after.json", after)
    report["host_root_headroom_after_hash"] = after["receipt_hash"]
    if failure_category is None and after["status"] != "passed":
        failure_category = "insufficient_host_root_headroom_after_cleanup"
    if failure_category is not None:
        report.update(
            status="stopped_without_host_runtime_scaffold",
            stop_reason=failure_category,
            scaffold_complete=False,
        )
    elif readiness is None or inventory is None:
        report.update(
            status="stopped_without_host_runtime_scaffold",
            stop_reason="runtime_receipt_missing",
            scaffold_complete=False,
        )
    elif cleanup["status"] != "passed":
        report.update(
            status="stopped_cleanup_unconfirmed",
            stop_reason="cleanup_unconfirmed",
            scaffold_complete=False,
        )
    else:
        contract = _scaffold_contract(manifest, report)
        atomic_dump_json(root / "host-runtime-scaffold-contract.json", contract)
        report.update(
            status="completed_pending_independent_v153_audit",
            stop_reason=None,
            scaffold_complete=True,
            scaffold_contract_published=True,
            scaffold_contract_hash=contract["contract_hash"],
        )
    return _write_report(root, report)


def main(argv: Sequence[str] | None = None) -> int:
    report = materialize(_parser().parse_args(argv))
    print(
        json.dumps(
            {
                "status": report["status"],
                "scaffold_complete": report["scaffold_complete"],
                "scaffold_contract_published": report["scaffold_contract_published"],
                "dind_identity_qualified": report["dind_identity_qualified"],
                "inner_mutable_inventory_empty": report["inner_mutable_inventory_empty"],
                "cleanup_confirmed": report["cleanup_confirmed"],
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["scaffold_complete"] and report["cleanup_confirmed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
