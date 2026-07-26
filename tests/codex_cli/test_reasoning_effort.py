from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

import pytest
from verigym_codex_cli import CodexCliAgentAdapter, CodexCliReadonlyAgentAdapter
from verigym_codex_cli.capabilities import runtime_capabilities
from verigym_codex_cli.config import agent_settings, readonly_agent_settings
from verigym_codex_cli.invocation import build_exec_arguments
from verigym_codex_cli.process import CodexCliProcessRunner, resolve_executable

from verigym.core.orchestrator import VeriGym
from verigym.registry.collections import build_registries
from verigym.reporting.service import ReportService
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig

pytestmark = pytest.mark.codex_cli

_EFFORT_OVERRIDE = 'model_reasoning_effort="xhigh"'


def _readonly_options(*, reasoning_effort: str = "xhigh") -> dict[str, object]:
    return {
        "model_id": "fake-model",
        "sandbox": "read-only",
        "approval_policy": "non-interactive",
        "reasoning_effort": reasoning_effort,
        "allow_proxy_environment": True,
        "max_process_time_s": 300,
    }


def _agent_options(*, reasoning_effort: str = "xhigh") -> dict[str, object]:
    return {
        "model_id": "fake-model",
        "sandbox": "workspace-write",
        "approval_policy": "non-interactive",
        "reasoning_effort": reasoning_effort,
        "allow_proxy_environment": True,
        "max_process_time_s": 300,
    }


def _assert_final_config_override(arguments: list[str], config_flag: str) -> None:
    assert arguments[-3:] == [config_flag, _EFFORT_OVERRIDE, "-"]
    assert arguments.count(_EFFORT_OVERRIDE) == 1


def test_both_tracks_own_xhigh_as_the_final_cli_config_override(
    fake_codex: tuple[Path, Path, object],
) -> None:
    _executable, _log, _scenario = fake_codex
    _identity, capabilities = runtime_capabilities()
    readonly = readonly_agent_settings(
        _readonly_options(),
        capabilities,
        task_wall_time_s=300,
    )
    agent = agent_settings(_agent_options(), capabilities, task_wall_time_s=300)

    for settings in (readonly, agent):
        arguments = build_exec_arguments(capabilities, settings)
        _assert_final_config_override(arguments, capabilities.config_flag)
        assert settings.requested_reasoning_effort == "xhigh"
        assert settings.effective_reasoning_effort == "xhigh"
        assert settings.reasoning_effort_source == "verigym_explicit_cli_override"
        assert settings.inherited_reasoning_effort_allowed is False
        assert settings.requested_process_timeout_s == 300
        assert settings.effective_process_timeout_s == 300
        assert settings.timeout_clamped is False
        assert settings.allow_proxy_environment is True

    assert (
        readonly.configuration_fingerprint
        == readonly_agent_settings(
            _readonly_options(),
            capabilities,
            task_wall_time_s=300,
        ).configuration_fingerprint
    )
    assert (
        agent.configuration_fingerprint
        == agent_settings(
            _agent_options(), capabilities, task_wall_time_s=300
        ).configuration_fingerprint
    )


@pytest.mark.parametrize("unsupported", ["max", "high", "none", "xhigh "])
def test_unauthorized_reasoning_effort_fails_before_model_process(
    fake_codex: tuple[Path, Path, object],
    unsupported: str,
) -> None:
    _executable, log, _scenario = fake_codex
    _identity, capabilities = runtime_capabilities()
    before = log.read_text(encoding="utf-8") if log.exists() else ""

    with pytest.raises(ValueError):
        readonly_agent_settings(
            _readonly_options(reasoning_effort=unsupported),
            capabilities,
            task_wall_time_s=300,
        )
    with pytest.raises(ValueError):
        agent_settings(
            _agent_options(reasoning_effort=unsupported),
            capabilities,
            task_wall_time_s=300,
        )

    assert (log.read_text(encoding="utf-8") if log.exists() else "") == before


