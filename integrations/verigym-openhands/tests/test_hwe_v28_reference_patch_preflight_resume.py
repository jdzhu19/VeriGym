from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym_hwe_bench.models import HweInstance

from verigym_openhands.hwe_v19_campaign import OPENHANDS_V19_QUALIFICATION_CANDIDATES

_REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY))
sys.path.insert(0, str(_REPOSITORY / "integrations/verigym-hwe-bench/src"))

_qualification = importlib.import_module(
    "scripts.qualify_cva6_openhands_v28_reference_patch_preflight_resume"
)


def _approved() -> dict[str, Any]:
    path = (
        _REPOSITORY
        / "configs/training/qwen35_hwe_openhands_v28_reference_patch_preflight_resume_v1.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _transfer(index: int) -> dict[str, Any]:
    return {
        "image_id": f"sha256:{index + 1:064x}",
        "manifest_digest": f"sha256:{index + 11:064x}",
        "transfer_receipt_hash": f"{index + 21:064x}",
    }


def _binding(index: int, transfer: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_hash": f"{index + 31:064x}",
        "source_hash": f"{index + 41:064x}",
        "source_image_lock_sha256": f"{index + 51:064x}",
        "verifier_image": transfer["image_id"],
        "verifier_manifest_digest": transfer["manifest_digest"],
        "source": f"sources/index-{index}",
        "smoke": f"smokes/index-{index}",
        "transfer_receipt_hash": transfer["transfer_receipt_hash"],
    }


def _predecessor() -> dict[str, Any]:
    inherited = {
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[index]: _transfer(index) for index in (0, 1)
    }
    transfers = {
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[index]: _transfer(index) for index in (3, 4, 5)
    }
    bindings: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    for index, task_id in enumerate(OPENHANDS_V19_QUALIFICATION_CANDIDATES[:5]):
        if index == 2:
            outcomes.append(
                {
                    "task_id": task_id,
                    "status": "predecessor_transfer_failed",
                    "predecessor_terminal_evidence": True,
                    "infrastructure_valid": False,
                    "base_failed": False,
                    "reference_passed": False,
                }
            )
            continue
        transfer = inherited[task_id] if index < 2 else transfers[task_id]
        bindings[task_id] = _binding(index, transfer)
        outcomes.append(
            {
                "task_id": task_id,
                "status": "qualified",
                "infrastructure_valid": True,
                "base_failed": True,
                "reference_passed": True,
            }
        )
    failure = {
        "failure_stage": "zero_model_qualification",
        "failure_type": "ConfigurationError",
    }
    assert content_hash(failure) == _qualification._PREDECESSOR_FAILURE_HASH
    return {
        "format_id": _qualification._v27.OPENHANDS_V27_PROGRESS_FORMAT,
        "identity": _qualification._v27.OPENHANDS_V27_IDENTITY,
        "authorization_hash": _qualification._v27.OPENHANDS_V27_APPROVAL_HASH,
        "status": "stopped_infrastructure_invalid",
        "progress_hash": _qualification._PREDECESSOR_PROGRESS_HASH,
        "active_task_id": OPENHANDS_V19_QUALIFICATION_CANDIDATES[5],
        "active_pull_receipt": None,
        "provider_calls": 0,
        "heldout_task_ids_loaded": [],
        "model_process_count": 0,
        "historical_attempts_retried": False,
        "host_candidate_images_present": 5,
        "temporary_transfer_scratch_removed": True,
        "temporary_containers_removed": True,
        "outcomes": outcomes,
        "qualified_bindings": bindings,
        "predecessor_image_transfers": inherited,
        "image_transfers": transfers,
        "failure_diagnostic": failure,
    }


def _report(*, eligible: bool) -> dict[str, Any]:
    return {
        "base_infrastructure_error": False,
        "base_failed": eligible,
        "base_resolved": False,
        "reference_passed": True,
        "model_process_count": 0,
        "base_verifier_results": [{"status": "failed"}],
        "verifier_results": [{"status": "passed"}],
    }


def _patch_instance(*, number: int, patch: str, files: list[str]) -> HweInstance:
    return HweInstance(
        org="openhwgroup",
        repo="cva6",
        number=number,
        title="fixture",
        problem_statement="fixture",
        base_commit="1" * 40,
        fix_patch=patch,
        tb_script="echo test\n",
        modified_files=files,
        expected_test_ids=["test"],
        language="SystemVerilog",
        license_id="SHL-0.51",
    )


def _edit_patch(path: str) -> str:
    return f"""diff --git a/{path} b/{path}
index 7898192..422c2b7 100644
--- a/{path}
+++ b/{path}
@@ -1 +1 @@
-a
+b
"""


def _add_patch(path: str) -> str:
    return f"""diff --git a/{path} b/{path}
new file mode 100644
index 0000000..6178079
--- /dev/null
+++ b/{path}
@@ -0,0 +1 @@
+new
"""


def test_v28_authorization_is_hash_bound_and_forbids_historical_retry() -> None:
    approved = _approved()
    validated = _qualification._validated_authorization(copy.deepcopy(approved))
    base = copy.deepcopy(approved)
    expected_hash = base.pop("authorization_hash")

    assert validated == approved
    assert expected_hash == _qualification.OPENHANDS_V28_APPROVAL_HASH
    assert content_hash(base) == expected_hash
    assert base["predecessor"]["attempted_task_ids"] == list(
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[:6]
    )
    assert base["continuation_candidate_numbers"] == [3059]
    assert base["required_controls"]["reference_patch_preflight_before_image_access"] is True
    assert base["required_controls"]["historical_attempts_retried"] is False
    assert base["authorized_actions"]["invoke_provider"] is False
    assert base["authorized_actions"]["load_heldout_tasks"] is False


def test_v28_predecessor_import_rejects_binding_drift() -> None:
    predecessor = _qualification._validated_predecessor_value(_predecessor())
    expected = {OPENHANDS_V19_QUALIFICATION_CANDIDATES[index] for index in (0, 1, 3, 4)}
    assert set(predecessor["qualified_bindings"]) == expected

    changed = _predecessor()
    task_id = OPENHANDS_V19_QUALIFICATION_CANDIDATES[3]
    changed["qualified_bindings"][task_id]["verifier_image"] = "sha256:" + "f" * 64
    with pytest.raises(ConfigurationError, match="binding changed"):
        _qualification._validated_predecessor_value(changed)


def test_v28_patch_preflight_receipts_are_content_free_and_hash_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pr1482 = _patch_instance(
        number=1482,
        patch=_edit_patch("rtl/a.sv") + _add_patch("rtl/new.sv"),
        files=["rtl/a.sv", "rtl/new.sv"],
    )
    pr3059 = _patch_instance(
        number=3059,
        patch=_edit_patch("rtl/a.sv") + _edit_patch("rtl/b.sv"),
        files=["rtl/a.sv", "rtl/b.sv"],
    )
    monkeypatch.setattr(
        _qualification,
        "_official_instances",
        lambda _dataset, _selected: [pr1482, pr3059],
    )
    receipts = _qualification._validated_patch_compatibility(
        tmp_path / "dataset.jsonl", _approved()["reference_patch_compatibility"]
    )

    assert len(receipts) == 2
    assert receipts[OPENHANDS_V19_QUALIFICATION_CANDIDATES[5]]["created_file_count"] == 1
    assert receipts[OPENHANDS_V19_QUALIFICATION_CANDIDATES[6]]["created_file_count"] == 0
    assert all(item["compatible"] is True for item in receipts.values())
    assert all(item["raw_output_persisted"] is False for item in receipts.values())
    assert all(item["network_accessed"] is False for item in receipts.values())
    assert all(item["docker_accessed"] is False for item in receipts.values())


def _install_resume_fakes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    eligible: bool,
) -> tuple[list[str], list[str]]:
    approved = _approved()
    v26_approved = json.loads(
        (
            _REPOSITORY / "configs/training/qwen35_hwe_openhands_v26_streamed_qualification_v1.json"
        ).read_text(encoding="utf-8")
    )
    inventory = copy.deepcopy(v26_approved["candidate_inventory"])
    calls: list[str] = []
    events: list[str] = []
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv(_qualification.OPENHANDS_V28_OPT_IN_ENV, "1")
    monkeypatch.setattr(
        _qualification._v26,
        "_load_json",
        lambda path: (
            v26_approved if Path(path).name.startswith("qwen35_hwe_openhands_v26") else approved
        ),
    )
    monkeypatch.setattr(_qualification._v26, "_validated_authorization", lambda value: value)
    monkeypatch.setattr(_qualification._v26, "_validated_dataset", lambda path, approved: path)
    monkeypatch.setattr(_qualification, "frozen_v19_candidate_inventory", lambda _path: inventory)
    monkeypatch.setattr(
        _qualification,
        "_validated_patch_compatibility",
        lambda _path, _binding: events.append("preflight") or {"fixture": {}},
    )
    monkeypatch.setattr(
        _qualification,
        "_validated_predecessor",
        lambda _path, _binding: events.append("predecessor") or _predecessor(),
    )
    monkeypatch.setattr(
        _qualification,
        "_validate_predecessor_images",
        lambda _value: events.append("images"),
    )
    monkeypatch.setattr(_qualification._v26, "_validate_network", lambda: events.append("network"))
    monkeypatch.setattr(_qualification._v26, "_validate_local_image", lambda binding: binding)
    monkeypatch.setattr(_qualification._v26, "_validated_tool_cache", lambda _binding: tmp_path)
    monkeypatch.setattr(_qualification._v26, "_inspect_host_image", lambda _reference: None)

    def new_directory(path: Path) -> Path:
        path.mkdir()
        return path

    monkeypatch.setattr(_qualification._v26, "_new_directory", new_directory)
    monkeypatch.setattr(_qualification, "_new_scratch_directory", lambda: scratch)
    monkeypatch.setattr(_qualification, "_cleanup_scratch", lambda _path: None)
    monkeypatch.setattr(_qualification, "_count_host_candidate_images", lambda: 6)
    monkeypatch.setattr(_qualification, "_count_temporary_containers", lambda: 0)

    monkeypatch.setattr(
        _qualification,
        "_run_controlled_container",
        lambda **_values: (
            b"",
            {"control_hash": "1" * 64},
            {"stderr_bytes": 0, "temporary_container_removed": True},
        ),
    )

    def transfer(*, reference: str, **_values: Any) -> dict[str, Any]:
        calls.append(reference)
        number = int(reference.rsplit("-", 1)[-1])
        base = {
            "reference": reference,
            "manifest_digest": f"sha256:{number + 1:064x}",
            "image_id": f"sha256:{number + 2:064x}",
        }
        return {**base, "transfer_receipt_hash": content_hash(base)}

    monkeypatch.setattr(_qualification, "_transfer_candidate", transfer)

    def prepare(**values: Any) -> None:
        Path(values["output"]).mkdir(parents=True)
        assert values["pull"] is False

    monkeypatch.setattr(_qualification, "prepare_source", prepare)

    def source_binding(source: Path, *, expected_task_id: str) -> dict[str, str]:
        del expected_task_id
        number = int(source.name.rsplit("-", 1)[-1])
        return {
            "task_hash": f"{number:064x}",
            "source_hash": f"{number + 1:064x}",
            "source_image_lock_sha256": f"{number + 2:064x}",
            "verifier_image": f"sha256:{number + 2:064x}",
            "verifier_manifest_digest": f"sha256:{number + 1:064x}",
        }

    monkeypatch.setattr(_qualification._v19, "_source_binding", source_binding)
    monkeypatch.setattr(
        _qualification._v19,
        "_completed_outcome",
        lambda candidate, binding, report: {
            "task_id": candidate["task_id"],
            "status": "qualified" if report["base_failed"] else "not_qualified",
            "infrastructure_valid": True,
            "base_failed": report["base_failed"],
            "reference_passed": True,
            "verifier_network": "none",
            "verifier_image": binding["verifier_image"],
            "model_process_count": 0,
        },
    )
    monkeypatch.setattr(
        _qualification,
        "run_zero_model_smoke",
        lambda source, output: _report(eligible=eligible),
    )
    return calls, events


