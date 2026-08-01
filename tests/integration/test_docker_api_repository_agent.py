from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from verigym.agents.repository_scripted import _GOOD_PATCHES, _PUBLIC_TEST_IDS
from verigym.core.hashing import hash_directory
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig
from verigym.models.openai_compatible import OpenAICompatibleModelClient
from verigym.registry.base import PluginOrigin
from verigym.registry.collections import build_registries
from verigym.reporting.loader import load_report_inputs
from verigym.reporting.service import ReportService
from verigym.runtimes.docker.engine import DockerCliEngine
from verigym.schemas.runtime import DockerExternalAgentRuntimeConfig, DockerRuntimeConfig

CODEX_NATIVE_SHA256 = "a31ae9450a26216eb1e7c53102fd42123dd675974310b0e2ca3aa4cb622a2c15"

pytestmark = [pytest.mark.integration, pytest.mark.docker]

TASKS = [
    "repo-rtl/arbiter-reset-recovery",
    "repo-rtl/counter-wrap",
    "repo-rtl/pipeline-stall-backpressure",
]


class RepositoryFakeProvider:
    def __init__(self) -> None:
        self.call_count = 0

    def create_chat_completion(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        connect_timeout_s: float,
        read_timeout_s: float,
        request_timeout_s: float,
        max_response_bytes: int,
    ) -> Mapping[str, Any]:
        del url, headers, connect_timeout_s, read_timeout_s, request_timeout_s, max_response_bytes
        messages = payload.get("messages")
        assert isinstance(messages, list) and len(messages) == 2
        user = messages[1]
        assert isinstance(user, dict) and isinstance(user.get("content"), str)
        context = json.loads(user["content"])
        task_id = context["task"]["id"]
        self.call_count += 1
        text = json.dumps(
            {
                "schema_version": "1.0",
                "actions": [
                    {"type": "apply_patch", "patch": _GOOD_PATCHES[task_id]},
                    {
                        "type": "tool_call",
                        "tool": "repository.public_test",
                        "arguments": {"test_id": _PUBLIC_TEST_IDS[task_id]},
                    },
                    {"type": "tool_call", "tool": "file.diff", "arguments": {}},
                    {"type": "final", "message": "fake provider candidate complete"},
                ],
            },
            separators=(",", ":"),
        )
        return {
            "id": f"fake-provider-{self.call_count}",
            "model": "fake-repository-model",
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }


def _image_id(reference: str) -> str:
    engine = DockerCliEngine()
    try:
        payload = engine.inspect_image(reference)
    finally:
        engine.close()
    if payload is None or not isinstance(payload.get("Id"), str):
        pytest.skip(f"required local image is unavailable: {reference}")
    return str(payload["Id"])


def _docker_config(image: str) -> DockerRuntimeConfig:
    agent_image = "verigym/codex-repository-agent:0.144.6"
    launcher_hash = hashlib.sha256(
        (Path(__file__).parents[2] / "src" / "verigym" / "public_test_launcher.py").read_bytes()
    ).hexdigest()
    return DockerRuntimeConfig(
        image=image,
        expected_image_id=_image_id(image),
        pull_policy="never",
        external_agent=DockerExternalAgentRuntimeConfig(
            image=agent_image,
            expected_image_id=_image_id(agent_image),
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version="codex-cli 0.144.6",
            expected_executable_sha256=CODEX_NATIVE_SHA256,
            process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels={
                "org.verigym.runtime.role": "repository-agent",
                "org.verigym.codex.version": "0.144.6",
                "org.verigym.codex.binary.sha256": CODEX_NATIVE_SHA256,
                "org.verigym.public_test_launcher.sha256": launcher_hash,
                "org.verigym.iverilog.version": "12.0",
                "org.verigym.provider_credentials": "absent",
                "org.verigym.credential_material": "absent",
            },
            run_as_user=f"{os.getuid()}:{os.getgid()}",
        ),
    )


