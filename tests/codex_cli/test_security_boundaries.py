from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from verigym_codex_cli import CodexCliReadonlyAgentAdapter
from verigym_codex_cli.capabilities import runtime_capabilities
from verigym_codex_cli.config import readonly_agent_settings
from verigym_codex_cli.events import EventParseError, parse_event_stream
from verigym_codex_cli.process import CodexCliProcessRunner, resolve_executable
from verigym_codex_cli.security import (
    CodexPolicyError,
    assert_instruction_isolation,
    assert_safe_workspace_tree,
    compare_workspace_snapshots,
    sandbox_backend_failure,
    snapshot_visible_workspace,
    validate_external_events,
)

from verigym.core.orchestrator import VeriGym
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunResult

pytestmark = pytest.mark.codex_cli

HISTORICAL_TRACK_B_COMMANDS = (
    Path(__file__).parents[1] / "fixtures" / "codex_cli" / "f6b159b_track_b_command_streams.json"
)


def _run_track_a(
    output: Path,
    *,
    model_id: str = "fake-model",
    allow_proxy_environment: bool = False,
) -> RunResult:
    registries = build_registries(discover_external=False)
    registries.agents.register(CodexCliReadonlyAgentAdapter())
    return VeriGym(registries).run(
        RunConfig(
            task_id="toy-rtl/and-gate-basic",
            mode=InteractionMode.AGENT,
            agent="codex-cli-readonly-agent",
            agent_options={
                "model_id": model_id,
                "sandbox": "read-only",
                "approval_policy": "non-interactive",
                "reasoning_effort": "xhigh",
                "allow_proxy_environment": allow_proxy_environment,
            },
            runtime="local",
            output=output,
        )
    )


@pytest.mark.parametrize(
    ("scenario_name", "category"),
    [
        ("auth_error", "authentication"),
        ("rate_limit", "rate_limit"),
        ("transport_error", "transport"),
        ("nonzero", "remote_process_error"),
    ],
)
def test_track_a_remote_failures_remain_structured_infrastructure(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
    scenario_name: str,
    category: str,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario(scenario_name)
    result = _run_track_a(tmp_path / "runs")
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == category
    assert result.scorecard.failure.infrastructure is True


@pytest.mark.parametrize("scenario_name", ["deep_event", "unknown_flood"])
def test_bounded_event_parser_rejects_adversarial_fake_streams(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
    scenario_name: str,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario(scenario_name)
    result = _run_track_a(tmp_path / "runs")
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "parser_error"


@pytest.mark.requires_iverilog
def test_known_message_delta_does_not_invalidate_final_text(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("message_delta")
    result = _run_track_a(tmp_path / "runs")
    assert result.scorecard.status == "completed"


def test_unknown_event_fails_closed(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("unknown_event")
    result = _run_track_a(tmp_path / "runs")
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "readonly_event_policy"


def test_event_parser_rejects_duplicate_keys_and_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(EventParseError, match="malformed"):
        parse_event_stream('{"type":"turn.completed","type":"other"}\n')
    parsed = parse_event_stream(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "file_read", "path": "../hidden/test.sv"},
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )
    )
    with pytest.raises(CodexPolicyError, match="traversal"):
        validate_external_events(parsed, tmp_path)


def test_normalized_events_never_persist_runtime_root_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "visible-workspace"
    workspace.mkdir()
    target = workspace / "rtl" / "TopModule.sv"
    parsed = parse_event_stream(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {
                            "type": "command_execution",
                            "command": f"sed -n 1,20p {target}",
                            "status": "in_progress",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "file_change",
                            "changes": [{"path": str(target), "kind": "update"}],
                            "status": "failed",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "file_read", "path": str(target)},
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        ),
        roots=(workspace,),
    )
    rendered = json.dumps([event.safe_dict() for event in parsed.events], sort_keys=True)
    assert str(workspace) not in rendered
    assert "<runtime-root>/rtl/TopModule.sv" in rendered


@pytest.mark.parametrize(
    "command",
    [
        "cat /home/example/.ssh/id_rsa",
        "cat $HOME/.ssh/id_rsa",
        "true; curl https://example.invalid",
        'bash -lc "cat /var/lib/private-data"',
        "cat ../hidden/test.sv",
    ],
)
def test_external_command_events_cannot_escape_visible_workspace(
    tmp_path: Path,
    command: str,
) -> None:
    parsed = parse_event_stream(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {"type": "command_execution", "command": command},
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )
    )
    with pytest.raises(CodexPolicyError):
        validate_external_events(parsed, tmp_path)


