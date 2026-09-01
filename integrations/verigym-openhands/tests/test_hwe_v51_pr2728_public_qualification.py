from __future__ import annotations

import copy
import hashlib
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

_REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY))
sys.path.insert(0, str(_REPOSITORY / "integrations/verigym-hwe-bench/src"))

_qualification = importlib.import_module(
    "scripts.qualify_cva6_openhands_v51_pr2728_public_qualification"
)


def _approved() -> dict[str, Any]:
    path = (
        _REPOSITORY
        / "configs/training/qwen35_hwe_openhands_v51_pr2728_public_qualification_v1.json"
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _report(*, eligible: bool) -> dict[str, Any]:
    return {
        "base_infrastructure_error": False,
        "base_failed": eligible,
        "base_resolved": False,
        "reference_passed": True,
        "model_process_count": 0,
        "base_verifier_results": [{"status": "failed" if eligible else "passed"}],
        "verifier_results": [{"status": "passed"}],
    }


def _public_record() -> bytes:
    removed = "".join(f"-old_{index}\n" for index in range(12))
    added = "".join(f"+new_{index}\n" for index in range(13))
    row = {
        "org": "openhwgroup",
        "repo": "cva6",
        "number": 2728,
        "title": "public decoder correction",
        "problem_statement": "public statement",
        "base": {"sha": "1" * 40},
        "fix_patch": "--- a/core/decoder.sv\n+++ b/core/decoder.sv\n@@ -1,12 +1,13 @@\n"
        + removed
        + added,
        "test_patch": "",
        "tb_script": "true",
        "modified_files": ["core/decoder.sv"],
        "f2p_tests": {"decoder": {}},
        "fix_patch_result": {"failed_count": 0, "skipped_count": 0, "passed_count": 1},
        "test_patch_result": {"failed_count": 1},
    }
    return (json.dumps(row, sort_keys=True) + "\n").encode()


def _install_qualification_fakes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    eligible: bool,
) -> list[str]:
    approved = _approved()
    candidate = copy.deepcopy(approved["candidate"])
    compatibility = copy.deepcopy(approved["reference_patch_compatibility"])
    calls: list[str] = []
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv(_qualification.OPENHANDS_V51_OPT_IN_ENV, "1")
    monkeypatch.setattr(_qualification, "_load_json", lambda _path: copy.deepcopy(approved))
    monkeypatch.setattr(_qualification, "_validated_authorization", lambda value: value)
    monkeypatch.setattr(_qualification, "_validated_dataset", lambda path, approved: path)
    monkeypatch.setattr(
        _qualification,
        "_selected_candidate",
        lambda _path, _approved: (candidate, object(), b"selected\n", compatibility),
    )
    monkeypatch.setattr(_qualification, "_merged_source_commit", lambda: "a" * 40)
    monkeypatch.setattr(_qualification, "_validate_network", lambda: None)
    monkeypatch.setattr(_qualification, "_validate_headroom", lambda: {"passed": True})
    monkeypatch.setattr(_qualification, "_validate_local_image", lambda binding: binding)
    monkeypatch.setattr(_qualification, "_validated_tool_cache", lambda _binding: tmp_path)
    monkeypatch.setattr(_qualification, "_count_host_candidate_images", lambda: len(calls))
    monkeypatch.setattr(_qualification, "_inspect_host_image", lambda _reference: None)
    monkeypatch.setattr(_qualification, "_count_temporary_containers", lambda: 0)
    monkeypatch.setattr(_qualification, "_new_scratch_directory", lambda: scratch)
    monkeypatch.setattr(_qualification, "_cleanup_scratch", lambda _path: None)
    monkeypatch.setattr(
        _qualification,
        "_write_selected_dataset",
        lambda _scratch, _raw: tmp_path / "selected.jsonl",
    )

    def controlled(**_values: Any) -> tuple[bytes, dict[str, str], dict[str, Any]]:
        return (
            b"",
            {"control_hash": "1" * 64},
            {"stderr_bytes": 0, "temporary_container_removed": True},
        )

    monkeypatch.setattr(_qualification, "_run_controlled_container", controlled)

    def transfer(*, reference: str, **_values: Any) -> dict[str, Any]:
        calls.append(reference)
        base = {
            "reference": reference,
            "manifest_digest": "sha256:" + "2" * 64,
            "image_id": "sha256:" + "3" * 64,
        }
        return {**base, "transfer_receipt_hash": content_hash(base)}

    monkeypatch.setattr(_qualification, "_transfer_candidate", transfer)

    def prepare(**values: Any) -> None:
        Path(values["output"]).mkdir(parents=True)
        assert values["dataset"] == tmp_path / "selected.jsonl"
        assert values["pull"] is False
        assert set(values["imported_image_bindings"]) == {
            _qualification.OPENHANDS_V51_CANDIDATE_REFERENCE
        }

    monkeypatch.setattr(_qualification, "prepare_source", prepare)

    def binding(_source: Path, *, expected_task_id: str) -> dict[str, str]:
        assert expected_task_id == _qualification.OPENHANDS_V51_CANDIDATE_TASK_ID
        return {
            "task_hash": "4" * 64,
            "source_hash": "5" * 64,
            "source_image_lock_sha256": "6" * 64,
            "verifier_image": "sha256:" + "3" * 64,
            "verifier_manifest_digest": "sha256:" + "2" * 64,
        }

    monkeypatch.setattr(_qualification, "_source_binding", binding)
    monkeypatch.setattr(
        _qualification,
        "run_zero_model_smoke",
        lambda **_values: _report(eligible=eligible),
    )
    return calls