def test_fake_provider_runs_ordinary_batch_report_and_zero_network_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = os.environ.get("VERIGYM_DOCKER_IMAGE", "verigym/rtl-iverilog:12.0")
    provider = RepositoryFakeProvider()
    registries = build_registries(discover_external=False)
    registries.models.register(
        OpenAICompatibleModelClient(
            client_id="fake-api-repository-model",
            provider_id="fake-provider",
            base_url="https://fake-provider.invalid/v1",
            model_id="fake-repository-model",
            api_key="fake-provider-unit-key",
            require_exact_model_id=True,
            transport=provider,
        ),
        origin=PluginOrigin(
            package="tests",
            version="1",
            entry_point=None,
            registration="runtime",
        ),
    )
    service = VeriGym(registries)
    output = tmp_path / "api-agent-experiment"
    config = ExperimentConfig.model_validate(
        {
            "name": "fake API repository agent ordinary batch",
            "suite": {"id": "repo-rtl", "tasks": {"include": TASKS, "exclude": []}},
            "runs": {
                "mode": "agent",
                "seeds": [11],
                "samples_per_task": 1,
                "pass_k": [1],
            },
            "systems": [
                {
                    "id": "fake-api-agent",
                    "agent": {
                        "id": "api-repository-agent",
                        "options": {
                            "action_plan_protocol": "strict_four_action_repository_repair_v1",
                        },
                    },
                    "model": {
                        "id": "fake-api-repository-model",
                        "options": {
                            "model_id": "fake-repository-model",
                            "require_exact_model_id": True,
                        },
                    },
                }
            ],
            "runtime": {
                "id": "docker",
                "docker": _docker_config(image).model_dump(mode="json"),
            },
            "execution": {
                "max_workers": 1,
                "max_plan_items": 3,
                "max_model_processes": 3,
                "resume_model_process_policy": "never_rerun_after_authorization",
                "seal_plan_before_execution": True,
                "frozen_campaign_identity": {"protocol": "fake_provider_repository_agent_v1"},
            },
            "output": {"root": output},
        }
    )
    planner = ExperimentPlanner(service)
    plan = planner.build(config)
    assert len(plan.items) == 3
    assert all(item.prompt_policy is not None for item in plan.items)
    result = BatchRunner(planner=planner, service_factory=lambda: service).run(plan)
    assert result.state.valid_terminal_count == 3
    assert result.state.infrastructure_error_count == 0
    assert provider.call_count == 3
    reports = ReportService().generate_all(output, group_by=("provider_id", "api_protocol"))
    assert reports.aggregate.coverage.resolved_runs == 3
    assert reports.aggregate.metadata["direct_llm_api_evaluation"]["executed"] is True
    csv_text = reports.csv_path.read_text(encoding="utf-8")
    assert "api_request_parameters_hash" in csv_text
    assert "fake-provider-unit-key" not in csv_text
    assert all(
        run.scorecard.efficiency.model_api_cost is None
        and run.scorecard.efficiency.model_api_cost_currency is None
        for run in load_report_inputs(output).valid_runs
    )
    for path in output.rglob("*"):
        if path.is_file():
            assert b"fake-provider-unit-key" not in path.read_bytes()
    for run in load_report_inputs(output).valid_runs:
        assert run.manifest.environment_summary["agent_workspace_credentials"] is False
        assert run.manifest.runtime.security is not None
        assert "VERIGYM_DEEPSEEK_API_KEY" not in run.manifest.runtime.security.environment_names

    monkeypatch.delenv("VERIGYM_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VERIGYM_DEEPSEEK_API_BASE_URL", raising=False)
    before_calls = provider.call_count
    for run_dir in sorted((output / "runs").iterdir()):
        before = hash_directory(run_dir)
        replay = replay_run(run_dir, verify=False, service=service)
        assert replay.integrity.status == "verified"
        assert hash_directory(run_dir) == before
    assert provider.call_count == before_calls
