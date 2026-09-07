"""One bounded Docker functional invocation per model-invisible MCP process."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from verigym_cadence.protocol import (
    MAX_REQUEST_BYTES,
    MCP_VERSION,
    IdentityRequest,
    bounded_read,
    unique_json,
)

from .functional import (
    SERVER_NAME,
    VERSION,
    FunctionalProfile,
    FunctionalRequest,
    FunctionalResponse,
    FunctionalSummary,
    run_functional,
)


class Service:
    def __init__(self, profile: FunctionalProfile) -> None:
        self.profile = profile
        self.initialized = False
        self.invoked = False

    def resolve(self, request: IdentityRequest, *, probe: bool = True) -> FunctionalSummary:
        summary = self.profile.summary()
        if (
            request.profile_id != summary.profile_id
            or request.declared_profile_hash != summary.declared_profile_hash
            or request.contract_hash != summary.contract_hash
            or request.expected_resolved_profile_hash not in {None, summary.resolved_profile_hash}
        ):
            raise ValueError("functional profile identity mismatch")
        if probe and run_functional(self.profile, None).status != "passed":
            raise ValueError("functional toolchain unavailable")
        return summary

    def verify(self, request: FunctionalRequest) -> FunctionalResponse:
        if self.invoked or request.expected_resolved_profile_hash is None:
            raise ValueError("one resolved functional invocation per process")
        candidate = request.candidate()
        if (
            request.task_id != self.profile.task_id
            or request.top != self.profile.top
            or list(candidate) != self.profile.sources
        ):
            raise ValueError("candidate differs from task contract")
        summary = self.resolve(request, probe=False)
        self.invoked = True
        outcome = run_functional(self.profile, candidate)
        if self.profile.summary() != summary:
            raise ValueError("functional profile changed during execution")
        return FunctionalResponse(
            profile=summary, candidate_hash=request.candidate_hash, outcome=outcome
        )

    def handle(self, message: Any) -> dict[str, Any] | None:
        request_id = message.get("id") if isinstance(message, dict) else None
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        try:
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise ValueError("invalid framing")
            method = message.get("method")
            if method == "initialize" and not self.initialized:
                if message.get("params", {}).get("protocolVersion") != MCP_VERSION:
                    raise ValueError("unsupported MCP protocol")
                self.initialized = True
                response["result"] = {
                    "protocolVersion": MCP_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": VERSION},
                }
            elif method == "notifications/initialized" and self.initialized and request_id is None:
                return None
            elif method == "tools/list" and self.initialized:
                response["result"] = {
                    "tools": [
                        {
                            "name": name,
                            "description": description,
                            "inputSchema": model.model_json_schema(),
                        }
                        for name, description, model in (
                            (
                                "resolve_profile",
                                "Resolve the fixed Docker functional toolchain.",
                                IdentityRequest,
                            ),
                            (
                                "verify",
                                "Run syntax/function checks; return status only.",
                                FunctionalRequest,
                            ),
                        )
                    ]
                }
            elif method == "tools/call" and self.initialized:
                params = message["params"]
                if set(params) != {"name", "arguments"}:
                    raise ValueError("unsupported fields")
                result: FunctionalSummary | FunctionalResponse
                if params["name"] == "resolve_profile":
                    result = self.resolve(IdentityRequest.model_validate(params["arguments"]))
                elif params["name"] == "verify":
                    result = self.verify(FunctionalRequest.model_validate(params["arguments"]))
                else:
                    raise ValueError("unsupported operation")
                response["result"] = {
                    "content": [],
                    "structuredContent": result.model_dump(),
                    "isError": False,
                }
            else:
                raise ValueError("unsupported method")
        except Exception:
            response["error"] = {"code": -32602, "message": "fixed functional request rejected"}
        return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    try:
        profile = FunctionalProfile.model_validate(unique_json(bounded_read(args.profile).decode()))
        service = Service(profile)
        for _ in range(4):
            line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
                return 2
            response = service.handle(unique_json(line.decode()))
            if response is not None:
                print(json.dumps(response, separators=(",", ":")), flush=True)
        return 0
    except Exception:
        print("functional service unavailable", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
