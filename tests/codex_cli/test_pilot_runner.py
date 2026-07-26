from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

from verigym.agents.parsing import parse_single_turn_rtl
from verigym.reporting.service import ReportService
from verigym.suites.verilog_eval.normalization import declared_modules

pytestmark = [pytest.mark.codex_cli, pytest.mark.codex_cli_pilot]

ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_BUNDLE = Path(
    "/data/jzhu484/verigym-codex-cli-verilog-eval-pilot-9a84c60-JmLJsywy/bundle"
)


def _runner() -> ModuleType:
    path = ROOT / "scripts" / "run_codex_cli_pilot.py"
    spec = importlib.util.spec_from_file_location("verigym_test_pilot_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _score(*, status: str, infrastructure: bool, category: str = "candidate") -> object:
    return SimpleNamespace(
        status=status,
        correctness=SimpleNamespace(infrastructure_error=False),
        failure=SimpleNamespace(infrastructure=infrastructure, category=category),
    )


def test_plan_order_interleaves_tracks_by_task_and_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    config = yaml.safe_load(
        (ROOT / "examples" / "experiments" / "codex-cli-verilog-eval-pilot.yaml").read_text()
    )
    monkeypatch.setattr(
        runner,
        "get_build_provenance",
        lambda: SimpleNamespace(
            source_commit="1" * 40,
            source_tree_hash="2" * 64,
            dirty=False,
        ),
    )
    origin = SimpleNamespace(registration="entry_point", package="verigym-codex-cli")
    registries = SimpleNamespace(agents=SimpleNamespace(origin=lambda _name: origin))
    snapshot = SimpleNamespace(
        git_commit=config["suite"]["expected_git_commit"],
        dataset_content_hash=config["suite"]["expected_dataset_content_hash"],
        model_dump=lambda **_kwargs: {"git_commit": config["suite"]["expected_git_commit"]},
    )
    plan = runner._build_plan(
        config,
        model_id="gpt-5.4",
        capability={
            "capability_fingerprint": "3" * 64,
            "executable_name": "codex",
            "executable_sha256": "4" * 64,
            "version_output": "codex-cli 0.144.6",
            "model_call_count": 0,
        },
        source_snapshot=snapshot,
        task_records=config["tasks"],
        registries=registries,
        toolchain_identity={"reference_compatible": True},
    )
    assert len(plan["items"]) == 30
    assert [
        (item["task_id"], item["sample_index"], item["track"]) for item in plan["items"][:6]
    ] == [
        (config["tasks"][0]["id"], 0, "codex_cli_readonly_single_turn_agent"),
        (config["tasks"][0]["id"], 0, "codex_cli_external_agent"),
        (config["tasks"][0]["id"], 1, "codex_cli_readonly_single_turn_agent"),
        (config["tasks"][0]["id"], 1, "codex_cli_external_agent"),
        (config["tasks"][0]["id"], 2, "codex_cli_readonly_single_turn_agent"),
        (config["tasks"][0]["id"], 2, "codex_cli_external_agent"),
    ]


def test_candidate_and_contained_policy_outcomes_do_not_trip_infrastructure_gate() -> None:
    runner = _runner()
    candidate = SimpleNamespace(scorecard=_score(status="completed", infrastructure=False))
    policy = SimpleNamespace(
        scorecard=_score(
            status="failed",
            infrastructure=False,
            category="workspace_policy",
        )
    )
    assert runner._is_infrastructure(candidate) is False
    assert runner._is_infrastructure(policy) is False
    assert runner._shared_external_prerequisite_failure(candidate) is None
    assert runner._shared_external_prerequisite_failure(policy) is None

    launched = 0
    for index in range(30):
        outcome = policy if index in {3, 9, 21} else candidate
        assert runner._shared_external_prerequisite_failure(outcome) is None
        launched += 1
    assert launched == 30


def test_only_shared_external_categories_stop_future_launches() -> None:
    runner = _runner()
    authentication = SimpleNamespace(
        scorecard=_score(
            status="error",
            infrastructure=True,
            category="authentication",
        )
    )
    timeout = SimpleNamespace(
        scorecard=_score(status="error", infrastructure=True, category="timeout")
    )
    assert (
        runner._shared_external_prerequisite_failure(authentication)
        == "shared_external_prerequisite:authentication"
    )
    assert runner._shared_external_prerequisite_failure(timeout) is None


def test_chatgpt_session_execution_rejects_api_key_environment_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "VERIGYM_CODEX_CREDENTIAL_ENV"):
        monkeypatch.delenv(name, raising=False)
    runner._require_no_api_key_environment()
    monkeypatch.setenv("OPENAI_API_KEY", "value-must-not-be-read")
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        runner._require_no_api_key_environment()


