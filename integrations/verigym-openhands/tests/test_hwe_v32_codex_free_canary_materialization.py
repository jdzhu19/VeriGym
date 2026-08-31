from __future__ import annotations

import copy
import importlib
import json
import subprocess
from pathlib import Path

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.image_lock import (
    HweAgentImageLock,
    build_hwe_command_image_lock,
)

_materialize = importlib.import_module("scripts.materialize_cva6_openhands_v32_codex_free_canary")
_REPOSITORY = Path(__file__).resolve().parents[3]
_AUTHORIZATION = (
    _REPOSITORY
    / "configs/training/qwen35_hwe_openhands_v32_codex_free_canary_materialization_v1.json"
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


def test_v32_authorization_is_hash_bound_and_zero_provider() -> None:
    authorization = _authorization()
    validated = _materialize._validated_authorization(authorization)

    assert validated["authorization_hash"] == _materialize.OPENHANDS_V32_APPROVAL_HASH
    assert validated["legacy_image_locks"] == [
        {"task_id": task_id, **copy.deepcopy(_materialize._LEGACY_INPUTS[task_id])}
        for task_id in _materialize._IMAGE_TASKS
    ]
    assert validated["authorized_actions"] == {
        "consume_sealed_v29_evidence": True,
        "record_sealed_v30_stop": True,
        "build_six_command_images": True,
        "scan_six_command_images": True,
        "materialize_successor_canary_contract": True,
        "invoke_provider": False,
        "execute_canary": False,
        "start_collection": False,
        "start_training": False,
        "load_heldout_tasks": False,
    }
    base = copy.deepcopy(authorization)
    observed = base.pop("authorization_hash")
    assert observed == content_hash(base)


def test_v32_authorization_rejects_provider_or_historical_retry() -> None:
    for section, field, value in (
        ("authorized_actions", "invoke_provider", True),
        ("required_controls", "historical_tasks_retried", True),
        ("command_image_inputs", "codex_present", True),
    ):
        changed = _authorization()
        changed[section][field] = value  # type: ignore[index]
        changed_base = copy.deepcopy(changed)
        changed_base.pop("authorization_hash")
        changed["authorization_hash"] = content_hash(changed_base)
        with pytest.raises(ConfigurationError, match="authorization"):
            _materialize._validated_authorization(changed)


def test_v32_contract_uses_new_identity_and_only_command_images() -> None:
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

    assert contract["campaign_id"] == _materialize.OPENHANDS_V32_CAMPAIGN_ID
    assert contract["agent_version_id"] == _materialize.OPENHANDS_V32_AGENT_VERSION_ID
    assert contract["runtime"]["command_execution_backend"] == "episode_container_exec_v1"
    assert contract["runtime"]["codex_cli_required"] is False
    assert [item["task_id"] for item in contract["schedule"]] == list(_materialize._CANARY_TASKS)
    assert all("command_image" in item for item in contract["task_bindings"].values())
    assert all("agent_image" not in item for item in contract["task_bindings"].values())


def test_v32_catalog_binds_six_distinct_command_images() -> None:
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


def test_v32_materializer_has_no_provider_or_canary_execution_surface() -> None:
    source = Path(_materialize.__file__).read_text(encoding="utf-8")

    assert "OPENHANDS_V19_CANARY_API_KEY_ENV" not in source
    assert "OPENHANDS_V19_CANARY_BASE_URL_ENV" not in source
    assert "_run_episode" not in source
    assert "build_cva6_hwe_command_image.sh" in source
    assert "scan_and_lock_cva6_hwe_command_image.py" in source


def test_v32_merged_path_gate_rejects_untracked_runner(tmp_path: Path, monkeypatch) -> None:
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