def test_external_command_event_allows_bounded_visible_rtl_check(tmp_path: Path) -> None:
    parsed = parse_event_stream(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {
                            "type": "command_execution",
                            "command": "iverilog -g2012 -o build/simv rtl/candidate.v",
                        },
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )
    )
    validate_external_events(parsed, tmp_path)


def test_runtime_logical_workspace_validation_does_not_require_a_host_mount() -> None:
    parsed = parse_event_stream(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {
                            "type": "command_execution",
                            "command": "sed -n 1,20p /workspace/rtl/TopModule.sv",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "file_change",
                            "changes": [{"path": "/workspace/rtl/TopModule.sv", "kind": "update"}],
                            "status": "completed",
                        },
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )
    )

    validate_external_events(parsed, Path("/workspace"), logical_workspace=True)

    escaped = parse_event_stream(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {
                            "type": "command_execution",
                            "command": "cat /workspace-neighbor/secret",
                        },
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )
    )
    with pytest.raises(CodexPolicyError, match="outside"):
        validate_external_events(escaped, Path("/workspace"), logical_workspace=True)


@pytest.mark.parametrize(
    "command",
    [
        "printf test",
        (
            "pwd && ls && sed -n '1,220p' README.md && "
            "printf '\\n--- rtl/TopModule.sv ---\\n' && "
            "sed -n '1,240p' rtl/TopModule.sv"
        ),
    ],
)
def test_historical_stdout_only_printf_commands_are_not_policy_false_positives(
    tmp_path: Path,
    command: str,
) -> None:
    parsed = parse_event_stream(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": command,
                            "status": "failed",
                            "exit_code": 1,
                        },
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )
    )
    validate_external_events(parsed, tmp_path)


def _validate_logical_track_b_command(command: str) -> None:
    parsed = parse_event_stream(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": command,
                            "status": "completed",
                            "exit_code": 0,
                        },
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )
    )
    validate_external_events(
        parsed,
        Path("/workspace"),
        logical_workspace=True,
        editable_globs=("rtl/TopModule.sv",),
    )


