#!/usr/bin/env python3
"""Qualify repaired open tools on PR-1816, optionally run one research-only Harness episode."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[1]
for relative in (
    "",
    "src",
    "integrations/verigym-hwe-bench/src",
    "integrations/verigym-deepseek-harness/src",
):
    sys.path.insert(0, str(REPOSITORY / relative))

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v172_open_toolchain as qualification,
)
from scripts import run_repository_rollout_dind_controller as dind  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.campaign import HWE_WORKSPACE_RUNTIME_IMAGE_ID  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
)
from verigym.hwe.open_toolchain import load_open_toolchain_manifest  # noqa: E402
from verigym.hwe.open_toolchain_git_builder_repair import OpenToolchainV188ImageLock  # noqa: E402

IDENTITY = "deepseek-harness-pr1816-open-research-s503-v1"
ARCHIVES = Path("/data2/jiadongzhu/Agent/hwe-bench-public-images")
REPAIR_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v188-git-builder-repair-v1"
)
OUTPUT = Path("/data2/jiadongzhu/Agent/experiments") / IDENTITY
BACKING = Path("/data2/jiadongzhu/docker") / IDENTITY
SCRATCH = Path("/data2/jiadongzhu/Agent/.verigym-tmp") / IDENTITY
CONSUMPTION = Path("/data2/jiadongzhu/Agent/experiments/pr1816-open-research-s503-consumed.json")


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024**2:
        raise ValueError("Required bounded JSON input is missing or unsafe")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _receipt(path: Path, field: str) -> dict[str, Any]:
    value = _json(path)
    if value.get(field) != content_hash({k: v for k, v in value.items() if k != field}):
        raise ValueError("Receipt content hash mismatch")
    return value


def review_repair(root: Path) -> tuple[OpenToolchainV188ImageLock, dict[str, Any], dict[str, Any]]:
    """Independently cross-check the repair's terminal evidence before loading any task."""
    report = _receipt(root / "zero-provider-report.json", "report_hash")
    cleanup = _receipt(root / "cleanup.json", "cleanup_hash")
    archive = _receipt(root / "final-image-archive.json", "receipt_hash")
    lock = OpenToolchainV188ImageLock.model_validate(_json(root / "final-image-lock.json"))
    if not (
        report.get("repair_succeeded") is True
        and report.get("archive_exported") is True
        and report.get("cleanup_complete") is True
        and cleanup.get("cleanup_complete") is True
        and report.get("image_lock_hash") == lock.lock_hash
        and report.get("final_image_id") == lock.image_id == archive.get("image_id")
        and report.get("cleanup_hash") == cleanup.get("cleanup_hash")
        and all(
            report.get(k) == 0
            for k in (
                "provider_calls",
                "model_process_count",
                "hwe_image_import_count",
                "task_source_prepare_count",
                "verifier_run_count",
            )
        )
    ):
        raise ValueError("Repair evidence does not establish a clean zero-provider success")
    path = Path(archive["archive_path"])
    sidecar = Path(archive["sidecar_path"])
    if not (
        path.is_relative_to(Path("/data2/jiadongzhu/Agent"))
        and path.is_file()
        and not path.is_symlink()
        and path.stat().st_size == archive["archive_bytes"]
        and _hash(path) == archive["archive_sha256"]
        and sidecar.is_file()
        and not sidecar.is_symlink()
        and _hash(sidecar) == archive["sidecar_sha256"]
        and sidecar.read_text().split() == [archive["archive_sha256"], path.name]
    ):
        raise ValueError("Repaired image archive or sidecar changed")
    review = {
        "repair_report_hash": report["report_hash"],
        "cleanup_hash": cleanup["cleanup_hash"],
        "image_lock_hash": lock.lock_hash,
        "archive_receipt_hash": archive["receipt_hash"],
        "repair_receipt_files": {p.name: _hash(p) for p in sorted(root.glob("*.json"))},
        "zero_provider_repair_valid": True,
    }
    return lock, archive, review


