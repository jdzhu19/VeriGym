from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash

from verigym_training_reference.policy_versions import register_training_policy_version
from verigym_training_reference.schemas import TrainingPolicyVersionManifest

SOURCE_COMMIT = "a" * 40
MODEL_ID = "Qwen/Qwen3.5-9B"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _hashed_manifest(path: Path, format_id: str) -> Path:
    base = {"schema_version": "1.0", "format_id": format_id, "record_count": 1}
    path.write_text(
        json.dumps({**base, "manifest_hash": content_hash(base)}),
        encoding="utf-8",
    )
    return path


def _adapter(root: Path, weights: bytes, **report_fields: Any) -> tuple[Path, Path]:
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
        "world_size": 4,
        "software": {"trainer": "fixture"},
        "adapter_inventory": inventory,
        "adapter_artifact_hash": hashlib.sha256(encoded).hexdigest(),
        **report_fields,
    }
    report = root / "training-report.json"
    report.write_text(json.dumps({**base, "report_hash": content_hash(base)}), encoding="utf-8")
    return root, report


def test_register_base_sft_and_grpo_policy_chain(tmp_path: Path) -> None:
    model = _model_root(tmp_path / "model")
    versions = tmp_path / "versions"
    base_path = versions / "base.json"
    base = register_training_policy_version(
        output=base_path,
        policy_version_id="qwen35-9b-base",
        weight_version=None,
        update_type="base",
        model_id=MODEL_ID,
        model_root=model,
        source_commit=SOURCE_COMMIT,
        loading_configuration={"format": "huggingface_safetensors"},
    )

    sft_data = _hashed_manifest(tmp_path / "sft-data.json", "verified_sft_fixture_v1")
    sft_adapter, sft_report = _adapter(tmp_path / "sft-adapter", b"sft-weights")
    sft_path = versions / "policy-v0.json"
    sft = register_training_policy_version(
        output=sft_path,
        policy_version_id="qwen35-9b-rtl-policy-v0",
        weight_version=0,
        update_type="verified_sft",
        model_id=MODEL_ID,
        model_root=model,
        source_commit=SOURCE_COMMIT,
        loading_configuration={"format": "peft_lora_safetensors"},
        artifact=sft_adapter,
        parent_manifest=base_path,
        training_manifest=sft_data,
        training_report=sft_report,
    )

    rollouts = _hashed_manifest(tmp_path / "rollouts.json", "rllm_rollout_fixture_v1")
    rewards = _hashed_manifest(tmp_path / "rewards.json", "verigym_reward_fixture_v1")
    grpo_adapter, grpo_report = _adapter(
        tmp_path / "grpo-adapter",
        b"grpo-weights",
        parent_adapter_weights_sha256=_sha256(sft_adapter / "adapter_model.safetensors"),
        rllm_commit="b" * 40,
        verl_commit="c" * 40,
    )
    grpo = register_training_policy_version(
        output=versions / "policy-v1.json",
        policy_version_id="qwen35-9b-rtl-policy-v1",
        weight_version=1,
        update_type="verigym_grpo",
        model_id=MODEL_ID,
        model_root=model,
        source_commit=SOURCE_COMMIT,
        loading_configuration={"format": "peft_lora_safetensors"},
        artifact=grpo_adapter,
        parent_manifest=sft_path,
        training_manifest=rollouts,
        reward_manifest=rewards,
        training_report=grpo_report,
    )

    assert base.weight_version is None
    assert sft.parent_version_hash == base.version_hash
    assert grpo.parent_version_hash == sft.version_hash
    assert grpo.framework_commits == {"rllm": "b" * 40, "verl": "c" * 40}
    assert grpo.loading_configuration["adapter_weights_sha256"] == _sha256(
        grpo_adapter / "adapter_model.safetensors"
    )
    assert str(tmp_path) not in (versions / "policy-v1.json").read_text(encoding="utf-8")


def test_policy_registration_rejects_wrong_parent_weights(tmp_path: Path) -> None:
    model = _model_root(tmp_path / "model")
    base_path = tmp_path / "base.json"
    register_training_policy_version(
        output=base_path,
        policy_version_id="base",
        weight_version=None,
        update_type="base",
        model_id=MODEL_ID,
        model_root=model,
        source_commit=SOURCE_COMMIT,
        loading_configuration={"format": "huggingface_safetensors"},
    )
    data = _hashed_manifest(tmp_path / "data.json", "fixture_v1")
    sft_adapter, sft_report = _adapter(tmp_path / "sft-adapter", b"sft-weights")
    sft_path = tmp_path / "sft.json"
    register_training_policy_version(
        output=sft_path,
        policy_version_id="policy-v0",
        weight_version=0,
        update_type="verified_sft",
        model_id=MODEL_ID,
        model_root=model,
        source_commit=SOURCE_COMMIT,
        loading_configuration={"format": "peft_lora_safetensors"},
        artifact=sft_adapter,
        parent_manifest=base_path,
        training_manifest=data,
        training_report=sft_report,
    )
    rewards = _hashed_manifest(tmp_path / "rewards.json", "reward_fixture_v1")
    adapter, report = _adapter(
        tmp_path / "grpo-adapter", b"grpo-weights", parent_adapter_weights_sha256="d" * 64
    )
    with pytest.raises(ConfigurationError, match="registered parent"):
        register_training_policy_version(
            output=tmp_path / "policy.json",
            policy_version_id="policy-v1",
            weight_version=1,
            update_type="verigym_grpo",
            model_id=MODEL_ID,
            model_root=model,
            source_commit=SOURCE_COMMIT,
            loading_configuration={"format": "peft_lora_safetensors"},
            artifact=adapter,
            parent_manifest=sft_path,
            training_manifest=data,
            reward_manifest=rewards,
            training_report=report,
        )


def test_policy_manifest_rejects_nested_secret_or_host_path() -> None:
    base = {
        "policy_version_id": "base",
        "update_type": "base",
        "model_id": MODEL_ID,
        "base_model_snapshot_hash": "1" * 64,
        "artifact_kind": "model_snapshot",
        "artifact_hash": "2" * 64,
        "source_commit": SOURCE_COMMIT,
        "loading_configuration": {"nested": {"api_key": "secret"}},
        "version_hash": "3" * 64,
    }
    with pytest.raises(ValidationError, match="credential-like"):
        TrainingPolicyVersionManifest.model_validate(base)
    base["loading_configuration"] = {"nested": {"cache": "/host/model"}}
    with pytest.raises(ValidationError, match="raw host path"):
        TrainingPolicyVersionManifest.model_validate(base)
