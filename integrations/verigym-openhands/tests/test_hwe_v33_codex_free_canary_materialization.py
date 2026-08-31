from __future__ import annotations

import copy
import importlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.hwe.image_lock import (
    HweAgentImageLock,
    build_hwe_command_image_lock,
)
from verigym.hwe.materialization_preflight import MaterializationHeadroomError

_materialize = importlib.import_module("scripts.materialize_cva6_openhands_v33_codex_free_canary")
_REPOSITORY = Path(__file__).resolve().parents[3]
_AUTHORIZATION = (
    _REPOSITORY
    / "configs/training/qwen35_hwe_openhands_v33_codex_free_canary_materialization_v1.json"
)


def _authorization() -> dict[str, object]:
    return json.loads(_AUTHORIZATION.read_text(encoding="utf-8"))


def _command_lock(task_id: str, index: int):
    legacy = _materialize._LEGACY_INPUTS[task_id]
    return build_hwe_command_image_lock(
        task_id=task_id,
        task_hash=legacy["task_hash"],
        source_hash=legacy["source_hash"],
        verifier_base_image_id=legacy["verifier_image"],
        derived_command_image_id="sha256:" + f"{index + 1:064x}",
        rg_sha256=_materialize._RG_SHA256,
        rg_release_archive_sha256=_materialize._RG_ARCHIVE_SHA256,
        toolchain_profile_id="cva6-verilator-5.008-container-native-v2",
        allowlisted_artifacts=[
            {"path": "/usr/bin/make", "sha256": "a" * 64, "role": "build_tool"},
            {
                "path": "/tools/verilator/bin/verilator_bin",
                "sha256": "b" * 64,
                "role": "simulator",
            },
        ],
        security_scan_id=f"{index + 10:064x}",
    )


def test_v33_authorization_is_hash_bound_and_zero_provider() -> None:
    authorization = _authorization()
    validated = _materialize._validated_authorization(authorization)

    assert validated["authorization_hash"] == _materialize.OPENHANDS_V33_APPROVAL_HASH
    assert validated["legacy_image_locks"] == [
        {"task_id": task_id, **copy.deepcopy(_materialize._LEGACY_INPUTS[task_id])}
        for task_id in _materialize._IMAGE_TASKS
    ]
    assert validated["authorized_actions"] == {
        "consume_sealed_v29_evidence": True,
        "record_sealed_v30_stop": True,
        "record_sealed_v32_stop": True,
        "run_zero_provider_headroom_preflight": True,
        "build_six_command_images": True,
        "scan_six_command_images": True,
        "materialize_successor_canary_contract": True,
        "reuse_v32_command_images": False,
        "rerun_public_qualification": False,
        "invoke_provider": False,
        "execute_canary": False,
        "start_collection": False,
        "start_training": False,
        "load_heldout_tasks": False,
    }
    base = copy.deepcopy(authorization)
    observed = base.pop("authorization_hash")
    assert observed == content_hash(base)


def test_v33_authorization_rejects_provider_or_historical_retry() -> None:
    for section, field, value in (
        ("authorized_actions", "invoke_provider", True),
        ("authorized_actions", "reuse_v32_command_images", True),
        ("authorized_actions", "rerun_public_qualification", True),
        ("required_controls", "historical_tasks_retried", True),
        ("required_controls", "headroom_preflight_before_image_build", False),
        ("command_image_inputs", "codex_present", True),
    ):
        changed = _authorization()
        changed[section][field] = value  # type: ignore[index]
        changed_base = copy.deepcopy(changed)
        changed_base.pop("authorization_hash")
        changed["authorization_hash"] = content_hash(changed_base)
        with pytest.raises(ConfigurationError, match="authorization"):
            _materialize._validated_authorization(changed)


