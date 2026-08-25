from __future__ import annotations

from pathlib import Path
from typing import Any

from verigym_openhands import hwe_mcp_stdio, repository_mcp_stdio


def _request(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def test_repository_mcp_strips_only_openhands_metadata(monkeypatch) -> None:
    observed: dict[str, Any] = {}

    def forward(_socket: Path, params: dict[str, Any]) -> dict[str, Any]:
        observed.update(params)
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    monkeypatch.setattr(repository_mcp_stdio, "_forward", forward)
    response = repository_mcp_stdio._handle(
        _request(
            "finish",
            {
                "message": "done",
                "summary": "OpenHands display metadata",
                "security_risk": "LOW",
            },
        ),
        Path("broker.sock"),
    )

    assert response is not None and "result" in response
    assert observed == {
        "name": "finish",
        "arguments": {"message": "done"},
        "tool_call_id": "7",
    }


def test_hwe_mcp_preserves_semantic_finish_summary() -> None:
    shell = hwe_mcp_stdio._sanitized_broker_call(
        {
            "name": "shell",
            "arguments": {
                "command": "rg -n csr rtl",
                "summary": "search RTL",
                "security_risk": "LOW",
            },
        }
    )
    finish = hwe_mcp_stdio._sanitized_broker_call(
        {
            "name": "finish",
            "arguments": {"summary": "validated", "security_risk": "LOW"},
        }
    )

    assert shell == ("shell", {"command": "rg -n csr rtl"})
    assert finish == ("finish", {"summary": "validated"})
