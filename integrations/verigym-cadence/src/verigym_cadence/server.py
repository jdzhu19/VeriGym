"""Single-job MCP stdio server for approved SEC candidates; no automatic retries."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from verigym.plugin_api import CommandSpec
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.runtime import SessionSpec

from .protocol import (
    LICENSE_ENVIRONMENT_NAMES,
    MAX_REQUEST_BYTES,
    MCP_VERSION,
    SERVER_NAME,
    VERSION,
    IdentityRequest,
    Outcome,
    ServerProfile,
    Summary,
    VerifyRequest,
    VerifyResponse,
    load_profile,
    unique_json,
)


def worker_call(profile: ServerProfile, operation: str, request: VerifyRequest | None) -> Any:
    """Only the hash-pinned, operator-owned executable is invoked, with structured stdin."""
    profile.resolve()
    payload = {
        "operation": operation,
        "profile": profile.model_dump(),
        "request": request.model_dump() if request is not None else None,
    }
    with tempfile.TemporaryDirectory(prefix="jg-control-") as empty:
        with LocalRuntime().create_session(SessionSpec(source_dir=empty, label="jg-control")) as s:
            result = s.execute(
                CommandSpec(
                    argv=[profile.worker.path],
                    stdin=json.dumps(payload),
                    timeout_s=(
                        min(profile.timeout_s, 20) if operation == "probe" else profile.timeout_s
                    )
                    + 10,
                    # LocalRuntime deliberately strips ambient variables. The fixed site
                    # worker needs these two only; values never enter the JSON/profile/trace.
                    env={
                        name: os.environ[name]
                        for name in LICENSE_ENVIRONMENT_NAMES
                        if name in os.environ
                    },
                )
            )
    if result.timed_out:
        return {"status": "timeout"}
    if result.error or result.output_truncated or result.exit_code != 0:
        return {"status": "infrastructure_failure"}
    # Never relay private stdout/stderr, exception text, paths, or counterexamples.
    return unique_json(result.stdout)


class Service:
    def __init__(self, profile: ServerProfile) -> None:
        self.profile = profile
        self.initialized = False
        self.verified = False

    def resolve(self, request: IdentityRequest) -> Summary:
        summary = self.profile.resolve()
        if (
            request.profile_id != summary.profile_id
            or request.contract_hash != summary.contract_hash
            or request.declared_profile_hash != summary.declared_profile_hash
            or request.expected_resolved_profile_hash not in {None, summary.resolved_profile_hash}
        ):
            raise ValueError("profile identity mismatch")
        versions = worker_call(self.profile, "probe", None)
        if versions != {
            "tool_version": summary.tool_version,
            "yosys_version": summary.yosys_version,
        }:
            raise ValueError("tool identity unavailable or mismatched")
        return summary

    def verify(self, request: VerifyRequest) -> VerifyResponse:
        if self.verified:
            raise ValueError("one SEC invocation per server process")
        if request.expected_resolved_profile_hash is None:
            raise ValueError("verification requires resolved identity")
        candidate = request.candidate()
        if (
            request.task_id != self.profile.task_id
            or request.top != self.profile.top
            or list(candidate) != self.profile.sources
            or request.candidate_hash not in self.profile.approved_candidate_hashes
        ):
            raise ValueError("candidate is outside the approved fixture contract")
        summary = self.resolve(request)
        self.verified = True  # A failed/timeout job must not be retried in this invocation.
        outcome = Outcome.model_validate(worker_call(self.profile, "verify", request))
        if self.profile.resolve() != summary:
            raise ValueError("server identity changed during verification")
        return VerifyResponse(
            profile=summary, candidate_hash=request.candidate_hash, outcome=outcome
        )

    def handle(self, message: Any) -> dict[str, Any] | None:
        request_id = message.get("id") if isinstance(message, dict) else None
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        result: BaseModel
        definitions: list[tuple[str, str, type[BaseModel]]] = [
            ("resolve_profile", "Resolve fixed SEC profile; no license claim.", IdentityRequest),
            ("verify", "Verify one approved candidate; return only SEC status.", VerifyRequest),
        ]
        try:
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise ValueError("invalid framing")
            method = message.get("method")
            if method == "initialize" and not self.initialized:
                if message.get("params", {}).get("protocolVersion") != MCP_VERSION:
                    raise ValueError("unsupported protocol")
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
                            "inputSchema": schema.model_json_schema(),
                        }
                        for name, description, schema in definitions
                    ]
                }
            elif method == "tools/call" and self.initialized:
                params = message["params"]
                if set(params) != {"name", "arguments"}:
                    raise ValueError("invalid call fields")
                if params["name"] == "resolve_profile":
                    result = self.resolve(IdentityRequest.model_validate(params["arguments"]))
                elif params["name"] == "verify":
                    result = self.verify(VerifyRequest.model_validate(params["arguments"]))
                else:
                    raise ValueError("unsupported tool")
                response["result"] = {
                    "content": [],
                    "structuredContent": result.model_dump(),
                    "isError": False,
                }
            else:
                raise ValueError("unsupported request")
        except Exception:
            response["error"] = {"code": -32602, "message": "fixed SEC request rejected"}
        return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    try:
        service = Service(load_profile(args.profile))
        for _ in range(4):
            line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
                return 2
            response = service.handle(unique_json(line.decode("utf-8")))
            if response is not None:
                print(json.dumps(response, separators=(",", ":")), flush=True)
        return 0
    except Exception:
        print("SEC service unavailable", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