def _historical_track_b_streams() -> dict[str, list[str]]:
    fixture = json.loads(HISTORICAL_TRACK_B_COMMANDS.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == "1.0"
    assert fixture["source_commit"] == "f6b159b01050806f9e20ef6626fc755dfa36f048"
    streams = {
        str(record["run_id"]): [str(command) for command in record["commands"]]
        for record in fixture["streams"]
    }
    assert len(streams) == 15
    assert sum(len(commands) for commands in streams.values()) == 40
    return streams


def test_all_fifteen_historical_first_policy_failures_clear_parser_regressions() -> None:
    streams = _historical_track_b_streams()
    for run_id, commands in streams.items():
        original_failure_index = 1 if run_id.endswith("Prob024_hadd-0") else 0
        _validate_logical_track_b_command(commands[original_failure_index])


def test_historical_printf_physical_line_break_is_opaque_data() -> None:
    streams = _historical_track_b_streams()
    command = streams["codex-pilot-codex_cli_external_agent-Prob035_count1to10-0"][1]
    assert "\n" in command
    _validate_logical_track_b_command(command)


@pytest.mark.parametrize(
    ("run_id", "command_index"),
    [
        ("codex-pilot-codex_cli_external_agent-Prob035_count1to10-0", 2),
        ("codex-pilot-codex_cli_external_agent-Prob085_shift4-0", 3),
        ("codex-pilot-codex_cli_external_agent-Prob107_fsm1s-0", 2),
    ],
)
def test_three_historical_secondary_violations_remain_policy_failures(
    run_id: str,
    command_index: int,
) -> None:
    command = _historical_track_b_streams()[run_id][command_index]
    with pytest.raises(CodexPolicyError, match="outside the visible workspace"):
        _validate_logical_track_b_command(command)


def test_git_remains_forbidden_without_dev_null_masking_the_reason() -> None:
    with pytest.raises(CodexPolicyError, match="network-capable"):
        _validate_logical_track_b_command("git diff -- rtl/TopModule.sv")


def test_strict_single_target_quoted_heredoc_is_accepted() -> None:
    _validate_logical_track_b_command(
        "/usr/bin/bash -lc \"cat > rtl/TopModule.sv <<'EOF'\nmodule TopModule;\nendmodule\nEOF\""
    )


@pytest.mark.parametrize(
    "command",
    [
        "cat > rtl/TopModule.sv <<EOF\nmodule TopModule; endmodule\nEOF",
        "cat > rtl/TopModule.sv <<'EOF'\nmodule TopModule; endmodule\nEOF\ncat rtl/TopModule.sv",
        "cat > rtl/TopModule.sv <<'EOF' | cat\nmodule TopModule; endmodule\nEOF",
        "cat > rtl/TopModule.sv > rtl/second.sv <<'EOF'\nmodule TopModule; endmodule\nEOF",
        "cat > README.md <<'EOF'\nreplacement\nEOF",
        "cat > ../TopModule.sv <<'EOF'\nmodule TopModule; endmodule\nEOF",
        "cat > /tmp/TopModule.sv <<'EOF'\nmodule TopModule; endmodule\nEOF",
        "curl > rtl/TopModule.sv <<'EOF'\nhttps://example.invalid\nEOF",
        "cat > rtl/TopModule.sv <<'EOF'\n$(cat /etc/passwd)\nEOF",
        "cat > rtl/TopModule.sv <<'EOF'\n`cat /etc/passwd`\nEOF",
        "cat > rtl/TopModule.sv <<'EOF'\n<(cat /etc/passwd)\nEOF",
        "printf safe\ncat rtl/TopModule.sv",
        "printf 'unterminated",
    ],
)
def test_multiline_and_quoting_abuse_remain_fail_closed(command: str) -> None:
    with pytest.raises(CodexPolicyError):
        _validate_logical_track_b_command(command)


def test_printf_path_like_operands_are_opaque_but_redirections_are_validated() -> None:
    _validate_logical_track_b_command(
        "printf '%s\\\\n' '../not-a-path /etc/not-a-read https://example.invalid'"
    )
    with pytest.raises(CodexPolicyError, match="outside the visible workspace"):
        _validate_logical_track_b_command("printf safe > /dev/null")


def test_printf_redirection_and_mcp_remain_fail_closed(tmp_path: Path) -> None:
    redirected = parse_event_stream(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "printf unsafe > rtl/TopModule.sv",
                        },
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )
    )
    with pytest.raises(CodexPolicyError, match="stdout-only"):
        validate_external_events(redirected, tmp_path)

    mcp = parse_event_stream(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "mcp_tool_call",
                            "name": "list_mcp_resources",
                        },
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )
    )
    with pytest.raises(CodexPolicyError, match="MCP"):
        validate_external_events(mcp, tmp_path)


def test_workspace_snapshots_record_before_after_hashes_without_contents(
    tmp_path: Path,
) -> None:
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    candidate = rtl / "TopModule.sv"
    candidate.write_text("module TopModule; endmodule\n", encoding="utf-8")
    (tmp_path / ".verigym_internal").mkdir()
    before = snapshot_visible_workspace(tmp_path)
    candidate.write_text("module TopModule(input a, output y); assign y=a; endmodule\n")
    after = snapshot_visible_workspace(tmp_path)
    evidence = compare_workspace_snapshots(
        before,
        after,
        editable_globs=("rtl/TopModule.sv",),
        readonly_globs=("README.md",),
    )
    assert before.workspace_hash != after.workspace_hash
    assert evidence["changed_paths"] == ["rtl/TopModule.sv"]
    assert evidence["policy_passed"] is True
    assert evidence["content_values_persisted"] is False
    assert "module TopModule" not in json.dumps(evidence)


def test_known_bwrap_namespace_failure_has_stable_infrastructure_category() -> None:
    assert (
        sandbox_backend_failure(
            "",
            "bwrap: Creating new namespace failed: Operation not permitted",
        )
        == "sandbox_backend_unavailable"
    )
    assert (
        sandbox_backend_failure(
            "",
            "permission profiles requiring direct runtime enforcement are incompatible "
            "with --use-legacy-landlock",
        )
        == "sandbox_backend_unavailable"
    )
    assert (
        sandbox_backend_failure(
            "",
            "error applying legacy Linux sandbox restrictions: Sandbox(LandlockRestrict)",
        )
        == "sandbox_backend_unavailable"
    )
    assert sandbox_backend_failure("ordinary command failure", "") is None