@pytest.mark.parametrize(
    ("eligible", "status", "qualified_count"),
    [
        (True, "qualified_pending_agent_images", 5),
        (False, "stopped_insufficient_capacity", 4),
    ],
)
def test_v28_processes_only_pr3059_and_preflights_before_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    eligible: bool,
    status: str,
    qualified_count: int,
) -> None:
    calls, events = _install_resume_fakes(tmp_path, monkeypatch, eligible=eligible)
    result = _qualification.qualify_v28_resumed_public_tasks(
        approval_path=tmp_path / "approval.json",
        predecessor_path=tmp_path / "predecessor.json",
        dataset=tmp_path / "dataset.jsonl",
        output=tmp_path / "output",
    )

    assert calls == ["ghcr.io/pku-liang/openhwgroup_m_cva6:pr-3059"]
    assert events == ["preflight", "predecessor", "images", "network"]
    assert result["status"] == status
    assert len(result["qualified_task_ids"]) == qualified_count
    assert result["outcomes"][5]["historical_source_preparation_rerun"] is False
    assert result["historical_attempts_retried"] is False
    assert result["provider_calls"] == 0
    assert result["heldout_task_ids_loaded"] == []


def test_v28_error_taxonomy_remains_allowlisted_and_content_free() -> None:
    category = _qualification._safe_error_category(b"unexpected status code 503")
    assert category == "registry_http_5xx"
    assert category in _qualification.OPENHANDS_V28_ERROR_CATEGORIES