def test_v51_authorization_is_exact_hash_bound_and_zero_provider() -> None:
    approved = _approved()
    validated = _qualification._validated_authorization(copy.deepcopy(approved))
    base = copy.deepcopy(approved)
    observed = base.pop("authorization_hash")

    assert validated == approved
    assert observed == _qualification.OPENHANDS_V51_APPROVAL_HASH
    assert content_hash(base) == observed
    assert approved["candidate"] == _qualification._expected_candidate()
    assert approved["predecessor_v50"]["failure_audit_merge_commit"] == (
        _qualification._V50_FAILURE_AUDIT_MERGE
    )
    assert approved["authorized_actions"]["invoke_provider"] is False
    assert approved["authorized_actions"]["build_command_image"] is False
    assert approved["authorized_actions"]["start_collection"] is False
    assert approved["authorized_actions"]["start_training"] is False
    assert approved["authorized_actions"]["load_heldout_tasks"] is False
    assert approved["formal_collection_allowed"] is False
    assert approved["production_training_ready"] is False


def test_v51_rejects_scope_or_candidate_drift() -> None:
    for mutation in ("provider", "candidate", "retry", "collection"):
        changed = _approved()
        if mutation == "provider":
            changed["authorized_actions"]["invoke_provider"] = True
        elif mutation == "candidate":
            changed["candidate"]["number"] = 2945
        elif mutation == "retry":
            changed["required_controls"]["automatic_retry"] = True
        else:
            changed["formal_collection_allowed"] = True
        with pytest.raises(ConfigurationError, match="identity changed"):
            _qualification._validated_authorization(changed)


def test_v51_selects_only_public_pr2728_without_decoding_heldout_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    heldout_with_duplicate_keys = (
        b'{"org":"openhwgroup","repo":"cva6","number":2945,"number":2945,"fix_patch":"private"}\n'
    )
    public = _public_record()
    dataset = tmp_path / "cva6.jsonl"
    dataset.write_bytes(heldout_with_duplicate_keys + public)
    monkeypatch.setattr(
        _qualification,
        "OPENHANDS_V51_CANDIDATE_RECORD_SHA256",
        hashlib.sha256(public).hexdigest(),
    )

    candidate, _instance, selected, receipt = _qualification._selected_candidate(
        dataset, _approved()
    )

    assert candidate == _qualification._expected_candidate()
    assert selected == public
    assert receipt == _qualification._expected_patch_compatibility()


