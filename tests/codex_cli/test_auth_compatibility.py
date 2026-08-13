from __future__ import annotations

import json
from pathlib import Path

import pytest
from verigym_codex_cli import (
    AuthModeError,
    resolve_auth_mode,
    run_auth_preflight,
)
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.cli import main
from verigym_codex_cli.config import readonly_agent_settings
from verigym_codex_cli.process import (
    CodexProcessError,
    auth_configuration,
    auth_identity_configuration,
)

from verigym.core.loaders import load_model
from verigym.reporting.aggregate import _auth_comparison_identity
from verigym.schemas.external_agent import ExternalAgentCallIdentity

pytestmark = pytest.mark.codex_cli


@pytest.mark.parametrize(
    ("requested", "resolved", "semantic_id", "alias_used"),
    [
        (
            "chatgpt_cli_session",
            "inherited_codex_login",
            "codex.auth.inherited_chatgpt_session.v1",
            True,
        ),
        (
            "inherited_codex_login",
            "inherited_codex_login",
            "codex.auth.inherited_chatgpt_session.v1",
            False,
        ),
        (
            "api_key_env",
            "api_key_env",
            "codex.auth.api_key_environment.v1",
            False,
        ),
        (
            "custom_provider_environment",
            "custom_provider_environment",
            "codex.auth.custom_provider_environment.v1",
            False,
        ),
    ],
)
def test_authentication_labels_have_one_typed_resolution(
    requested: str,
    resolved: str,
    semantic_id: str,
    alias_used: bool,
) -> None:
    identity = resolve_auth_mode(requested)
    assert identity.safe_dict() == {
        "requested_auth_mode": requested,
        "resolved_auth_mode": resolved,
        "auth_semantic_id": semantic_id,
        "auth_alias_used": alias_used,
    }


@pytest.mark.parametrize(
    "unsupported",
    [
        "unknown",
        "ChatGPT_CLI_SESSION",
        "chatgpt_cli_session ",
        " chatgpt_cli_session",
        "",
    ],
)
def test_unknown_case_and_whitespace_authentication_labels_are_rejected(
    unsupported: str,
) -> None:
    with pytest.raises(AuthModeError):
        resolve_auth_mode(unsupported)


def test_unset_runtime_auth_mode_reuses_the_logged_in_codex_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VERIGYM_CODEX_AUTH_MODE", raising=False)

    resolution, credential_env = auth_identity_configuration()

    assert resolution.requested_auth_mode == "inherited_codex_login"
    assert resolution.resolved_auth_mode == "inherited_codex_login"
    assert resolution.auth_alias_used is False
    assert credential_env is None


def test_alias_preserves_provenance_but_shares_semantic_comparison(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _executable, _log, _scenario = fake_codex
    _identity, capabilities = discover_capabilities(force=True)
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")
    resolved_mode, credential_env = auth_configuration()
    assert resolved_mode == "inherited_codex_login"
    assert credential_env is None
    options = {"model_id": "fake-model"}
    alias = readonly_agent_settings(options, capabilities, task_wall_time_s=300)
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "inherited_codex_login")
    legacy = readonly_agent_settings(options, capabilities, task_wall_time_s=300)
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "api_key_env")
    monkeypatch.setenv("VERIGYM_TEST_API_KEY", "test-only-value-that-must-not-persist")
    monkeypatch.setenv("VERIGYM_CODEX_CREDENTIAL_ENV", "VERIGYM_TEST_API_KEY")
    api_key = readonly_agent_settings(
        options,
        capabilities,
        task_wall_time_s=300,
    )

    assert alias.configuration_fingerprint != legacy.configuration_fingerprint
    assert _auth_comparison_identity(alias.safe_configuration(capabilities)) == (
        _auth_comparison_identity(legacy.safe_configuration(capabilities))
    )
    assert _auth_comparison_identity(alias.safe_configuration(capabilities)) != (
        _auth_comparison_identity(api_key.safe_configuration(capabilities))
    )
    serialized = json.dumps(api_key.safe_configuration(capabilities), sort_keys=True)
    assert "test-only-value-that-must-not-persist" not in serialized
    assert "VERIGYM_TEST_API_KEY" not in serialized


def test_alias_preflight_is_structured_and_invokes_only_login_status(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _executable, log, _scenario = fake_codex
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    sentinel = codex_home / "auth.json"
    sentinel.write_text("opaque-test-sentinel\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")

    result = run_auth_preflight()
    assert result.status == "pass"
    assert result.requested_auth_mode == "chatgpt_cli_session"
    assert result.resolved_auth_mode == "inherited_codex_login"
    assert result.auth_semantic_id == "codex.auth.inherited_chatgpt_session.v1"
    assert result.auth_alias_used is True
    assert result.codex_login_status == "Logged in using ChatGPT"
    assert result.diagnostic_processes == 1
    assert result.model_calls == 0
    assert result.login_processes == 0
    assert result.logout_processes == 0
    assert sentinel.read_text(encoding="utf-8") == "opaque-test-sentinel\n"
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert records == [{"command": "login_status", "kind": "diagnostic"}]

    output = tmp_path / "auth-preflight.json"
    main(["auth-preflight", "--json", str(output)])
    printed = capsys.readouterr().out
    assert (
        "authentication mode alias resolved:\nchatgpt_cli_session -> inherited_codex_login"
    ) in printed
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["model_calls"] == 0
    assert payload["login_processes"] == 0


def test_preflight_returns_external_prerequisite_without_login_flow(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _executable, log, scenario = fake_codex
    scenario("unauthenticated")
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")
    result = run_auth_preflight()
    assert result.status == "external_prerequisite"
    assert result.external_prerequisite_satisfied is False
    assert result.model_calls == 0
    assert result.login_processes == 0
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert records == [{"command": "login_status", "kind": "diagnostic"}]


def test_unknown_mode_fails_before_any_cli_activity(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _executable, log, _scenario = fake_codex
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "unsupported")
    with pytest.raises(CodexProcessError):
        auth_configuration()
    with pytest.raises(CodexProcessError):
        run_auth_preflight()
    assert not log.exists()


def test_legacy_external_agent_identity_fixture_round_trips_and_schema_is_stable() -> None:
    fixture = Path("tests/fixtures/golden/v1/codex_cli/legacy_external_agent_identity.json")
    identity = load_model(fixture, ExternalAgentCallIdentity)
    assert identity.auth_mode_label == "inherited_codex_login"
    assert identity.requested_auth_mode is None
    assert identity.resolved_auth_mode is None
    assert identity.auth_semantic_id is None
    assert identity.auth_alias_used is None
    assert identity.requested_reasoning_effort is None
    assert identity.effective_reasoning_effort is None
    assert identity.reasoning_effort_source is None
    assert identity.inherited_reasoning_effort_allowed is None
    assert ExternalAgentCallIdentity.model_validate(identity.model_dump(mode="json")) == identity
    assert ExternalAgentCallIdentity.model_json_schema(
        mode="serialization"
    ) == ExternalAgentCallIdentity.model_json_schema(mode="serialization")
