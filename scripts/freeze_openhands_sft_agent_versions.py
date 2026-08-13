#!/usr/bin/env python3
"""Freeze distinct OpenHands base and SFT-adapter development policies."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from verigym_openhands import OpenHandsRepositoryAgentAdapter

from verigym.core.hashing import content_hash
from verigym.evolution.memory import validate_agent_version
from verigym.experiments.state import atomic_dump_json
from verigym.protocols.repository_action import repository_tool_definitions
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import AgentVersionManifest

_HASH = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Freeze OpenHands base/adapter agent versions.")
    parser.add_argument("--base-model-id", required=True)
    parser.add_argument("--adapter-model-id", required=True)
    parser.add_argument("--runtime-identity-hash", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--training-dataset-manifest", type=Path, required=True)
    parser.add_argument("--adapter-artifact-hash", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.base_model_id == arguments.adapter_model_id:
        raise ValueError("base and adapter model IDs must differ")
    for value, label in (
        (arguments.runtime_identity_hash, "runtime identity"),
        (arguments.adapter_artifact_hash, "adapter artifact"),
    ):
        if not _HASH.fullmatch(value):
            raise ValueError(f"{label} must be lowercase SHA-256")
    if not _COMMIT.fullmatch(arguments.source_commit):
        raise ValueError("source commit must be a full Git SHA")
    manifest = _json_object(arguments.training_dataset_manifest)
    training_hash = manifest.get("manifest_hash")
    if (
        manifest.get("format_id") != "verigym_verified_multiturn_sft_dataset_v1"
        or manifest.get("record_count") != 8
        or not isinstance(training_hash, str)
        or not _HASH.fullmatch(training_hash)
    ):
        raise ValueError("training dataset is not the frozen eight-record multi-turn set")
    output = _new_directory(arguments.output)
    agent = OpenHandsRepositoryAgentAdapter()
    prompt_contract_hash = _prompt_contract_hash(agent)
    common = {
        "status": "frozen",
        "executable_in_m10b": False,
        "base_agent_id": agent.descriptor.name,
        "agent_descriptor_hash": content_hash(agent.descriptor),
        "reasoning_effort": "model-default",
        "auth_semantic_id": "local-openai-compatible-model-server",
        "runtime_identity_hash": arguments.runtime_identity_hash,
        "tool_policy_hash": content_hash(repository_tool_definitions(dialect="openai")),
        "prompt_contract_hash": prompt_contract_hash,
        "source_commit": arguments.source_commit,
        "image_hashes": {},
        "reward_schema_hash": None,
        "reward_profile_hash": None,
        "model_weights_modified": False,
    }
    base = _seal_agent_version(
        {
            **common,
            "agent_version_id": "openhands-qwen35-9b-base-v1",
            "parent_version_hash": None,
            "update_type": "none",
            "model_id": arguments.base_model_id,
            "package_hashes": {
                "openhands-sdk-1.42.1": content_hash("openhands-sdk==1.42.1"),
                "verigym-source": content_hash(arguments.source_commit),
            },
            "training_dataset_hash": None,
        }
    )
    adapter = _seal_agent_version(
        {
            **common,
            "agent_version_id": "openhands-qwen35-9b-sft-adapter-v1",
            "parent_version_hash": base.version_hash,
            "update_type": "external_adapter",
            "model_id": arguments.adapter_model_id,
            "package_hashes": {
                "adapter-artifact": arguments.adapter_artifact_hash,
                "openhands-sdk-1.42.1": content_hash("openhands-sdk==1.42.1"),
                "verigym-source": content_hash(arguments.source_commit),
            },
            "training_dataset_hash": training_hash,
        }
    )
    atomic_dump_json(output / "base-agent-version.json", base)
    atomic_dump_json(output / "adapter-agent-version.json", adapter)
    result = {
        "format_id": "verigym_openhands_base_adapter_policy_freeze_v1",
        "base_agent_version_hash": base.version_hash,
        "adapter_agent_version_hash": adapter.version_hash,
        "training_dataset_hash": training_hash,
        "adapter_artifact_hash": arguments.adapter_artifact_hash,
        "distinct_model_ids": True,
        "benchmark_score_claimed": False,
    }
    atomic_dump_json(output / "freeze-report.json", result)
    return result


def _prompt_contract_hash(agent: OpenHandsRepositoryAgentAdapter) -> str:
    spec = agent.prompt_policy_spec
    assert spec is not None
    return content_hash(
        {
            "resolver_id": "agent_execution_prompt_policy_v1",
            "prompt_contract_id": spec.prompt_contract_id,
            "prompt_contract_version": spec.prompt_contract_version,
            "interaction_mode": InteractionMode.AGENT,
            "task_context_policy": spec.task_context_policy,
            "base_instruction_policy": spec.base_instruction_policy,
            "content_visibility_policy": spec.content_visibility_policy,
            "max_prompt_bytes": spec.max_prompt_bytes,
            "max_task_context_bytes": spec.max_task_context_bytes,
            "agent_descriptor_hash": content_hash(agent.descriptor),
        }
    )


def _seal_agent_version(payload: dict[str, Any]) -> AgentVersionManifest:
    draft = AgentVersionManifest.model_construct(**payload, version_hash="0" * 64)
    identity = draft.model_dump(mode="json", exclude={"version_hash"})
    return validate_agent_version(
        AgentVersionManifest.model_validate({**payload, "version_hash": content_hash(identity)})
    )


def _json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 4 * 1024 * 1024:
        raise ValueError("training manifest must be a bounded regular JSON file")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("training manifest must contain a JSON object")
    return value


def _new_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ValueError("policy-freeze output must be new or empty")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def main() -> int:
    try:
        report = _run(_parser().parse_args())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
