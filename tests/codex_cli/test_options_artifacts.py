from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from verigym.core.integrity import (
    verify_artifact_manifest,
    write_run_artifact_manifest,
)
from verigym.schemas.model import ModelRunConfig
from verigym.schemas.run import RunConfig

pytestmark = pytest.mark.codex_cli


def test_plugin_options_are_bounded_secret_free_and_hashed() -> None:
    first = RunConfig(
        task_id="toy-rtl/and-gate-basic",
        agent_options={"model_id": "model-a"},
    )
    second = first.model_copy(update={"agent_options": {"model_id": "model-b"}})
    assert first.identity_payload() != second.identity_payload()
    with pytest.raises(ValidationError):
        RunConfig(
            task_id="toy-rtl/and-gate-basic",
            agent_options={"auth_token": "literal-secret"},
        )
    with pytest.raises(ValidationError):
        ModelRunConfig(client_options={"output_path": "/home/user/result"})
    with pytest.raises(ValidationError):
        RunConfig(
            task_id="toy-rtl/and-gate-basic",
            agent_options={"nested": {"value": [[[[[[[[["too-deep"]]]]]]]]]}},
        )


def test_legacy_empty_options_are_omitted_from_identity_payload() -> None:
    config = RunConfig(task_id="toy-rtl/and-gate-basic")
    payload = config.identity_payload()
    assert "agent_options" not in payload
    assert "client_options" not in payload["model_options"]


def test_codex_artifacts_are_integrity_bound_and_tamper_detected(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from verigym_codex_cli import CodexCliReadonlyAgentAdapter

    from verigym.core.orchestrator import VeriGym
    from verigym.registry.collections import build_registries
    from verigym.schemas.common import InteractionMode

    _executable, _log, _scenario = fake_codex
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")
    registries = build_registries(discover_external=False)
    registries.agents.register(CodexCliReadonlyAgentAdapter())
    result = VeriGym(registries).run(
        RunConfig(
            task_id="toy-rtl/and-gate-basic",
            mode=InteractionMode.AGENT,
            agent="codex-cli-readonly-agent",
            agent_options={
                "model_id": "fake-model",
                "sandbox": "read-only",
                "reasoning_effort": "xhigh",
            },
            output=tmp_path / "runs",
        )
    )
    identity = result.manifest.external_agent_observations[-1]
    assert identity.requested_auth_mode == "chatgpt_cli_session"
    assert identity.resolved_auth_mode == "inherited_codex_login"
    assert identity.auth_semantic_id == ("codex.auth.inherited_chatgpt_session.v1")
    assert identity.requested_reasoning_effort == "xhigh"
    assert identity.effective_reasoning_effort == "xhigh"
    assert identity.reasoning_effort_source == ("verigym_explicit_cli_override")
    assert identity.inherited_reasoning_effort_allowed is False
    assert verify_artifact_manifest(result.run_dir, expected_scope="run").status == "verified"
    codex_artifacts = result.run_dir / "artifacts" / "codex_cli"
    accounting = json.loads((codex_artifacts / "accounting.json").read_text(encoding="utf-8"))
    invocation = json.loads((codex_artifacts / "invocation.json").read_text(encoding="utf-8"))
    assert accounting["input_tokens"] == 11
    assert accounting["output_tokens"] == 7
    assert accounting["total_tokens"] == 18
    assert invocation["credential_values_persisted"] is False
    assert invocation["argv"][-3:] == [
        "--config",
        'model_reasoning_effort="xhigh"',
        "-",
    ]
    from verigym.reporting.service import ReportService

    reports = ReportService().generate_all(
        tmp_path / "runs",
        output_dir=tmp_path / "reports",
        group_by=("integration_track", "requested_model_id", "cli_version"),
    )
    rows = list(csv.DictReader(StringIO(reports.csv_path.read_text(encoding="utf-8"))))
    assert len(rows) == 1
    assert float(rows[0]["cli_process_wall_time_s"]) > 0
    assert rows[0]["external_tool_call_count"] == "0"
    assert rows[0]["requested_auth_mode"] == "chatgpt_cli_session"
    assert rows[0]["resolved_auth_mode"] == "inherited_codex_login"
    assert rows[0]["auth_semantic_id"] == ("codex.auth.inherited_chatgpt_session.v1")
    assert rows[0]["auth_alias_used"] == "true"
    assert rows[0]["requested_reasoning_effort"] == "xhigh"
    assert rows[0]["effective_reasoning_effort"] == "xhigh"
    assert rows[0]["reasoning_effort_source"] == "verigym_explicit_cli_override"
    assert rows[0]["inherited_reasoning_effort_allowed"] == "false"
    summary = result.run_dir / "artifacts" / "codex_cli" / "summary.json"
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["tampered"] = True
    summary.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Exception, match="hash|size"):
        verify_artifact_manifest(result.run_dir, expected_scope="run")
    write_run_artifact_manifest(result.run_dir, result.manifest.run_id)