def test_v33_contract_uses_new_identity_and_only_command_images() -> None:
    commands = {
        task_id: _command_lock(task_id, index)
        for index, task_id in enumerate(_materialize._CANARY_TASKS)
    }
    contract = _materialize._canary_contract(
        {"receipt_hash": "c" * 64},
        {
            "campaign_id": "openhands-hwe-v19-required-tool-canary-v1",
            "gate": {
                "all_six_result_planes_required": True,
                "automatic_next_identity_allowed": False,
                "benchmark_or_trajectory_failure_policy": "canary_fail_closed",
                "decision_token_limit": 65536,
                "infrastructure_or_security_failure_policy": "stop_immediately",
                "truncation_allowed": False,
            },
        },
        commands,
    )

    assert contract["campaign_id"] == _materialize.OPENHANDS_V33_CAMPAIGN_ID
    assert contract["agent_version_id"] == _materialize.OPENHANDS_V33_AGENT_VERSION_ID
    assert contract["runtime"]["command_execution_backend"] == "episode_container_exec_v1"
    assert contract["runtime"]["codex_cli_required"] is False
    assert [item["task_id"] for item in contract["schedule"]] == list(_materialize._CANARY_TASKS)
    assert all("command_image" in item for item in contract["task_bindings"].values())
    assert all("agent_image" not in item for item in contract["task_bindings"].values())


def test_v33_catalog_binds_six_distinct_command_images() -> None:
    commands = {
        task_id: _command_lock(task_id, index)
        for index, task_id in enumerate(_materialize._IMAGE_TASKS)
    }
    # The catalog consumes only the predecessor lock hash. Construct that narrow typed input so
    # this credential-free test never imports external experiment evidence.
    legacy = {
        task_id: HweAgentImageLock.model_construct(
            task_id=task_id,
            lock_hash=_materialize._LEGACY_INPUTS[task_id]["lock_hash"],
        )
        for task_id in _materialize._IMAGE_TASKS
    }
    progress = {
        task_id: {
            "lock": f"image-locks/pr-{task_id.rsplit('-', 1)[-1]}.json",
            "lock_file_sha256": f"{index + 20:064x}",
        }
        for index, task_id in enumerate(_materialize._IMAGE_TASKS)
    }
    catalog = _materialize._command_catalog(legacy, commands, progress)

    assert catalog["task_count"] == 6
    assert len({item["command_image"] for item in catalog["tasks"]}) == 6
    assert catalog["codex_present"] is False
    assert catalog["command_execution_backend"] == "episode_container_exec_v1"


def test_v33_materializer_has_no_provider_or_canary_execution_surface() -> None:
    source = Path(_materialize.__file__).read_text(encoding="utf-8")

    assert "OPENHANDS_V19_CANARY_API_KEY_ENV" not in source
    assert "OPENHANDS_V19_CANARY_BASE_URL_ENV" not in source
    assert "_run_episode" not in source
    assert "require_materialization_headroom" in source
    assert "_validate_v32_stop" in source
    assert "build_cva6_hwe_command_image.sh" in source
    assert "scan_and_lock_cva6_hwe_command_image.py" in source


