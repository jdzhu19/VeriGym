from __future__ import annotations

import copy
import importlib
import io
import json
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash

from verigym_openhands.hwe_v19_campaign import OPENHANDS_V19_QUALIFICATION_CANDIDATES

_REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY))
sys.path.insert(0, str(_REPOSITORY / "integrations/verigym-hwe-bench/src"))

_qualification = importlib.import_module("scripts.qualify_cva6_openhands_v25_streamed_public_tasks")


def _approved() -> dict[str, Any]:
    path = _REPOSITORY / "configs/training/qwen35_hwe_openhands_v25_streamed_qualification_v1.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    return value


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


def _install_stream_fakes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    eligible_by_number: dict[int, bool],
) -> list[str]:
    approved = _approved()
    calls: list[str] = []
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv(_qualification.OPENHANDS_V25_OPT_IN_ENV, "1")
    monkeypatch.setattr(_qualification, "_load_json", lambda _path: approved)
    monkeypatch.setattr(_qualification, "_validated_authorization", lambda value: value)
    monkeypatch.setattr(_qualification, "_validated_dataset", lambda path, approved: path)
    monkeypatch.setattr(
        _qualification,
        "frozen_v19_candidate_inventory",
        lambda _path: approved["candidate_inventory"],
    )
    monkeypatch.setattr(_qualification, "_validate_network", lambda: None)
    monkeypatch.setattr(
        _qualification,
        "_validate_local_image",
        lambda binding: binding,
    )
    monkeypatch.setattr(
        _qualification,
        "_validated_tool_cache",
        lambda _binding: tmp_path,
    )
    monkeypatch.setattr(_qualification, "_count_host_candidate_images", lambda: len(calls))
    monkeypatch.setattr(_qualification, "_inspect_host_image", lambda _reference: None)
    monkeypatch.setattr(_qualification, "_count_temporary_containers", lambda: 0)
    monkeypatch.setattr(_qualification, "_new_scratch_directory", lambda: scratch)
    monkeypatch.setattr(_qualification, "_cleanup_scratch", lambda _path: None)

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
        assert set(values["imported_image_bindings"]) == {
            _qualification.OPENHANDS_V25_CANDIDATE_REFERENCES[len(calls) - 1]
        }

    monkeypatch.setattr(_qualification, "prepare_source", prepare)

    def binding(source: Path, *, expected_task_id: str) -> dict[str, str]:
        number = int(source.name.rsplit("-", 1)[-1])
        return {
            "task_hash": f"{number:064x}",
            "source_hash": f"{number + 1:064x}",
            "source_image_lock_sha256": f"{number + 2:064x}",
            "verifier_image": f"sha256:{number + 2:064x}",
            "verifier_manifest_digest": f"sha256:{number + 1:064x}",
        }

    monkeypatch.setattr(_qualification, "_source_binding", binding)

    def smoke(*, source: Path, output: Path) -> dict[str, Any]:
        del output
        number = int(source.name.rsplit("-", 1)[-1])
        return _report(eligible=eligible_by_number[number])

    monkeypatch.setattr(_qualification, "run_zero_model_smoke", smoke)
    return calls


def test_v25_authorization_is_hash_bound_and_scope_limited() -> None:
    approved = _approved()
    validated = _qualification._validated_authorization(copy.deepcopy(approved))
    value = copy.deepcopy(approved)
    expected_hash = value.pop("authorization_hash")

    assert validated == approved
    assert expected_hash == _qualification.OPENHANDS_V25_APPROVAL_HASH
    assert content_hash(value) == expected_hash
    assert [item["number"] for item in value["candidate_inventory"]] == [
        2330,
        3226,
        2844,
        3231,
        2989,
        1482,
        3059,
    ]
    assert value["authorized_actions"]["invoke_provider"] is False
    assert value["authorized_actions"]["load_heldout_tasks"] is False
    assert value["required_controls"]["automatic_retry"] is False


def test_v25_streams_until_five_qualified_without_transferring_seventh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_stream_fakes(
        tmp_path,
        monkeypatch,
        eligible_by_number={
            2330: True,
            3226: False,
            2844: True,
            3231: True,
            2989: True,
            1482: True,
            3059: True,
        },
    )
    output = tmp_path / "output"
    result = _qualification.qualify_v25_streamed_public_tasks(
        approval_path=tmp_path / "approval.json",
        dataset=tmp_path / "dataset.jsonl",
        output=output,
    )

    assert result["status"] == "qualified_pending_agent_images"
    assert len(calls) == 6
    assert result["qualified_task_ids"] == [
        OPENHANDS_V19_QUALIFICATION_CANDIDATES[index] for index in (0, 2, 3, 4, 5)
    ]
    assert result["training_reserve_task_ids"] == result["qualified_task_ids"][:3]
    assert result["validation_reserve_task_ids"] == result["qualified_task_ids"][3:]
    assert result["provider_calls"] == 0
    assert result["heldout_task_ids_loaded"] == []


def test_v25_capacity_gate_stops_before_an_impossible_fourth_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_stream_fakes(
        tmp_path,
        monkeypatch,
        eligible_by_number={number: False for number in (2330, 3226, 2844, 3231, 2989, 1482, 3059)},
    )
    result = _qualification.qualify_v25_streamed_public_tasks(
        approval_path=tmp_path / "approval.json",
        dataset=tmp_path / "dataset.jsonl",
        output=tmp_path / "output",
    )

    assert result["status"] == "stopped_insufficient_capacity"
    assert len(calls) == 3
    assert len(result["outcomes"]) == 3
    assert result["qualified_task_ids"] == []


def test_v25_crane_tarball_binds_config_and_digest_sentinel(tmp_path: Path) -> None:
    image_id = "sha256:" + "1" * 64
    sentinel = _qualification._sentinel_reference()
    manifest = json.dumps(
        [{"Config": image_id, "RepoTags": [sentinel], "Layers": ["layer.tar.gz"]}]
    ).encode()
    path = tmp_path / "image.tar"
    with tarfile.open(path, "w") as archive:
        for name, payload in (
            (image_id, b"config"),
            ("layer.tar.gz", b"layer"),
            ("manifest.json", manifest),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    receipt = _qualification._validated_crane_tarball(
        path,
        expected_image_id=image_id,
        expected_sentinel=sentinel,
    )

    assert receipt["config_image_id"] == image_id
    assert receipt["sentinel_reference"] == sentinel
    assert receipt["member_count"] == 3

    with pytest.raises(ConfigurationError, match="identity changed"):
        _qualification._validated_crane_tarball(
            path,
            expected_image_id="sha256:" + "2" * 64,
            expected_sentinel=sentinel,
        )
