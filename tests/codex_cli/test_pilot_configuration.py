from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.codex_cli, pytest.mark.codex_cli_pilot]

ROOT = Path(__file__).resolve().parents[2]


def test_prepared_pilot_freezes_exactly_thirty_partitioned_runs() -> None:
    path = ROOT / "examples" / "experiments" / "codex-cli-verilog-eval-pilot.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert len(payload["tasks"]) == 5
    assert [track["id"] for track in payload["tracks"]] == [
        "codex_cli_model_proxy",
        "codex_cli_external_agent",
    ]
    assert payload["sampling"]["sample_indices"] == [0, 1, 2]
    assert (
        len(payload["tasks"]) * len(payload["tracks"]) * len(payload["sampling"]["sample_indices"])
        == payload["execution"]["planned_runs"]
        == 30
    )
    assert payload["execution"]["allow_retry"] is False
    assert payload["execution"]["allow_best_of_k_selection"] is False
    assert payload["execution"]["allow_outer_agent_repair"] is False
    assert len({task["task_hash"] for task in payload["tasks"]}) == 5
    assert len({task["source_hash"] for task in payload["tasks"]}) == 5
    assert payload["suite"]["expected_git_commit"]
    assert payload["suite"]["expected_dataset_content_hash"]


def test_pilot_has_two_independent_execution_guards() -> None:
    path = ROOT / "examples" / "experiments" / "codex-cli-verilog-eval-pilot.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["guard"]["opt_in_env"] == "VERIGYM_RUN_CODEX_PILOT"
    assert payload["guard"]["required_value"] == "1"
    assert payload["guard"]["budget_env"] == "VERIGYM_CODEX_PILOT_BUDGET"
    source = (ROOT / "scripts" / "run_codex_cli_pilot.py").read_text(encoding="utf-8")
    assert 'os.environ.get("VERIGYM_RUN_CODEX_PILOT") == "1"' in source
    assert 'os.environ.get("VERIGYM_CODEX_PILOT_BUDGET")' in source
    assert '"status": "plan_only"' in source
