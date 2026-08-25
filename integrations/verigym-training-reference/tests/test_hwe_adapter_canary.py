from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym.core.external_agent import _EVENT_TYPE
from verigym.hwe.deepseek_harness_development_training import (
    load_development_training_preregistration,
)

from verigym_training_reference.hwe_decision_sft_64k_adapter_canary_entry import (
    model_checkpoint_manifest,
)
from verigym_training_reference.hwe_decision_sft_64k_adapter_canary_training import (
    assert_adapter_canary_branch_config,
    prepare_adapter_canary_branch_config,
)
from verigym_training_reference.hwe_decision_sft_64k_heldout import (
    ModelDecisionError,
    adapter_artifact_inventory,
    parse_qwen_assistant_decision,
)
from verigym_training_reference.hwe_decision_sft_64k_native_inference import (
    _load_model_sharded,
    parse_qwen_tool_calls,
)

_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _ROOT / "configs/training/qwen35_hwe_deepseek_harness_development_training_v1.json"


def _authorization(preregistration: object) -> SimpleNamespace:
    return SimpleNamespace(
        authorization_hash="a" * 64,
        recipe_hash=preregistration.recipe_hash,
        schedule_hash=preregistration.canary.schedule_hash,
        step_16_checkpoint_contents=("model", "optimizer", "extra"),
        step_32_checkpoint_contents=("model",),
    )


@pytest.mark.parametrize("branch", ["producer", "resume"])
def test_adapter_canary_changes_only_authorized_checkpoint_fields(branch: str) -> None:
    preregistration = load_development_training_preregistration(_CONFIG)
    authorization = _authorization(preregistration)
    resolved = prepare_adapter_canary_branch_config(
        {},
        preregistration,
        authorization,
        branch=branch,
        checkpoint_root="/bounded/checkpoints",
    )
    assert_adapter_canary_branch_config(
        resolved,
        preregistration=preregistration,
        authorization=authorization,
        branch=branch,
        checkpoint_root="/bounded/checkpoints",
    )
    assert resolved["checkpoint"]["save_contents"] == (
        ["model", "optimizer", "extra"] if branch == "producer" else ["model"]
    )


def test_adapter_canary_rejects_training_math_drift() -> None:
    preregistration = load_development_training_preregistration(_CONFIG)
    authorization = _authorization(preregistration)
    resolved = prepare_adapter_canary_branch_config(
        {},
        preregistration,
        authorization,
        branch="resume",
        checkpoint_root="/bounded/checkpoints",
    )
    resolved["optim"]["lr"] = 2e-4
    with pytest.raises(ValueError, match="optim.lr changed"):
        assert_adapter_canary_branch_config(
            resolved,
            preregistration=preregistration,
            authorization=authorization,
            branch="resume",
            checkpoint_root="/bounded/checkpoints",
        )


def test_qwen_native_tool_call_parser_accepts_exact_xml() -> None:
    calls = parse_qwen_tool_calls(
        "checking the task\n<tool_call>\n<function=read_file>\n"
        "<parameter=path>\nTASK.md\n</parameter>\n</function>\n</tool_call>"
    )
    assert calls == [{"name": "read_file", "arguments": {"path": "TASK.md"}}]


@pytest.mark.parametrize(
    "text",
    [
        "<tool_call><function=unknown></function></tool_call>",
        "<tool_call><function=read_file></function></tool_call> suffix",
        "<tool_call><function=read_file>garbage</function></tool_call>",
    ],
)
def test_qwen_native_tool_call_parser_fails_closed(text: str) -> None:
    with pytest.raises(ValueError):
        parse_qwen_tool_calls(text)


def test_model_only_checkpoint_manifest_rejects_optimizer_state(tmp_path: Path) -> None:
    step = tmp_path / "global_step_32"
    (step / "huggingface").mkdir(parents=True)
    (step / "huggingface/config.json").write_text("{}")
    for rank in range(4):
        (step / f"model_world_size_4_rank_{rank}.pt").write_bytes(bytes([rank]))
    manifest = model_checkpoint_manifest(tmp_path, global_step=32)
    assert manifest["global_step"] == 32
    (step / "optim_world_size_4_rank_0.pt").write_bytes(b"not allowed")
    with pytest.raises(RuntimeError, match="model-only scope"):
        model_checkpoint_manifest(tmp_path, global_step=32)


def test_frozen_config_is_json() -> None:
    assert json.loads(_CONFIG.read_text())["format_id"].endswith("development_training_v1")


def test_qwen_heldout_decision_preserves_only_public_prefix() -> None:
    public, calls = parse_qwen_assistant_decision(
        "Inspecting the task.\n"
        "<tool_call><function=read_file><parameter=path>TASK.md</parameter>"
        "</function></tool_call>"
    )
    assert public == "Inspecting the task."
    assert calls == [{"name": "read_file", "arguments": {"path": "TASK.md"}}]


@pytest.mark.parametrize(
    "text",
    [
        "text only",
        "<think>secret</think><tool_call><function=finish>"
        "<parameter=summary>done</parameter></function></tool_call>",
        "<tool_call><function=read_file><parameter=path>TASK.md</parameter>"
        "</function></tool_call>interleaved<tool_call><function=inspect_diff>"
        "</function></tool_call>",
        "<tool_call><function=finish><parameter=summary>done</parameter>"
        "</function></tool_call><tool_call><function=inspect_diff></function></tool_call>",
    ],
)
def test_qwen_heldout_decision_fails_closed(text: str) -> None:
    with pytest.raises((ModelDecisionError, ValueError)):
        parse_qwen_assistant_decision(text)


def test_heldout_adapter_inventory_is_exact_and_hash_bound(tmp_path: Path) -> None:
    (tmp_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "adapter_model.safetensors").write_bytes(b"adapter")
    inventory, artifact_hash = adapter_artifact_inventory(tmp_path)
    assert [item["path"] for item in inventory] == [
        "adapter_config.json",
        "adapter_model.safetensors",
    ]
    assert len(artifact_hash) == 64
    (tmp_path / "checkpoint.pt").write_bytes(b"forbidden")
    with pytest.raises(ValueError, match="inventory differs"):
        adapter_artifact_inventory(tmp_path)


def test_qwen_heldout_event_uses_registered_external_agent_namespace() -> None:
    assert _EVENT_TYPE.fullmatch("deepseek_harness_qwen35_heldout_prompt_policy_bound")


def test_qwen_sharded_loader_rejects_unqualified_gpu_profile() -> None:
    with pytest.raises(ValueError, match="exactly four GPUs"):
        _load_model_sharded(
            Path("/not-read"),
            None,
            gpu_count=2,
            max_memory_per_gpu_bytes=20 * 1024**3,
        )
    with pytest.raises(ValueError, match="memory bound changed"):
        _load_model_sharded(
            Path("/not-read"),
            None,
            gpu_count=4,
            max_memory_per_gpu_bytes=19 * 1024**3,
        )