def test_inherited_max_is_overridden_for_fake_track_a_and_track_b(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _executable, log, scenario = fake_codex
    scenario("require_xhigh_override")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    private_sentinel = "unrelated-private-setting-must-not-persist"
    (codex_home / "config.toml").write_text(
        f'unrelated_setting = "{private_sentinel}"\nmodel_reasoning_effort = "max"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    registries = build_registries(discover_external=False)
    registries.agents.register(CodexCliReadonlyAgentAdapter())
    registries.agents.register(CodexCliAgentAdapter())
    service = VeriGym(registries)
    runs = tmp_path / "runs"
    track_a = service.run(
        RunConfig(
            task_id="toy-rtl/and-gate-basic",
            mode=InteractionMode.AGENT,
            agent="codex-cli-readonly-agent",
            agent_options=_readonly_options(),
            runtime="local",
            output=runs,
        )
    )
    track_b = service.run(
        RunConfig(
            task_id="toy-rtl/and-gate-basic",
            mode=InteractionMode.AGENT,
            agent="codex-cli-agent",
            agent_options=_agent_options(),
            runtime="local",
            output=runs,
        )
    )

    model_records = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "model"
    ]
    assert len(model_records) == 2
    for record in model_records:
        assert record["requested_reasoning_effort"] == "xhigh"
        assert record["effective_reasoning_effort"] == "xhigh"
        assert record["reasoning_effort_source"] == "verigym_explicit_cli_override"
        assert private_sentinel not in json.dumps(record, sort_keys=True)
        _assert_final_config_override(record["arguments"], "--config")

    for result in (track_a, track_b):
        external_identity = result.manifest.external_agent_observations[-1]
        assert external_identity.requested_reasoning_effort == "xhigh"
        assert external_identity.effective_reasoning_effort == "xhigh"
        assert external_identity.reasoning_effort_source == "verigym_explicit_cli_override"
        assert external_identity.inherited_reasoning_effort_allowed is False

    for result in (track_a, track_b):
        artifacts = result.run_dir / "artifacts" / "codex_cli"
        persisted = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(artifacts.iterdir())
        )
        assert private_sentinel not in persisted
        invocation = json.loads((artifacts / "invocation.json").read_text(encoding="utf-8"))
        assert invocation["argv"][-3:] == ["--config", _EFFORT_OVERRIDE, "-"]
        assert invocation["requested_reasoning_effort"] == "xhigh"
        assert invocation["effective_reasoning_effort"] == "xhigh"
        assert invocation["reasoning_effort_source"] == "verigym_explicit_cli_override"
        assert invocation["inherited_reasoning_effort_allowed"] is False

    reports = ReportService().generate_all(runs, output_dir=tmp_path / "reports")
    rows = list(csv.DictReader(StringIO(reports.csv_path.read_text(encoding="utf-8"))))
    assert len(rows) == 2
    assert {row["requested_reasoning_effort"] for row in rows} == {"xhigh"}
    assert {row["effective_reasoning_effort"] for row in rows} == {"xhigh"}
    assert {row["reasoning_effort_source"] for row in rows} == {"verigym_explicit_cli_override"}
    assert {row["inherited_reasoning_effort_allowed"] for row in rows} == {"false"}
    partitions = reports.aggregate.metadata["codex_cli_identity_partitions"]
    assert isinstance(partitions, list)
    assert len(partitions) == 2
    assert all(item["effective_reasoning_effort"] == "xhigh" for item in partitions)
    assert all(
        item["reasoning_effort_source"] == "verigym_explicit_cli_override" for item in partitions
    )
    assert "Effective effort" in reports.markdown_path.read_text(encoding="utf-8")


def test_fake_cli_rejects_missing_override_when_inherited_value_is_max(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _executable, _log, scenario = fake_codex
    scenario("require_xhigh_override")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'model_reasoning_effort = "max"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    cwd = tmp_path / "empty"
    cwd.mkdir()

    result = CodexCliProcessRunner(
        resolve_executable(),
        auth_mode="inherited_codex_login",
    ).run(["exec"], cwd=cwd, timeout_s=2, stdin_bytes=b"safe fake prompt")

    assert result.exit_code == 1
    assert "explicit model_reasoning_effort xhigh override is required" in result.stdout