def test_instruction_symlink_and_hardlink_contamination_is_rejected(
    tmp_path: Path,
) -> None:
    contaminated = tmp_path / "contaminated"
    contaminated.mkdir()
    (contaminated / "AGENTS.md").write_text("untrusted instructions\n", encoding="utf-8")
    child = contaminated / "workspace"
    child.mkdir()
    with pytest.raises(CodexPolicyError, match="contamination"):
        assert_instruction_isolation(child)

    safe = tmp_path / "safe"
    safe.mkdir()
    original = safe / "candidate.v"
    original.write_text("module candidate; endmodule\n", encoding="utf-8")
    os.link(original, safe / "hardlink.v")
    with pytest.raises(CodexPolicyError, match="hardlink"):
        assert_safe_workspace_tree(safe)

    original.unlink()
    (safe / "hardlink.v").unlink()
    (safe / "escape.v").symlink_to("/etc/passwd")
    with pytest.raises(CodexPolicyError, match="symlink"):
        assert_safe_workspace_tree(safe)


def test_process_environment_is_allowlisted_and_credentials_are_not_persisted(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _executable, log, scenario = fake_codex
    scenario("valid")
    monkeypatch.setenv("VERIGYM_UNRELATED_SECRET", "must-not-reach-child")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    runner = CodexCliProcessRunner(
        resolve_executable(),
        auth_mode="inherited_codex_login",
        max_output_bytes=1024 * 1024,
    )
    result = runner.run(["exec"], cwd=cwd, timeout_s=2, stdin_bytes=b"safe prompt")
    assert result.exit_code == 0
    record = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "model"
    ][-1]
    assert record["unrelated_secret_visible"] is False
    assert "VERIGYM_UNRELATED_SECRET" not in record["environment_names"]
    assert record["environment_path"] == "/usr/local/bin:/usr/bin:/bin"
    assert {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }.isdisjoint(record["environment_names"])

    scenario("credential_output")
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "api_key_env")
    monkeypatch.setenv("VERIGYM_CODEX_CREDENTIAL_ENV", "OPENAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-credential-012345")
    run = _run_track_a(tmp_path / "runs")
    assert run.scorecard.failure is not None
    artifacts = run.run_dir / "artifacts" / "codex_cli"
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in artifacts.iterdir())
    assert "unit-test-credential" not in persisted


def test_process_environment_forwards_only_explicit_proxy_allowlist(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _executable, log, scenario = fake_codex
    scenario("valid")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setenv("ALL_PROXY", "must-not-reach-child")
    monkeypatch.setenv("http_proxy", "must-not-reach-child")
    monkeypatch.setenv("https_proxy", "must-not-reach-child")
    monkeypatch.setenv("no_proxy", "must-not-reach-child")
    monkeypatch.setenv("VERIGYM_UNRELATED_SECRET", "must-not-reach-child")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    result = CodexCliProcessRunner(
        resolve_executable(),
        auth_mode="inherited_codex_login",
        max_output_bytes=1024 * 1024,
        allow_proxy_environment=True,
    ).run(["exec"], cwd=cwd, timeout_s=2, stdin_bytes=b"safe prompt")
    assert result.exit_code == 0
    record = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "model"
    ][-1]
    environment_names = set(record["environment_names"])
    assert environment_names & {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"} == {
        "HTTP_PROXY",
        "NO_PROXY",
    }
    assert {
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "VERIGYM_UNRELATED_SECRET",
    }.isdisjoint(environment_names)


