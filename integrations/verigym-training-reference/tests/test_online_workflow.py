from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from verigym_training_reference.rtl import extract_rtl_candidate


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _script(name: str) -> ModuleType:
    path = Path(__file__).parents[3] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_rtl_candidate_prefers_explicit_tags() -> None:
    candidate, method = extract_rtl_candidate(
        "analysis```verilog\nmodule Wrong; endmodule\n```"
        "<verilog>module TopModule; endmodule</verilog>"
    )
    assert candidate == "module TopModule; endmodule\n"
    assert method == "verilog_tags"


def test_extract_rtl_candidate_has_bounded_fallback_order() -> None:
    fenced, fenced_method = extract_rtl_candidate(
        "```systemverilog\nmodule TopModule; endmodule\n```"
    )
    plain, plain_method = extract_rtl_candidate("module TopModule; endmodule")
    assert fenced == plain == "module TopModule; endmodule\n"
    assert fenced_method == "markdown_fence_fallback"
    assert plain_method == "full_response_fallback"


def test_online_manifest_embeds_only_public_task_material(tmp_path: Path) -> None:
    prepare = _script("prepare_qwen35_online_tasks.py")
    public_base = {
        "schema_version": "1.0",
        "task_id": "suite/variant/task",
        "task_description": "Implement the public interface.",
        "public_readme": "Public instructions",
        "candidate_path": "TopModule.v",
        "candidate_skeleton": "module TopModule; endmodule\n",
        "source_hash": "a" * 64,
        "task_hash": "b" * 64,
        "hidden_assets_included": False,
    }
    public = {**public_base, "record_hash": _canonical_hash(public_base)}
    public_path = tmp_path / "public-input.json"
    public_path.write_text(json.dumps(public), encoding="utf-8")
    policy_base = {
        "policy_version_id": "policy-v1",
        "weight_version": 1,
    }
    policy = {**policy_base, "version_hash": _canonical_hash(policy_base)}
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    output = tmp_path / "online-tasks.json"

    assert (
        prepare.main(
            [
                "--public-input",
                str(public_path),
                "--variant",
                "variant",
                "--verifier-image",
                "image:tag",
                "--verifier-image-id",
                "sha256:" + "c" * 64,
                "--input-policy-version",
                str(policy_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    manifest_text = output.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["tasks"][0]["public_record"] == public
    assert str(tmp_path) not in manifest_text
    assert "source_root" not in manifest_text


def test_online_broker_returns_hash_bound_sparse_outcome(tmp_path: Path) -> None:
    broker_module = _script("run_qwen35_online_verifier_broker.py")
    public_base = {
        "task_id": "suite/variant/task",
        "hidden_assets_included": False,
    }
    public = {**public_base, "record_hash": _canonical_hash(public_base)}
    binding = {
        "task_id": public["task_id"],
        "public_input_hash": public["record_hash"],
        "public_record": public,
        "variant": "variant",
        "verifier_image": "image:tag",
        "verifier_image_id": "sha256:" + "c" * 64,
    }
    manifest_base = {
        "format_id": "verigym_online_tasks_v1",
        "tasks": [binding],
    }
    manifest = {**manifest_base, "manifest_hash": _canonical_hash(manifest_base)}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    broker_root = tmp_path / "broker"
    requests = broker_root / "requests"
    requests.mkdir(parents=True)
    (broker_root / "responses").mkdir()
    (broker_root / "STOP").write_text("stop\n", encoding="utf-8")
    candidate = "module TopModule; endmodule\n"
    request_base = {
        "format_id": "verigym_online_verifier_request_v1",
        "request_id": "d" * 64,
        "task_id": public["task_id"],
        "public_input_hash": public["record_hash"],
        "candidate": candidate,
        "candidate_hash": hashlib.sha256(candidate.encode()).hexdigest(),
    }
    request = {**request_base, "request_hash": _canonical_hash(request_base)}
    (requests / f"{request['request_id']}.json").write_text(json.dumps(request), encoding="utf-8")

    def score(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["binding"]["source_root"] == str(tmp_path)
        return {
            "infrastructure_valid": True,
            "resolved": True,
            "compile_status": "passed",
            "task_hash": "e" * 64,
            "verifier_hash": "f" * 64,
            "candidate_hash": request["candidate_hash"],
        }

    broker_module.score_online_candidate = score
    report = tmp_path / "broker-report.json"
    assert (
        broker_module.main(
            [
                "--task-manifest",
                str(manifest_path),
                "--source-root",
                str(tmp_path),
                "--broker-root",
                str(broker_root),
                "--verifier-output",
                str(tmp_path / "runs"),
                "--report",
                str(report),
            ]
        )
        == 0
    )
    response = json.loads((broker_root / "responses" / f"{request['request_id']}.json").read_text())
    response_identity = dict(response)
    response_hash = response_identity.pop("response_hash")
    assert response["request_hash"] == request["request_hash"]
    assert response["resolved"] is True
    assert _canonical_hash(response_identity) == response_hash
    assert json.loads(report.read_text())["infrastructure_invalid_count"] == 0