def test_contained_workspace_policy_mutation_is_evaluable_not_a_boundary_escape(
    tmp_path: Path,
) -> None:
    runner = _runner()
    artifact_root = tmp_path / "artifacts" / "codex_cli"
    artifact_root.mkdir(parents=True)
    (artifact_root / "workspace_policy.json").write_text(
        json.dumps(
            {
                "policy_passed": False,
                "violations": [
                    "external agent changed a read-only path: README.md",
                ],
            }
        ),
        encoding="utf-8",
    )
    result = SimpleNamespace(
        run_dir=tmp_path,
        scorecard=_score(
            status="failed",
            infrastructure=False,
            category="workspace_policy",
        ),
    )
    assert runner._actual_security_breach(result) is False
    assert runner._is_infrastructure(result) is False


def test_incomplete_outer_runtime_security_evidence_is_a_security_breach(
    tmp_path: Path,
) -> None:
    runner = _runner()
    artifact_root = tmp_path / "artifacts" / "codex_cli"
    artifact_root.mkdir(parents=True)
    (artifact_root / "runtime_process.json").write_text(
        json.dumps(
            {
                "cleanup_complete": False,
                "runtime_identity": {
                    "execution_owner": "verigym_runtime",
                    "execution_backend": "docker_outer_runtime_delegated",
                    "agent_image_id": "sha256:" + "a" * 64,
                    "verifier_image_id": "sha256:" + "b" * 64,
                },
                "security": {
                    "boundary": "docker_outer_runtime",
                    "network_mode": "none",
                    "effective_controls_verified": False,
                },
            }
        ),
        encoding="utf-8",
    )
    result = SimpleNamespace(
        run_dir=tmp_path,
        scorecard=_score(
            status="failed",
            infrastructure=False,
            category="runtime_security_controls",
        ),
    )
    assert runner._actual_security_breach(result) is True
    assert runner._is_infrastructure(result) is True


def test_reference_toolchain_gate_rejects_icarus_13_and_accepts_12() -> None:
    runner = _runner()
    compatible = {
        "reference_compatible": True,
        "tools": {
            "iverilog": {"version": "Icarus Verilog version 12.0"},
            "vvp": {"version": "Icarus Verilog runtime version 12.0"},
        },
    }
    runner._require_reference_compatible_toolchain(compatible)
    incompatible = {
        "reference_compatible": False,
        "tools": {
            "iverilog": {"version": "Icarus Verilog version 13.0"},
            "vvp": {"version": "Icarus Verilog runtime version 13.0"},
        },
    }
    with pytest.raises(SystemExit, match="Icarus v12"):
        runner._require_reference_compatible_toolchain(incompatible)


def test_noncanonical_pass_at_k_is_null_not_fallback() -> None:
    runner = _runner()
    assert runner._pass_at_k_values(0, canonical=False) == {
        "1": None,
        "2": None,
        "3": None,
    }
    assert runner._pass_at_k_values(2, canonical=True) == {
        "1": pytest.approx(2 / 3),
        "2": 1.0,
        "3": 1.0,
    }


