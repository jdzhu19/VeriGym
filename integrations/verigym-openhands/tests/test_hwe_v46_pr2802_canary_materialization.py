from __future__ import annotations

import copy
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.hwe.image_lock import HweCommandImageLock, build_hwe_command_image_lock

_materialize = importlib.import_module("scripts.materialize_cva6_openhands_v46_pr2802_canary")
_REPOSITORY = Path(__file__).resolve().parents[3]
_AUTHORIZATION = (
    _REPOSITORY / "configs/training/qwen35_hwe_openhands_v46_pr2802_canary_materialization_v1.json"
)


def _authorization() -> dict[str, object]:
    return json.loads(_AUTHORIZATION.read_text(encoding="utf-8"))


def _command_lock(task_id: str, index: int):
    expected = (
        _materialize._TRAINING_LEGACY
        if task_id == _materialize._TRAINING_TASK
        else _materialize._VALIDATION_COMMAND
    )
    if task_id == _materialize._VALIDATION_TASK:
        return HweCommandImageLock.model_construct(
            task_id=task_id,
            task_hash=expected["task_hash"],
            source_hash=expected["source_hash"],
            verifier_base_image_id=expected["verifier_image"],
            derived_command_image_id=expected["command_image"],
            lock_hash=expected["lock_hash"],
            security_scan_id=expected["security_scan_id"],
        )
    return build_hwe_command_image_lock(
        task_id=task_id,
        task_hash=expected["task_hash"],
        source_hash=expected["source_hash"],
        verifier_base_image_id=expected["verifier_image"],
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


def test_v46_authorization_is_exact_hash_bound_and_zero_provider() -> None:
    authorization = _authorization()
    validated = _materialize._validated_authorization(authorization)

    assert validated["authorization_hash"] == _materialize.OPENHANDS_V46_APPROVAL_HASH
    assert validated["authorized_actions"] == {
        "consume_sealed_v33_validation_binding": True,
        "consume_sealed_v43_failure_evidence": True,
        "consume_sealed_v44_stop_evidence": True,
        "consume_sealed_v45_failure_evidence": True,
        "consume_legacy_pr2802_qualification": True,
        "run_zero_provider_headroom_preflight": True,
        "build_pr2802_command_image": True,
        "scan_pr2802_command_image": True,
        "materialize_v22_canary_contract": True,
        "invoke_provider": False,
        "execute_canary": False,
        "start_formal_collection": False,
        "start_training": False,
        "load_heldout_tasks": False,
    }
    base = copy.deepcopy(authorization)
    observed = base.pop("authorization_hash")
    assert observed == content_hash(base)
    assert validated["launcher_isolation"] == {
        "absolute_host_paths_persisted": False,
        "ambient_interpreter_allowed": False,
        "competing_editable_path_regression_required": True,
        "include_system_site_packages": False,
        "pyvenv_config_sha256": _materialize._REPOSITORY_VENV_CONFIG_SHA256,
        "python_version": "3.12.13",
        "python_executable_matches_authorized": True,
        "python_prefix_matches_authorized": True,
        "repository_src_precedes_site_packages": True,
        "runtime_location_policy": "repository_local_isolated_venv",
        "verigym_package_root_matches_authorized": True,
    }
    serialized = json.dumps(validated, sort_keys=True)
    assert str(_materialize._AUTHORIZED_REPOSITORY) not in serialized
    assert str(_materialize._AUTHORIZED_REPOSITORY_VENV) not in serialized
    assert str(_materialize._AUTHORIZED_REPOSITORY_PYTHON) not in serialized


def test_v46_authorization_rejects_provider_role_or_retry_drift() -> None:
    for section, field, value in (
        ("authorized_actions", "invoke_provider", True),
        ("authorized_actions", "execute_canary", True),
        ("required_controls", "historical_tasks_retried", True),
        ("required_controls", "validation_reserve_roles_changed", True),
        ("command_image_inputs", "image_count", 2),
    ):
        changed = _authorization()
        changed[section][field] = value  # type: ignore[index]
        base = copy.deepcopy(changed)
        base.pop("authorization_hash")
        changed["authorization_hash"] = content_hash(base)
        with pytest.raises(ConfigurationError, match="authorization"):
            _materialize._validated_authorization(changed)


def test_v46_authorization_is_independent_of_the_ci_checkout_path(
    tmp_path: Path, monkeypatch
) -> None:
    expected = _materialize._expected_authorization()

    monkeypatch.setattr(_materialize, "_REPOSITORY", tmp_path / "ci-checkout")

    assert _materialize._expected_authorization() == expected
    serialized = json.dumps(expected, sort_keys=True)
    assert str(_materialize._AUTHORIZED_REPOSITORY) not in serialized
    assert expected["launcher_isolation"]["runtime_location_policy"] == (
        "repository_local_isolated_venv"
    )


def test_v46_runtime_receipt_is_export_safe_and_passes_context_scan(
    tmp_path: Path, monkeypatch
) -> None:
    runtime_prefix = tmp_path / "isolated-runtime"
    runtime_prefix.mkdir()
    runtime_python = Path(sys.executable)
    config = runtime_prefix / "pyvenv.cfg"
    config.write_text("include-system-site-packages = false\n", encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(runtime_prefix))
    monkeypatch.setattr(_materialize, "_AUTHORIZED_REPOSITORY", _REPOSITORY)
    monkeypatch.setattr(_materialize, "_AUTHORIZED_REPOSITORY_VENV", runtime_prefix)
    monkeypatch.setattr(_materialize, "_AUTHORIZED_REPOSITORY_PYTHON", runtime_python)
    monkeypatch.setattr(_materialize, "_REPOSITORY_VENV", runtime_prefix)
    monkeypatch.setattr(_materialize, "_REPOSITORY_PYTHON", runtime_python)
    monkeypatch.setattr(_materialize, "_REPOSITORY_PYTHON_VERSION", sys.version_info[:3])
    monkeypatch.setattr(
        sys,
        "path",
        [
            str(_materialize._REPOSITORY_SRC),
            *(entry for entry in sys.path if entry != str(_materialize._REPOSITORY_SRC)),
        ],
    )
    monkeypatch.setattr(
        _materialize,
        "_REPOSITORY_VENV_CONFIG_SHA256",
        hash_bytes(config.read_bytes()),
    )

    runtime = _materialize._require_repository_runtime()

    assert runtime == {
        "absolute_host_paths_persisted": False,
        "include_system_site_packages": False,
        "pyvenv_config_sha256": hash_bytes(config.read_bytes()),
        "python_executable_matches_authorized": True,
        "python_prefix_matches_authorized": True,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "repository_src_first": True,
        "verigym_package_root_matches_authorized": True,
    }
    progress = {"format_id": _materialize.OPENHANDS_V46_PROGRESS_FORMAT, "runtime": runtime}
    artifact = tmp_path / "materialization-progress.json"
    artifact.write_text(json.dumps(progress, sort_keys=True), encoding="utf-8")
    forbidden = (
        str(_REPOSITORY),
        str(runtime_prefix),
        str(runtime_python),
        str(_materialize._VERIGYM_PACKAGE_ROOT),
    )
    serialized = artifact.read_text(encoding="utf-8")
    assert all(value not in serialized for value in forbidden)
    report = scan_artifact_roots(
        [tmp_path],
        report_id="openhands-v46-runtime-receipt-regression",
        forbidden_host_roots=forbidden,
    )
    require_security_scan_pass(report)
    assert report.gate == "pass"


def test_v46_contract_uses_v22_and_never_reexecutes_successful_training_canary() -> None:
    training = _command_lock(_materialize._TRAINING_TASK, 0)
    validation = _command_lock(_materialize._VALIDATION_TASK, 1)

    contract = _materialize._canary_contract(training, validation)

    assert contract["protocol_profile"] == "required_tool_atomic_shape_recovery_v22"
    assert [item["task_id"] for item in contract["schedule"]] == list(_materialize._CANARY_TASKS)
    assert [item["role"] for item in contract["schedule"]] == ["training", "validation"]
    assert {item["seed"] for item in contract["schedule"]} == {496}
    assert {item["sample_index"] for item in contract["schedule"]} == {12}
    assert contract["campaign_id"] == "openhands-hwe-v47-v22-required-tool-canary-v1"
    assert contract["training_task_disposition_after_success"] == (
        "import_canary_without_formal_reexecution"
    )
    assert contract["provider_calls_during_materialization"] == 0
    assert contract["formal_collection_allowed"] is False
    assert contract["formal_collection_started"] is False
    assert contract["training_started"] is False

    changed = copy.deepcopy(contract)
    changed["protocol_profile"] = "required_tool_atomic_shape_recovery_v21"
    base = copy.deepcopy(changed)
    base.pop("contract_hash")
    changed["contract_hash"] = content_hash(base)
    with pytest.raises(ConfigurationError, match="contract policy"):
        _materialize.validate_v46_canary_contract(changed)


def test_v46_catalog_builds_one_training_image_and_reuses_only_v33_validation() -> None:
    training = _command_lock(_materialize._TRAINING_TASK, 0)
    validation = _command_lock(_materialize._VALIDATION_TASK, 1)
    progress = {
        "lock": "image-locks/pr-2802.json",
        "lock_file_sha256": "c" * 64,
    }

    catalog = _materialize._command_catalog(training, validation, progress)

    assert catalog["task_count"] == 2
    assert [item["role"] for item in catalog["tasks"]] == [
        "training_canary_replacement",
        "canary_validation",
    ]
    assert [item["source"] for item in catalog["tasks"]] == [
        "v46_materialized",
        "sealed_v33_reuse",
    ]
    assert catalog["tasks"][1]["command_image_lock"] == "v33:image-locks/pr-3204.json"
    assert catalog["codex_present"] is False
    assert catalog["provider_credentials_present"] is False
    assert catalog["provider_calls"] == 0

    duplicate = training.model_copy(
        update={"derived_command_image_id": validation.derived_command_image_id}
    )
    with pytest.raises(ConfigurationError, match="not task-distinct"):
        _materialize._command_catalog(duplicate, validation, progress)


def test_v46_failure_diagnostic_persists_only_allowlisted_content_free_fields(
    tmp_path: Path,
) -> None:
    scans = tmp_path / "security-scans"
    scans.mkdir()
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
        "task_id": _materialize._TRAINING_TASK,
        "diagnostic": diagnostic,
        "secrets_detected": False,
        "scan_passed": False,
    }
    scan = {**scan_base, "security_scan_id": content_hash(scan_base)}
    path = scans / "pr-2802.json"
    path.write_text(json.dumps(scan), encoding="utf-8")

    imported = _materialize._failure_diagnostic(tmp_path)

    assert imported is not None
    assert imported["status"] == "validated_content_free_failure"
    assert imported["error_category"] == "docker_start_failed"
    assert imported["raw_output_persisted"] is False

    diagnostic_base["error_category"] = "raw daemon message"
    changed_diagnostic = {
        **diagnostic_base,
        "diagnostic_hash": content_hash(diagnostic_base),
    }
    changed_scan_base = {**scan_base, "diagnostic": changed_diagnostic}
    changed_scan = {
        **changed_scan_base,
        "security_scan_id": content_hash(changed_scan_base),
    }
    path.write_text(json.dumps(changed_scan), encoding="utf-8")
    assert _materialize._failure_diagnostic(tmp_path) == {"status": "invalid_diagnostic_receipt"}


