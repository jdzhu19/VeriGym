from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.image_lock import HweAgentImageLock

from verigym_openhands.hwe_v19_campaign import (
    OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS,
    OPENHANDS_V19_QUALIFICATION_CANDIDATES,
)

_REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY))
sys.path.insert(0, str(_REPOSITORY / "integrations/verigym-hwe-bench/src"))

_qualification = importlib.import_module("scripts.qualify_cva6_openhands_v19_public_tasks")
_images = importlib.import_module("scripts.build_and_lock_cva6_openhands_v19_agent_images")
_prewarm = importlib.import_module("scripts.prewarm_cva6_openhands_v19_images")


def _patch(changed: int) -> str:
    lines = ["--- a/a.sv", "+++ b/a.sv"]
    lines.extend(f"+new_{index}" for index in range(changed))
    return "\n".join(lines)


def _dataset(path: Path) -> Path:
    counts = {2330: 4, 3226: 6, 2844: 7, 3231: 7, 2989: 8, 1482: 14, 3059: 15}
    rows = [
        {
            "org": "openhwgroup",
            "repo": "cva6",
            "number": number,
            "modified_files": ["a.sv", "b.sv"],
            "fix_patch": _patch(counts[number]),
        }
        for number in OPENHANDS_V19_QUALIFICATION_CANDIDATE_NUMBERS
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _report(*, eligible: bool = True) -> dict[str, Any]:
    return {
        "base_infrastructure_error": False,
        "base_failed": eligible,
        "base_resolved": False,
        "reference_passed": True,
        "model_process_count": 0,
        "base_verifier_results": [{"status": "failed"}],
        "verifier_results": [{"status": "passed"}],
    }


def _binding(source: Path, *, expected_task_id: str) -> dict[str, str]:
    suffix = int(expected_task_id.rsplit("-", 1)[-1])
    return {
        "task_hash": f"{suffix:064x}",
        "source_hash": f"{suffix + 1:064x}",
        "source_image_lock_sha256": f"{suffix + 2:064x}",
        "verifier_image": f"sha256:{suffix + 3:064x}",
        "verifier_manifest_digest": f"sha256:{suffix + 4:064x}",
    }


def test_v19_public_qualification_skips_mismatch_and_stops_at_five(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def prepare(**values: Any) -> None:
        calls.append(str(values["selected_tasks"][0]))
        Path(values["output"]).mkdir(parents=True)
        assert values["pull"] is False

    def smoke(*, source: Path, output: Path) -> dict[str, Any]:
        del output
        return _report(eligible=source.name != "pr-3226")

    monkeypatch.setenv(_qualification.OPENHANDS_V19_PUBLIC_QUALIFICATION_OPT_IN_ENV, "1")
    monkeypatch.setattr(_qualification, "prepare_source", prepare)
    monkeypatch.setattr(_qualification, "_source_binding", _binding)
    monkeypatch.setattr(_qualification, "run_zero_model_smoke", smoke)
    output = tmp_path / "qualification"
    progress = _qualification.qualify_v19_public_tasks(
        dataset=_dataset(tmp_path / "cva6.jsonl"),
        output=output,
    )

    assert progress["status"] == "qualified_pending_agent_images"
    assert len(calls) == 6
    assert progress["qualified_task_ids"] == [
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[index] for index in (0, 2, 3, 4, 5)
    ]
    assert progress["training_reserve_task_ids"] == progress["qualified_task_ids"][:3]
    assert progress["validation_reserve_task_ids"] == progress["qualified_task_ids"][3:]
    assert progress["heldout_task_ids_loaded"] == []
    stored = json.loads((output / "qualification-progress.json").read_text(encoding="utf-8"))
    stored_hash = stored["progress_hash"]
    assert stored_hash == content_hash(
        {key: value for key, value in stored.items() if key != "progress_hash"}
    )
    assert _images._validated_qualification_progress(stored)["progress_hash"] == stored_hash


def test_v19_public_qualification_stops_atomically_on_infrastructure_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = 0

    def prepare(**values: Any) -> None:
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("offline image missing")
        Path(values["output"]).mkdir(parents=True)

    monkeypatch.setenv(_qualification.OPENHANDS_V19_PUBLIC_QUALIFICATION_OPT_IN_ENV, "1")
    monkeypatch.setattr(_qualification, "prepare_source", prepare)
    monkeypatch.setattr(_qualification, "_source_binding", _binding)
    monkeypatch.setattr(_qualification, "run_zero_model_smoke", lambda **_values: _report())
    output = tmp_path / "qualification"

    with pytest.raises(ConfigurationError, match="infrastructure-invalid"):
        _qualification.qualify_v19_public_tasks(
            dataset=_dataset(tmp_path / "cva6.jsonl"),
            output=output,
        )

    progress = json.loads((output / "qualification-progress.json").read_text(encoding="utf-8"))
    assert progress["status"] == "stopped_infrastructure_invalid"
    assert len(progress["outcomes"]) == 2
    assert progress["outcomes"][-1]["infrastructure_valid"] is False
    assert count == 2


def _v1_template() -> HweAgentImageLock:
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_agent_image_lock_v1",
        "task_id": OPENHANDS_V19_QUALIFICATION_CANDIDATES[0],
        "task_hash": "1" * 64,
        "source_hash": "2" * 64,
        "verifier_base_image_id": "sha256:" + "3" * 64,
        "derived_agent_image_id": "sha256:" + "4" * 64,
        "codex_version": "codex-cli 0.147.0",
        "host_codex_sha256": "5" * 64,
        "agent_codex_sha256": _images._EXPECTED_AGENT_CODEX_SHA256,
        "agent_rg_sha256": _images._EXPECTED_AGENT_RG_SHA256,
        "collection_profile_id": "hwe_standard_v1",
        "tool_contract_id": "hwe_native_shell_v1",
        "toolchain_profile_id": "cva6-verilator-5.008-native-shell-v1",
        "allowlisted_artifacts": [
            {"path": "/usr/bin/make", "sha256": "6" * 64, "role": "build_tool"},
            {
                "path": "/tools/verilator/bin/verilator_bin",
                "sha256": "7" * 64,
                "role": "simulator",
            },
        ],
        "source_whiteout_path": "/home/cva6",
        "visible_workspace_path": "/workspace/repository",
        "build_network": "none",
        "runtime_network": "none",
        "provider_credentials_present": False,
        "hidden_assets_present": False,
        "verifier_payload_present": False,
        "reference_patch_present": False,
        "security_scan_id": "8" * 64,
        "security_scan_passed": True,
    }
    return HweAgentImageLock.model_validate({**base, "lock_hash": content_hash(base)})


def test_v19_agent_image_identity_rebinds_only_task_specific_fields() -> None:
    template = _v1_template()
    task_id = OPENHANDS_V19_QUALIFICATION_CANDIDATES[1]
    binding = {
        "task_id": task_id,
        "task_hash": "9" * 64,
        "source_hash": "a" * 64,
        "verifier_image": "sha256:" + "b" * 64,
    }
    identity = _images._legacy_identity(
        template=template,
        binding=binding,
        receipt={
            "task_id": task_id,
            "derived_agent_image_id": "sha256:" + "c" * 64,
        },
    )

    assert identity.task_id == task_id
    assert identity.task_hash == binding["task_hash"]
    assert identity.source_hash == binding["source_hash"]
    assert identity.verifier_base_image_id == binding["verifier_image"]
    assert identity.agent_codex_sha256 == template.agent_codex_sha256
    assert identity.allowlisted_artifacts == template.allowlisted_artifacts


def test_v19_prewarm_uses_frozen_local_identities_when_already_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_prewarm.OPENHANDS_V19_PREWARM_OPT_IN_ENV, "1")
    monkeypatch.setattr(_prewarm, "_validate_downloader_image", lambda _image: None)
    monkeypatch.setattr(_prewarm, "_validate_network", lambda: None)
    monkeypatch.setattr(
        _prewarm,
        "_inspect_host_image",
        lambda _reference: {
            "image_id": "sha256:" + "d" * 64,
            "manifest_digest": "sha256:" + "e" * 64,
        },
    )

    progress = _prewarm.prewarm_v19_images(
        output=tmp_path / "prewarm",
        downloader_image=_prewarm.OPENHANDS_V19_DOWNLOADER_IMAGE,
    )

    assert progress["status"] == "completed"
    assert progress["download_network"] == "verigym-hwe-net"
    assert progress["default_bridge_used"] is False
    assert len(progress["images"]) == 7
    assert os.environ[_prewarm.OPENHANDS_V19_PREWARM_OPT_IN_ENV] == "1"


