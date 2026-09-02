from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.external_agent import RuntimeExternalAgentBridge
from verigym.core.trace import TraceWriter
from verigym.core.workspace import WorkspacePolicy
from verigym.hwe.image_lock import HweCommandImageLock
from verigym.runtimes.base import RuntimeSession
from verigym.schemas.runtime import WorkspaceDiff
from verigym.schemas.tool import CommandSpec, CompletedCommand

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts import (  # noqa: E402
    collect_ibex_hwe_deepseek_harness_v67_provider_canary as canary,
)

_AUTHORIZATION = _REPOSITORY_ROOT / Path(
    "configs/training/qwen35_hwe_deepseek_harness_v67_ibex_pr166_provider_canary_v1.json"
)
_COMMAND_LOCK = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v66-ibex-pr166-command-image-v1/image-locks/pr-166.json"
)


class _ExactTokenizer:
    tokenizer_id = "Qwen3.5-9B/local-frozen-chat-template"
    tokenizer_hash = "1" * 64
    chat_template_hash = "2" * 64

    def count_decision_example(self, **_kwargs: Any) -> tuple[int, int, int]:
        return 3, 2, 1

    def tokenize_decision_example(self, **_kwargs: Any) -> tuple[list[int], list[int]]:
        return [11, 12, 13], [0, 0, 1]


class _FixedSurfaceSession(RuntimeSession):
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def execute(self, command: CommandSpec) -> CompletedCommand:
        del command
        raise AssertionError("execution is not part of the marker regression")

    def read_file(self, path: str) -> bytes:
        del path
        raise AssertionError("file access is not part of the marker regression")

    def write_file(self, path: str, data: bytes) -> None:
        del path, data
        raise AssertionError("file access is not part of the marker regression")

    def snapshot_diff(self) -> WorkspaceDiff:
        raise AssertionError("diff capture is not part of the marker regression")

    def close(self) -> None:
        return None


def _source_row() -> dict[str, Any]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in ("apply_patch", "finish", "inspect_diff", "list_files", "read_file", "shell")
    ]
    return {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_deepseek_harness_decision_sft_v3",
        "sample_id": "3" * 64,
        "task_id": canary.TASK_ID,
        "task_hash": "4" * 64,
        "source_hash": "5" * 64,
        "candidate_hash": "6" * 64,
        "verifier_hash": "7" * 64,
        "transcript_hash": "8" * 64,
        "decision_index": 2,
        "target_message_index": 4,
        "call_ids": ["call-diff", "call-finish"],
        "action_names": ["inspect_diff", "finish"],
        "tool_action_count": 2,
        "trajectory_assistant_decision_count": 3,
        "trajectory_accepted_tool_action_count": 2,
        "trajectory_masked_policy_error_decision_count": 1,
        "trajectory_masked_format_error_decision_count": 1,
        "trajectory_format_repair_count": 1,
        "tools": tools,
        "input_messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "masked failed decision"},
            {"role": "tool", "content": "public error"},
        ],
        "target_message": {
            "role": "assistant",
            "content": "Public validation conclusion.",
            "tool_calls": [
                {
                    "id": "call-diff",
                    "type": "function",
                    "function": {"name": "inspect_diff", "arguments": "{}"},
                },
                {
                    "id": "call-finish",
                    "type": "function",
                    "function": {"name": "finish", "arguments": '{"summary":"done"}'},
                },
            ],
        },
        "tokenizer_id": _ExactTokenizer.tokenizer_id,
        "tokenizer_hash": _ExactTokenizer.tokenizer_hash,
        "chat_template_hash": _ExactTokenizer.chat_template_hash,
        "input_tokens": 2,
        "target_tokens": 1,
        "token_count": 3,
        "max_length": 32_768,
        "truncation": "error",
        "eligible": True,
        "supervised_target_kind": "complete_assistant_decision",
        "supervised_roles": ["assistant"],
        "input_loss_masked": True,
        "failed_tool_decisions_loss_masked": True,
        "format_error_decisions_loss_masked": True,
        "exact_model_visible_context": True,
        "context_transformed_after_collection": False,
        "nap_required": False,
        "verifier_resolved": True,
        "infrastructure_valid": True,
        "public_assistant_text_exported": True,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
        "record_hash": "9" * 64,
    }


