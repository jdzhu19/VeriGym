from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from verigym_deepseek_harness.config import API_KEY_ENV, BASE_URL_ENV, resolve_settings
from verigym_deepseek_harness.process import run_harness_helper

from verigym.hwe.deepseek_harness import (
    DEEPSEEK_HARNESS_MODEL,
    DEEPSEEK_HARNESS_TOOL_NAMES,
    build_deepseek_harness_transcript,
    build_deepseek_harness_transcript_v3,
)
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID
from verigym.hwe.trajectory import HweNormalizedEvent


class _ProviderHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    recovery_mode = False

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 4 * 1024 * 1024:
            self.send_error(400)
            return
        value = json.loads(self.rfile.read(length))
        type(self).requests.append(value)
        if type(self).recovery_mode and len(type(self).requests) == 1:
            chunks = [
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": "unfinished public analysis",
                                "reasoning_content": "",
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 2048, "total_tokens": 2098},
                },
            ]
        else:
            chunks = [
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": (
                                    "Recovered with a typed finish."
                                    if type(self).recovery_mode
                                    else None
                                ),
                                "reasoning_content": "",
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-finish",
                                        "type": "function",
                                        "function": {
                                            "name": "finish",
                                            "arguments": '{"summary":"fake conformance complete"}',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [
                        {"index": 0, "delta": {"content": ""}, "finish_reason": "tool_calls"}
                    ],
                    "usage": {"prompt_tokens": 101, "completion_tokens": 9, "total_tokens": 110},
                },
            ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for chunk in chunks:
            encoded = json.dumps(chunk, separators=(",", ":")).encode()
            self.wfile.write(b"data: " + encoded + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _serve_broker(
    path: Path,
    observed: list[dict[str, Any]],
    ready: threading.Event,
) -> None:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(1)
        ready.set()
        connection, _ = server.accept()
        with connection:
            raw = bytearray()
            while not raw.endswith(b"\n"):
                block = connection.recv(65_536)
                if not block:
                    break
                raw.extend(block)
            observed.append(json.loads(raw))
            response = {
                "ok": True,
                "text": "No candidate diff.",
                "sequence": 0,
                "workspace_epoch_before": 0,
                "workspace_epoch_after": 0,
                "changed_paths": [],
                "result_success": True,
            }
            connection.sendall(json.dumps(response, separators=(",", ":")).encode() + b"\n")
    finally:
        server.close()


@pytest.mark.docker
def test_official_harness_one_action_fake_provider_conformance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = subprocess.run(
        [
            "docker",
            "network",
            "inspect",
            "verigym-hwe-net",
            "--format",
            "{{(index .IPAM.Config 0).Gateway}}",
        ],
        capture_output=True,
        check=False,
        text=True,
    ).stdout.strip()
    if not gateway:
        pytest.skip("verigym-hwe-net has no reachable gateway")
    _ProviderHandler.requests = []
    _ProviderHandler.recovery_mode = False
    provider = ThreadingHTTPServer(("0.0.0.0", 0), _ProviderHandler)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    broker_root = tmp_path / "broker"
    session_root = tmp_path / "sessions"
    broker_root.mkdir(mode=0o700)
    session_root.mkdir(mode=0o700)
    broker_requests: list[dict[str, Any]] = []
    broker_ready = threading.Event()
    broker_thread = threading.Thread(
        target=_serve_broker,
        args=(broker_root / "broker.sock", broker_requests, broker_ready),
        daemon=True,
    )
    broker_thread.start()
    assert broker_ready.wait(timeout=2)
    monkeypatch.setenv(API_KEY_ENV, "test_only_not_a_secret")
    monkeypatch.setenv(BASE_URL_ENV, f"http://{gateway}:{provider.server_port}/v1")
    settings = resolve_settings(
        {
            "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
            "model_id": DEEPSEEK_HARNESS_MODEL,
            "max_process_time_s": 120,
        },
        task_wall_time_s=120,
    )
    try:
        result = run_harness_helper(
            settings,
            mode="run",
            prompt="Call finish once for fake-provider conformance.",
            system_prompt="Use exactly one typed finish action and no prose.",
            session_id="fake-provider-conformance",
            session_root=session_root,
            broker_root=broker_root,
        )
    finally:
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)
    broker_thread.join(timeout=2)

    assert result.finish_reason == "completed", {
        "events": result.events,
        "provider_requests": _ProviderHandler.requests,
        "broker_requests": broker_requests,
    }
    assert result.final_response == ""
    assert result.provider_request_started is True
    assert json.loads((session_root / "provider-request-started-v1.json").read_text()) == {
        "format_id": "verigym_deepseek_harness_provider_request_started_v1",
        "provider_request_ordinal": 1,
    }
    assert broker_requests == [
        {
            "id": "call-finish",
            "name": "finish",
            "arguments": {"summary": "fake conformance complete"},
        }
    ]
    assert len(_ProviderHandler.requests) == 1
    request = _ProviderHandler.requests[0]
    assert request["model"] == DEEPSEEK_HARNESS_MODEL
    assert request["temperature"] == 0
    assert request["max_tokens"] == 2048
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}
    assert "reasoning_effort" not in request
    assert [item["function"]["name"] for item in request["tools"]] == list(
        DEEPSEEK_HARNESS_TOOL_NAMES
    )
    assert [message["role"] for message in request["messages"]] == ["system", "user"]
    transcript = build_deepseek_harness_transcript(
        task_id="hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
        system_prompt="Use exactly one typed finish action and no prose.",
        task_prompt="Call finish once for fake-provider conformance.",
        session_events=result.events,
        broker_events=[
            HweNormalizedEvent(
                sequence=0,
                action="finish",
                arguments={"summary": "fake conformance complete"},
                workspace_epoch_before=0,
                workspace_epoch_after=0,
                compact_observation_sha256=hashlib.sha256(b"No candidate diff.").hexdigest(),
                event_mapping="deepseek_harness_native_tool",
            )
        ],
        broker_call_ids=["call-finish"],
        harness_identity=settings.harness_identity(),
    )
    assert transcript["causal_validation"] == "passed"
    assert len(transcript["normalized_events"]) == 1


