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


def _client() -> CodexExecModelClient:
    return CodexExecModelClient().clone_for_run(
        ModelRunConfig(
            model_id="fake-model",
            client_options={
                "sandbox": "most-restrictive-supported",
                "reject_tool_use": True,
            },
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