def _bridge(tmp_path: Path) -> RuntimeExternalAgentBridge:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return RuntimeExternalAgentBridge(
        session=_FixedSurfaceSession(workspace),
        artifact_root=tmp_path / "artifacts",
        isolation_level="docker_standard",
        policy=WorkspacePolicy(editable_globs=("repository/**",), readonly_globs=("TASK.md",)),
        trace=TraceWriter(tmp_path / "runs" / "episode" / "trace.jsonl", "test-run"),
    )


def test_authorization_is_hash_bound_and_keeps_collection_closed() -> None:
    authorization = json.loads(_AUTHORIZATION.read_text(encoding="utf-8"))
    assert canary.validate_authorization(authorization)["authorization_hash"] == (
        canary.AUTHORIZATION_HASH
    )
    tampered = copy.deepcopy(authorization)
    tampered["provider_budget"]["max_provider_calls"] = 65
    with pytest.raises(ConfigurationError, match="authorization identity"):
        canary.validate_authorization(tampered)


def test_provider_consumption_accepts_real_core_bounded_marker(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge.emit_event(
        "deepseek_harness_provider_request_started",
        {
            "provider_request_started": True,
            "provider_request_count_lower_bound": 1,
            "credential_values_persisted": False,
        },
    )
    assert canary._provider_request_started_in_runs(tmp_path) is True  # noqa: SLF001


def test_marker_drift_is_consumed_and_seals_a_report(tmp_path: Path) -> None:
    trace = TraceWriter(tmp_path / "runs" / "episode" / "trace.jsonl", "episode")
    trace.emit(
        "deepseek_harness_provider_request_started",
        {
            "provider_request_started": True,
            "provider_request_count_lower_bound": 2,
            "credential_values_persisted": False,
        },
    )
    assert canary._provider_boundary_state(tmp_path) == (True, False)  # noqa: SLF001
    with pytest.raises(ConfigurationError, match="marker payload"):
        canary._provider_request_started_in_runs(tmp_path)  # noqa: SLF001

    result = canary._stop_after_episode_exception(  # noqa: SLF001
        tmp_path,
        {"schema_version": "1.0", "format_id": "test-result"},
        RuntimeError("not persisted"),
    )
    assert result["task_consumed"] is True
    assert result["failure_reason"] == "provider_episode:provider_marker_payload_invalid"
    assert (tmp_path / "canary-report.json").is_file()


def test_exact_64k_derivation_preserves_public_rationale_and_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_row()
    monkeypatch.setattr(
        canary,
        "materialize_deepseek_harness_decision_examples_v3",
        lambda *_args, **_kwargs: [copy.deepcopy(source)],
    )
    records, dry_runs = canary.materialize_exact_64k_records(
        {"transcript_hash": "8" * 64},
        binding={},
        tokenizer=_ExactTokenizer(),  # type: ignore[arg-type]
    )
    assert len(records) == len(dry_runs) == 1
    assert records[0]["input_messages"] == source["input_messages"]
    assert records[0]["target_message"] == source["target_message"]
    assert records[0]["tool_action_count"] == 2
    assert records[0]["max_length"] == 65_536
    assert dry_runs[0]["truncation_applied"] is False


@pytest.mark.skipif(not _COMMAND_LOCK.is_file(), reason="v66 command image lock is not installed")
def test_runtime_uses_locked_pr166_command_image_with_no_network() -> None:
    authorization = canary.validate_authorization(
        json.loads(_AUTHORIZATION.read_text(encoding="utf-8"))
    )
    lock = canary._materialized_lock(canary.MATERIALIZATION_ROOT, authorization)  # noqa: SLF001
    assert lock == HweCommandImageLock.model_validate_json(
        _COMMAND_LOCK.read_text(encoding="utf-8")
    )
    runtime = canary._runtime_config(lock)  # noqa: SLF001
    assert runtime.network_mode == "none"
    assert runtime.command_image is not None
    assert runtime.command_image.network_mode == "none"
    assert runtime.command_image.execution_backend == "episode_container_exec_v1"
    assert runtime.command_image.expected_image_id == lock.derived_command_image_id
