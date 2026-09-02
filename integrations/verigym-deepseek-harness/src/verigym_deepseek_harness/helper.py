#!/usr/bin/env python3
"""Sanitized child process that drives the pinned SDK through a controller container."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from deepseek_harness import (  # type: ignore[import-not-found]
    DeepSeekHarness,
    DeepSeekHarnessConfig,
)

_REVISION = "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e"
_MODEL = "deepseek-v4-flash"
_CONTROLLER = "sha256:daa74c183f7d8c1ba55ed79c76e912f50be8782ca9d2da640645f906dce474b8"
_NETWORK = "verigym-hwe-net"
# The source root is mounted read-only, so Docker cannot create a new nested mount point.
# Overlay the existing official example directory; bare packages then resolve through the
# checkout's ``examples/node_modules`` exactly as the upstream standalone example does.
_RUNTIME_ASSETS_TARGET = "/workspace/examples/jsonrpc-agent"
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
_FORMAT_RECOVERY_PROMPT = (
    "VERIGYM_HWE_FORMAT_RECOVERY_V1: The previous assistant turn ended without an "
    "executable typed-tool action. Continue the same task and call a typed HWE tool now. "
    "Prefer exactly one tool call; if the repair is complete, call finish. Do not repeat the "
    "task, ask a question, or provide a text-only answer."
)
_PROVIDER_MARKER = "/sessions/provider-request-started-v1.json"


def main() -> int:
    try:
        request = _request()
        result = _run(request)
    except Exception as exc:
        result = {
            "ok": False,
            "error_type": type(exc).__name__,
            "message": "DeepSeek Harness controller execution failed closed",
        }
    sys.stdout.write(json.dumps(result, separators=(",", ":"), ensure_ascii=False) + "\n")
    return 0 if result.get("ok") is True else 1


def _request() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
    if not raw or len(raw) > 4 * 1024 * 1024:
        raise ValueError("invalid helper request size")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("helper request must be an object")
    allowed = {
        "mode",
        "prompt",
        "session_id",
        "source_root",
        "runtime_assets",
        "session_root",
        "broker_root",
        "controller_image_id",
        "system_prompt",
        "max_format_repairs",
    }
    if set(value) - allowed:
        raise ValueError("helper request has unknown fields")
    return value


def _run(request: dict[str, Any]) -> dict[str, Any]:
    mode = request.get("mode")
    if mode not in {"initialize", "run"}:
        raise ValueError("helper mode is invalid")
    source_root = _directory(request.get("source_root"), "source_root")
    if source_root.name != _REVISION:
        raise ValueError("helper source revision changed")
    runtime_assets = _directory(request.get("runtime_assets"), "runtime_assets")
    session_root = _private_directory(request.get("session_root"), "session_root")
    broker_root = _private_directory(request.get("broker_root"), "broker_root")
    controller = request.get("controller_image_id")
    if controller != _CONTROLLER:
        raise ValueError("helper controller identity changed")
    session_id = request.get("session_id")
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        raise ValueError("helper session id is invalid")
    system_prompt = request.get("system_prompt")
    if (
        not isinstance(system_prompt, str)
        or not system_prompt.strip()
        or len(system_prompt.encode("utf-8")) > 1024 * 1024
    ):
        raise ValueError("helper system prompt is invalid")
    prompt = request.get("prompt")
    if mode == "run" and (
        not isinstance(prompt, str)
        or not prompt.strip()
        or len(prompt.encode("utf-8")) > 2 * 1024 * 1024
    ):
        raise ValueError("helper task prompt is invalid")
    max_format_repairs = request.get("max_format_repairs", 0)
    if not isinstance(max_format_repairs, int) or max_format_repairs not in {0, 1}:
        raise ValueError("helper format repair budget is invalid")
    if not os.environ.get("DEEPSEEK_API_KEY") or not os.environ.get("DEEPSEEK_BASE_URL"):
        raise ValueError("helper provider environment is incomplete")

    cidfile = session_root / "controller.cid"
    if cidfile.exists():
        raise ValueError("helper controller cidfile already exists")
    launch = _controller_arguments(
        source_root=source_root,
        runtime_assets=runtime_assets,
        session_root=session_root,
        broker_root=broker_root,
        cidfile=cidfile,
    )
    config = DeepSeekHarnessConfig(
        provider="deepseek-official",
        model=_MODEL,
        max_tokens=2048,
        cwd="/workspace",
        runtime_cwd=str(source_root),
        session_root="/sessions",
        cordis=f"{_RUNTIME_ASSETS_TARGET}/cordis.yml",
        env={
            "DSH_BROKER_SOCKET": "/broker/broker.sock",
            "DSH_PROVIDER_START_MARKER": _PROVIDER_MARKER,
            "DSH_SYSTEM_PROMPT": system_prompt,
        },
        launch_args_override=tuple(launch),
        request_timeout_seconds=3600,
        shutdown_timeout_seconds=10,
    )
    try:
        with DeepSeekHarness(config) as harness:
            if mode == "initialize":
                result: dict[str, Any] = {
                    "ok": True,
                    "initialized": True,
                    "events": [],
                    "format_repairs": [],
                    "run_interval_count": 0,
                }
            else:
                session = harness.start_session(session_id)
                runs = [session.run(str(prompt))]
                repair_prompts: list[str] = []
                while len(repair_prompts) < max_format_repairs and _needs_format_repair(
                    runs[-1].finish_reason,
                    runs[-1].events,
                ):
                    repair_prompts.append(_FORMAT_RECOVERY_PROMPT)
                    runs.append(session.run(_FORMAT_RECOVERY_PROMPT))
                run = runs[-1]
                result = {
                    "ok": True,
                    "initialized": True,
                    "session_id": run.session_id,
                    "finish_reason": run.finish_reason,
                    "final_response": run.final_response,
                    "events": [event for interval in runs for event in interval.events],
                    "format_repairs": repair_prompts,
                    "run_interval_count": len(runs),
                }
    finally:
        _remove_owned_controller(cidfile)
        _freeze_private_tree(session_root)
    return result


def _needs_format_repair(
    finish_reason: str | None,
    events: list[dict[str, Any]],
) -> bool:
    if finish_reason == "max-tokens":
        return True
    assistant_messages = [event for event in events if event.get("type") == "assistant/message"]
    if not assistant_messages:
        return True
    data = assistant_messages[-1].get("data")
    message = data.get("message") if isinstance(data, dict) else None
    blocks = message.get("content") if isinstance(message, dict) else None
    return not isinstance(blocks, list) or not any(
        isinstance(block, dict) and block.get("type") == "tool-call" for block in blocks
    )


def _controller_arguments(
    *,
    source_root: Path,
    runtime_assets: Path,
    session_root: Path,
    broker_root: Path,
    cidfile: Path,
) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--cidfile",
        str(cidfile),
        "--init",
        "--interactive",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "512",
        "--memory",
        "2g",
        "--cpus",
        "2",
        "--network",
        _NETWORK,
        "--user",
        "1004:100",
        "--workdir",
        "/workspace",
        "--label",
        "org.verigym.managed=true",
        "--label",
        "org.verigym.role=deepseek-harness-controller",
        "--mount",
        f"type=bind,source={source_root},target=/workspace,readonly",
        "--mount",
        f"type=bind,source={runtime_assets},target={_RUNTIME_ASSETS_TARGET},readonly",
        "--mount",
        f"type=bind,source={session_root},target=/sessions",
        "--mount",
        f"type=bind,source={broker_root},target=/broker",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=268435456,mode=1777",
        "--env",
        "DEEPSEEK_API_KEY",
        "--env",
        "DEEPSEEK_BASE_URL",
        "--env",
        "DSH_BROKER_SOCKET",
        "--env",
        "DSH_CORDIS_CONFIG",
        "--env",
        "DSH_CWD",
        "--env",
        "DSH_SESSION_ROOT",
        "--env",
        "DSH_PROVIDER_START_MARKER",
        "--env",
        "DSH_SYSTEM_PROMPT",
        "--env",
        "HOME=/tmp/dsh-home",
        "--env",
        "LANG=C.UTF-8",
        "--env",
        "LC_ALL=C.UTF-8",
        _CONTROLLER,
        "node",
        "--import",
        "tsx",
        "/workspace/packages/examples/jsonrpc-demo/src/bin.ts",
    ]


def _directory(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError(f"helper {label} must be absolute")
    requested = Path(value)
    metadata = os.lstat(requested)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"helper {label} is unsafe")
    return requested.resolve(strict=True)


def _private_directory(value: object, label: str) -> Path:
    path = _directory(value, label)
    os.chmod(path, 0o700)
    return path


def _remove_owned_controller(cidfile: Path) -> None:
    if not cidfile.is_file() or cidfile.is_symlink():
        return
    container_id = cidfile.read_text(encoding="utf-8").strip()
    if _CONTAINER_ID.fullmatch(container_id):
        subprocess.run(
            ["docker", "rm", "--force", container_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    cidfile.unlink(missing_ok=True)


def _freeze_private_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("helper private session tree contains a symlink")
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    os.chmod(root, 0o700)


if __name__ == "__main__":
    raise SystemExit(main())
