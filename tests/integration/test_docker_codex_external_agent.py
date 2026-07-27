from __future__ import annotations

import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from verigym.runtimes.docker.engine import DockerCliEngine
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.external_agent import ExternalProcessRequest
from verigym.schemas.runtime import (
    DockerExternalAgentRuntimeConfig,
    DockerRuntimeConfig,
    SessionSpec,
)

pytestmark = [pytest.mark.integration, pytest.mark.docker]

CODEX_BINARY_SHA256 = "a31ae9450a26216eb1e7c53102fd42123dd675974310b0e2ca3aa4cb622a2c15"


def _sse(events: list[dict[str, Any]]) -> bytes:
    output: list[str] = []
    for event in events:
        output.append(f"event: {event['type']}\n")
        output.append(f"data: {json.dumps(event, separators=(',', ':'))}\n\n")
    return "".join(output).encode("utf-8")


def _created(response_id: str) -> dict[str, Any]:
    return {"type": "response.created", "response": {"id": response_id}}


def _completed(response_id: str) -> dict[str, Any]:
    return {
        "type": "response.completed",
        "response": {
            "id": response_id,
            "usage": {
                "input_tokens": 0,
                "input_tokens_details": None,
                "output_tokens": 0,
                "output_tokens_details": None,
                "total_tokens": 0,
            },
        },
    }


class FakeProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: list[dict[str, Any]] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("content-length", "0")))
        body = json.loads(raw)
        self.requests.append(
            {
                "path": self.path,
                "body": body,
                "authorization_header_present": any(
                    name.lower() == "authorization" for name in self.headers
                ),
            }
        )
        if len(self.requests) == 1:
            command = (
                "set -eu; "
                'test "$(id -u)" != 0; '
                "test \"$(awk '/^CapEff:/ {print $2}' /proc/self/status)\" = "
                '"0000000000000000"; '
                'test "$(awk \'/^NoNewPrivs:/ {print $2}\' /proc/self/status)" = "1"; '
                'test "$(ls /sys/class/net)" = "lo"; '
                "test ! -S /var/run/docker.sock; "
                "test ! -e /host-home; "
                "test ! -e /source-repository; "
                "test ! -e /hidden-verifier; "
                "test ! -e /workspace/verifier; "
                "test ! -e /workspace/../sibling-run; "
                "test ! -e /dev/docker; "
                "test ! -e /dev/shm; "
                "for name in OPENAI_API_KEY CODEX_API_KEY "
                "HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy "
                "ALL_PROXY all_proxy; "
                'do test -z "${!name+x}"; done; '
                "if touch /verigym-rootfs-write 2>/dev/null; then exit 41; fi; "
                "if touch /workspace/../sibling-run 2>/dev/null; then exit 42; fi; "
                "printf docker-runtime-only > /workspace/runtime-proof.txt"
            )
            arguments = json.dumps(
                {
                    "cmd": command,
                    "shell": "bash",
                    "login": False,
                    "yield_time_ms": 10_000,
                },
                separators=(",", ":"),
            )
            events = [
                _created("fake-response-1"),
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "function_call",
                        "call_id": "runtime-security-proof",
                        "name": "exec_command",
                        "arguments": arguments,
                    },
                },
                _completed("fake-response-1"),
            ]
        else:
            events = [
                _created("fake-response-2"),
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "message",
                        "role": "assistant",
                        "id": "fake-message-1",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "module TopModule; endmodule",
                            }
                        ],
                    },
                },
                _completed("fake-response-2"),
            ]
        payload = _sse(events)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)


class FakeProxyHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str]] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _reject(self) -> None:
        self.requests.append((self.command, self.path))
        self.send_response(502)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_CONNECT(self) -> None:  # noqa: N802
        self._reject()

    def do_GET(self) -> None:  # noqa: N802
        self._reject()

    def do_POST(self) -> None:  # noqa: N802
        self._reject()


def _image_id(engine: DockerCliEngine, reference: str) -> str:
    payload = engine.inspect_image(reference)
    if payload is None or not isinstance(payload.get("Id"), str):
        pytest.skip(f"required local image is unavailable: {reference}")
    return str(payload["Id"])


