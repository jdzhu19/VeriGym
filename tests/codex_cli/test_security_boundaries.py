from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from verigym_codex_cli import CodexExecModelClient
from verigym_codex_cli.events import EventParseError, parse_event_stream
from verigym_codex_cli.process import CodexCliProcessRunner, resolve_executable
from verigym_codex_cli.security import (
    CodexPolicyError,
    assert_instruction_isolation,
    assert_safe_workspace_tree,
    validate_external_events,
)

from verigym.plugin_api import (
    ModelClientError,
    ModelErrorCategory,
    ModelMessage,
    ModelRequest,
    ModelRunConfig,
)

pytestmark = pytest.mark.codex_cli


def _request() -> ModelRequest:
    return ModelRequest(
        request_id="security-request",
        messages=[ModelMessage(role="user", content="Return a small AND gate.")],
    )


def _client(config: ModelRunConfig | None = None) -> CodexExecModelClient:
    return CodexExecModelClient().clone_for_run(config or ModelRunConfig(model_id="fake-model"))


@pytest.mark.parametrize(
    ("scenario_name", "category"),
    [
        ("auth_error", ModelErrorCategory.AUTHENTICATION),
        ("rate_limit", ModelErrorCategory.RATE_LIMIT),
        ("transport_error", ModelErrorCategory.TRANSPORT),
        ("nonzero", ModelErrorCategory.INTERNAL),
    ],
)
def test_track_a_remote_failures_remain_structured_infrastructure(
    fake_codex: tuple[Path, Path, object],
    scenario_name: str,
    category: ModelErrorCategory,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario(scenario_name)
    with pytest.raises(ModelClientError) as raised:
        _client().generate(_request())
    assert raised.value.info.category == category


@pytest.mark.parametrize("scenario_name", ["deep_event", "unknown_flood"])
def test_bounded_event_parser_rejects_adversarial_fake_streams(
    fake_codex: tuple[Path, Path, object],
    scenario_name: str,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario(scenario_name)
    with pytest.raises(ModelClientError) as raised:
        _client().generate(_request())
    assert raised.value.info.category == ModelErrorCategory.INVALID_RESPONSE


@pytest.mark.parametrize("scenario_name", ["unknown_event", "message_delta"])
def test_forward_compatible_non_tool_events_do_not_invalidate_final_text(
    fake_codex: tuple[Path, Path, object],
    scenario_name: str,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario(scenario_name)
    response = _client().generate(_request())
    assert response.text.startswith("module and_gate")


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
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-credential-012345")
    client = _client(
        ModelRunConfig(
            model_id="fake-model",
            api_key_env="OPENAI_API_KEY",
        )
    )
    with pytest.raises(ModelClientError):
        client.generate(_request())
    artifacts = tmp_path / "artifacts"
    client.export_run_artifacts(artifacts)
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
    disabled = _client(ModelRunConfig(model_id="fake-model"))
    enabled = _client(
        ModelRunConfig(
            model_id="fake-model",
            client_options={"allow_proxy_environment": True},
        )
    )
    assert disabled.descriptor.configuration_fingerprint != (
        enabled.descriptor.configuration_fingerprint
    )
    assert disabled.descriptor.configuration["allow_proxy_environment"] is False
    assert disabled.descriptor.configuration["proxy_environment_allowed"] is False
    assert disabled.descriptor.configuration["forwarded_proxy_environment_names"] == []
    assert enabled.descriptor.configuration["proxy_environment_allowed"] is True
    assert enabled.descriptor.configuration["allow_proxy_environment"] is True
    assert enabled.descriptor.configuration["forwarded_proxy_environment_names"] == [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
    ]

    scenario("proxy_output")
    with pytest.raises(ModelClientError) as raised:
        enabled.generate(_request())
    persisted_error = str(raised.value)
    destination = tmp_path / "proxy-artifacts"
    enabled.export_run_artifacts(destination)
    persisted = (
        persisted_error
        + "\n"
        + "\n".join(path.read_text(encoding="utf-8") for path in destination.iterdir())
    )
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


def test_model_id_argument_injection_is_data_not_shell_syntax(
    fake_codex: tuple[Path, Path, object],
) -> None:
    _executable, log, _scenario = fake_codex
    model_id = "fake-model;touch-pwned"
    response = _client(ModelRunConfig(model_id=model_id)).generate(_request())
    assert response.text.startswith("module and_gate")
    record = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "model"
    ][-1]
    model_index = record["arguments"].index("--model")
    assert record["arguments"][model_index + 1] == model_id
    assert not Path("pwned").exists()

    with pytest.raises(ValueError, match="begin"):
        _client(ModelRunConfig(model_id="-c"))
    with pytest.raises(ValueError, match="identifier"):
        _client(ModelRunConfig(model_id="fake\nmodel"))


def _process_running(pid: int) -> bool:
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        fields = stat_path.read_text(encoding="utf-8").split()
    except OSError:
        return False
    return len(fields) > 2 and fields[2] != "Z"