def test_v33_merged_path_gate_rejects_untracked_runner(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    runner = repository / "runner.py"
    runner.write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(_materialize, "_REQUIRED_MERGED_PATHS", ("runner.py",))

    with pytest.raises(subprocess.CalledProcessError):
        _materialize._require_tracked_merged_paths(repository)

    subprocess.run(["git", "add", "runner.py"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=VeriGym Test",
            "-c",
            "user.email=verigym-test@example.invalid",
            "commit",
            "-qm",
            "Track runner",
        ],
        cwd=repository,
        check=True,
    )
    _materialize._require_tracked_merged_paths(repository)


def test_v33_validates_exact_v32_stop_without_importing_failed_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "v32"
    receipts = root / "image-receipts"
    receipts.mkdir(parents=True)
    progress_base = {
        "identity": "openhands-hwe-v32-codex-free-canary-materialization-v1",
        "status": "stopped_security_or_infrastructure_invalid",
        "failure_task_id": _materialize._task(2330),
        "locks": {},
        "provider_calls": 0,
        "model_process_count": 0,
        "heldout_task_ids_loaded": [],
        "canary_executed": False,
        "collection_started": False,
        "training_started": False,
    }
    progress = {**progress_base, "progress_hash": content_hash(progress_base)}
    progress_path = root / "materialization-progress.json"
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    receipt = {
        "format_id": "verigym_hwe_command_image_build_receipt_v1",
        "task_id": _materialize._task(2330),
        "derived_command_image_id": _materialize._V32_FAILED_COMMAND_IMAGE,
        "unsanitized_command_image_id": _materialize._V32_FAILED_UNSANITIZED_IMAGE,
        "codex_present": False,
        "build_network": "none",
    }
    receipt_path = receipts / "pr-2330.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(_materialize, "_V32_PROGRESS_HASH", progress["progress_hash"])
    monkeypatch.setattr(
        _materialize, "_V32_PROGRESS_SHA256", hash_bytes(progress_path.read_bytes())
    )
    monkeypatch.setattr(_materialize, "_V32_RECEIPT_SHA256", hash_bytes(receipt_path.read_bytes()))

    _materialize._validate_v32_stop(root)

    (root / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="inventory"):
        _materialize._validate_v32_stop(root)


def test_v33_failure_diagnostic_imports_only_content_free_v2_fields(tmp_path: Path) -> None:
    root = tmp_path / "output"
    scans = root / "security-scans"
    scans.mkdir(parents=True)
    diagnostic_base = {
        "format_id": "verigym_hwe_command_image_diagnostic_v2",
        "status": "failed",
        "failure_stage": "container_diagnostic_start",
        "error_category": "docker_start_failed",
        "assertion_id": None,
        "exit_code": 125,
        "container_exit_code": 0,
        "temporary_container_removed": True,
        "temporary_workspace_removed": True,
        "raw_output_persisted": False,
        "create_nonempty_output_hashed": False,
        "nonempty_output_hashed": False,
        "cleanup_nonempty_output_hashed": False,
    }
    diagnostic = {**diagnostic_base, "diagnostic_hash": content_hash(diagnostic_base)}
    scan_base = {
        "format_id": "verigym_hwe_command_image_security_scan_v2",
        "scanner_profile_id": "cva6-hwe-command-container-native-offline-v2",
        "task_id": _materialize._task(2330),
        "diagnostic": diagnostic,
        "secrets_detected": False,
        "scan_passed": False,
    }
    scan = {**scan_base, "security_scan_id": content_hash(scan_base)}
    (scans / "pr-2330.json").write_text(json.dumps(scan), encoding="utf-8")

    imported = _materialize._failure_diagnostic(root, _materialize._task(2330))

    assert imported == {
        "status": "validated_content_free_failure",
        "security_scan_id": scan["security_scan_id"],
        "diagnostic_hash": diagnostic["diagnostic_hash"],
        "failure_stage": "container_diagnostic_start",
        "error_category": "docker_start_failed",
        "assertion_id": None,
        "exit_code": 125,
        "container_exit_code": 0,
        "temporary_container_removed": True,
        "temporary_workspace_removed": True,
        "raw_output_persisted": False,
    }


def test_v33_headroom_receipt_binds_each_role_byte_and_inode_minimum() -> None:
    filesystems = [
        {
            **copy.deepcopy(requirement),
            "observed_free_bytes": int(requirement["minimum_free_bytes"]) + 4096,
            "observed_free_inodes": int(requirement["minimum_free_inodes"]) + 1,
            "bytes_satisfied": True,
            "inodes_satisfied": True,
        }
        for requirement in _materialize._HEADROOM_REQUIREMENTS
    ]
    receipt_base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_command_image_materialization_headroom_v1",
        "status": "passed",
        "policy": copy.deepcopy(_materialize._HEADROOM_POLICY),
        "filesystems": filesystems,
        "provider_calls": 0,
        "model_process_count": 0,
        "raw_command_output_persisted": False,
    }
    receipt = {**receipt_base, "preflight_hash": content_hash(receipt_base)}

    assert _materialize._validated_headroom_receipt(receipt) == receipt

    changed = copy.deepcopy(receipt)
    changed["filesystems"][0]["minimum_free_inodes"] = 1  # type: ignore[index]
    changed_base = copy.deepcopy(changed)
    changed_base.pop("preflight_hash")
    changed["preflight_hash"] = content_hash(changed_base)
    with pytest.raises(ConfigurationError, match="headroom observation"):
        _materialize._validated_headroom_receipt(changed)


