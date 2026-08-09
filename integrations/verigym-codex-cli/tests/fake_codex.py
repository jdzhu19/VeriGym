#!/usr/bin/env python3
"""Offline fake for Codex CLI protocol, policy, and failure tests.

The executable intentionally uses Python 3.6-compatible syntax so the safe
subprocess PATH can select a minimal system interpreter on older hosts.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main():
    arguments = sys.argv[1:]
    scenario = os.environ.get("VERIGYM_FAKE_CODEX_SCENARIO", "valid")
    if arguments == ["--version"]:
        print("fake-codex 1.2.3")
        _log({"kind": "diagnostic", "command": "version"})
        return 0
    if arguments == ["--help"]:
        print(_top_help(scenario))
        _log({"kind": "diagnostic", "command": "help"})
        return 0
    if arguments == ["exec", "--help"]:
        if scenario == "unsupported_noninteractive":
            print("exec unavailable", file=sys.stderr)
            return 2
        print(_exec_help(scenario))
        _log({"kind": "diagnostic", "command": "exec_help"})
        return 0
    if arguments == ["login", "status"]:
        _log({"kind": "diagnostic", "command": "login_status"})
        if scenario == "unauthenticated":
            print("Not logged in", file=sys.stderr)
            return 1
        print("Logged in using ChatGPT")
        return 0
    if not arguments or arguments[0] != "exec":
        print("unsupported fake invocation", file=sys.stderr)
        return 2
    prompt = sys.stdin.read()
    cwd = Path.cwd()
    initial_files = sorted(
        path.relative_to(cwd).as_posix() for path in cwd.rglob("*") if path.is_file()
    )
    model = _argument_value(arguments, "--model", "-m") or "fake-unconfigured"
    explicit_reasoning_effort = _config_value(arguments, "model_reasoning_effort")
    inherited_reasoning_effort = (
        _inherited_reasoning_effort() if scenario == "require_xhigh_override" else None
    )
    effective_reasoning_effort = explicit_reasoning_effort or inherited_reasoning_effort
    reasoning_effort_source = (
        "verigym_explicit_cli_override"
        if explicit_reasoning_effort is not None
        else "inherited_codex_config"
        if inherited_reasoning_effort is not None
        else "unspecified"
    )
    model_record = {
        "kind": "model",
        "arguments": arguments,
        "cwd": str(cwd),
        "initial_files": initial_files,
        "prompt": prompt,
        "scenario": scenario,
        "environment_names": sorted(os.environ),
        "environment_path": os.environ.get("PATH"),
        "unrelated_secret_visible": "VERIGYM_UNRELATED_SECRET" in os.environ,
        "requested_reasoning_effort": explicit_reasoning_effort,
        "effective_reasoning_effort": effective_reasoning_effort,
        "reasoning_effort_source": reasoning_effort_source,
    }
    if scenario == "timeout_partial_malformed":
        # Emit before writing the diagnostic log so a busy audit filesystem cannot
        # consume the entire deliberately short timeout window.
        _emit(
            {
                "type": "thread.started",
                "thread_id": "must-not-be-inferred",
                "model": model,
            }
        )
        print("{not-json", flush=True)
        _log(model_record)
        time.sleep(10)
        return 0
    _log(model_record)
    if scenario == "require_xhigh_override" and explicit_reasoning_effort != "xhigh":
        _emit(
            {
                "type": "error",
                "message": "explicit model_reasoning_effort xhigh override is required",
            }
        )
        return 1
    if scenario == "timeout":
        time.sleep(10)
        return 0
    if scenario == "orphan":
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                ("import signal,time;signal.signal(signal.SIGTERM, signal.SIG_IGN);time.sleep(30)"),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _log({"kind": "orphan", "pid": child.pid})
        return 0
    if scenario in {
        "agent_good",
        "agent_bad",
        "agent_symlink",
        "agent_hardlink",
        "agent_credential_file",
        "agent_internal_file",
    }:
        _edit_workspace(cwd, good=scenario == "agent_good")
    if scenario == "agent_symlink":
        (cwd / "rtl" / "escape.v").symlink_to("/etc/passwd")
    if scenario == "agent_hardlink":
        candidate = next((cwd / "rtl").glob("*.v"))
        os.link(candidate, cwd / "rtl" / "hardlink.v")
    if scenario == "agent_credential_file":
        (cwd / "rtl" / ".env").write_text("SAFE_TEST_VALUE=1\n", encoding="utf-8")
    if scenario == "agent_internal_file":
        (cwd / ".verigym_internal" / "agent-data").write_text(
            "must not survive\n",
            encoding="utf-8",
        )
    if scenario == "malformed":
        print("{not-json")
        return 0
    if scenario == "oversized":
        print(json.dumps({"type": "unknown", "payload": "x" * (2 * 1024 * 1024)}))
        return 0
    if scenario == "oversized_stderr":
        print("x" * (2 * 1024 * 1024), file=sys.stderr)
        return 1
    if scenario == "deep_event":
        value = {"leaf": True}
        for _ in range(40):
            value = {"nested": value}
        _emit({"type": "unknown", "payload": value})
        return 0
    if scenario == "unknown_flood":
        for index in range(10_001):
            _emit({"type": "future.event", "sequence": index})
        return 0
    if scenario == "secret_output":
        _emit({"type": "error", "message": "Bearer sk-FAKESECRET0123456789"})
        return 1
    if scenario == "credential_output":
        _emit(
            {
                "type": "error",
                "message": os.environ.get("OPENAI_API_KEY", "credential-unavailable"),
            }
        )
        return 1
    if scenario == "proxy_output":
        proxy_values = [
            os.environ.get(name, "")
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
            if name in os.environ
        ]
        _emit({"type": "error", "message": " | ".join(proxy_values)})
        print("proxy diagnostics: " + " | ".join(proxy_values), file=sys.stderr)
        return 1
    if scenario == "auth_error":
        _emit({"type": "error", "message": "authentication unavailable (401)"})
        print("login required", file=sys.stderr)
        return 1
    if scenario == "rate_limit":
        _emit({"type": "error", "message": "rate limit (429)"})
        return 1
    if scenario == "transport_error":
        _emit({"type": "error", "message": "network connection unavailable (503)"})
        return 1
    if scenario == "nonzero":
        _emit({"type": "error", "message": "remote process failed"})
        return 7

    _emit(
        {
            "type": "thread.started",
            "thread_id": f"fake-{scenario}",
            "model": model,
        }
    )
    _emit({"type": "turn.started"})
    _emit(
        {
            "type": "item.completed",
            "item": {
                "type": "reasoning",
                "text": "private fake reasoning must never persist",
            },
        }
    )
    if scenario == "unknown_event":
        _emit({"type": "future.event", "payload": {"safe": True}})
    if scenario == "message_delta":
        _emit({"type": "message.delta", "text": "partial response"})
    if scenario == "tool_use":
        _emit(
            {
                "type": "item.started",
                "item": {"type": "command_execution", "command": "ls", "status": "running"},
            }
        )
        _emit(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "ls",
                    "status": "completed",
                    "exit_code": 0,
                },
            }
        )
    if scenario == "path_escape":
        _emit(
            {
                "type": "item.completed",
                "item": {"type": "file_read", "path": "/etc/passwd"},
            }
        )
    if scenario in {"agent_bwrap", "agent_bwrap_unsafe_command"}:
        command = "printf test"
        if scenario == "agent_bwrap_unsafe_command":
            command = "/bin/bash -lc \"sed -n '1p' rtl/and_gate.v\nsed -n '1p' README.md\""
        _emit(
            {
                "type": "item.started",
                "item": {
                    "type": "command_execution",
                    "command": command,
                    "status": "running",
                },
            }
        )
        _emit(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": command,
                    "status": "failed",
                    "exit_code": 1,
                    "aggregated_output": (
                        "bwrap: Creating new namespace failed: Operation not permitted"
                    ),
                },
            }
        )
    if scenario == "agent_legacy_landlock_incompatible":
        _emit(
            {
                "type": "item.started",
                "item": {
                    "type": "file_change",
                    "changes": [{"path": "rtl/and_gate.v", "kind": "update"}],
                    "status": "in_progress",
                },
            }
        )
        _emit(
            {
                "type": "item.completed",
                "item": {
                    "type": "file_change",
                    "changes": [{"path": "rtl/and_gate.v", "kind": "update"}],
                    "status": "failed",
                },
            }
        )
        print(
            "permission profiles requiring direct runtime enforcement are incompatible "
            "with --use-legacy-landlock",
            file=sys.stderr,
        )
    if scenario == "agent_landlock_unavailable":
        print(
            "error applying legacy Linux sandbox restrictions: Sandbox(LandlockRestrict)",
            file=sys.stderr,
        )
    if scenario == "agent_mcp":
        _emit(
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "name": "list_mcp_resources",
                    "status": "completed",
                },
            }
        )
    if scenario in {
        "agent_good",
        "agent_bad",
        "agent_credential_file",
    }:
        changed = "rtl/and_gate.v" if (cwd / "rtl" / "and_gate.v").is_file() else "rtl/counter.v"
        _emit(
            {
                "type": "item.completed",
                "item": {
                    "type": "file_change",
                    "changes": [{"path": changed, "kind": "update"}],
                    "status": "completed",
                },
            }
        )
    text = (
        "External workspace update complete." if (cwd / "rtl").is_dir() else _model_response(prompt)
    )
    _emit(
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": text},
        }
    )
    if scenario == "multiple_final":
        _emit(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "second final"},
            }
        )
    usage = None if scenario == "unknown_usage" else {"input_tokens": 11, "output_tokens": 7}
    completed = {"type": "turn.completed"}
    if usage is not None:
        completed["usage"] = usage
    _emit(completed)
    return 0


def _top_help(scenario):
    approval = (
        ""
        if scenario == "unsupported_approval"
        else "\n  -a, --ask-for-approval <POLICY> [untrusted, on-request, never]"
    )
    return (
        "Codex CLI\n"
        "Usage: codex [OPTIONS] [COMMAND]\n"
        "  -c, --config <key=value> Override configuration\n"
        "  -m, --model <MODEL> Select model\n"
        "  -s, --sandbox <MODE> [read-only, workspace-write, danger-full-access]" + approval
    )


def _exec_help(scenario):
    json_flag = "" if scenario == "unsupported_json" else "\n      --json Emit JSONL events"
    sandbox_values = (
        "[read-only]"
        if scenario == "unsupported_sandbox"
        else "[read-only, workspace-write, danger-full-access]"
    )
    ephemeral = "" if scenario == "unsupported_ephemeral" else "\n      --ephemeral"
    return (
        "Run Codex non-interactively\n"
        "Usage: codex exec [OPTIONS] [PROMPT]\n"
        "If PROMPT is '-' instructions are read from stdin.\n"
        "  -c, --config <key=value>\n"
        "  -m, --model <MODEL>\n"
        f"  -s, --sandbox <MODE> {sandbox_values}\n"
        "  -a, --ask-for-approval <POLICY> [untrusted, on-request, never]\n"
        "      --skip-git-repo-check\n"
        "      --strict-config\n"
        "      --ignore-user-config\n"
        "      --ignore-rules"
        f"{json_flag}{ephemeral}"
    )


def _edit_workspace(cwd, *, good):
    and_gate = cwd / "rtl" / "and_gate.v"
    counter = cwd / "rtl" / "counter.v"
    if and_gate.is_file():
        expression = "a & b" if good else "a | b"
        and_gate.write_text(
            "module and_gate (\n"
            "    input wire a,\n"
            "    input wire b,\n"
            "    output wire y\n"
            ");\n"
            f"    assign y = {expression};\n"
            "endmodule\n",
            encoding="utf-8",
        )
    elif counter.is_file():
        body = (
            "        if (reset) begin\n"
            "            q <= 8'h00;\n"
            "        end else begin\n"
            "            q <= q + 8'h01;\n"
            "        end\n"
            if good
            else "        q <= 8'h00;\n"
        )
        counter.write_text(
            "module counter (\n"
            "    input wire clk,\n"
            "    input wire reset,\n"
            "    output reg [7:0] q\n"
            ");\n\n"
            "    always @(posedge clk) begin\n"
            f"{body}"
            "    end\n"
            "endmodule\n",
            encoding="utf-8",
        )


def _model_response(prompt):
    if "counter" in prompt.lower():
        return (
            "module counter (\n"
            "    input wire clk,\n"
            "    input wire reset,\n"
            "    output reg [7:0] q\n"
            ");\n"
            "    always @(posedge clk) begin\n"
            "        if (reset) q <= 8'h00;\n"
            "        else q <= q + 8'h01;\n"
            "    end\n"
            "endmodule\n"
        )
    return (
        "module and_gate (\n"
        "    input wire a,\n"
        "    input wire b,\n"
        "    output wire y\n"
        ");\n"
        "    assign y = a & b;\n"
        "endmodule\n"
    )


def _argument_value(arguments, *flags):
    for flag in flags:
        if flag in arguments:
            index = arguments.index(flag)
            if index + 1 < len(arguments):
                return arguments[index + 1]
    return None


def _config_value(arguments, key):
    value = None
    for index, argument in enumerate(arguments[:-1]):
        if argument not in {"--config", "-c"}:
            continue
        candidate = arguments[index + 1]
        prefix = key + "="
        if not candidate.startswith(prefix):
            continue
        value = candidate[len(prefix) :]
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
    return value


def _inherited_reasoning_effort():
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home is None:
        return None
    config = Path(codex_home) / "config.toml"
    if not config.is_file():
        return None
    with config.open(encoding="utf-8") as stream:
        for line in stream:
            stripped = line.strip()
            if not stripped.startswith("model_reasoning_effort"):
                continue
            _, _, raw = stripped.partition("=")
            value = raw.strip().split("#", 1)[0].strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                return value[1:-1]
    return None


def _emit(value):
    print(json.dumps(value, sort_keys=True), flush=True)


def _log(value):
    path = os.environ.get("VERIGYM_FAKE_CODEX_LOG")
    if path is None:
        return
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    raise SystemExit(main())