def test_v19_prewarm_rejects_tcp_daemon_and_seals_interrupted_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        _prewarm,
        "_docker_json",
        lambda _arguments: [
            {
                "Path": "dockerd-entrypoint.sh",
                "Args": ["--host=tcp://0.0.0.0:2375"],
                "HostConfig": {"NetworkMode": "verigym-hwe-net"},
            }
        ],
    )
    with pytest.raises(ConfigurationError, match="effective controls changed"):
        _prewarm._validate_nested_daemon("downloader")

    root = tmp_path / "prewarm"
    root.mkdir()
    base = {
        "schema_version": "1.0",
        "format_id": _prewarm.OPENHANDS_V19_PREWARM_FORMAT,
        "status": "running",
        "downloader_image": _prewarm.OPENHANDS_V19_DOWNLOADER_IMAGE,
        "download_network": _prewarm.OPENHANDS_V19_PREWARM_NETWORK,
        "default_bridge_used": False,
        "proxy_values_recorded": False,
        "images": {},
        "references": list(_prewarm.OPENHANDS_V19_PREWARM_REFERENCES),
    }
    (root / "prewarm-progress.json").write_text(
        json.dumps({**base, "progress_hash": content_hash(base)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        _prewarm.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(_prewarm, "_inspect_host_image", lambda _reference: None)
    sealed = _prewarm.seal_v19_prewarm_security_failure(
        output=root,
        reason="downloader_tcp_api_exposed",
    )

    assert sealed["status"] == "stopped_security_invalid"
    assert sealed["host_images_imported"] == 0
    assert sealed["qualification_started"] is False
    assert sealed["provider_calls"] == 0


def test_v19_stopped_qualification_audit_is_hash_bound_and_authorizes_no_next_stage() -> None:
    path = _REPOSITORY / "configs/training/qwen35_hwe_openhands_v19_public_qualification_v1.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    expected_hash = audit.pop("audit_hash")

    assert expected_hash == content_hash(audit)
    assert audit["status"] == "stopped_security_invalid"
    assert audit["host_images_imported"] == 0
    assert audit["qualified_task_count"] == 0
    assert audit["training_reserve_task_ids"] == []
    assert audit["validation_reserve_task_ids"] == []
    assert audit["heldout_task_ids_loaded"] == []
    assert audit["canary_contract_materialized"] is False
    assert audit["provider_canary_started"] is False
    assert audit["production_training_ready"] is False
    assert audit["benchmark_score_claimed"] is False