def _docker(*args: str, timeout: int = 120) -> bytes:
    result = subprocess.run(
        ["docker", *args],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Docker {args[0]} failed with exit code {result.returncode}")
    return result.stdout


@contextlib.contextmanager
def _without_provider_environment():
    names = (*ZERO_PROVIDER_CONFIGURATION_ENV_NAMES, "DOCKER_HOST", "DOCKER_CONTEXT")
    saved = {name: os.environ.pop(name) for name in names if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


@contextlib.contextmanager
def _runtime_temporary_directory(path: Path):
    path.mkdir(mode=0o700)
    previous = tempfile.tempdir
    previous_env = os.environ.get("TMPDIR")
    tempfile.tempdir = str(path)
    os.environ["TMPDIR"] = str(path)
    try:
        yield
    finally:
        tempfile.tempdir = previous
        if previous_env is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = previous_env


@contextlib.contextmanager
def isolated_runtime(manifest: Any):
    """Own fresh /data2 storage and remove only resources created by this invocation."""
    for path in (BACKING, SCRATCH):
        if path.exists() or path.is_symlink():
            raise ValueError("Research runtime requires fresh backing and scratch paths")
    BACKING.mkdir(mode=0o700)
    SCRATCH.mkdir(mode=0o700)
    volumes: list[tuple[str, str]] = []
    name = f"verigym-{IDENTITY}"
    started = False
    old_owner = dind._DIND_OWNER
    dind._DIND_OWNER = IDENTITY
    try:
        for role in ("data", "socket"):
            backing = BACKING / role
            backing.mkdir(mode=0o700)
            volume = f"verigym-{IDENTITY}-{role}"
            dind._create_bind_backed_volume(volume, owner=IDENTITY, role=role, backing=backing)
            volumes.append((volume, role))
        empty = SCRATCH / "empty-home"
        empty.mkdir(mode=0o700)

        def mark_started() -> None:
            nonlocal started
            started = True

        dind._start_dind(
            name=name,
            image_id=manifest.dind_image_id,
            data_volume=volumes[0][0],
            socket_volume=volumes[1][0],
            source_volume=None,
            scratch_volume=None,
            empty_home=empty,
            same_path_mounts=dind._same_path_mounts({OUTPUT: "rw", SCRATCH: "rw"}),
            startup_timeout_s=120,
            on_container_started=mark_started,
        )
        with _runtime_temporary_directory(SCRATCH / "temporary"):
            yield name, f"unix://{BACKING / 'socket/docker.sock'}"
    finally:
        if started:
            _docker("container", "rm", "--force", name)
        for volume, role in reversed(volumes):
            dind._bind_backed_volume(volume, owner=IDENTITY, role=role, backing=BACKING / role)
            _docker("volume", "rm", volume)
        # BACKING was created above and contains only this invocation's nested Docker storage.
        _docker(
            "run",
            "--rm",
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
            "256m",
            "--memory-swap",
            "256m",
            "--cpus",
            "1",
            "--mount",
            f"type=bind,src={BACKING},dst=/owned",
            "--entrypoint",
            "/bin/sh",
            manifest.dind_image_id,
            "-ceu",
            f"find /owned -depth -mindepth 1 -delete; chown {os.getuid()}:{os.getgid()} /owned",
            timeout=1800,
        )
        BACKING.rmdir()
        shutil.rmtree(SCRATCH)
        dind._DIND_OWNER = old_owner
        atomic_dump_json(
            OUTPUT / "cleanup.json",
            {
                "cleanup_complete": not BACKING.exists() and not SCRATCH.exists(),
                "owned_outer_removed": True,
                "owned_volumes_removed": True,
            },
        )


def qualify(
    manifest: Any, lock: OpenToolchainV188ImageLock, archive: dict[str, Any], host: str
) -> dict[str, Any]:
    inspection = qualification.inspect_offline_image_archive(manifest.task, archive_root=ARCHIVES)
    atomic_dump_json(OUTPUT / "official-archive.json", inspection)
    patch_receipt, instance = qualification._patch_receipt(manifest, archive_root=ARCHIVES)
    atomic_dump_json(OUTPUT / "reference-patch-compatibility.json", patch_receipt)
    _docker("--host", host, "load", "--input", archive["archive_path"], timeout=1800)
    if qualification._docker_image_id(lock.image_id, host=host) != lock.image_id:
        raise ValueError("Loaded open-tool image differs from the reviewed repair")
    with qualification._docker_host(host):
        qualification._load_official_image(manifest, archive_root=ARCHIVES)
        source = OUTPUT / "source"
        qualification.prepare_source(
            dataset=ARCHIVES / manifest.task.dataset_relpath,
            output=source,
            selected_tasks=[manifest.task.instance_id],
            pull=False,
            imported_image_bindings={
                manifest.task.registry_reference: {
                    "image_id": manifest.official_verifier_image,
                    "manifest_digest": manifest.task.registry_manifest_digest,
                }
            },
            docker_control_timeout_s=300,
        )
        official = qualification.run_zero_model_smoke(
            source=source,
            output=OUTPUT / "official-qualification",
            docker_control_timeout_s=300,
        )
        open_result = qualification._run_open_comparison(
            source=source,
            instance=instance,
            image_id=lock.image_id,
            docker_host=host,
            root=OUTPUT,
        )
        atomic_dump_json(OUTPUT / "open-comparison.json", open_result)
        qualification._validate_inner_cleanup(host)
    passed = (
        qualification.zero_model_infrastructure_valid(official)
        and qualification.zero_model_fail_to_pass_eligible(official)
        and open_result.get("base_failed") is True
        and open_result.get("reference_passed") is True
    )
    if not passed:
        raise ValueError("Both routes must reproduce base-FAIL/reference-PASS")
    return {
        "task_id": manifest.task.task_id,
        "agent_image": lock.image_id,
        "official_verifier_image": manifest.official_verifier_image,
        "agent_toolchain_id": lock.agent_toolchain_id,
        "both_routes_qualified": True,
        "official_receipt_sha256": _hash(OUTPUT / "official-qualification/smoke-report.json"),
        "open_receipt_hash": open_result["receipt_hash"],
        "provider_calls": 0,
    }


def runtime_config(lock: OpenToolchainV188ImageLock):
    from verigym.schemas.runtime import DockerCommandImageRuntimeConfig, DockerRuntimeConfig

    return DockerRuntimeConfig(
        image=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        expected_image_id=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        pull_policy="never",
        run_as_user=lock.effective_user,
        memory_bytes=16 * 1024**3,
        cpus=4,
        pids_limit=4096,
        max_command_time_s=900,
        command_image=DockerCommandImageRuntimeConfig(
            image=lock.image_id,
            expected_image_id=lock.image_id,
            expected_rg_version="15.2.0",
            expected_rg_sha256=lock.binary_sha256["rg"],
            protocol="hwe_command_image_v1",
            execution_backend="episode_container_exec_v1",
            required_image_labels={
                "org.verigym.agent-toolchain-id": lock.agent_toolchain_id,
                "org.verigym.role": "agent-only-non-authoritative",
                "org.verigym.official-verifier-included": "false",
            },
            run_as_user=lock.effective_user,
            memory_bytes=16 * 1024**3,
            cpus=4,
            pids_limit=4096,
            max_command_time_s=3600,
            identity_probe_timeout_s=300,
            max_output_bytes=32 * 1024**2,
        ),
    )


def run_canary(
    manifest: Any, lock: OpenToolchainV188ImageLock, qualified: dict[str, Any], name: str, host: str
) -> dict[str, Any]:
    from scripts.materialize_hwe_deepseek_harness_v158_explicit_endpoint_scaffold import (
        _bound_runtime_registry,
    )
    from verigym.core.security_scanner import scan_artifact_roots
    from verigym.hwe.deepseek_harness import (
        DEEPSEEK_HARNESS_MODEL,
        validate_deepseek_harness_transcript_v3,
    )
    from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID
    from verigym.schemas.common import InteractionMode
    from verigym.schemas.run import RunConfig
    from verigym.schemas.suite import SuiteSourceConfig

    if qualified.get("both_routes_qualified") is not True or CONSUMPTION.exists():
        raise ValueError("Canary is unqualified or its identity has already been consumed")
    dind._ensure_inner_image(
        container=name, image_id=HWE_WORKSPACE_RUNTIME_IMAGE_ID, timeout_s=1800
    )
    service, template = _bound_runtime_registry(host)
    source = SuiteSourceConfig(source_root=OUTPUT / "source", variant="repo-repair-v1")
    suite, task, _assets = service.load_task(manifest.task.task_id, source)
    config = runtime_config(lock)
    # Resolve settings and exercise the actual configured runtime before consuming the episode.
    from verigym_deepseek_harness.config import require_provider_environment, resolve_settings

    options = {
        "model_id": DEEPSEEK_HARNESS_MODEL,
        "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
        "max_process_time_s": 3600,
        "max_output_bytes": 32 * 1024**2,
        "command_image_lock_hash": lock.lock_hash,
        "whole_episode_retries": 0,
        "controller_docker_host": "unix:///var/run/docker.sock",
    }
    require_provider_environment()
    settings = resolve_settings(options, task_wall_time_s=task.budget.max_wall_time_s)
    configured = template.configure(config)
    try:
        configured.prepare(f"{IDENTITY}-preflight")
    finally:
        configured.close()
    from verigym_deepseek_harness.process import run_harness_helper

    session_root = SCRATCH / "initialize-session"
    broker_root = SCRATCH / "initialize-broker"
    session_root.mkdir(mode=0o700)
    broker_root.mkdir(mode=0o700)
    initialized = run_harness_helper(
        settings,
        mode="initialize",
        prompt="",
        system_prompt="",
        session_id=f"{IDENTITY}-initialize",
        session_root=session_root,
        broker_root=broker_root,
        docker_host=settings.docker_host,
    )
    if (
        initialized.run_interval_count != 0
        or (session_root / "provider-request-started-v1.json").exists()
    ):
        raise ValueError("Harness initialization crossed the provider boundary")
    with CONSUMPTION.open("x") as stream:
        json.dump(
            {
                "identity": IDENTITY,
                "task_id": task.id,
                "seed": 503,
                "sample_index": 19,
                "qualification_hash": content_hash(qualified),
                "whole_episode_retries": 0,
            },
            stream,
        )
    try:
        with qualification._docker_host(host):
            result = service.run(
                RunConfig(
                    task_id=task.id,
                    suite_source=source,
                    expected_suite_source_snapshot=suite.source_snapshot(),
                    expected_task_hash=content_hash(task),
                    expected_source_hash=task.source.content_hash,
                    mode=InteractionMode.AGENT,
                    agent="deepseek-harness-hwe-agent-v4",
                    agent_options=options,
                    runtime="docker",
                    docker_config=config,
                    seed=503,
                    sample_index=19,
                    output=OUTPUT / "research-runs",
                    run_id=IDENTITY,
                    experiment_id=IDENTITY,
                    plan_item_id=IDENTITY,
                    system_id="deepseek-harness-open-tools-research-v4",
                    base_seed=503,
                )
            )
        run = Path(result.run_dir)
        transcript_path = (
            run / "artifacts/deepseek_harness/deepseek_harness_teacher_transcript_v3.json"
        )
        transcript_valid = False
        if transcript_path.is_file():
            validate_deepseek_harness_transcript_v3(_json(transcript_path))
            transcript_valid = True
        from verigym_deepseek_harness.config import API_KEY_ENV, BASE_URL_ENV

        scan = scan_artifact_roots(
            [run / "artifacts/deepseek_harness"],
            report_id=IDENTITY,
            proxy_values=(os.environ[API_KEY_ENV], os.environ[BASE_URL_ENV]),
            forbidden_host_roots=(
                str(OUTPUT / "source"),
                str(REPOSITORY),
                str(settings.source_root),
            ),
        )
        atomic_dump_json(OUTPUT / "research-security-scan.json", scan)
        evidence_path = run / "artifacts/deepseek_harness/collection_evidence.json"
        evidence = _json(evidence_path) if evidence_path.exists() else {}
        return {
            "task_id": task.id,
            "seed": 503,
            "sample_index": 19,
            "research_only": True,
            "resolved": result.scorecard.resolved,
            "transcript_valid": transcript_valid,
            "security_valid": scan.gate == "pass",
            "provider_request_started": evidence.get("provider_request_started", False),
            "provider_calls": evidence.get("observed_provider_calls", 0),
            "provider_tokens": evidence.get("observed_provider_total_tokens", 0),
            "run_directory": str(run),
            "agent_toolchain_id": lock.agent_toolchain_id,
            "official_verifier_image": lock.official_verifier_image,
            "scorecard": result.scorecard.model_dump(mode="json"),
            "formal_collection_started": False,
            "sft_admitted": False,
            "training_started": False,
        }
    finally:
        template.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-canary", action="store_true")
    args = parser.parse_args()
    if os.getuid() == 0 or OUTPUT.exists() or OUTPUT.is_symlink():
        raise ValueError("Require a non-root operator and fresh research output")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ValueError("Research launcher requires the default host Docker endpoint")
    if args.run_canary and CONSUMPTION.exists():
        raise ValueError("The research canary identity has already been consumed")
    if shutil.disk_usage("/").free < 4 * 1024**3 or shutil.disk_usage("/data2").free < 50 * 1024**3:
        raise ValueError("Insufficient control-root or /data2 headroom")
    manifest = load_open_toolchain_manifest(
        REPOSITORY
        / "configs/training/qwen35_hwe_deepseek_harness_v172_open_toolchain_qualification_v1.json"
    )
    lock, archive, review = review_repair(REPAIR_ROOT)
    if lock.official_verifier_image != manifest.official_verifier_image:
        raise ValueError("Qualification and repair bind different official verifiers")
    OUTPUT.mkdir(mode=0o700)
    atomic_dump_json(OUTPUT / "repair-review.json", review)
    outcome: dict[str, Any] = {
        "identity": IDENTITY,
        "research_only": True,
        "status": "preparing",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True
        ).strip(),
        "runner_sha256": _hash(Path(__file__)),
    }
    atomic_dump_json(OUTPUT / "progress.json", outcome)
    try:
        with isolated_runtime(manifest) as (name, host):
            with _without_provider_environment():
                qualified = qualify(manifest, lock, archive, host)
            atomic_dump_json(OUTPUT / "qualification.json", qualified)
            outcome["qualification"] = qualified
            outcome["status"] = "qualified"
            atomic_dump_json(OUTPUT / "progress.json", outcome)
            if args.run_canary:
                outcome["canary"] = run_canary(manifest, lock, qualified, name, host)
                atomic_dump_json(OUTPUT / "research-canary.json", outcome["canary"])
                outcome["status"] = "research_canary_completed"
    except Exception as exc:
        outcome.update(status="stopped", error_type=type(exc).__name__)
        raise
    finally:
        outcome["consumption_marker_present"] = CONSUMPTION.exists()
        atomic_dump_json(OUTPUT / "result.json", outcome)
    print(json.dumps({"status": outcome["status"], "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