def test_track_metrics_report_pass_at_one_two_and_three() -> None:
    runner = _runner()
    records = [
        {
            "track": "codex_cli_external_agent",
            "launched": True,
            "terminal": True,
            "evaluable": True,
            "resolved": False,
            "compile_status": "failed",
            "hidden_regression_status": "not_run",
            "infrastructure_error": False,
            "typed_tool_policy_passed": True,
            "external_total_tokens": None,
            "wall_time_s": 1.0,
        }
        for _ in range(15)
    ]
    partitions = [
        {
            "integration_track": "codex_cli_external_agent",
            "values": {"1": 1 / 3, "2": 2 / 3, "3": 1.0},
        }
        for _ in range(5)
    ]
    metrics = runner._track_metrics(records, partitions)
    assert metrics == [
        {
            "integration_track": "codex_cli_external_agent",
            "planned_count": 15,
            "launched_count": 15,
            "terminal_count": 15,
            "evaluable_count": 15,
            "resolved_count": 0,
            "compile_pass_count": 0,
            "hidden_test_pass_count": 0,
            "infrastructure_failure_count": 0,
            "infrastructure_failure_rate": 0.0,
            "typed_tool_policy_failure_count": 0,
            "known_usage_count": 0,
            "missing_usage_count": 15,
            "wall_time_total_s": 15.0,
            "wall_time_mean_s": 1.0,
            "pass_at_1_macro": pytest.approx(1 / 3),
            "pass_at_2_macro": pytest.approx(2 / 3),
            "pass_at_3_macro": 1.0,
        }
    ]


def test_historical_track_a_forensic_summary_preserves_all_fifteen_outcomes() -> None:
    fixture = json.loads(
        (
            ROOT
            / "tests"
            / "fixtures"
            / "codex_cli"
            / "historical_track_a_9a84c60_forensic_summary.json"
        ).read_text()
    )
    records = fixture["records"]
    assert fixture["historical_bundle_mutated"] is False
    assert len(records) == 15
    assert len({(record["task"], record["sample"]) for record in records}) == 15
    assert sum(record["origin"] == "hidden_testbench" for record in records) == 13
    assert sum(record["origin"] == "candidate" for record in records) == 2
    assert sum(record["v12_exit"] == 0 for record in records) == 13
    assert all(len(record["message"]) == 64 for record in records)
    assert all(len(record["candidate"]) == 64 for record in records)


@pytest.mark.skipif(
    not HISTORICAL_BUNDLE.is_dir(),
    reason="sealed historical 9a84c60 bundle is unavailable",
)
def test_all_historical_track_a_messages_round_trip_to_frozen_candidates() -> None:
    fixture = json.loads(
        (
            ROOT
            / "tests"
            / "fixtures"
            / "codex_cli"
            / "historical_track_a_9a84c60_forensic_summary.json"
        ).read_text()
    )
    runs_root = HISTORICAL_BUNDLE / "pilot" / "runs"
    for record in fixture["records"]:
        run_id = (
            f"codex-pilot-codex_cli_readonly_single_turn_agent-{record['task']}-{record['sample']}"
        )
        run_dir = runs_root / run_id
        raw_records = [
            json.loads(line)
            for line in (run_dir / "artifacts" / "codex_cli" / "raw_stdout.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        parsed_records = [
            json.loads(line)
            for line in (run_dir / "artifacts" / "codex_cli" / "parsed_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        raw_messages = [
            item["raw"]["item"]["text"]
            for item in raw_records
            if item.get("raw", {}).get("type") == "item.completed"
            and item.get("raw", {}).get("item", {}).get("type") == "agent_message"
        ]
        parsed_messages = [
            item["payload"]["text"]
            for item in parsed_records
            if item.get("category") == "message_completed"
        ]
        assert raw_messages == parsed_messages
        assert len(parsed_messages) == 1
        message = parsed_messages[0]
        assert hashlib.sha256(message.encode()).hexdigest() == record["message"]
        parsed_rtl = parse_single_turn_rtl(message)
        candidate = (run_dir / "candidate" / "rtl" / "TopModule.sv").read_text(encoding="utf-8")
        assert parsed_rtl == candidate
        assert hashlib.sha256(candidate.encode()).hexdigest() == record["candidate"]
        assert declared_modules(candidate) == ["TopModule"]


@pytest.mark.skipif(
    not HISTORICAL_BUNDLE.is_dir(),
    reason="sealed historical 9a84c60 bundle is unavailable",
)
def test_supported_task_reporting_dimension_generates_without_fallback(
    tmp_path: Path,
) -> None:
    reports = ReportService().generate_all(
        HISTORICAL_BUNDLE / "pilot" / "runs",
        output_dir=tmp_path / "reports",
        group_by=("task", "integration_track"),
    )
    assert reports.aggregate.coverage.terminal_child_runs == 21
    assert (tmp_path / "reports" / "aggregate.json").is_file()
    assert (tmp_path / "reports" / "runs.csv").is_file()
    assert (tmp_path / "reports" / "report.md").is_file()
