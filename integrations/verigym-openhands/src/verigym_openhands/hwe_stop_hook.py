"""Broker-aware OpenHands Stop hook with one fail-closed same-session recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import stat
from pathlib import Path
from typing import Any

TERMINAL_STATUS_OPERATION = "verigym_hwe_terminal_status_v1"
OPENHANDS_FORMAT_RECOVERY_POLICY = "openhands_broker_stop_hook_recovery_v1"
OPENHANDS_FORMAT_RECOVERY_BUDGET = 1
OPENHANDS_FORMAT_RECOVERY_REASON = (
    "Your previous response did not call a tool. Continue in this same session with exactly "
    "one typed tool call and no prose. If the task is complete, call finish."
)
OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256 = hashlib.sha256(
    f"[Stop hook feedback] {OPENHANDS_FORMAT_RECOVERY_REASON}".encode()
).hexdigest()
_MAX_STATUS_BYTES = 4096


def query_terminal_status(socket_path: Path) -> dict[str, bool]:
    """Read the content-free terminal state from the private HWE broker socket."""

    if socket_path.is_symlink():
        raise ValueError("broker socket cannot be a symlink")
    metadata = os.lstat(socket_path)
    if not stat.S_ISSOCK(metadata.st_mode):
        raise ValueError("broker status endpoint is not a socket")
    payload = (
        json.dumps({"operation": TERMINAL_STATUS_OPERATION}, separators=(",", ":")).encode() + b"\n"
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2.0)
        client.connect(str(socket_path))
        client.sendall(payload)
        response = _receive(client)
    decoded = json.loads(response)
    fields = ("finished", "policy_failed", "infrastructure_failed")
    if (
        not isinstance(decoded, dict)
        or decoded.get("ok") is not True
        or any(not isinstance(decoded.get(field), bool) for field in fields)
    ):
        raise ValueError("broker terminal status response is malformed")
    return {field: decoded[field] for field in fields}


def evaluate_stop(socket_path: Path, state_path: Path) -> tuple[int, dict[str, str]]:
    """Return the hook exit code and structured verdict without leaking broker details."""

    try:
        status = query_terminal_status(socket_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return 1, {"decision": "allow", "reason": "broker terminal status unavailable"}
    if status["finished"]:
        return 0, {"decision": "allow", "reason": "broker typed finish observed"}
    if status["policy_failed"] or status["infrastructure_failed"]:
        return 0, {"decision": "allow", "reason": "broker terminal failure observed"}
    try:
        _claim_recovery(state_path)
    except FileExistsError:
        return 0, {"decision": "allow", "reason": "format recovery budget exhausted"}
    except OSError:
        return 1, {"decision": "allow", "reason": "format recovery state unavailable"}
    return 2, {"decision": "deny", "reason": OPENHANDS_FORMAT_RECOVERY_REASON}


def _claim_recovery(path: Path) -> None:
    if path.exists() or path.is_symlink():
        metadata = os.lstat(path)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise OSError("format recovery state is unsafe")
        raise FileExistsError(path)
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir() or path.parent.is_symlink():
        raise OSError("format recovery state parent is unsafe")
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_format_recovery_state_v1",
        "policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
        "recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
        "recovery_count": 1,
        "model_visible_message_sha256": OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256,
        "same_session": True,
        "whole_episode_retries": 0,
    }
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_recovery_count(path: Path) -> int:
    """Validate the private recovery state and return its frozen count."""

    if not path.exists() and not path.is_symlink():
        return 0
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("OpenHands format recovery state is unsafe")
    if metadata.st_size <= 0 or metadata.st_size > _MAX_STATUS_BYTES:
        raise ValueError("OpenHands format recovery state size is invalid")
    value = json.loads(path.read_bytes())
    expected = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_format_recovery_state_v1",
        "policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
        "recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
        "recovery_count": 1,
        "model_visible_message_sha256": OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256,
        "same_session": True,
        "whole_episode_retries": 0,
    }
    if value != expected:
        raise ValueError("OpenHands format recovery state changed")
    return 1


def _receive(client: socket.socket) -> bytes:
    data = bytearray()
    while len(data) <= _MAX_STATUS_BYTES:
        block = client.recv(min(4096, _MAX_STATUS_BYTES + 1 - len(data)))
        if not block:
            break
        data.extend(block)
        if data.endswith(b"\n"):
            break
    if len(data) > _MAX_STATUS_BYTES or not data.endswith(b"\n"):
        raise ValueError("invalid broker terminal status framing")
    return bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    arguments = parser.parse_args()
    exit_code, result = evaluate_stop(arguments.socket, arguments.state)
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()


__all__ = [
    "TERMINAL_STATUS_OPERATION",
    "evaluate_stop",
    "query_terminal_status",
    "read_recovery_count",
]