def test_v46_materializer_has_no_provider_canary_or_collection_surface() -> None:
    source = Path(_materialize.__file__).read_text(encoding="utf-8")

    assert "OPENHANDS_V19_CANARY_API_KEY_ENV" not in source
    assert "OPENHANDS_V19_CANARY_BASE_URL_ENV" not in source
    assert "DEEPSEEK_API_KEY" not in source
    assert "_run_episode" not in source
    assert "require_materialization_headroom" in source
    assert "build_cva6_hwe_command_image.sh" in source
    assert "scan_and_lock_cva6_hwe_command_image.py" in source
    assert source.count("_build_one(") == 2


def test_v46_bootstrap_precedes_a_competing_stale_editable_path(tmp_path: Path) -> None:
    stale_root = tmp_path / "stale-src"
    stale_package = stale_root / "verigym"
    stale_package.mkdir(parents=True)
    (stale_package / "__init__.py").write_text("STALE = True\n", encoding="utf-8")
    runner = _REPOSITORY / "scripts/materialize_cva6_openhands_v46_pr2802_canary.py"
    command = (
        "import runpy; "
        f"state = runpy.run_path({str(runner)!r}); "
        "print(state['_VERIGYM_PACKAGE_ROOT'])"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(stale_root)

    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=_REPOSITORY,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == str((_REPOSITORY / "src/verigym").resolve())


def test_v46_bootstrap_rejects_an_already_loaded_foreign_verigym(tmp_path: Path) -> None:
    stale_root = tmp_path / "stale-src"
    stale_package = stale_root / "verigym"
    stale_package.mkdir(parents=True)
    (stale_package / "__init__.py").write_text("STALE = True\n", encoding="utf-8")
    runner = _REPOSITORY / "scripts/materialize_cva6_openhands_v46_pr2802_canary.py"
    command = (
        "import runpy, sys; "
        f"sys.path.insert(0, {str(stale_root)!r}); "
        "import verigym; "
        f"runpy.run_path({str(runner)!r})"
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "refuses a preloaded verigym from another source tree" in result.stderr


def test_v46_merged_path_gate_rejects_untracked_runner(tmp_path: Path, monkeypatch) -> None:
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


def test_v46_merged_path_gate_binds_the_pr2802_authorization_identity() -> None:
    expected = {
        "configs/training/qwen35_hwe_openhands_v46_pr2802_canary_materialization_v1.json",
        "docs/audits/2026-09-01_openhands-v44-pr2802-materialization-stopped-before-output.md",
        "docs/audits/2026-09-01_openhands-v45-pr2802-materialization-security-invalid.md",
        "docs/audits/2026-09-01_openhands-v46-pr2802-canary-materialization-redaction-repair-authorization.md",
        "scripts/materialize_cva6_openhands_v46_pr2802_canary.py",
    }

    required = set(_materialize._REQUIRED_MERGED_PATHS)
    assert expected <= required
    assert not any("v46_fresh_training_canary" in path for path in required)
    assert all((_REPOSITORY / path).is_file() for path in expected)


@pytest.mark.skipif(
    "VERIGYM_V43_FAILED_EVIDENCE_ROOT" not in os.environ,
    reason="requires the sealed local v43 failed canary",
)
def test_v46_accepts_only_the_exact_sealed_v43_failure() -> None:
    root = Path(os.environ["VERIGYM_V43_FAILED_EVIDENCE_ROOT"])

    _materialize._validate_v43_failure(root)


@pytest.mark.skipif(
    "VERIGYM_V44_STOP_EVIDENCE_ROOT" not in os.environ,
    reason="requires the sealed local v44 pre-output stop",
)
def test_v46_accepts_only_the_exact_sealed_v44_stop() -> None:
    root = Path(os.environ["VERIGYM_V44_STOP_EVIDENCE_ROOT"])

    _materialize._validate_v44_stop(root)


@pytest.mark.skipif(
    "VERIGYM_V45_FAILED_EVIDENCE_ROOT" not in os.environ,
    reason="requires the sealed local v45 security-invalid materialization",
)
def test_v46_accepts_only_the_exact_sealed_v45_failure() -> None:
    root = Path(os.environ["VERIGYM_V45_FAILED_EVIDENCE_ROOT"])

    _materialize._validate_v45_failure(root)


@pytest.mark.skipif(
    "VERIGYM_PR2802_LEGACY_IMAGE_LOCK" not in os.environ,
    reason="requires the sealed local PR-2802 legacy image lock",
)
def test_v46_accepts_the_exact_pr2802_legacy_binding() -> None:
    path = Path(os.environ["VERIGYM_PR2802_LEGACY_IMAGE_LOCK"])

    lock = _materialize._validated_training_legacy(path)

    assert lock.task_id == _materialize._TRAINING_TASK
    assert lock.task_hash == _materialize._TRAINING_LEGACY["task_hash"]
    assert lock.source_hash == _materialize._TRAINING_LEGACY["source_hash"]
    assert lock.lock_hash == _materialize._TRAINING_LEGACY["lock_hash"]
