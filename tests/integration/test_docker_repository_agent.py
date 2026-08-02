from __future__ import annotations

import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from verigym_codex_cli.agent import CodexCliAgentAdapter
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.util import atomic_json

from verigym.core.hashing import hash_bytes
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.evolution.memory import build_agent_version, build_memory_pack
from verigym.registry.collections import build_registries
from verigym.runtimes.docker.engine import DockerCliEngine
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import (
    DockerExternalAgentRuntimeConfig,
    DockerRuntimeConfig,
)
from verigym.suites.verilog_eval.schemas import IcarusCompatibility
from verigym.suites.verilog_eval.toolchain import classify_icarus_version

pytestmark = [pytest.mark.integration, pytest.mark.docker]

CODEX_NATIVE_SHA256 = "a31ae9450a26216eb1e7c53102fd42123dd675974310b0e2ca3aa4cb622a2c15"
CODEX_WRAPPER_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"
TASKS = [
    "repo-rtl/arbiter-reset-recovery",
    "repo-rtl/counter-wrap",
    "repo-rtl/pipeline-stall-backpressure",
]
HELDOUT_TASKS = [
    "repo-rtl/arbiter-rotating-priority-heldout",
    "repo-rtl/counter-load-wrap-heldout",
    "repo-rtl/pipeline-flush-heldout",
]


def _image_id(reference: str) -> str:
    engine = DockerCliEngine()
    try:
        payload = engine.inspect_image(reference)
    finally:
        engine.close()
    if payload is None or not isinstance(payload.get("Id"), str):
        pytest.skip(f"required local image is unavailable: {reference}")
    return str(payload["Id"])


def _docker_config() -> DockerRuntimeConfig:
    verifier = os.environ.get("VERIGYM_DOCKER_IMAGE", "verigym/rtl-iverilog:12.0")
    agent = os.environ.get(
        "VERIGYM_CODEX_REPOSITORY_AGENT_IMAGE",
        "verigym/codex-repository-agent:0.144.6",
    )
    launcher_hash = hash_bytes(
        (Path(__file__).parents[2] / "src" / "verigym" / "public_test_launcher.py").read_bytes()
    )
    return DockerRuntimeConfig(
        image=verifier,
        expected_image_id=_image_id(verifier),
        external_agent=DockerExternalAgentRuntimeConfig(
            image=agent,
            expected_image_id=_image_id(agent),
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version="codex-cli 0.144.6",
            expected_executable_sha256=CODEX_NATIVE_SHA256,
            process_argv=[
                "/usr/local/bin/codex",
                "exec-server",
                "--listen",
                "stdio://",
            ],
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
            max_process_time_s=300,
            max_output_bytes=8 * 1024 * 1024,
        ),
    )


def _heldout_grant(path: Path) -> None:
    memory = build_memory_pack(
        {
            "principles": ["Confirm observable behavior before making a focused change."],
            "public_test_strategy": ["Use bounded public feedback before finalizing."],
            "workspace_policy_reminders": ["Keep edits inside the editable workspace."],
            "debugging_checklist": ["Check reset, control priority, boundaries, and recovery."],
            "patch_discipline": ["Review a minimal coherent diff before finishing."],
        }
    )
    version = build_agent_version(
        agent_version_id="codex-cli-agent-v1",
        status="frozen",
        parent_version_hash="1" * 64,
        update_type="context_memory",
        executable_in_m10b=True,
        base_agent_id="codex-cli-agent",
        agent_descriptor_hash="2" * 64,
        model_id="gpt-5.4",
        reasoning_effort="xhigh",
        auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        runtime_identity_hash="3" * 64,
        tool_policy_hash="4" * 64,
        prompt_contract_hash="5" * 64,
        source_commit="53b0755715a876432ddcdface143632278ccddd3",
        package_hashes={"verigym": "6" * 64, "plugin": "7" * 64},
        image_hashes={"agent": "8" * 64, "verifier": "9" * 64},
        training_dataset_hash="a" * 64,
        reward_schema_hash="b" * 64,
        reward_profile_hash="c" * 64,
        memory_builder_identity_hash="d" * 64,
        memory_pack_hash=memory.content_hash,
        model_weights_modified=False,
    )
    atomic_json(path, version.model_dump(mode="json"))


