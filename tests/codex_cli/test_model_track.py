from __future__ import annotations

import json
from pathlib import Path

import pytest
from verigym_codex_cli import CodexExecModelClient

from verigym.plugin_api import (
    ModelClientError,
    ModelErrorCategory,
    ModelMessage,
    ModelRequest,
    ModelRunConfig,
)

pytestmark = [pytest.mark.codex_cli, pytest.mark.codex_cli_model]


def _request(request_id: str = "request-1") -> ModelRequest:
    return ModelRequest(
        request_id=request_id,
        messages=[
            ModelMessage(role="system", content="Return RTL without tools."),
            ModelMessage(role="user", content="Implement an AND gate."),
        ],
    )


def _client(
    *,
    max_process_time_s: float | None = None,
    max_output_bytes: int | None = None,
    allow_proxy_environment: bool = False,
) -> CodexExecModelClient:
    client_options: dict[str, object] = {
        "sandbox": "most-restrictive-supported",
        "reject_tool_use": True,
        "allow_proxy_environment": allow_proxy_environment,
    }
    if max_process_time_s is not None:
        client_options["max_process_time_s"] = max_process_time_s
    if max_output_bytes is not None:
        client_options["max_output_bytes"] = max_output_bytes
    return CodexExecModelClient().clone_for_run(
        ModelRunConfig(
            model_id="fake-model",
            request_timeout_s=max_process_time_s or 90,
            client_options=client_options,
        )
    )


def test_one_request_is_normalized_in_empty_directory(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, log, _scenario = fake_codex
    client = _client()
    response = client.generate(_request())
    assert response.provider_model_id == "fake-model"
    assert response.usage.total_tokens == 18
    assert response.text.startswith("module and_gate")
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    model_calls = [record for record in calls if record["kind"] == "model"]
    assert len(model_calls) == 1
    assert model_calls[0]["initial_files"] == []
    prompt = model_calls[0]["prompt"]
    assert prompt.index('role="system"') < prompt.index('role="user"')
    assert str(Path.cwd()) not in prompt
    destination = tmp_path / "codex_cli"
    client.export_run_artifacts(destination)
    assert {
        "capabilities.json",
        "invocation.json",
        "parsed_events.jsonl",
        "raw_stdout.jsonl",
        "raw_stderr.log",
        "identity.json",
        "accounting.json",
        "summary.json",
    } == {path.name for path in destination.iterdir()}
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in destination.iterdir())
    assert "private fake reasoning" not in persisted


def test_alias_mode_track_a_records_requested_resolved_and_semantic_identity(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _executable, _log, _scenario = fake_codex
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")
    client = _client()
    configuration = client.descriptor.configuration
    assert configuration["requested_auth_mode"] == "chatgpt_cli_session"
    assert configuration["resolved_auth_mode"] == "inherited_codex_login"
    assert configuration["auth_semantic_id"] == ("codex.auth.inherited_chatgpt_session.v1")
    assert configuration["auth_alias_used"] is True
    client.generate(_request())
    destination = tmp_path / "codex_cli"
    client.export_run_artifacts(destination)
    identity = json.loads((destination / "identity.json").read_text(encoding="utf-8"))
    invocation = json.loads((destination / "invocation.json").read_text(encoding="utf-8"))
    for payload in (identity, invocation):
        assert payload["requested_auth_mode"] == "chatgpt_cli_session"
        assert payload["resolved_auth_mode"] == "inherited_codex_login"
        assert payload["auth_semantic_id"] == ("codex.auth.inherited_chatgpt_session.v1")
        assert payload["auth_alias_used"] is True


def test_unknown_usage_remains_null(
    fake_codex: tuple[Path, Path, object],
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("unknown_usage")
    response = _client().generate(_request())
    assert response.usage.input_tokens is None
    assert response.usage.output_tokens is None
    assert response.usage.total_tokens is None


def test_tool_use_invalidates_track_a(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("tool_use")
    client = _client()
    with pytest.raises(ModelClientError) as raised:
        client.generate(_request())
    assert raised.value.info.category == ModelErrorCategory.INVALID_RESPONSE
    destination = tmp_path / "codex_cli"
    client.export_run_artifacts(destination)
    summary = json.loads((destination / "summary.json").read_text(encoding="utf-8"))
    assert summary["tool_use_event_count"] == 2
    assert summary["valid_model_response"] is False


@pytest.mark.parametrize("scenario", ["malformed", "multiple_final", "oversized"])
def test_malformed_or_ambiguous_output_is_invalid(
    fake_codex: tuple[Path, Path, object],
    scenario: str,
) -> None:
    _executable, _log, setter = fake_codex
    setter(scenario)
    with pytest.raises(ModelClientError) as raised:
        _client().generate(_request())
    assert raised.value.info.category == ModelErrorCategory.INVALID_RESPONSE


def test_clone_state_and_session_are_independent(
    fake_codex: tuple[Path, Path, object],
) -> None:
    _executable, log, _scenario = fake_codex
    first = _client()
    second = _client()
    first.generate(_request("first"))
    second.generate(_request("second"))
    with pytest.raises(ModelClientError):
        first.generate(_request("third"))
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    model_records = [record for record in records if record["kind"] == "model"]
    assert len(model_records) == 2
    assert model_records[0]["cwd"] != model_records[1]["cwd"]


def test_secret_shaped_output_is_redacted(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("secret_output")
    client = _client()
    with pytest.raises(ModelClientError):
        client.generate(_request())
    destination = tmp_path / "codex_cli"
    client.export_run_artifacts(destination)
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in destination.iterdir())
    assert "FAKESECRET" not in persisted


def test_track_a_timeout_has_primary_timeout_taxonomy(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("timeout")
    client = _client(max_process_time_s=0.05)
    with pytest.raises(ModelClientError) as raised:
        client.generate(_request())
    assert raised.value.info.category == ModelErrorCategory.TIMEOUT
    destination = tmp_path / "codex_cli"
    client.export_run_artifacts(destination)
    summary = json.loads((destination / "summary.json").read_text(encoding="utf-8"))
    assert summary["failure_category"] == "timeout"
    assert summary["timed_out"] is True
    assert summary["diagnostic_only"] is True
    assert summary["canonical_stream_complete"] is False


def test_track_a_output_overflow_has_primary_output_limit_taxonomy(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("oversized_stderr")
    client = _client(max_output_bytes=1024)
    with pytest.raises(ModelClientError) as raised:
        client.generate(_request())
    assert raised.value.info.category == ModelErrorCategory.OUTPUT_LIMIT
    destination = tmp_path / "codex_cli"
    client.export_run_artifacts(destination)
    summary = json.loads((destination / "summary.json").read_text(encoding="utf-8"))
    assert summary["failure_category"] == "output_limit"
    assert summary["stderr_truncated"] is True
    assert summary["diagnostic_only"] is True
    assert summary["canonical_stream_complete"] is False


def test_track_a_fake_flow_succeeds_with_proxy_forwarding(
    fake_codex: tuple[Path, Path, object],
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("valid")
    response = _client(allow_proxy_environment=True).generate(_request())
    assert response.text.startswith("module and_gate")