def test_real_docker_exec_server_uses_fake_provider_without_container_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if os.environ.get("VERIGYM_RUN_DOCKER_TESTS") != "1":
        pytest.skip("set VERIGYM_RUN_DOCKER_TESTS=1 for Docker integration tests")
    verifier_reference = os.environ.get(
        "VERIGYM_DOCKER_IMAGE",
        "verigym/rtl-iverilog:12.0",
    )
    agent_reference = os.environ.get(
        "VERIGYM_CODEX_AGENT_IMAGE",
        "verigym/codex-exec-server:0.144.6",
    )
    codex = Path(
        os.environ.get(
            "VERIGYM_CODEX_BINARY",
            "/home/jzhu484/.npm-global/bin/codex",
        )
    ).resolve(strict=True)
    if hashlib.sha256(codex.read_bytes()).hexdigest() != (
        "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"
    ):
        pytest.skip("exact Codex CLI 0.144.6 host control plane is unavailable")
    engine = DockerCliEngine()
    verifier_id = _image_id(engine, verifier_reference)
    agent_id = _image_id(engine, agent_reference)
    engine.close()

    FakeProviderHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeProviderHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    FakeProxyHandler.requests = []
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), FakeProxyHandler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    proxy_url = f"http://proxy-user:proxy-password@127.0.0.1:{proxy.server_address[1]}"
    monkeypatch.setenv("HTTP_PROXY", proxy_url)
    monkeypatch.setenv("HTTPS_PROXY", proxy_url)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.setenv("http_proxy", "http://ignored-lower.invalid:9000")
    monkeypatch.setenv("https_proxy", "http://ignored-lower.invalid:9443")
    monkeypatch.setenv("no_proxy", "ignored.lower.invalid")
    monkeypatch.setenv("ALL_PROXY", "http://ignored-all.invalid:1080")
    monkeypatch.setenv("all_proxy", "http://ignored-all-lower.invalid:1080")
    codex_home = tmp_path / "fake-codex-home"
    codex_home.mkdir()
    port = server.server_address[1]
    (codex_home / "config.toml").write_text(
        "\n".join(
            [
                'model = "gpt-5.4"',
                'model_provider = "verigym_fake"',
                'approval_policy = "never"',
                'sandbox_mode = "read-only"',
                "",
                "[model_providers.verigym_fake]",
                'name = "VeriGym zero-real-model provider"',
                f'base_url = "http://127.0.0.1:{port}/v1"',
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
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    source = tmp_path / "source"
    (source / "rtl").mkdir(parents=True)
    (source / "rtl" / "TopModule.sv").write_text(
        "module TopModule; endmodule\n",
        encoding="utf-8",
    )
    inventory_engine = DockerCliEngine()
    before_managed = inventory_engine.list_managed_containers()
    inventory_engine.close()
    runtime = DockerRuntime(
        DockerRuntimeConfig(
            image=verifier_reference,
            expected_image_id=verifier_id,
            external_agent=DockerExternalAgentRuntimeConfig(
                image=agent_reference,
                expected_image_id=agent_id,
                expected_executable_name="codex",
                expected_executable_path="/usr/local/bin/codex",
                expected_executable_version="codex-cli 0.144.6",
                expected_executable_sha256=CODEX_BINARY_SHA256,
                process_argv=[
                    "/usr/local/bin/codex",
                    "exec-server",
                    "--listen",
                    "stdio://",
                ],
                protocol="codex_app_server_remote_environment_v1",
                required_image_labels={
                    "org.verigym.codex.version": "0.144.6",
                    "org.verigym.codex.binary.sha256": CODEX_BINARY_SHA256,
                    "org.verigym.credential_material": "absent",
                },
                run_as_user=f"{os.getuid()}:{os.getgid()}",
                max_process_time_s=30,
                max_output_bytes=1024 * 1024,
            ),
        )
    )
    runtime.prepare("zero-real-model-docker-external-process")
    session = runtime.create_session(
        SessionSpec(
            source_dir=str(source),
            label="agent",
            max_output_bytes=1024 * 1024,
        )
    )
    try:
        result = session.execute_external_process(
            ExternalProcessRequest(
                protocol="codex_app_server_remote_environment_v1",
                runtime_role="agent",
                argv=[
                    "/usr/local/bin/codex",
                    "exec-server",
                    "--listen",
                    "stdio://",
                ],
                logical_cwd="/workspace",
                stdin_text="Perform the frozen fake-provider runtime proof.",
                stdin_transport="runtime_protocol_adapter",
                network_policy="none",
                mount_policy="task_workspace_only",
                writable_destinations=["/workspace", "/tmp"],
                container_environment_names=[],
                integration_track="codex_cli_external_agent",
                workspace_mode="visible_task_workspace",
                logical_workspace_root="/workspace",
                requested_model_id="gpt-5.4",
                requested_reasoning_effort="xhigh",
                executable_path=codex,
                executable_name=codex.name,
                executable_sha256=hashlib.sha256(codex.read_bytes()).hexdigest(),
                executable_version="codex-cli 0.144.6",
                capability_fingerprint="f" * 64,
                requested_auth_mode="chatgpt_cli_session",
                resolved_auth_mode="inherited_codex_login",
                auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
                allow_proxy_environment=True,
                forwarded_proxy_environment_names=["HTTP_PROXY", "HTTPS_PROXY"],
                timeout_s=30,
                max_output_bytes=1024 * 1024,
                editable_globs=["rtl/**"],
                readonly_globs=[],
            )
        )
        assert result.exit_code == 0, result.stderr
        assert result.terminal_event_seen
        assert not result.timed_out
        assert not result.output_limit_hit
        assert result.cleanup_complete
        assert result.security.effective_controls_verified
        assert result.security.network_mode == "none"
        assert result.security.user_config_metadata_unchanged
        assert not result.security.credential_environment_names_in_container
        assert not result.security.proxy_environment_names_in_container
        assert result.security.control_plane_proxy_forwarding_enabled
        assert result.security.control_plane_forwarded_proxy_environment_names == [
            "HTTP_PROXY",
            "HTTPS_PROXY",
        ]
        assert result.security.control_plane_synthesized_environment_names == [
            "NO_PROXY",
            "no_proxy",
        ]
        assert result.security.control_plane_mandatory_loopback_bypass_present
        assert not result.security.api_key_environment_forwarded
        assert proxy_url not in result.stdout
        assert proxy_url not in result.stderr
        assert result.runtime_identity.agent_image_id == agent_id
        assert result.runtime_identity.verifier_image_id == verifier_id
        assert session.read_file("runtime-proof.txt") == b"docker-runtime-only"
        assert result.security.workspace_changed_paths == ["runtime-proof.txt"]
        assert len(FakeProviderHandler.requests) == 2
        assert all(
            not request["authorization_header_present"] for request in FakeProviderHandler.requests
        )
        assert all(
            request["body"].get("model") == "gpt-5.4" for request in FakeProviderHandler.requests
        )
    finally:
        session.close()
        runtime.close()
        server.shutdown()
        server.server_close()
        proxy.shutdown()
        proxy.server_close()
    inventory_engine = DockerCliEngine()
    assert inventory_engine.list_managed_containers() == before_managed
    inventory_engine.close()
    assert runtime.descriptor.cleanup is not None
    assert runtime.descriptor.cleanup.complete
    assert FakeProxyHandler.requests == []