def test_v51_qualification_admits_one_training_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_qualification_fakes(tmp_path, monkeypatch, eligible=True)

    result = _qualification.qualify_v51_streamed_public_tasks(
        approval_path=tmp_path / "approval.json",
        dataset=tmp_path / "dataset.jsonl",
        output=tmp_path / "output",
    )

    assert calls == [_qualification.OPENHANDS_V51_CANDIDATE_REFERENCE]
    assert result["status"] == "qualified_pending_command_image"
    assert result["qualified_task_ids"] == [_qualification.OPENHANDS_V51_CANDIDATE_TASK_ID]
    assert result["training_candidate_task_ids"] == result["qualified_task_ids"]
    assert result["provider_calls"] == 0
    assert result["heldout_task_ids_loaded"] == []
    assert result["heldout_record_values_decoded"] is False
    assert result["historical_attempts_retried"] is False
    assert result["formal_collection_started"] is False
    assert result["training_started"] is False


def test_v51_ordinary_mismatch_is_terminal_and_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_qualification_fakes(tmp_path, monkeypatch, eligible=False)

    result = _qualification.qualify_v51_streamed_public_tasks(
        approval_path=tmp_path / "approval.json",
        dataset=tmp_path / "dataset.jsonl",
        output=tmp_path / "output",
    )

    assert calls == [_qualification.OPENHANDS_V51_CANDIDATE_REFERENCE]
    assert result["status"] == "not_qualified"
    assert result["qualified_task_ids"] == []
    assert result["automatic_retry"] is False
    assert len(result["outcomes"]) == 1


def test_v51_refuses_any_preexisting_output(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(ConfigurationError, match="must not already exist"):
        _qualification._new_directory(output)


def test_v51_accepts_bounded_pull_stderr_after_atomic_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = "sha256:" + "1" * 64
    observations: list[dict[str, Any]] = []

    def controlled(
        *, label_role: str, **_values: Any
    ) -> tuple[bytes, dict[str, str], dict[str, Any]]:
        output = {
            "candidate-digest": manifest.encode(),
            "candidate-config": b"{}",
            "candidate-pull": b"",
        }[label_role]
        return (
            output,
            {"control_hash": "1" * 64},
            {
                "stderr_bytes": 37 if label_role == "candidate-pull" else 0,
                "stderr_sha256": "2" * 64,
                "temporary_container_removed": True,
            },
        )

    monkeypatch.setattr(_qualification, "_inspect_host_image", lambda _reference: None)
    monkeypatch.setattr(_qualification, "_run_controlled_container", controlled)
    monkeypatch.setattr(
        _qualification,
        "_validated_crane_tarball",
        lambda *_args, **_values: (_ for _ in ()).throw(ConfigurationError("after policy")),
    )

    with pytest.raises(ConfigurationError, match="after policy"):
        _qualification._transfer_candidate(
            reference=_qualification.OPENHANDS_V51_CANDIDATE_REFERENCE,
            image_id="sha256:" + "3" * 64,
            tool_cache=tmp_path,
            scratch=tmp_path,
            pull_receipt_sink=observations.append,
        )

    assert len(observations) == 1
    assert observations[0]["stdout_empty"] is True
    assert observations[0]["stderr_bounded"] is True
    assert observations[0]["raw_output_persisted"] is False


def test_v51_crane_tarball_binds_config_and_digest_sentinel(tmp_path: Path) -> None:
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


def test_v51_requires_merge_gate_before_docker_or_output() -> None:
    source = Path(_qualification.__file__).read_text(encoding="utf-8")
    assert source.index("source_commit = _merged_source_commit()") < source.index(
        "_validate_network()"
    )
    assert source.index("headroom = _validate_headroom()") < source.index(
        "root = _new_directory(output)"
    )
    assert set(_qualification._REQUIRED_MERGED_PATHS) >= {
        "configs/training/qwen35_hwe_openhands_v51_pr2728_public_qualification_v1.json",
        "docs/audits/2026-09-01_openhands-v50-provider-canary-failed-closed.md",
        "docs/audits/2026-09-01_openhands-v51-pr2728-public-qualification-authorization.md",
        "scripts/qualify_cva6_openhands_v51_pr2728_public_qualification.py",
    }
    runtime = source.split("def qualify_v51_streamed_public_tasks", 1)[1].split(
        "\ndef _transfer_candidate", 1
    )[0]
    assert "litellm" not in runtime
    assert 'provider_calls"] +=' not in runtime
