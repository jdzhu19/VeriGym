#!/usr/bin/env python3
"""Run one content-free Codex/MCP transport probe with bounded evidence only."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from verigym_codex_cli.agenteval_config import (
    AGENTEVAL_AGENT_VERSION_HASH,
    AGENTEVAL_AGENT_VERSION_ID,
    AGENTEVAL_PROMPT_HASH,
    AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    agenteval_settings,
)
from verigym_codex_cli.agenteval_invocation import (
    build_agenteval_arguments,
    sanitized_agenteval_invocation,
)
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.events import parse_event_stream
from verigym_codex_cli.process import CodexCliProcessRunner, auth_identity_configuration

from verigym.core.repository_tool_broker import (
    RepositoryToolBroker,
    RepositoryToolBrokerLimits,
)
from verigym.experiments.state import atomic_dump_json
from verigym.protocols.repository_action import repository_tool_definitions
from verigym.schemas.common import ErrorCategory
from verigym.schemas.tool import ToolResult

_CAMPAIGN_ID = "rtl-agenteval-codex-gpt54-xhigh-server-category-probe-v1"
_OUTPUT = Path("/data/jzhu484/Agent/experiments") / _CAMPAIGN_ID
_SCRATCH = Path("/data/jzhu484/Agent/.verigym-tmp")
_OPT_IN = "VERIGYM_RUN_CODEX_AGENT_EVAL_SERVER_PROBE_V1"
_CANONICAL_TOOLS = frozenset(item["name"] for item in repository_tool_definitions(dialect="mcp"))


class _ContentFreeBridge:
    def invoke_workspace_tool(self, tool: str, _arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(tool=tool, success=True, category=ErrorCategory.SUCCESS)


def _server_category(value: object) -> str:
    if value == "verigym":
        return "exact_verigym"
    if value == "codex_apps":
        return "codex_apps"
    if isinstance(value, str) and "verigym" in value.lower():
        return "verigym_alias"
    if isinstance(value, str) and value.startswith("mcp__"):
        return "other_namespaced"
    return "other"


def _completed_mcp_categories(stdout: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if (
            event.get("type") != "item.completed"
            or not isinstance(item, dict)
            or item.get("type") != "mcp_tool_call"
        ):
            continue
        tool = item.get("tool", item.get("name"))
        records.append(
            {
                "server_category": _server_category(item.get("server", item.get("server_name"))),
                "tool_category": "canonical" if tool in _CANONICAL_TOOLS else "other",
                "has_public_result": isinstance(item.get("result"), dict),
                "failed": item.get("status") == "failed" or item.get("error") is not None,
            }
        )
    return records


def main() -> int:
    if os.environ.get(_OPT_IN) != "1":
        raise RuntimeError(f"execution requires {_OPT_IN}=1")
    if _OUTPUT.exists() or _OUTPUT.is_symlink():
        raise RuntimeError("probe output must not already exist")
    _identity, capabilities = discover_capabilities(force=True)
    auth, _credential_env = auth_identity_configuration()
    options: dict[str, Any] = {
        "model_id": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "max_process_time_s": 180,
        "max_output_bytes": 8 * 1024 * 1024,
        "allow_proxy_environment": bool(
            os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        ),
        "expected_cli_version": "codex-cli 0.147.0",
        "expected_cli_executable_sha256": (
            "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"
        ),
        "expected_capability_fingerprint": capabilities.capability_fingerprint,
        "expected_prompt_hash": AGENTEVAL_PROMPT_HASH,
        "expected_tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        "expected_requested_auth_mode": auth.requested_auth_mode,
        "expected_resolved_auth_mode": auth.resolved_auth_mode,
        "expected_auth_semantic_id": auth.auth_semantic_id,
        "prompt_contract_id": "repository_action_v2_prompt_v6",
        "scoring_agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "scoring_agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
    }
    settings = agenteval_settings(options, capabilities, task_wall_time_s=180)
    prompt = (
        "Use only the VeriGym MCP tools. Call apply_patch once with a canonical unified diff "
        "for repository/probe.txt, then inspect_diff, then typed finish. Do not use any other "
        "tool and do not end before finish."
    )
    with tempfile.TemporaryDirectory(prefix="codex-server-probe-", dir=_SCRATCH) as raw:
        control = Path(raw)
        cwd = control / "cwd"
        cwd.mkdir(mode=0o700)
        broker = RepositoryToolBroker(
            bridge=_ContentFreeBridge(),  # type: ignore[arg-type]
            socket_path=control / "b" / "mcp.sock",
            public_test_ids=(),
            limits=RepositoryToolBrokerLimits(20, 5, 3),
            wall_time_s=180,
            finalization_reserve_s=settings.finalization_reserve_s,
            max_exploratory_calls=settings.max_exploratory_calls,
        )
        arguments = build_agenteval_arguments(
            capabilities,
            settings,
            socket_path=broker.socket_path,
        )
        invocation = sanitized_agenteval_invocation(arguments, settings, capabilities)
        runner = CodexCliProcessRunner(
            _identity,
            auth_mode=settings.execution.resolved_auth_mode,
            credential_env=settings.execution.credential_env,
            max_output_bytes=settings.execution.max_output_bytes,
            allow_proxy_environment=settings.execution.allow_proxy_environment,
        )
        broker.start()
        try:
            process = runner.run(
                arguments,
                cwd=cwd,
                timeout_s=180,
                stdin_bytes=prompt.encode(),
                cancellation_event=broker.cancellation_event,
            )
        finally:
            broker.stop()
        broker_stats = broker.stats()
    parsed = parse_event_stream(process.stdout)
    records = _completed_mcp_categories(process.stdout)
    category_counts = Counter(str(item["server_category"]) for item in records)
    summary = {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "model": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "codex_processes_authorized": 1,
        "codex_processes_started": 1,
        "automatic_retries": 0,
        "agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
        "prompt_hash": AGENTEVAL_PROMPT_HASH,
        "tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        "apps_enabled": invocation["apps_enabled"],
        "completed_mcp_calls": len(records),
        "server_category_counts": dict(sorted(category_counts.items())),
        "records": records,
        "broker_tool_calls": broker_stats.tool_calls,
        "broker_finished": broker_stats.finished,
        "exit_code": process.exit_code,
        "timed_out": process.timed_out,
        "provider_usage_complete": (
            parsed.input_tokens is not None and parsed.output_tokens is not None
        ),
        "raw_event_stream_persisted": False,
        "message_content_persisted": False,
        "reasoning_content_persisted": False,
    }
    _OUTPUT.mkdir(parents=True)
    atomic_dump_json(_OUTPUT / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if broker_stats.finished and not process.timed_out else 2


if __name__ == "__main__":
    raise SystemExit(main())