def _sse(events: list[dict[str, Any]]) -> bytes:
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
        for event in events
    ).encode("utf-8")


class RepositoryFakeProvider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: list[dict[str, Any]] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("content-length", "0")))
        body = json.loads(raw)
        self.requests.append(
            {
                "body": body,
                "authorization_header_present": any(
                    name.lower() == "authorization" for name in self.headers
                ),
            }
        )
        response_id = f"repo-fake-{len(self.requests)}"
        events: list[dict[str, Any]] = [
            {"type": "response.created", "response": {"id": response_id}}
        ]
        if len(self.requests) == 1:
            events.append(
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "function_call",
                        "call_id": "list-public-tests",
                        "name": "exec_command",
                        "arguments": json.dumps(
                            {
                                "cmd": "verigym-public-test list",
                                "shell": "bash",
                                "login": False,
                                "yield_time_ms": 10_000,
                            },
                            separators=(",", ":"),
                        ),
                    },
                }
            )
        else:
            events.append(
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "message",
                        "role": "assistant",
                        "id": "repo-final-message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Submitted the visible repository without repair.",
                            }
                        ],
                    },
                }
            )
        events.append(
            {
                "type": "response.completed",
                "response": {
                    "id": response_id,
                    "usage": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                    },
                },
            }
        )
        payload = _sse(events)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)


@pytest.mark.conformance
def test_repository_agent_image_runs_all_reference_patches_with_role_separation(
    tmp_path: Path,
) -> None:
    if os.environ.get("VERIGYM_RUN_DOCKER_TESTS") != "1":
        pytest.skip("set VERIGYM_RUN_DOCKER_TESTS=1 for Docker integration tests")
    config = _docker_config()
    for task_id in TASKS:
        result = VeriGym().run(
            RunConfig(
                task_id=task_id,
                agent="repo-scripted-good",
                runtime="docker",
                docker_config=config,
                output=tmp_path / "runs",
            )
        )
        assert result.scorecard.resolved
        assert all(outcome.passed for outcome in result.manifest.repository_public_tests)
        assert all(
            outcome.network_policy == "none" and outcome.public_assets_read_only
            for outcome in result.manifest.repository_public_tests
        )
        assert result.manifest.repository_public_tool_invocation_count == 2
        assert result.manifest.repository_candidate is not None
        assert result.manifest.repository_candidate.patch.reapply_exact
        assert result.manifest.runtime.image is not None
        assert result.manifest.runtime.image.iverilog_version is not None
        assert result.manifest.runtime.cleanup is not None
        assert result.manifest.runtime.cleanup.complete
        replay = replay_run(result.run_dir, verify=True)
        assert replay.reverified_resolved is True


@pytest.mark.conformance
def test_all_six_m10b_references_pass_exact_icarus12_docker_verification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if os.environ.get("VERIGYM_RUN_DOCKER_TESTS") != "1":
        pytest.skip("set VERIGYM_RUN_DOCKER_TESTS=1 for Docker integration tests")
    grant = tmp_path / "frozen-v1.json"
    _heldout_grant(grant)
    monkeypatch.setenv("VERIGYM_M10B_HELDOUT_AGENT_VERSION_MANIFEST", str(grant))
    config = _docker_config()
    for task_id in [*TASKS, *HELDOUT_TASKS]:
        result = VeriGym().run(
            RunConfig(
                task_id=task_id,
                agent="repo-scripted-good",
                runtime="docker",
                docker_config=config,
                output=tmp_path / "six-reference-runs",
            )
        )
        assert result.scorecard.resolved
        assert result.manifest.repository_candidate is not None
        assert result.manifest.repository_candidate.patch.reapply_exact
        assert result.manifest.runtime.image is not None
        assert (
            classify_icarus_version(result.manifest.runtime.image.iverilog_version)
            == IcarusCompatibility.REFERENCE_COMPATIBLE
        )
        assert result.manifest.runtime.cleanup is not None
        assert result.manifest.runtime.cleanup.complete


