"""Minimal MCP stdio server for the private canonical repository broker."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any

from verigym.protocols.repository_action import repository_tool_definitions

_MAX_MESSAGE_BYTES = 2 * 1024 * 1024


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--codex-compatible-patch", action="store_true")
    arguments = parser.parse_args()
    tool_definitions = repository_tool_definitions(
        dialect="mcp",
        patch_format_profile=(
            "strict_unified_and_codex_native_v1"
            if arguments.codex_compatible_patch
            else "strict_unified_v1"
        ),
    )
    while True:
        raw = sys.stdin.buffer.readline(_MAX_MESSAGE_BYTES + 1)
        if not raw:
            return
        if len(raw) > _MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
            return
        try:
            request = json.loads(raw)
            response = _handle(request, arguments.socket, tool_definitions)
        except Exception as exc:
            response = _error(None, -32603, f"MCP adapter error: {type(exc).__name__}")
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":"), ensure_ascii=False) + "\n")
            sys.stdout.flush()


def _handle(
    request: Any,
    socket_path: Path,
    tool_definitions: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if tool_definitions is None:
        tool_definitions = repository_tool_definitions(dialect="mcp")
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _error(None, -32600, "invalid JSON-RPC request")
    request_id = request.get("id")
    method = request.get("method")
    if method == "initialize":
        params = request.get("params")
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        protocol = requested if isinstance(requested, str) else "2024-11-05"
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "verigym", "version": "0.1.0"},
            },
        }
    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tool_definitions}}
    if method == "tools/call":
        params = request.get("params")
        if not isinstance(params, dict):
            return _error(request_id, -32602, "tool parameters must be an object")
        result = _forward(socket_path, {**params, "tool_call_id": str(request_id)})
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return _error(request_id, -32601, "method not found")


def _forward(socket_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    request = json.dumps(params, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
    if len(request) > _MAX_MESSAGE_BYTES:
        return _tool_error("tool request exceeds the broker bound")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1810.0)
            client.connect(str(socket_path))
            client.sendall(request)
            payload = json.loads(_receive_line(client))
    except Exception as exc:
        return _tool_error(f"broker unavailable: {type(exc).__name__}")
    if not isinstance(payload, dict):
        return _tool_error("broker returned an invalid response")
    return payload


def _receive_line(client: socket.socket) -> bytes:
    data = bytearray()
    while len(data) <= _MAX_MESSAGE_BYTES:
        block = client.recv(min(65536, _MAX_MESSAGE_BYTES + 1 - len(data)))
        if not block:
            break
        data.extend(block)
        if data.endswith(b"\n"):
            break
    if len(data) > _MAX_MESSAGE_BYTES or not data.endswith(b"\n"):
        raise ValueError("invalid broker response framing")
    return bytes(data)


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


if __name__ == "__main__":
    main()
