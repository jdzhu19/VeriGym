from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash

from verigym_training_reference.online_policy import export_online_policy_version
from verigym_training_reference.policy_versions import register_training_policy_version

MODEL_ID = "Qwen/Qwen3.5-9B"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_hashed(path: Path, base: dict[str, Any], hash_field: str) -> Path:
    path.write_text(
        json.dumps({**base, hash_field: content_hash(base)}),
        encoding="utf-8",
    )
    return path


def _model_root(root: Path) -> Path:
    root.mkdir()
    (root / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["Qwen3_5ForConditionalGeneration"],
                "model_type": "qwen3_5",
            }
        ),
        encoding="utf-8",
    )
    (root / "model.safetensors").write_bytes(b"base-weights")
    return root


def _adapter(root: Path, weights: bytes) -> tuple[Path, Path]:
    root.mkdir()
    (root / "adapter_config.json").write_text('{"r": 8}\n', encoding="utf-8")
    (root / "adapter_model.safetensors").write_bytes(weights)
    inventory = [
        {
            "path": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(root.iterdir())
    ]
    encoded = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    base = {
        "schema_version": "1.0",
        "training_kind": "fixture",
        "learning_rate": 1e-5,
        "world_size": 1,
        "software": {"trainer": "fixture"},
        "adapter_inventory": inventory,
        "adapter_artifact_hash": hashlib.sha256(encoded).hexdigest(),
    }
    report = root / "training-report.json"
    _write_hashed(report, base, "report_hash")
    return root, report


def _parent_policy(tmp_path: Path, model: Path) -> tuple[Path, Path]:
    versions = tmp_path / "versions"
    base_path = versions / "base.json"
    register_training_policy_version(
        output=base_path,
        policy_version_id="base",
        weight_version=None,
        update_type="base",
        model_id=MODEL_ID,
        model_root=model,
        source_commit="a" * 40,
        loading_configuration={"format": "huggingface_safetensors"},
    )
    data = _write_hashed(
        tmp_path / "sft-data.json",
        {"schema_version": "1.0", "format_id": "fixture_v1", "record_count": 1},
        "manifest_hash",
    )
    adapter, report = _adapter(tmp_path / "parent-adapter", b"parent-weights")
    parent_path = versions / "policy-v0.json"
    register_training_policy_version(
        output=parent_path,
        policy_version_id="policy-v0",
        weight_version=0,
        update_type="verified_sft",
        model_id=MODEL_ID,
        model_root=model,
        source_commit="a" * 40,
        loading_configuration={"format": "peft_lora_safetensors"},
        artifact=adapter,
        parent_manifest=base_path,
        training_manifest=data,
        training_report=report,
    )
    return parent_path, adapter


def _online_inputs(tmp_path: Path, parent_path: Path) -> tuple[Path, Path, Path, Path]:
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    task_base = {
        "schema_version": "1.0",
        "format_id": "verigym_online_tasks_v1",
        "input_policy_version_hash": parent["version_hash"],
        "input_policy_version_id": parent["policy_version_id"],
        "input_weight_version": parent["weight_version"],
        "tasks": [{"task_id": "suite/task"}],
    }
    tasks = _write_hashed(tmp_path / "online-tasks.json", task_base, "manifest_hash")
    task_hash = json.loads(tasks.read_text(encoding="utf-8"))["manifest_hash"]
    requests = [
        {
            "task_id": "suite/task",
            "request_hash": "1" * 64,
            "response_hash": "2" * 64,
            "resolved": True,
            "infrastructure_valid": True,
        },
        {
            "task_id": "suite/task",
            "request_hash": "3" * 64,
            "response_hash": "4" * 64,
            "resolved": False,
            "infrastructure_valid": True,
        },
    ]
    broker_base = {
        "schema_version": "1.0",
        "format_id": "verigym_online_verifier_broker_report_v1",
        "task_manifest_hash": task_hash,
        "request_count": 2,
        "resolved_count": 1,
        "infrastructure_invalid_count": 0,
        "requests": requests,
    }
    broker = _write_hashed(tmp_path / "broker.json", broker_base, "report_hash")
    completion_base = {
        "schema_version": "1.0",
        "format_id": "verigym_rllm_verl_online_smoke_report_v1",
        "status": "completed",
        "task_manifest_hash": task_hash,
        "input_policy_version_hash": parent["version_hash"],
        "input_policy_version_id": parent["policy_version_id"],
        "input_weight_version": parent["weight_version"],
        "task_ids": ["suite/task"],
        "rollout_count": 2,
        "resolved_count": 1,
        "rewards_by_task": {"suite/task": [1.0, 0.0]},
        "reward_variance_group_count": 1,
        "infrastructure_invalid_count": 0,
        "adapter_changed_tensor_count": 2,
        "adapter_max_abs_delta": 1e-6,
        "world_size": 4,
        "software": {"rllm": "0.3.0rc0", "verl": "0.7.1"},
        "rllm_commit": "b" * 40,
        "verl_commit": "c" * 40,
        "verigym_commit": "d" * 40,
        "effective_policy_update_verified": True,
        "full_ray_vllm_stack_qualified": True,
    }
    completion = _write_hashed(tmp_path / "completion.json", completion_base, "report_hash")
    checkpoint = tmp_path / "checkpoints"
    output_adapter = checkpoint / "global_step_1" / "actor" / "lora_adapter"
    output_adapter.mkdir(parents=True)
    (checkpoint / "latest_checkpointed_iteration.txt").write_text("1\n", encoding="utf-8")
    (output_adapter / "adapter_config.json").write_text('{"r": 8}\n', encoding="utf-8")
    (output_adapter / "adapter_model.safetensors").write_bytes(b"updated-weights")
    return completion, broker, tasks, checkpoint


def test_export_online_policy_registers_compact_successor(tmp_path: Path) -> None:
    model = _model_root(tmp_path / "model")
    parent, parent_adapter = _parent_policy(tmp_path, model)
    completion, broker, tasks, checkpoint = _online_inputs(tmp_path, parent)
    output = tmp_path / "registered-policy"

    version = export_online_policy_version(
        completion_report=completion,
        broker_report=broker,
        task_manifest=tasks,
        checkpoint_root=checkpoint,
        parent_manifest=parent,
        model_root=model,
        output=output,
        policy_version_id="policy-v1",
        learning_rate=1e-6,
    )

    parent_value = json.loads(parent.read_text(encoding="utf-8"))
    assert version.weight_version == 1
    assert version.parent_version_hash == parent_value["version_hash"]
    assert version.framework_commits == {"rllm": "b" * 40, "verl": "c" * 40}
    assert (output / "adapter" / "adapter_model.safetensors").read_bytes() == b"updated-weights"
    assert not (output / "adapter" / "tokenizer.json").exists()
    adapter_config = json.loads(
        (output / "adapter" / "adapter_config.json").read_text(encoding="utf-8")
    )
    assert adapter_config["base_model_name_or_path"] == MODEL_ID
    assert version.loading_configuration["adapter_weights_sha256"] != _sha256(
        parent_adapter / "adapter_model.safetensors"
    )
    reward = json.loads((output / "reward-manifest.json").read_text(encoding="utf-8"))
    assert reward["rewards_by_task"] == {"suite/task": [1.0, 0.0]}
    assert str(tmp_path) not in (output / "policy-version.json").read_text(encoding="utf-8")


def test_export_online_policy_rejects_parent_mismatch_atomically(tmp_path: Path) -> None:
    model = _model_root(tmp_path / "model")
    parent, _ = _parent_policy(tmp_path, model)
    completion, broker, tasks, checkpoint = _online_inputs(tmp_path, parent)
    value = json.loads(completion.read_text(encoding="utf-8"))
    value["input_policy_version_hash"] = "e" * 64
    identity = dict(value)
    identity.pop("report_hash")
    value["report_hash"] = content_hash(identity)
    completion.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "registered-policy"

    with pytest.raises(ConfigurationError, match="registered parent"):
        export_online_policy_version(
            completion_report=completion,
            broker_report=broker,
            task_manifest=tasks,
            checkpoint_root=checkpoint,
            parent_manifest=parent,
            model_root=model,
            output=output,
            policy_version_id="policy-v1",
            learning_rate=1e-6,
        )

    assert not output.exists()