def test_fake_codex_repository_episode_uses_public_mount_and_ordinary_freeze(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if os.environ.get("VERIGYM_RUN_DOCKER_TESTS") != "1":
        pytest.skip("set VERIGYM_RUN_DOCKER_TESTS=1 for Docker integration tests")
    codex_value = os.environ.get("VERIGYM_CODEX_BINARY")
    if codex_value is None:
        pytest.skip("set VERIGYM_CODEX_BINARY for the Codex repository-agent integration test")
    codex = Path(codex_value).resolve(strict=True)
    if hashlib.sha256(codex.read_bytes()).hexdigest() != CODEX_WRAPPER_SHA256:
        pytest.skip("exact Codex CLI 0.144.6 host control plane is unavailable")
    RepositoryFakeProvider.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), RepositoryFakeProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        "\n".join(
            [
                'model = "gpt-5.4"',
                'model_provider = "verigym_repo_fake"',
                'approval_policy = "never"',
                'sandbox_mode = "read-only"',
                "",
                "[model_providers.verigym_repo_fake]",
                'name = "VeriGym zero-model repository provider"',
                f'base_url = "http://127.0.0.1:{server.server_address[1]}/v1"',
                'wire_api = "responses"',
                "request_max_retries = 0",
                "stream_max_retries = 0",
                "supports_websockets = false",
                "requires_openai_auth = false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    capability_file = tmp_path / "capabilities.json"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("VERIGYM_CODEX_BINARY", str(codex))
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")
    identity, capability = discover_capabilities(force=True)
    del identity
    atomic_json(capability_file, capability.safe_dict())
    monkeypatch.setenv("VERIGYM_CODEX_CAPABILITY_FILE", str(capability_file))
    for name in (
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    registries = build_registries(discover_external=False)
    registries.agents.register(CodexCliAgentAdapter())
    try:
        result = VeriGym(registries).run(
            RunConfig(
                task_id="repo-rtl/counter-wrap",
                agent="codex-cli-agent",
                agent_options={
                    "model_id": "gpt-5.4",
                    "sandbox": "workspace-write",
                    "approval_policy": "non-interactive",
                    "reasoning_effort": "xhigh",
                    "allow_proxy_environment": False,
                    "max_process_time_s": 60,
                    "expected_execution_backend": "docker_outer_runtime_delegated",
                },
                runtime="docker",
                docker_config=_docker_config(),
                output=tmp_path / "fake-codex-run",
            )
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result.scorecard.status == "completed"
    assert not result.scorecard.correctness.infrastructure_error
    assert result.manifest.repository_candidate is not None
    assert result.manifest.repository_candidate.patch.changed_files == []
    assert len(result.manifest.repository_public_tests) == 1
    assert result.manifest.repository_public_tool_invocation_count == 2
    assert len(result.manifest.external_agent_observations) == 1
    assert len(RepositoryFakeProvider.requests) == 2
    assert all(
        request["body"].get("model") == "gpt-5.4" for request in RepositoryFakeProvider.requests
    )
    assert all(
        not request["authorization_header_present"] for request in RepositoryFakeProvider.requests
    )
    runtime_result = json.loads(
        (result.run_dir / "artifacts" / "codex_cli" / "runtime_process.json").read_text(
            encoding="utf-8"
        )
    )
    assert runtime_result["security"]["public_test_assets_mounted_read_only"] is True
    assert "/verigym-public" in runtime_result["security"]["read_only_destinations"]
    assert runtime_result["security"]["hidden_verifier_mounted"] is False
    assert runtime_result["security"]["source_repository_mounted"] is False
    assert runtime_result["security"]["host_home_mounted"] is False
    assert runtime_result["security"]["docker_socket_mounted"] is False
    assert runtime_result["security"]["credential_files_mounted"] is False
    assert runtime_result["security"]["credential_environment_names_in_container"] == []
    assert runtime_result["security"]["proxy_environment_names_in_container"] == []
    assert runtime_result["security"]["provider_network_in_container"] is False
    assert runtime_result["security"]["effective_controls_verified"] is True
    assert runtime_result["security"]["container_removed"] is True
    assert runtime_result["security"]["cleanup_verified"] is True
    assert (
        runtime_result["runtime_identity"]["agent_image_id"]
        != (runtime_result["runtime_identity"]["verifier_image_id"])
    )
    assert not any(
        path.parts[0] in {"hidden", ".verigym_internal"}
        for path in (result.run_dir / "candidate").rglob("*")
        if path.is_file()
    )
    replay_run(result.run_dir, verify=True)
