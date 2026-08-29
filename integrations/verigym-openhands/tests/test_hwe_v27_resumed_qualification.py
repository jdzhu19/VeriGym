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

from verigym_openhands.hwe_v19_campaign import OPENHANDS_V19_QUALIFICATION_CANDIDATES

_REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY))
sys.path.insert(0, str(_REPOSITORY / "integrations/verigym-hwe-bench/src"))

_qualification = importlib.import_module("scripts.qualify_cva6_openhands_v27_resumed_public_tasks")


def _approved() -> dict[str, Any]:
    path = _REPOSITORY / "configs/training/qwen35_hwe_openhands_v27_resumed_qualification_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate(number: int, index: int) -> dict[str, Any]:
    return {
        "number": number,
        "task_id": OPENHANDS_V19_QUALIFICATION_CANDIDATES[index],
        "instance_id": f"openhwgroup/cva6:pr-{number}",
        "changed_line_count": index + 4,
        "modified_file_count": 2,
    }


def _predecessor() -> dict[str, Any]:
    tasks = list(OPENHANDS_V19_QUALIFICATION_CANDIDATES[:2])
    transfers: dict[str, dict[str, Any]] = {}
    bindings: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    for index, task_id in enumerate(tasks):
        image = f"sha256:{index + 1:064x}"
        manifest = f"sha256:{index + 11:064x}"
        receipt = f"{index + 21:064x}"
        transfers[task_id] = {
            "image_id": image,
            "manifest_digest": manifest,
            "transfer_receipt_hash": receipt,
        }
        bindings[task_id] = {
            "task_hash": f"{index + 31:064x}",
            "source_hash": f"{index + 41:064x}",
            "source_image_lock_sha256": f"{index + 51:064x}",
            "verifier_image": image,
            "verifier_manifest_digest": manifest,
            "source": f"sources/pr-{(2330, 3226)[index]}",
            "smoke": f"smokes/pr-{(2330, 3226)[index]}",
            "transfer_receipt_hash": receipt,
        }
        outcomes.append(
            {
                "task_id": task_id,
                "status": "qualified",
                "infrastructure_valid": True,
                "base_failed": True,
                "reference_passed": True,
                "verifier_network": "none",
                "verifier_image": image,
                "model_process_count": 0,
            }
        )
    failure = {
        "control_hash": "a54278952589ae4e50dbdb779ce4bf0e91622bc0bcfa8bd4596644a696218b70",
        "create_exit_code": 0,
        "create_stderr_bytes": 0,
        "create_stdout_bytes": 65,
        "exit_code": 1,
        "failure_stage": "candidate-pull",
        "failure_type": "ConfigurationError",
        "format_id": "verigym_openhands_hwe_v26_command_receipt_v1",
        "network": "verigym-hwe-net",
        "role": "candidate-pull",
        "schema_version": "1.0",
        "stderr_bytes": 2157,
        "stderr_present": True,
        "stderr_sha256": "4436c6d3ce3d869dfe46317ade6f350b8da0f79c12c0dc744128594ffe9d1e78",
        "stdout_bytes": 0,
        "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "temporary_container_removed": True,
    }
    assert content_hash(failure) == _qualification._PREDECESSOR_FAILURE_HASH
    return {
        "format_id": _qualification._v26.OPENHANDS_V26_PROGRESS_FORMAT,
        "identity": _qualification._v26.OPENHANDS_V26_IDENTITY,
        "authorization_hash": _qualification._v26.OPENHANDS_V26_APPROVAL_HASH,
        "status": "stopped_security_or_infrastructure_invalid",
        "progress_hash": _qualification._PREDECESSOR_PROGRESS_HASH,
        "active_task_id": OPENHANDS_V19_QUALIFICATION_CANDIDATES[2],
        "active_pull_receipt": None,
        "provider_calls": 0,
        "heldout_task_ids_loaded": [],
        "model_process_count": 0,
        "temporary_transfer_scratch_removed": True,
        "temporary_containers_removed": True,
        "outcomes": outcomes,
        "qualified_bindings": bindings,
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


def test_v27_authorization_is_hash_bound_and_never_retries_history() -> None:
    approved = _approved()
    validated = _qualification._validated_authorization(copy.deepcopy(approved))
    base = copy.deepcopy(approved)
    expected_hash = base.pop("authorization_hash")

    assert validated == approved
    assert expected_hash == _qualification.OPENHANDS_V27_APPROVAL_HASH
    assert content_hash(base) == expected_hash
    assert base["predecessor"]["attempted_task_ids"] == list(
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[:3]
    )
    assert base["continuation_candidate_numbers"] == [3231, 2989, 1482, 3059]
    assert base["required_controls"]["historical_attempts_retried"] is False
    assert base["required_controls"]["automatic_retry"] is False
    assert base["authorized_actions"]["invoke_provider"] is False
    assert base["authorized_actions"]["load_heldout_tasks"] is False
    assert _qualification._sentinel_reference() == _qualification._v26._sentinel_reference()


def test_v27_predecessor_import_rejects_any_binding_drift() -> None:
    predecessor = _qualification._validated_predecessor_value(_predecessor())
    assert list(predecessor["qualified_bindings"]) == list(
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[:2]
    )

    changed = _predecessor()
    first = OPENHANDS_V19_QUALIFICATION_CANDIDATES[0]
    changed["qualified_bindings"][first]["verifier_image"] = "sha256:" + "f" * 64
    with pytest.raises(ConfigurationError, match="binding changed"):
        _qualification._validated_predecessor_value(changed)


@pytest.mark.parametrize(
    ("diagnostic", "category"),
    [
        (b"unexpected status code 503 Service Unavailable", "registry_http_5xx"),
        (b"response status: 429 Too Many Requests", "registry_http_4xx"),
        (b"x509: certificate signed by unknown authority", "tls_verification"),
        (b"dial tcp: no such host", "dns_resolution"),
        (b"net/http: request canceled (Client.Timeout)", "transport_timeout"),
        (b"read: connection reset by peer", "transport_connection"),
        (b"cache rename: file exists", "cache_filesystem"),
        (b"tarball writer failed", "archive_writer"),
        (b"write failed: no space left on device", "resource_exhaustion"),
        (b"token=secret-value: opaque failure", "unknown"),
    ],
)
def test_v27_error_taxonomy_is_allowlisted_and_content_free(
    diagnostic: bytes, category: str
) -> None:
    result = _qualification._safe_error_category(diagnostic)
    assert result == category
    assert result in _qualification.OPENHANDS_V27_ERROR_CATEGORIES
    assert "secret-value" not in result


def test_v27_gate_skips_only_the_sealed_predecessor_failure() -> None:
    predecessor = _predecessor()
    outcomes = copy.deepcopy(predecessor["outcomes"])
    outcomes.append(_qualification._predecessor_failure_outcome(_candidate(2844, 2), predecessor))
    state = _qualification._qualification_state(outcomes)
    assert state["qualified_task_ids"] == list(OPENHANDS_V19_QUALIFICATION_CANDIDATES[:2])
    assert state["next_task_id"] == OPENHANDS_V19_QUALIFICATION_CANDIDATES[3]
    assert state["capacity_impossible"] is False

    outcomes[-1]["predecessor_terminal_evidence"] = False
    with pytest.raises(ConfigurationError, match="marker changed"):
        _qualification._qualification_state(outcomes)


def _install_resume_fakes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    eligible_by_number: dict[int, bool],
) -> list[str]:
    approved = _approved()
    v26_approved = json.loads(
        (
            _REPOSITORY / "configs/training/qwen35_hwe_openhands_v26_streamed_qualification_v1.json"
        ).read_text(encoding="utf-8")
    )
    inventory = copy.deepcopy(v26_approved["candidate_inventory"])
    calls: list[str] = []
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv(_qualification.OPENHANDS_V27_OPT_IN_ENV, "1")
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
        "_validated_predecessor",
        lambda _path, _binding: _predecessor(),
    )
    monkeypatch.setattr(_qualification, "_validate_predecessor_images", lambda _value: None)
    monkeypatch.setattr(_qualification._v26, "_validate_network", lambda: None)
    monkeypatch.setattr(_qualification._v26, "_validate_local_image", lambda binding: binding)
    monkeypatch.setattr(_qualification._v26, "_validated_tool_cache", lambda _binding: tmp_path)
    monkeypatch.setattr(_qualification._v26, "_inspect_host_image", lambda _reference: None)
    monkeypatch.setattr(_qualification, "_new_scratch_directory", lambda: scratch)
    monkeypatch.setattr(_qualification, "_cleanup_scratch", lambda _path: None)
    monkeypatch.setattr(_qualification, "_count_host_candidate_images", lambda: 2 + len(calls))
    monkeypatch.setattr(_qualification, "_count_temporary_containers", lambda: 0)

    def controlled(**_values: Any) -> tuple[bytes, dict[str, str], dict[str, Any]]:
        return (
            b"",
            {"control_hash": "1" * 64},
            {"stderr_bytes": 0, "temporary_container_removed": True},
        )

    monkeypatch.setattr(_qualification, "_run_controlled_container", controlled)

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

    def binding(source: Path, *, expected_task_id: str) -> dict[str, str]:
        del expected_task_id
        number = int(source.name.rsplit("-", 1)[-1])
        return {
            "task_hash": f"{number:064x}",
            "source_hash": f"{number + 1:064x}",
            "source_image_lock_sha256": f"{number + 2:064x}",
            "verifier_image": f"sha256:{number + 2:064x}",
            "verifier_manifest_digest": f"sha256:{number + 1:064x}",
        }

    monkeypatch.setattr(_qualification._v19, "_source_binding", binding)
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
        lambda source, output: _report(
            eligible=eligible_by_number[int(source.name.rsplit("-", 1)[-1])]
        ),
    )
    return calls


