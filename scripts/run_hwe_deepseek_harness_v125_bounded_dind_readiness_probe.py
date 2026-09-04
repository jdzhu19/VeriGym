#!/usr/bin/env python3
"""Run one provider-free DinD probe with an exact explicit readiness predicate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
for _source_root in reversed((_REPOSITORY, _REPOSITORY / "src")):
    _source_text = str(_source_root.resolve(strict=True))
    sys.path[:] = [_source_text, *(entry for entry in sys.path if entry != _source_text)]

from scripts import (  # noqa: E402
    run_hwe_deepseek_harness_v123_bounded_dind_identity_probe as _v123,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV125BoundedDindReadinessProbeManifest,
    load_v123_bounded_dind_identity_probe_manifest,
    load_v125_bounded_dind_readiness_probe_manifest,
)
from verigym.runtimes.docker.engine import DockerCliEngine, EngineResult  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v125-bounded-dind-readiness-probe-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V125_BOUNDED_DIND_READINESS_PROBE"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v125_bounded_dind_readiness_probe_v1.json"
)
V123_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v123_bounded_dind_identity_probe_v1.json"
)
V123_RUNNER = _REPOSITORY / ("scripts/run_hwe_deepseek_harness_v123_bounded_dind_identity_probe.py")
V123_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v123-bounded-dind-identity-probe-authorization.md"
)
V124_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v124-v123-result.md"
V123_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v123-bounded-dind-identity-probe-v1"
)
V123_FILES = {
    "report": V123_ROOT / "identity-probe-report.json",
    "progress": V123_ROOT / "identity-probe-progress.json",
    "probe": V123_ROOT / "identity-probe-receipt.json",
    "cleanup": V123_ROOT / "cleanup-receipt.json",
    "host_image": V123_ROOT / "host-image-identity.json",
    "headroom": V123_ROOT / "headroom-preflight.json",
    "volume_setup": V123_ROOT / "volume-setup-receipt.json",
    "predecessor": V123_ROOT / "predecessor-preflight.json",
}
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v125-bounded-dind-readiness-probe-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v125")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v125-control")
DIAGNOSTIC_SCRATCH = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v125-scratch")

_PROVIDER_ENV_NAMES = _v123._PROVIDER_ENV_NAMES
_CLOSED_FLAGS = _v123._CLOSED_FLAGS
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v125_bounded_dind_readiness_probe_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v124-v123-result.md",
    "docs/audits/2026-09-04_deepseek-harness-v125-bounded-dind-readiness-probe-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v125_bounded_dind_readiness_probe.py",
    "scripts/run_hwe_deepseek_harness_v125_bounded_dind_readiness_probe.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)


class _ProbeFailure(Exception):
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
        raise ConfigurationError("v125 predecessor JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v125 predecessor JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v125 predecessor JSON must be an object")
    return value


def _canonical_hash(value: Mapping[str, Any], field: str) -> str:
    base = dict(value)
    claimed = base.pop(field, None)
    observed = content_hash(base)
    if claimed != observed:
        raise ConfigurationError("v125 predecessor canonical hash changed")
    return observed


def _git_text(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@contextmanager
def _v125_legacy_bindings() -> Iterator[None]:
    """Rebind only path/owner constants while calling the frozen v123 Docker primitives."""

    replacements = {
        "IDENTITY": IDENTITY,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "DIND_PARENT": DIND_PARENT,
        "DIND_DATA_BACKING": DIND_DATA_BACKING,
        "DIND_SOCKET_BACKING": DIND_SOCKET_BACKING,
        "CONTROL_ROOT": CONTROL_ROOT,
        "DIAGNOSTIC_SCRATCH": DIAGNOSTIC_SCRATCH,
    }
    previous = {name: getattr(_v123, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(_v123, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(_v123, name, value)


def _reseal(value: Mapping[str, Any], *, field: str, format_id: str) -> dict[str, Any]:
    base = dict(value)
    base.pop(field, None)
    base["format_id"] = format_id
    return {**base, field: content_hash(base)}


def _require_execution_boundary(arguments: argparse.Namespace) -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v125 requires a non-root host identity")
    if any(name in os.environ for name in _PROVIDER_ENV_NAMES):
        raise ConfigurationError("v125 refuses a provider configuration environment")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v125 requires the default local Docker endpoint")
    if arguments.manifest != MANIFEST or arguments.output != OUTPUT_ROOT:
        raise ConfigurationError("v125 manifest and output identities are exact")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v125 requires a positive post-merge main run ID")


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV125BoundedDindReadinessProbeManifest,
) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        if _git_text("ls-files", "--error-unmatch", "--", relative) != relative:
            raise ConfigurationError("v125 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git_text("branch", "--show-current")
    head = _git_text("rev-parse", "HEAD")
    upstream = _git_text("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v124_audit_commit, head],
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
        raise ConfigurationError("v125 requires clean merged origin/main after v124")
    return head


def _validate_static_predecessor(
    manifest: DeepSeekHarnessV125BoundedDindReadinessProbeManifest,
) -> dict[str, Any]:
    v123_manifest = load_v123_bounded_dind_identity_probe_manifest(V123_MANIFEST)
    values = {name: _load_json(path) for name, path in V123_FILES.items()}
    report = values["report"]
    if (
        _hash_file(V123_MANIFEST) != manifest.v123_manifest_sha256
        or v123_manifest.manifest_hash != manifest.v123_manifest_hash
        or _hash_file(V123_RUNNER) != manifest.v123_runner_sha256
        or _hash_file(V123_AUTHORIZATION) != manifest.v123_authorization_sha256
        or _hash_file(V124_AUDIT) != manifest.v124_audit_sha256
        or _hash_file(V123_FILES["report"]) != manifest.v123_report_sha256
        or _hash_file(V123_FILES["progress"]) != manifest.v123_report_sha256
        or _canonical_hash(report, "report_hash") != manifest.v123_report_hash
        or _canonical_hash(values["progress"], "report_hash") != manifest.v123_report_hash
        or _hash_file(V123_FILES["probe"]) != manifest.v123_probe_sha256
        or _canonical_hash(values["probe"], "receipt_hash") != manifest.v123_probe_hash
        or _hash_file(V123_FILES["cleanup"]) != manifest.v123_cleanup_sha256
        or _canonical_hash(values["cleanup"], "receipt_hash") != manifest.v123_cleanup_hash
        or _hash_file(V123_FILES["host_image"]) != manifest.v123_host_image_sha256
        or _canonical_hash(values["host_image"], "receipt_hash") != manifest.v123_host_image_hash
        or _hash_file(V123_FILES["headroom"]) != manifest.v123_headroom_sha256
        or _canonical_hash(values["headroom"], "preflight_hash") != manifest.v123_headroom_hash
        or _hash_file(V123_FILES["volume_setup"]) != manifest.v123_volume_setup_sha256
        or _canonical_hash(values["volume_setup"], "receipt_hash")
        != manifest.v123_volume_setup_hash
        or _hash_file(V123_FILES["predecessor"]) != manifest.v123_predecessor_sha256
        or _canonical_hash(values["predecessor"], "receipt_hash") != manifest.v123_predecessor_hash
    ):
        raise ConfigurationError("v125 audited predecessor binding changed")
    entries = list(V123_ROOT.rglob("*"))
    directories = 1 + sum(path.is_dir() and not path.is_symlink() for path in entries)
    files = sum(path.is_file() and not path.is_symlink() for path in entries)
    symlinks = sum(path.is_symlink() for path in entries)
    probe = values["probe"]
    cleanup = values["cleanup"]
    if (
        directories != manifest.v123_evidence_directory_count
        or files != manifest.v123_evidence_regular_file_count
        or symlinks != manifest.v123_evidence_symlink_count
        or report != values["progress"]
        or report.get("identity") != "deepseek-harness-hwe-v123-bounded-dind-identity-probe-v1"
        or report.get("status") != "completed_pending_independent_v124_audit"
        or report.get("diagnostic_complete") is not True
        or report.get("diagnostic_category") != "explicit_info_identity_failed"
        or report.get("dind_identity_qualified") is not False
        or report.get("cleanup_confirmed") is not True
        or report.get("startup_attempt_count") != 1
        or report.get("startup_attempt_limit") != 1
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or report.get("model_process_count") != 0
        or any(report.get(name) is not False for name in _CLOSED_FLAGS)
        or probe.get("status") != "probe_failed"
        or probe.get("diagnostic_category") != "explicit_info_identity_failed"
        or probe.get("daemon_ready") is not True
        or probe.get("readiness_poll_count") != 1
        or probe.get("explicit_info_exit_code") != 0
        or probe.get("explicit_info_stdout_bytes") != 3
        or probe.get("explicit_info_stderr_bytes") != 98
        or probe.get("explicit_info_value_count") != 1
        or probe.get("explicit_info_server_version_equal") is not False
        or probe.get("explicit_info_driver_equal") is not False
        or probe.get("explicit_info_default_runtime_equal") is not False
        or probe.get("legacy_version_category") != "daemon_connect_failure"
        or cleanup.get("status") != "passed"
        or any(
            values[name].get("status") != "passed"
            for name in values
            if name not in {"report", "progress", "probe"}
        )
        or manifest.predecessor_volume_inspection_allowed is not False
        or manifest.predecessor_volume_mutation_allowed is not False
    ):
        raise ConfigurationError("v125 requires the exact audited v123 terminal state")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v125_predecessor_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "v123_manifest_hash": manifest.v123_manifest_hash,
        "v123_report_hash": manifest.v123_report_hash,
        "v123_probe_hash": manifest.v123_probe_hash,
        "v123_cleanup_hash": manifest.v123_cleanup_hash,
        "v124_audit_commit": manifest.v124_audit_commit,
        "v124_post_merge_main_run_id": manifest.v124_post_merge_main_run_id,
        "v124_post_merge_main_all_eight_classes_passed": True,
        "v123_evidence_directory_count": directories,
        "v123_evidence_regular_file_count": files,
        "v123_evidence_symlink_count": symlinks,
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_mutated": False,
        "task_archives_read": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _new_output(path: Path) -> Path:
    with _v125_legacy_bindings():
        return _v123._new_output(path)


def _create_runtime_paths(manifest: DeepSeekHarnessV125BoundedDindReadinessProbeManifest) -> None:
    with _v125_legacy_bindings():
        _v123._create_runtime_paths(manifest)  # type: ignore[arg-type]


def _headroom_receipt() -> dict[str, Any]:
    with _v125_legacy_bindings():
        value = _v123._headroom_receipt()
    return _reseal(
        value,
        field="preflight_hash",
        format_id="verigym_deepseek_harness_hwe_v125_headroom_preflight_v1",
    )


def _host_image_receipt(
    manifest: DeepSeekHarnessV125BoundedDindReadinessProbeManifest,
    engine: DockerCliEngine,
) -> dict[str, Any]:
    try:
        with _v125_legacy_bindings():
            value = _v123._host_image_receipt(manifest, engine)  # type: ignore[arg-type]
    except _v123._ProbeFailure as exc:
        raise _ProbeFailure(exc.category) from exc
    return _reseal(
        value,
        field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v125_host_image_identity_v1",
    )


def _create_volume(
    manifest: DeepSeekHarnessV125BoundedDindReadinessProbeManifest,
    engine: DockerCliEngine,
    *,
    name: str,
    role: str,
    backing: Path,
) -> None:
    try:
        with _v125_legacy_bindings():
            _v123._create_volume(
                manifest,  # type: ignore[arg-type]
                engine,
                name=name,
                role=role,
                backing=backing,
            )
    except _v123._ProbeFailure as exc:
        raise _ProbeFailure(exc.category) from exc


def _volume_setup_receipt(
    manifest: DeepSeekHarnessV125BoundedDindReadinessProbeManifest,
) -> dict[str, Any]:
    with _v125_legacy_bindings():
        value = _v123._volume_setup_receipt(manifest)  # type: ignore[arg-type]
    return _reseal(
        value,
        field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v125_volume_setup_v1",
    )


def _docker_call(
    engine: DockerCliEngine,
    arguments: list[str],
    *,
    timeout_s: int,
    maximum_bytes: int,
) -> EngineResult:
    return _v123._docker_call(
        engine,
        arguments,
        timeout_s=timeout_s,
        maximum_bytes=maximum_bytes,
    )


def _summary(result: EngineResult, prefix: str) -> dict[str, Any]:
    return _v123._summary(result, prefix)


def _classify_readiness(result: EngineResult, value_count: int) -> str:
    if result.timed_out:
        return "timeout"
    if result.output_truncated:
        return "output_bound_exceeded"
    if result.exit_code != 0:
        return "nonzero_exit"
    if result.stderr:
        return "stderr_present"
    if value_count != 3:
        return "invalid_value_count"
    return "complete_identity"


def _seal_probe_receipt(base: dict[str, Any]) -> dict[str, Any]:
    fixed = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v125_readiness_probe_v1",
        "identity": IDENTITY,
        "startup_attempt_count": 1,
        "startup_attempt_limit": 1,
        "json_info_readiness_used": False,
        "fixed_poll_count_cap_used": False,
        "raw_stdout_persisted": False,
        "raw_stderr_persisted": False,
        "raw_output_hashed": False,
        "raw_exception_persisted": False,
        "container_identity_persisted": False,
        "host_paths_persisted": False,
        "provider_request_started": False,
        "provider_calls": 0,
    }
    value = {**fixed, **base}
    return {**value, "receipt_hash": content_hash(value)}


def _run_readiness_probe(
    manifest: DeepSeekHarnessV125BoundedDindReadinessProbeManifest,
    engine: DockerCliEngine,
    name: str,
) -> dict[str, Any]:
    with _v125_legacy_bindings():
        started = _docker_call(
            engine,
            _v123._startup_command(manifest, name),  # type: ignore[arg-type]
            timeout_s=manifest.startup_command_timeout_seconds,
            maximum_bytes=manifest.maximum_diagnostic_output_bytes,
        )
        common: dict[str, Any] = {
            **_summary(started, "docker_run"),
            "docker_run_stdout_shape": "unavailable",
            "outer_controls_valid": False,
            "daemon_ready": False,
            "readiness_poll_count": 0,
            "readiness_last_category": "not_attempted",
            "readiness_exit_code": None,
            "readiness_timed_out": False,
            "readiness_output_truncated": False,
            "readiness_stdout_bytes": 0,
            "readiness_stderr_bytes": 0,
            "readiness_value_count": 0,
            "readiness_server_version_equal": False,
            "readiness_driver_equal": False,
            "readiness_default_runtime_equal": False,
            "identity_qualified": False,
        }
        if (
            started.exit_code != 0
            or started.timed_out
            or started.output_truncated
            or _CONTAINER_ID.fullmatch(started.stdout.strip()) is None
        ):
            common.update(
                status="probe_failed",
                diagnostic_category=_v123._classify_failure("docker_run", started),
            )
            return _seal_probe_receipt(common)
        common["docker_run_stdout_shape"] = "immutable_id"
        if not _v123._outer_controls_valid(manifest, engine, name):  # type: ignore[arg-type]
            common.update(
                status="probe_failed",
                diagnostic_category="outer_container_controls_invalid",
            )
            return _seal_probe_receipt(common)
        common["outer_controls_valid"] = True
        deadline = time.monotonic() + manifest.readiness_timeout_seconds
        while time.monotonic() < deadline:
            common["readiness_poll_count"] += 1
            result = _docker_call(
                engine,
                [
                    "exec",
                    name,
                    "docker",
                    "info",
                    "--format",
                    "{{.ServerVersion}}\t{{.Driver}}\t{{.DefaultRuntime}}",
                ],
                timeout_s=manifest.readiness_command_timeout_seconds,
                maximum_bytes=manifest.maximum_diagnostic_output_bytes,
            )
            values = result.stdout.rstrip("\r\n").split("\t") if result.exit_code == 0 else []
            category = _classify_readiness(result, len(values))
            common.update(_summary(result, "readiness"))
            common["readiness_value_count"] = len(values)
            common["readiness_last_category"] = category
            if category == "complete_identity":
                common["readiness_server_version_equal"] = values[0] == manifest.dind_server_version
                common["readiness_driver_equal"] = values[1] == manifest.dind_storage_driver
                common["readiness_default_runtime_equal"] = (
                    values[2] == manifest.dind_default_runtime
                )
                qualified = all(
                    common[key]
                    for key in (
                        "readiness_server_version_equal",
                        "readiness_driver_equal",
                        "readiness_default_runtime_equal",
                    )
                )
                common["daemon_ready"] = qualified
                common["identity_qualified"] = qualified
                common["status"] = "passed" if qualified else "probe_failed"
                common["diagnostic_category"] = (
                    "dind_identity_qualified" if qualified else "explicit_info_identity_mismatch"
                )
                return _seal_probe_receipt(common)
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(float(manifest.readiness_poll_interval_seconds), remaining))
        common.update(status="probe_failed", diagnostic_category="dind_readiness_timeout")
        return _seal_probe_receipt(common)


def _cleanup(
    manifest: DeepSeekHarnessV125BoundedDindReadinessProbeManifest,
    engine: DockerCliEngine,
    *,
    main_name: str,
    data_attempted: bool,
    socket_attempted: bool,
) -> dict[str, Any]:
    with _v125_legacy_bindings():
        main_removed, main_category = _v123._remove_container(
            manifest,  # type: ignore[arg-type]
            engine,
            main_name,
            role="identity-probe-daemon",
        )
        owned = {
            "data": data_attempted
            and _v123._inspect_volume(
                manifest,  # type: ignore[arg-type]
                engine,
                name=manifest.dind_data_volume,
                role="data",
                backing=DIND_DATA_BACKING,
            ),
            "socket": socket_attempted
            and _v123._inspect_volume(
                manifest,  # type: ignore[arg-type]
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
            helper_name = f"verigym-dind-v125-cleanup-{secrets.token_hex(10)}"
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
                    "verigym.role=identity-probe-cleanup",
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
                if helper.exit_code == 0 and not helper.timed_out and not helper.output_truncated
                else _v123._classify_failure("cleanup_helper", helper)
            )
            helper_removed, helper_remove_category = _v123._remove_container(
                manifest,  # type: ignore[arg-type]
                engine,
                helper_name,
                role="identity-probe-cleanup",
            )
            if not helper_removed:
                helper_status = helper_remove_category
        data_removed, data_category = _v123._remove_volume(
            manifest,  # type: ignore[arg-type]
            engine,
            name=manifest.dind_data_volume,
            role="data",
            backing=DIND_DATA_BACKING,
            attempted=data_attempted,
        )
        socket_removed, socket_category = _v123._remove_volume(
            manifest,  # type: ignore[arg-type]
            engine,
            name=manifest.dind_socket_volume,
            role="socket",
            backing=DIND_SOCKET_BACKING,
            attempted=socket_attempted,
        )
        data_restored = _v123._backing_restored(DIND_DATA_BACKING)
        socket_restored = _v123._backing_restored(DIND_SOCKET_BACKING)
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
        "format_id": "verigym_deepseek_harness_hwe_v125_cleanup_v1",
        "identity": IDENTITY,
        "status": "passed" if passed else "cleanup_unconfirmed",
        "main_container_removed": main_removed,
        "main_container_cleanup_category": main_category,
        "cleanup_helper_attempted": helper_attempted,
        "cleanup_helper_exit_code": helper_exit_code,
        "cleanup_helper_status": helper_status,
        "cleanup_helper_container_removed": helper_removed,
        "data_volume_removed": data_removed,
        "data_volume_cleanup_category": data_category,
        "socket_volume_removed": socket_removed,
        "socket_volume_cleanup_category": socket_category,
        "data_backing_empty_and_ownership_restored": data_restored,
        "socket_backing_empty_and_ownership_restored": socket_restored,
        "volume_removal_independent_of_cleanup_helper": True,
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_mutated": False,
        "raw_stdout_persisted": False,
        "raw_stderr_persisted": False,
        "raw_output_hashed": False,
        "container_identity_persisted": False,
        "host_paths_persisted": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _base_report(
    manifest: DeepSeekHarnessV125BoundedDindReadinessProbeManifest,
    *,
    source_commit: str,
    post_merge_main_run_id: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v125_readiness_probe_report_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "diagnostic_complete": False,
        "startup_attempt_limit": 1,
        "startup_attempt_count": 0,
        "diagnostic_category": None,
        "dind_identity_qualified": False,
        "cleanup_confirmed": False,
        "predecessor_preflight_hash": None,
        "headroom_preflight_hash": None,
        "host_image_identity_hash": None,
        "volume_setup_receipt_hash": None,
        "readiness_probe_receipt_hash": None,
        "cleanup_receipt_hash": None,
        "task_archives_read": False,
        "tasks_materialized": False,
        "base_reference_verification_started": False,
        "harness_controller_started": False,
        "docker_networks_created": False,
        "registry_accessed": False,
        "provider_credentials_available": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_mutated": False,
        "json_info_readiness_used": False,
        "fixed_poll_count_cap_used": False,
        "raw_docker_output_persisted": False,
        "raw_docker_output_hashed": False,
        "raw_exception_persisted": False,
        "container_identity_persisted": False,
        "host_paths_persisted_in_diagnostics": False,
        "requires_independent_v126_audit": True,
        **{name: False for name in _CLOSED_FLAGS},
    }


def _write_report(root: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(report)
    base.pop("report_hash", None)
    value = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(root / "readiness-probe-progress.json", value)
    atomic_dump_json(root / "readiness-probe-report.json", value)
    return value


def diagnose(arguments: argparse.Namespace) -> dict[str, Any]:
    _require_execution_boundary(arguments)
    manifest = load_v125_bounded_dind_readiness_probe_manifest(arguments.manifest)
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
    main_name = f"verigym-dind-v125-{secrets.token_hex(10)}"
    failure_category: str | None = None
    probe: dict[str, Any] | None = None
    cleanup: dict[str, Any]
    try:
        _create_runtime_paths(manifest)
        headroom = _headroom_receipt()
        atomic_dump_json(root / "headroom-preflight.json", headroom)
        report["headroom_preflight_hash"] = headroom["preflight_hash"]
        if headroom["status"] != "passed":
            raise _ProbeFailure("insufficient_headroom")
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
        report["status"] = "bounded_readiness_probe"
        _write_report(root, report)
        probe = _run_readiness_probe(manifest, engine, main_name)
        atomic_dump_json(root / "readiness-probe-receipt.json", probe)
        report.update(
            {
                "startup_attempt_count": 1,
                "diagnostic_category": probe["diagnostic_category"],
                "readiness_probe_receipt_hash": probe["receipt_hash"],
                "dind_identity_qualified": probe["status"] == "passed",
            }
        )
    except _ProbeFailure as exc:
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
                "format_id": "verigym_deepseek_harness_hwe_v125_cleanup_v1",
                "identity": IDENTITY,
                "status": "cleanup_unconfirmed",
                "cleanup_controller_failure": True,
                "raw_exception_persisted": False,
                "provider_calls": 0,
            }
            cleanup["receipt_hash"] = content_hash(cleanup)
        atomic_dump_json(root / "cleanup-receipt.json", cleanup)
        engine.close()
    report["cleanup_receipt_hash"] = cleanup["receipt_hash"]
    report["cleanup_confirmed"] = cleanup["status"] == "passed"
    if failure_category is not None:
        report.update(
            status="stopped_before_diagnostic_completion",
            stop_reason=failure_category,
            diagnostic_complete=False,
        )
    elif probe is None:
        report.update(
            status="stopped_before_diagnostic_completion",
            stop_reason="readiness_probe_receipt_missing",
            diagnostic_complete=False,
        )
    elif cleanup["status"] != "passed":
        report.update(
            status="stopped_cleanup_unconfirmed",
            stop_reason="cleanup_unconfirmed",
            diagnostic_complete=True,
        )
    else:
        report.update(
            status="completed_pending_independent_v126_audit",
            stop_reason=None,
            diagnostic_complete=True,
        )
    return _write_report(root, report)


def main(argv: Sequence[str] | None = None) -> int:
    report = diagnose(_parser().parse_args(argv))
    print(
        json.dumps(
            {
                "status": report["status"],
                "diagnostic_complete": report["diagnostic_complete"],
                "diagnostic_category": report["diagnostic_category"],
                "dind_identity_qualified": report["dind_identity_qualified"],
                "cleanup_confirmed": report["cleanup_confirmed"],
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["diagnostic_complete"] and report["cleanup_confirmed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