def test_proxy_values_are_redacted_and_proxy_policy_partitions_identity(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    proxy_values = {
        "HTTP_PROXY": "http://proxy-user:proxy-password@proxy.unit.invalid:8080",
        "HTTPS_PROXY": "https://secure-user:secure-password@proxy.unit.invalid:8443",
        "NO_PROXY": "localhost,127.0.0.1,private.unit.invalid",
    }
    for name, value in proxy_values.items():
        monkeypatch.setenv(name, value)
    _identity, capabilities = runtime_capabilities()
    disabled = readonly_agent_settings(
        {"model_id": "fake-model"},
        capabilities,
        task_wall_time_s=300,
    )
    enabled = readonly_agent_settings(
        {"model_id": "fake-model", "allow_proxy_environment": True},
        capabilities,
        task_wall_time_s=300,
    )
    assert disabled.configuration_fingerprint != enabled.configuration_fingerprint
    disabled_configuration = disabled.safe_configuration(capabilities)
    enabled_configuration = enabled.safe_configuration(capabilities)
    assert disabled_configuration["allow_proxy_environment"] is False
    assert disabled_configuration["proxy_environment_allowed"] is False
    assert disabled_configuration["forwarded_proxy_environment_names"] == []
    assert enabled_configuration["proxy_environment_allowed"] is True
    assert enabled_configuration["allow_proxy_environment"] is True
    assert enabled_configuration["forwarded_proxy_environment_names"] == [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
    ]

    scenario("proxy_output")
    result = _run_track_a(tmp_path / "runs", allow_proxy_environment=True)
    assert result.scorecard.failure is not None
    destination = result.run_dir / "artifacts" / "codex_cli"
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in destination.iterdir())
    for proxy_value in proxy_values.values():
        assert proxy_value not in persisted
    for secret_fragment in (
        "proxy-user",
        "proxy-password",
        "secure-user",
        "secure-password",
        "private.unit.invalid",
    ):
        assert secret_fragment not in persisted
    invocation = json.loads((destination / "invocation.json").read_text(encoding="utf-8"))
    assert invocation["proxy_values_persisted"] is False
    assert invocation["allow_proxy_environment"] is True
    assert invocation["forwarded_proxy_environment_names"] == [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
    ]


def test_output_timeout_and_orphan_cleanup_are_bounded(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, log, scenario = fake_codex
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    identity = resolve_executable()

    scenario("oversized_stderr")
    bounded = CodexCliProcessRunner(
        identity,
        auth_mode="inherited_codex_login",
        max_output_bytes=1024,
    ).run(["exec"], cwd=cwd, timeout_s=2, stdin_bytes=b"prompt")
    assert bounded.stderr_truncated is True
    assert len(bounded.stderr.encode("utf-8")) <= 1024

    scenario("timeout")
    timed = CodexCliProcessRunner(
        identity,
        auth_mode="inherited_codex_login",
    ).run(["exec"], cwd=cwd, timeout_s=0.05, stdin_bytes=b"prompt")
    assert timed.timed_out is True
    assert timed.process_group_cleaned is True
    assert timed.duration_s < 3

    scenario("orphan")
    orphaned = CodexCliProcessRunner(
        identity,
        auth_mode="inherited_codex_login",
    ).run(["exec"], cwd=cwd, timeout_s=2, stdin_bytes=b"prompt")
    assert orphaned.process_group_cleaned is True
    orphan_pid = [
        json.loads(line)["pid"]
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "orphan"
    ][-1]
    deadline = time.monotonic() + 2
    while _process_running(orphan_pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _process_running(orphan_pid)


@pytest.mark.requires_iverilog
def test_model_id_argument_injection_is_data_not_shell_syntax(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, log, _scenario = fake_codex
    model_id = "fake-model;touch-pwned"
    result = _run_track_a(tmp_path / "runs", model_id=model_id)
    assert result.scorecard.status == "completed"
    record = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "model"
    ][-1]
    model_index = record["arguments"].index("--model")
    assert record["arguments"][model_index + 1] == model_id
    assert not Path("pwned").exists()

    _identity, capabilities = runtime_capabilities()
    with pytest.raises(ValueError, match="begin"):
        readonly_agent_settings(
            {"model_id": "-c"},
            capabilities,
            task_wall_time_s=300,
        )
    with pytest.raises(ValueError, match="identifier"):
        readonly_agent_settings(
            {"model_id": "fake\nmodel"},
            capabilities,
            task_wall_time_s=300,
        )


def _process_running(pid: int) -> bool:
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        fields = stat_path.read_text(encoding="utf-8").split()
    except OSError:
        return False
    return len(fields) > 2 and fields[2] != "Z"