@pytest.mark.docker
def test_official_harness_v3_recovers_one_text_only_interval_in_same_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = subprocess.run(
        [
            "docker",
            "network",
            "inspect",
            "verigym-hwe-net",
            "--format",
            "{{(index .IPAM.Config 0).Gateway}}",
        ],
        capture_output=True,
        check=False,
        text=True,
    ).stdout.strip()
    if not gateway:
        pytest.skip("verigym-hwe-net has no reachable gateway")
    _ProviderHandler.requests = []
    _ProviderHandler.recovery_mode = True
    provider = ThreadingHTTPServer(("0.0.0.0", 0), _ProviderHandler)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    broker_root = tmp_path / "broker"
    session_root = tmp_path / "sessions"
    broker_root.mkdir(mode=0o700)
    session_root.mkdir(mode=0o700)
    broker_requests: list[dict[str, Any]] = []
    broker_ready = threading.Event()
    broker_thread = threading.Thread(
        target=_serve_broker,
        args=(broker_root / "broker.sock", broker_requests, broker_ready),
        daemon=True,
    )
    broker_thread.start()
    assert broker_ready.wait(timeout=2)
    monkeypatch.setenv(API_KEY_ENV, "test_only_not_a_secret")
    monkeypatch.setenv(BASE_URL_ENV, f"http://{gateway}:{provider.server_port}/v1")
    settings = resolve_settings(
        {
            "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
            "model_id": DEEPSEEK_HARNESS_MODEL,
            "max_process_time_s": 120,
        },
        task_wall_time_s=120,
    )
    try:
        result = run_harness_helper(
            settings,
            mode="run",
            prompt="Repair the fake-provider task and finish.",
            system_prompt="Public text plus typed tools are allowed; finish with a tool call.",
            session_id="fake-provider-v3-recovery",
            session_root=session_root,
            broker_root=broker_root,
            max_format_repairs=1,
        )
    finally:
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)
        _ProviderHandler.recovery_mode = False
    broker_thread.join(timeout=2)

    assert result.finish_reason == "completed"
    assert result.final_response == "Recovered with a typed finish."
    assert result.provider_request_started is True
    assert result.run_interval_count == 2
    assert len(result.format_repairs) == 1
    assert result.format_repairs[0].startswith("VERIGYM_HWE_FORMAT_RECOVERY_V1:")
    assert len(_ProviderHandler.requests) == 2
    assert [message["role"] for message in _ProviderHandler.requests[1]["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert broker_requests == [
        {
            "id": "call-finish",
            "name": "finish",
            "arguments": {"summary": "fake conformance complete"},
        }
    ]
    transcript = build_deepseek_harness_transcript_v3(
        task_id="hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
        system_prompt="Public text plus typed tools are allowed; finish with a tool call.",
        task_prompt="Repair the fake-provider task and finish.",
        session_events=result.events,
        broker_events=[
            HweNormalizedEvent(
                sequence=0,
                action="finish",
                arguments={"summary": "fake conformance complete"},
                workspace_epoch_before=0,
                workspace_epoch_after=0,
                compact_observation_sha256=hashlib.sha256(b"No candidate diff.").hexdigest(),
                event_mapping="deepseek_harness_native_tool",
            )
        ],
        broker_call_ids=["call-finish"],
        harness_identity=settings.harness_identity(),
        format_repair_prompts=result.format_repairs,
    )
    assert transcript["assistant_decision_count"] == 2
    assert transcript["supervised_decision_count"] == 1
    assert transcript["masked_format_error_decision_count"] == 1
    assert transcript["format_repair_count"] == 1