def test_v33_headroom_rejection_happens_before_any_image_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("v29", "v30", "v32", "scratch", "docker"):
        (tmp_path / name).mkdir()
    authorization = tmp_path / "authorization.json"
    authorization.write_text("{}", encoding="utf-8")
    validation = tmp_path / "validation.json"
    validation.write_text("{}", encoding="utf-8")
    rg_binary = tmp_path / "rg"
    rg_binary.write_bytes(b"rg")
    rg_binary.chmod(0o700)
    rg_archive = tmp_path / "rg.tar.gz"
    rg_archive.write_bytes(b"archive")
    monkeypatch.setenv(_materialize.OPENHANDS_V33_OPT_IN_ENV, "1")
    monkeypatch.setattr(
        _materialize,
        "_validated_authorization",
        lambda _value: {"authorization_hash": "a" * 64},
    )
    monkeypatch.setattr(_materialize, "_merged_source_commit", lambda: "b" * 40)
    monkeypatch.setattr(
        _materialize,
        "_validated_prior_evidence",
        lambda *_args: ({"receipt_hash": "c" * 64}, {"contract_hash": "d" * 64}),
    )
    monkeypatch.setattr(_materialize, "_validate_v32_stop", lambda _root: None)
    monkeypatch.setattr(_materialize, "_validated_legacy_locks", lambda *_args: {})
    monkeypatch.setattr(_materialize, "_RG_SHA256", hash_bytes(rg_binary.read_bytes()))
    monkeypatch.setattr(_materialize, "_RG_ARCHIVE_SHA256", hash_bytes(rg_archive.read_bytes()))
    monkeypatch.setattr(_materialize, "discover_docker_root", lambda: tmp_path / "docker")
    rejection_base = {
        "format_id": "verigym_hwe_command_image_materialization_headroom_v1",
        "status": "rejected_insufficient_headroom",
        "policy": copy.deepcopy(_materialize._HEADROOM_POLICY),
        "provider_calls": 0,
        "model_process_count": 0,
    }
    rejection = {**rejection_base, "preflight_hash": content_hash(rejection_base)}

    def reject_headroom(**_kwargs):
        raise MaterializationHeadroomError(rejection)

    monkeypatch.setattr(_materialize, "require_materialization_headroom", reject_headroom)
    monkeypatch.setattr(
        _materialize,
        "_build_one",
        lambda **_kwargs: pytest.fail("image construction must not start"),
    )
    output = tmp_path / "v33-output"
    arguments = SimpleNamespace(
        authorization=authorization,
        v29_root=tmp_path / "v29",
        v30_root=tmp_path / "v30",
        v32_root=tmp_path / "v32",
        validation_image_lock=validation,
        rg_binary=rg_binary,
        rg_release_archive=rg_archive,
        scratch_root=tmp_path / "scratch",
        output=output,
    )

    with pytest.raises(ConfigurationError, match="headroom"):
        _materialize.materialize(arguments)

    persisted = json.loads((output / "headroom-preflight.json").read_text(encoding="utf-8"))
    progress = json.loads((output / "materialization-progress.json").read_text(encoding="utf-8"))
    assert persisted == rejection
    assert progress["status"] == "stopped_insufficient_headroom"
    assert progress["locks"] == {}