def test_v27_resumes_at_pr3231_and_stops_at_exact_five(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_resume_fakes(
        tmp_path,
        monkeypatch,
        eligible_by_number={3231: True, 2989: True, 1482: True, 3059: True},
    )
    result = _qualification.qualify_v27_resumed_public_tasks(
        approval_path=tmp_path / "approval.json",
        predecessor_path=tmp_path / "predecessor.json",
        dataset=tmp_path / "dataset.jsonl",
        output=tmp_path / "output",
    )

    assert [int(reference.rsplit("-", 1)[-1]) for reference in calls] == [3231, 2989, 1482]
    assert result["status"] == "qualified_pending_agent_images"
    assert result["qualified_task_ids"] == [
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[index] for index in (0, 1, 3, 4, 5)
    ]
    assert result["historical_attempts_retried"] is False
    assert result["provider_calls"] == 0
    assert result["heldout_task_ids_loaded"] == []


def test_v27_recomputes_capacity_before_third_continuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_resume_fakes(
        tmp_path,
        monkeypatch,
        eligible_by_number={3231: False, 2989: False, 1482: True, 3059: True},
    )
    result = _qualification.qualify_v27_resumed_public_tasks(
        approval_path=tmp_path / "approval.json",
        predecessor_path=tmp_path / "predecessor.json",
        dataset=tmp_path / "dataset.jsonl",
        output=tmp_path / "output",
    )

    assert [int(reference.rsplit("-", 1)[-1]) for reference in calls] == [3231, 2989]
    assert result["status"] == "stopped_insufficient_capacity"
    assert result["qualified_task_ids"] == list(OPENHANDS_V19_QUALIFICATION_CANDIDATES[:2])
