from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from verigym.schemas.run import RunConfig


def _launcher_module() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "run_rtl_agenteval_codex_pilot_v2.py"
    spec = importlib.util.spec_from_file_location("rtl_agenteval_pilot_v2_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    scripts_path = str(path.parent)
    sys.path.insert(0, scripts_path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_path)
    return module


def test_historical_and_current_campaign_matrices_are_frozen() -> None:
    launcher = _launcher_module()
    qualification = launcher._DEFINITIONS["qualification"]
    pilot = launcher._DEFINITIONS["pilot-v2"]

    assert qualification.process_count == 3
    assert [spec.run_id for spec in qualification.specs] == [
        "01-counter-dc",
        "02-rtl-repo-test-000003",
        "03-rtl-repo-test-000004",
    ]
    assert pilot.process_count == 14
    assert len({spec.run_id for spec in pilot.specs}) == 14
    assert all(
        spec.run_id.startswith(f"{ordinal:02d}-") for ordinal, spec in enumerate(pilot.specs, 1)
    )
    assert [(spec.source_key, spec.profile_name, spec.ppa) for spec in pilot.specs[:4]] == [
        ("counter", "counter_open", True),
        ("counter", "counter_dc", True),
        ("up_down", "up_down_open", True),
        ("up_down", "up_down_dc", True),
    ]
    assert sum(spec.source_key == "verilog_eval" for spec in pilot.specs) == 5
    assert sum(spec.source_key == "rtl_repo" for spec in pilot.specs) == 5
    assert all("official-parquet-v1-agent-eval-v2" in spec.task_id for spec in pilot.specs[9:])
    prior_verilog = {
        "Prob014_andgate",
        "Prob024_hadd",
        "Prob035_count1to10",
        "Prob085_shift4",
        "Prob107_fsm1s",
    }
    prior_rtl_repo = {f"test-{index:06d}" for index in range(6)}
    assert not {spec.task_id.rsplit("/", 1)[-1] for spec in pilot.specs[4:9]}.intersection(
        prior_verilog
    )
    assert not {spec.task_id.rsplit("/", 1)[-1] for spec in pilot.specs[9:]}.intersection(
        prior_rtl_repo
    )
    qualification_v2 = launcher._DEFINITIONS["qualification-v2"]
    pilot_v3 = launcher._DEFINITIONS["pilot-v3"]
    qualification_v3 = launcher._DEFINITIONS["qualification-v3"]
    pilot_v4 = launcher._DEFINITIONS["pilot-v4"]
    qualification_v4 = launcher._DEFINITIONS["qualification-v4"]
    pilot_v5 = launcher._DEFINITIONS["pilot-v5"]
    qualification_v5 = launcher._DEFINITIONS["qualification-v5"]
    pilot_v6 = launcher._DEFINITIONS["pilot-v6"]
    qualification_v6 = launcher._DEFINITIONS["qualification-v6"]
    pilot_v7 = launcher._DEFINITIONS["pilot-v7"]
    assert [spec.run_id for spec in qualification_v2.specs] == [
        "01-counter-open",
        "02-rtl-repo-test-000002",
        "03-rtl-repo-test-000005",
    ]
    assert pilot_v3.specs == pilot.specs
    assert [spec.run_id for spec in qualification_v3.specs] == [
        "01-counter-open",
        "02-rtl-repo-test-000003",
        "03-rtl-repo-test-000004",
    ]
    assert pilot_v4.specs == pilot.specs
    assert qualification_v4.specs == qualification_v3.specs
    assert pilot_v5.specs == pilot.specs
    assert qualification_v5.specs == qualification_v4.specs
    assert pilot_v6.specs == pilot.specs
    assert [spec.run_id for spec in qualification_v6.specs] == [
        "01-counter-open",
        "02-rtl-repo-test-000003",
        "03-rtl-repo-test-000004",
    ]
    assert all(
        "official-parquet-v1-agent-eval-v3" in spec.task_id for spec in qualification_v6.specs[1:]
    )
    assert [spec.task_id for spec in pilot_v7.specs[:9]] == [
        spec.task_id for spec in pilot.specs[:9]
    ]
    assert all("official-parquet-v1-agent-eval-v3" in spec.task_id for spec in pilot_v7.specs[9:])
    assert qualification.agent_version_id == "codex-cli-agenteval-gpt54-xhigh-v6"
    assert qualification_v2.agent_version_id == "codex-cli-agenteval-gpt54-xhigh-v7"
    assert qualification_v3.agent_version_id == "codex-cli-agenteval-gpt54-xhigh-v8"
    assert qualification_v4.agent_version_id == "codex-cli-agenteval-gpt54-xhigh-v9"
    assert qualification_v5.agent_version_id == "codex-cli-agenteval-gpt54-xhigh-v10"
    assert qualification_v6.agent_version_id == "codex-cli-agenteval-gpt54-xhigh-v10"
    assert qualification_v6.rtl_repo_projection_version == "v3"
    assert qualification_v6.rtl_repo_completion_contract == "immediate_next_physical_line_v1"
    assert pilot_v4.bounded_event_categories_safe is True
    assert pilot_v5.process_count == 14
    assert pilot_v5.bounded_event_categories_safe is True
    assert pilot_v6.process_count == 14
    assert pilot_v6.bounded_event_categories_safe is True
    assert pilot_v7.process_count == 14
    assert pilot_v7.bounded_event_categories_safe is True


def test_v7_scoring_contract_uses_broker_validated_optional_message_shape() -> None:
    launcher = _launcher_module()
    definition = launcher._DEFINITIONS["qualification-v2"]

    receipt = launcher._scoring_event_contract_qualification(definition)

    assert receipt["passed"] is True
    assert receipt["model_calls"] == 0
    assert receipt["post_finish_assistant_message_present"] is False
    assert receipt["transport_id_required_for_scoring"] is False
    assert receipt["transport_arguments_revalidated_by_event_projection"] is False
    assert receipt["raw_event_stream_persisted"] is False
    assert any("openai/codex" in url for url in receipt["official_references"])
    assert any("2405.17378" in url for url in receipt["official_references"])


def test_v3_agent_options_freeze_v7_prompt_and_identity() -> None:
    launcher = _launcher_module()
    definition = launcher._DEFINITIONS["qualification-v2"]
    options = launcher._agent_options(
        SimpleNamespace(capability_fingerprint="c" * 64),
        SimpleNamespace(
            requested_auth_mode="chatgpt_cli_session",
            resolved_auth_mode="inherited_codex_login",
            auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        ),
        definition,
    )

    assert options["prompt_contract_id"] == "repository_action_v2_prompt_v5"
    assert options["scoring_agent_version_id"] == definition.agent_version_id
    assert options["scoring_agent_version_hash"] == definition.agent_version_hash
    assert options["expected_prompt_hash"] == definition.prompt_hash
    assert options["expected_tool_policy_fingerprint"] == definition.tool_policy_fingerprint


def test_v4_agent_options_freeze_v8_prompt_and_identity() -> None:
    launcher = _launcher_module()
    definition = launcher._DEFINITIONS["qualification-v3"]
    options = launcher._agent_options(
        SimpleNamespace(capability_fingerprint="c" * 64),
        SimpleNamespace(
            requested_auth_mode="chatgpt_cli_session",
            resolved_auth_mode="inherited_codex_login",
            auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        ),
        definition,
    )

    assert options["prompt_contract_id"] == "repository_action_v2_prompt_v6"
    assert options["scoring_agent_version_id"] == "codex-cli-agenteval-gpt54-xhigh-v8"


def test_v5_agent_options_freeze_v9_broker_attested_identity() -> None:
    launcher = _launcher_module()
    definition = launcher._DEFINITIONS["qualification-v4"]
    options = launcher._agent_options(
        SimpleNamespace(capability_fingerprint="c" * 64),
        SimpleNamespace(
            requested_auth_mode="chatgpt_cli_session",
            resolved_auth_mode="inherited_codex_login",
            auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        ),
        definition,
    )

    assert options["prompt_contract_id"] == "repository_action_v2_prompt_v6"
    assert options["scoring_agent_version_id"] == "codex-cli-agenteval-gpt54-xhigh-v9"
    receipt = launcher._scoring_event_contract_qualification(definition)
    assert receipt["broker_tool_sequence_required_for_scoring"] is True
    assert receipt["mcp_server_label_authoritative"] is False
    assert receipt["direct_mcp_exposure_required"] is False


def test_v6_agent_options_freeze_v10_direct_mcp_identity() -> None:
    launcher = _launcher_module()
    definition = launcher._DEFINITIONS["qualification-v5"]
    options = launcher._agent_options(
        SimpleNamespace(capability_fingerprint="c" * 64),
        SimpleNamespace(
            requested_auth_mode="chatgpt_cli_session",
            resolved_auth_mode="inherited_codex_login",
            auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        ),
        definition,
    )

    assert options["prompt_contract_id"] == "repository_action_v2_prompt_v6"
    assert options["scoring_agent_version_id"] == "codex-cli-agenteval-gpt54-xhigh-v10"
    receipt = launcher._scoring_event_contract_qualification(definition)
    assert receipt["broker_tool_sequence_required_for_scoring"] is True
    assert receipt["direct_mcp_exposure_required"] is True


def test_v7_campaign_reuses_v10_agent_and_freezes_rtl_repo_v3_identity() -> None:
    launcher = _launcher_module()
    definition = launcher._DEFINITIONS["qualification-v6"]

    assert definition.agent_version_id == "codex-cli-agenteval-gpt54-xhigh-v10"
    assert definition.prompt_contract_id == "repository_action_v2_prompt_v6"
    assert definition.rtl_repo_variant == "official-parquet-v1-agent-eval-v3"
    assert definition.rtl_repo_suite_version.endswith("agent-eval-v3")
    assert definition.rtl_repo_completion_contract == "immediate_next_physical_line_v1"


def test_v3_campaign_keeps_the_historical_broker_regression_on_v2(tmp_path: Path) -> None:
    launcher = _launcher_module()
    inputs = {
        "rtllm": tmp_path / "rtllm",
        "verilog_eval": tmp_path / "verilog-eval",
        "rtl_repo": tmp_path / "rtl-repo",
    }
    campaign = launcher._source_configs(inputs, launcher._DEFINITIONS["qualification-v6"])
    broker_regression = launcher._broker_regression_source_configs(campaign, inputs)

    assert campaign["rtl_repo"].variant == "official-parquet-v1-agent-eval-v3"
    assert broker_regression["rtl_repo"].variant == "official-parquet-v1-agent-eval-v2"
    assert broker_regression["counter"] == campaign["counter"]
    assert broker_regression["verilog_eval"] == campaign["verilog_eval"]


def _gymfix_summary(launcher: ModuleType) -> dict[str, object]:
    run_ids = [
        "01-counter-open",
        "02-counter-dc",
        "03-rtl-repo-test-000002",
        "04-rtl-repo-test-000003",
        "05-rtl-repo-test-000005",
        "06-rtl-repo-test-000004-control",
    ]
    return {
        "campaign_id": launcher.gymfix._CAMPAIGN_ID,
        "diagnostic_complete": True,
        "infrastructure_complete": True,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 6,
        "provider_observations_recorded": 6,
        "automatic_retries": 0,
        "fully_successful": False,
        "runs": [
            {
                "run_id": run_id,
                "typed_finish": run_id != "03-rtl-repo-test-000002",
                "provider_usage_complete": True,
                "timed_out": False,
                "policy_failure": False,
                "infrastructure_failure": False,
            }
            for run_id in run_ids
        ],
    }


def test_qualification_predecessor_requires_three_complete_eventfix_controls(
    tmp_path: Path,
) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = _gymfix_summary(launcher)
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification"])

    assert receipt["read_only"] is True
    assert receipt["fully_successful"] is False
    summary["runs"][3]["typed_finish"] = False  # type: ignore[index]
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="event-fix control"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification"])


def test_pilot_v2_predecessor_requires_successful_v6_qualification(tmp_path: Path) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = {
        "campaign_id": launcher._QUALIFICATION_ID,
        "qualification_complete": True,
        "fully_successful": True,
        "pilot_v2_authorized": True,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 3,
        "provider_observations_recorded": 3,
        "automatic_retries": 0,
        "runs": [
            {
                "resolved": True,
                "typed_finish": True,
                "provider_usage_complete": True,
                "identity_observation_count": 1,
            }
            for _ in range(3)
        ],
    }
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v2"])

    assert receipt["fully_successful"] is True
    summary["pilot_v2_authorized"] = False
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="fully successful v6 qualification"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v2"])


def _failed_v6_qualification_summary(launcher: ModuleType) -> dict[str, object]:
    outcomes = [
        ("01-counter-dc", True, True, None),
        (
            "02-rtl-repo-test-000003",
            False,
            True,
            "scoring_event_mcp_outside_verigym",
        ),
        (
            "03-rtl-repo-test-000004",
            False,
            False,
            "scoring_event_missing_finish",
        ),
    ]
    return {
        "campaign_id": launcher._QUALIFICATION_ID,
        "qualification_complete": True,
        "infrastructure_complete": True,
        "fully_successful": False,
        "pilot_v2_authorized": False,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 3,
        "provider_observations_recorded": 3,
        "automatic_retries": 0,
        "runs": [
            {
                "run_id": run_id,
                "resolved": resolved,
                "typed_finish": typed_finish,
                "failure_subcategory": subcategory,
                "provider_usage_complete": True,
                "identity_observation_count": 1,
                "timed_out": False,
                "policy_failure": False,
                "infrastructure_failure": False,
            }
            for run_id, resolved, typed_finish, subcategory in outcomes
        ],
    }


def test_qualification_v2_requires_exact_failed_v6_receipt(tmp_path: Path) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = _failed_v6_qualification_summary(launcher)
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification-v2"])

    assert receipt["read_only"] is True
    assert receipt["fully_successful"] is False
    summary["runs"][1]["failure_subcategory"] = "changed"  # type: ignore[index]
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="frozen v6 outcomes"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification-v2"])


def _failed_v7_qualification_summary(launcher: ModuleType) -> dict[str, object]:
    outcomes = [
        ("01-counter-open", True, True, True, False, None),
        (
            "02-rtl-repo-test-000002",
            False,
            False,
            True,
            False,
            "scoring_event_mcp_server",
        ),
        ("03-rtl-repo-test-000005", False, False, False, True, None),
    ]
    return {
        "campaign_id": launcher._QUALIFICATION_V2_ID,
        "qualification_complete": False,
        "infrastructure_complete": False,
        "fully_successful": False,
        "pilot_v3_authorized": False,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 3,
        "provider_observations_recorded": 3,
        "automatic_retries": 0,
        "runs": [
            {
                "run_id": run_id,
                "resolved": resolved,
                "typed_finish": typed_finish,
                "provider_usage_complete": usage_complete,
                "timed_out": timed_out,
                "failure_subcategory": subcategory,
                "identity_observation_count": 1,
                "policy_failure": False,
                "infrastructure_failure": False,
            }
            for (
                run_id,
                resolved,
                typed_finish,
                usage_complete,
                timed_out,
                subcategory,
            ) in outcomes
        ],
    }


def test_qualification_v3_requires_exact_failed_v7_receipt(tmp_path: Path) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = _failed_v7_qualification_summary(launcher)
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification-v3"])

    assert receipt["read_only"] is True
    assert receipt["fully_successful"] is False
    summary["runs"][2]["provider_usage_complete"] = True  # type: ignore[index]
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="frozen v7 outcomes"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification-v3"])


def test_pilot_v3_requires_successful_v7_qualification(tmp_path: Path) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = {
        "campaign_id": launcher._QUALIFICATION_V2_ID,
        "qualification_complete": True,
        "fully_successful": True,
        "pilot_v3_authorized": True,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 3,
        "provider_observations_recorded": 3,
        "automatic_retries": 0,
        "runs": [
            {
                "resolved": True,
                "typed_finish": True,
                "provider_usage_complete": True,
                "identity_observation_count": 1,
            }
            for _ in range(3)
        ],
    }
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v3"])

    assert receipt["fully_successful"] is True
    summary["pilot_v3_authorized"] = False
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="fully successful v7 qualification"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v3"])


def test_pilot_v4_requires_successful_v8_qualification(tmp_path: Path) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = {
        "campaign_id": launcher._QUALIFICATION_V3_ID,
        "qualification_complete": True,
        "fully_successful": True,
        "pilot_v4_authorized": True,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 3,
        "provider_observations_recorded": 3,
        "automatic_retries": 0,
        "runs": [
            {
                "resolved": True,
                "typed_finish": True,
                "provider_usage_complete": True,
                "identity_observation_count": 1,
            }
            for _ in range(3)
        ],
    }
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v4"])

    assert receipt["fully_successful"] is True
    summary["pilot_v4_authorized"] = False
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="fully successful v8 qualification"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v4"])


def _failed_v8_qualification_summary(launcher: ModuleType) -> dict[str, object]:
    return {
        "campaign_id": launcher._QUALIFICATION_V3_ID,
        "qualification_complete": True,
        "infrastructure_complete": True,
        "fully_successful": False,
        "pilot_v4_authorized": False,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 3,
        "provider_observations_recorded": 3,
        "automatic_retries": 0,
        "runs": [
            {
                "run_id": run_id,
                "resolved": False,
                "typed_finish": True,
                "provider_usage_complete": True,
                "timed_out": False,
                "failure_category": "scoring_event_ineligible",
                "failure_subcategory": "scoring_event_mcp_server",
                "identity_observation_count": 1,
                "policy_failure": False,
                "infrastructure_failure": False,
            }
            for run_id in (
                "01-counter-open",
                "02-rtl-repo-test-000003",
                "03-rtl-repo-test-000004",
            )
        ],
    }


def test_qualification_v4_requires_exact_failed_v8_receipt(tmp_path: Path) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = _failed_v8_qualification_summary(launcher)
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification-v4"])

    assert receipt["read_only"] is True
    summary["runs"][0]["typed_finish"] = False  # type: ignore[index]
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="frozen v8 outcomes"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification-v4"])


def test_pilot_v5_requires_successful_v9_qualification(tmp_path: Path) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = {
        "campaign_id": launcher._QUALIFICATION_V4_ID,
        "qualification_complete": True,
        "fully_successful": True,
        "pilot_v5_authorized": True,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 3,
        "provider_observations_recorded": 3,
        "automatic_retries": 0,
        "runs": [
            {
                "resolved": True,
                "typed_finish": True,
                "provider_usage_complete": True,
                "identity_observation_count": 1,
            }
            for _ in range(3)
        ],
    }
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v5"])

    assert receipt["fully_successful"] is True
    summary["pilot_v5_authorized"] = False
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="fully successful v9 qualification"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v5"])


def _failed_v9_qualification_summary(launcher: ModuleType) -> dict[str, object]:
    outcomes = [
        ("01-counter-open", True, None),
        ("02-rtl-repo-test-000003", False, "scoring_event_mcp_tool"),
        ("03-rtl-repo-test-000004", False, "scoring_event_mcp_tool"),
    ]
    return {
        "campaign_id": launcher._QUALIFICATION_V4_ID,
        "qualification_complete": True,
        "infrastructure_complete": True,
        "fully_successful": False,
        "pilot_v5_authorized": False,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 3,
        "provider_observations_recorded": 3,
        "automatic_retries": 0,
        "runs": [
            {
                "run_id": run_id,
                "resolved": resolved,
                "typed_finish": True,
                "provider_usage_complete": True,
                "timed_out": False,
                "failure_subcategory": failure_subcategory,
                "identity_observation_count": 1,
                "policy_failure": False,
                "infrastructure_failure": False,
            }
            for run_id, resolved, failure_subcategory in outcomes
        ],
    }


def test_qualification_v5_requires_exact_failed_v9_receipt(tmp_path: Path) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = _failed_v9_qualification_summary(launcher)
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification-v5"])

    assert receipt["read_only"] is True
    summary["runs"][1]["failure_subcategory"] = "changed"  # type: ignore[index]
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="frozen v9 outcomes"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification-v5"])


def test_pilot_v6_requires_successful_v10_qualification(tmp_path: Path) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = {
        "campaign_id": launcher._QUALIFICATION_V5_ID,
        "qualification_complete": True,
        "fully_successful": True,
        "pilot_v6_authorized": True,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 3,
        "provider_observations_recorded": 3,
        "automatic_retries": 0,
        "runs": [
            {
                "resolved": True,
                "typed_finish": True,
                "provider_usage_complete": True,
                "identity_observation_count": 1,
            }
            for _ in range(3)
        ],
    }
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v6"])

    assert receipt["fully_successful"] is True
    summary["pilot_v6_authorized"] = False
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="fully successful v10 qualification"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v6"])


def _failed_v10_qualification_summary(launcher: ModuleType) -> dict[str, object]:
    outcomes = [
        ("01-counter-open", True),
        ("02-rtl-repo-test-000003", False),
        ("03-rtl-repo-test-000004", True),
    ]
    runs = [
        {
            "run_id": run_id,
            "resolved": resolved,
            "typed_finish": True,
            "provider_usage_complete": True,
            "timed_out": False,
            "failure_category": None,
            "failure_subcategory": None,
            "identity_observation_count": 1,
            "policy_failure": False,
            "infrastructure_failure": False,
            "compile_passed": run_id == "01-counter-open",
            "legal_candidate_ppa": run_id == "01-counter-open",
            "final_ppa_eligible": run_id == "01-counter-open",
        }
        for run_id, resolved in outcomes
    ]
    return {
        "campaign_id": launcher._QUALIFICATION_V5_ID,
        "qualification_complete": True,
        "infrastructure_complete": True,
        "fully_successful": False,
        "pilot_v6_authorized": False,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 3,
        "provider_observations_recorded": 3,
        "automatic_retries": 0,
        "runs": runs,
    }


def test_qualification_v6_requires_exact_verifier_rejected_v10_receipt(
    tmp_path: Path,
) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = _failed_v10_qualification_summary(launcher)
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification-v6"])

    assert receipt["read_only"] is True
    summary["runs"][1]["failure_subcategory"] = "changed"  # type: ignore[index]
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="frozen v10 outcomes"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["qualification-v6"])


def test_pilot_v7_requires_successful_v3_qualification(tmp_path: Path) -> None:
    launcher = _launcher_module()
    path = tmp_path / "summary.json"
    summary = {
        "campaign_id": launcher._QUALIFICATION_V6_ID,
        "qualification_complete": True,
        "fully_successful": True,
        "pilot_v7_authorized": True,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 3,
        "provider_observations_recorded": 3,
        "automatic_retries": 0,
        "runs": [
            {
                "resolved": True,
                "typed_finish": True,
                "provider_usage_complete": True,
                "identity_observation_count": 1,
            }
            for _ in range(3)
        ],
    }
    path.write_text(json.dumps(summary), encoding="utf-8")

    receipt = launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v7"])

    assert receipt["fully_successful"] is True
    summary["pilot_v7_authorized"] = False
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Exception, match="fully successful v10/v3 qualification"):
        launcher._validate_predecessor(path, launcher._DEFINITIONS["pilot-v7"])


def _configs(output: Path, definition: object) -> list[RunConfig]:
    return [
        RunConfig(task_id=spec.task_id, output=output / "runs", run_id=spec.run_id)
        for spec in definition.specs
    ]


def _observation(definition: object) -> SimpleNamespace:
    return SimpleNamespace(
        invocation_count=1,
        requested_model_id="gpt-5.4",
        observed_model_id=None,
        effective_reasoning_effort="xhigh",
        harness_id=definition.agent_version_id,
        agent_version_hash=definition.agent_version_hash,
        prompt_contract_hash=definition.prompt_hash,
        tool_policy_fingerprint=definition.tool_policy_fingerprint,
    )


def _execution_result(
    root: Path,
    config: RunConfig,
    definition: object,
    *,
    failure: object | None = None,
    infrastructure_error: bool = False,
    resolved: bool = True,
) -> SimpleNamespace:
    run_dir = root / "actual-runs" / str(config.run_id)
    evidence = run_dir / "artifacts" / "codex_cli"
    evidence.mkdir(parents=True)
    (evidence / "process.json").write_text("{}", encoding="utf-8")
    (evidence / "identity.json").write_text("{}", encoding="utf-8")
    return SimpleNamespace(
        run_dir=run_dir,
        manifest=SimpleNamespace(external_agent_observations=[_observation(definition)]),
        scorecard=SimpleNamespace(
            resolved=resolved,
            correctness=SimpleNamespace(infrastructure_error=infrastructure_error),
            failure=failure,
        ),
    )


class _FakeService:
    def __init__(
        self,
        root: Path,
        definition: object,
        outcomes: list[dict[str, object]],
    ) -> None:
        self.root = root
        self.definition = definition
        self.outcomes = outcomes
        self.calls = 0

    def run(self, config: RunConfig) -> SimpleNamespace:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        return _execution_result(self.root, config, self.definition, **outcome)


def test_pilot_v4_runs_exactly_fourteen_without_retry_and_continues_model_failure(
    tmp_path: Path,
) -> None:
    launcher = _launcher_module()
    definition = launcher._DEFINITIONS["pilot-v4"]
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    outcomes: list[dict[str, object]] = [{} for _ in range(14)]
    outcomes[0] = {
        "failure": SimpleNamespace(kind="model", infrastructure=False),
        "resolved": False,
    }
    outcomes[1] = {"resolved": False}
    service = _FakeService(tmp_path, definition, outcomes)

    results = launcher._execute_bounded(service, _configs(output, definition), output, definition)
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]

    assert len(results) == 14
    assert service.calls == 14
    assert [record["status"] for record in records[:2]] == [
        "contained_model_failure",
        "verifier_rejection",
    ]
    assert all(record["identity_observation_count"] == 1 for record in records)
    assert all(record["retry_count"] == 0 for record in records)


@pytest.mark.parametrize(
    "outcome",
    [
        {
            "failure": SimpleNamespace(kind="runtime", infrastructure=True),
            "infrastructure_error": True,
        },
        {"failure": SimpleNamespace(kind="policy", infrastructure=False), "resolved": False},
    ],
)
def test_pilot_v4_stops_on_infrastructure_or_safety_failure(
    tmp_path: Path,
    outcome: dict[str, object],
) -> None:
    launcher = _launcher_module()
    definition = launcher._DEFINITIONS["pilot-v4"]
    output = tmp_path / "campaign"
    (output / "evidence").mkdir(parents=True)
    service = _FakeService(tmp_path, definition, [{}, outcome, *({} for _ in range(12))])

    with pytest.raises(launcher.CampaignInfrastructureError, match="identity, or safety"):
        launcher._execute_bounded(service, _configs(output, definition), output, definition)

    assert service.calls == 2
    records = json.loads(
        (output / "evidence" / "process-authorizations.json").read_text(encoding="utf-8")
    )["records"]
    assert len(records) == 2
    assert records[-1]["status"] in {"infrastructure_failure", "policy_failure"}
    assert records[-1]["retry_count"] == 0


def _summary_result(
    launcher: ModuleType,
    tmp_path: Path,
    definition: object,
    index: int,
) -> SimpleNamespace:
    spec = definition.specs[index]
    run_dir = tmp_path / spec.run_id
    evidence = run_dir / "artifacts" / "codex_cli"
    evidence.mkdir(parents=True)
    (evidence / "identity.json").write_text("{}", encoding="utf-8")
    (evidence / "broker.json").write_text(
        json.dumps({"finished": True, "finish_calls": 1}), encoding="utf-8"
    )
    (evidence / "process.json").write_text(json.dumps({"timed_out": False}), encoding="utf-8")
    (evidence / "provider-usage.json").write_text(
        json.dumps({"usage_complete": True}), encoding="utf-8"
    )
    (evidence / "summary.json").write_text(
        json.dumps({"failure_subcategory": None}), encoding="utf-8"
    )
    candidate_hash = f"{index + 1:x}" * 64
    profile_hash = "f" * 64 if spec.ppa else None
    evaluations = []
    if spec.ppa:
        evaluations = [
            SimpleNamespace(
                test_id="compile",
                passed=True,
                metrics=None,
                candidate_hash=candidate_hash,
                profile_hash=None,
            ),
            SimpleNamespace(
                test_id="ppa",
                passed=True,
                metrics=object(),
                candidate_hash=candidate_hash,
                profile_hash=profile_hash,
            ),
        ]
    return SimpleNamespace(
        run_dir=run_dir,
        manifest=SimpleNamespace(
            run_id=spec.run_id,
            task_id=spec.task_id,
            candidate_hash=candidate_hash,
            resolved_profile_hash=profile_hash,
            external_agent_observations=[_observation(definition)],
            agent_feedback_evaluations=evaluations,
        ),
        scorecard=SimpleNamespace(
            resolved=True,
            correctness=SimpleNamespace(infrastructure_error=False),
            failure=None,
            quality=SimpleNamespace(
                ppa=SimpleNamespace(eligible=True) if spec.ppa else None,
            ),
        ),
    )


def test_pilot_v4_success_requires_all_processes_finishes_usage_and_ppa(
    tmp_path: Path,
) -> None:
    launcher = _launcher_module()
    definition = launcher._DEFINITIONS["pilot-v4"]
    results = [
        _summary_result(launcher, tmp_path, definition, index)
        for index in range(definition.process_count)
    ]

    summary = launcher._campaign_summary(
        results,
        {"all_valid": True},
        {"passed": True},
        {"passed": True},
        definition,
    )

    assert summary["pilot_complete"] is True
    assert summary["fully_successful"] is True
    assert summary["codex_processes_started"] == 14
    assert summary["provider_observations_recorded"] == 14
    assert summary["pilot_is_benchmark_score"] is False
    assert summary["benchmark_score_claimed"] is False

    results[0].scorecard.quality.ppa.eligible = False
    rejected = launcher._campaign_summary(
        results,
        {"all_valid": True},
        {"passed": True},
        {"passed": True},
        definition,
    )
    assert rejected["pilot_complete"] is True
    assert rejected["fully_successful"] is False


def test_v4_launchers_have_distinct_opt_ins_and_refuse_nonempty_outputs(
    tmp_path: Path,
) -> None:
    launcher = _launcher_module()
    source = Path(launcher.__file__).read_text(encoding="utf-8")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "user-data").write_text("preserve", encoding="utf-8")

    with pytest.raises(Exception, match="must not already exist"):
        launcher.smoke._new_path(occupied, "experiment output")

    assert "VERIGYM_RUN_RTL_AGENT_EVAL_EVENTFIX_QUALIFICATION" in source
    assert "VERIGYM_RUN_RTL_AGENT_EVAL_PILOT_V2" in source
    assert "VERIGYM_RUN_RTL_AGENT_EVAL_TRANSPORTFIX_QUALIFICATION_V2" in source
    assert "VERIGYM_RUN_RTL_AGENT_EVAL_PILOT_V3" in source
    assert "VERIGYM_RUN_RTL_AGENT_EVAL_FINALIZATIONFIX_QUALIFICATION_V3" in source
    assert "VERIGYM_RUN_RTL_AGENT_EVAL_PILOT_V4" in source
    assert "VERIGYM_RUN_RTL_AGENT_EVAL_BROKERATTEST_QUALIFICATION_V4" in source
    assert "VERIGYM_RUN_RTL_AGENT_EVAL_PILOT_V5" in source
    assert "VERIGYM_RUN_RTL_AGENT_EVAL_DIRECTMCP_QUALIFICATION_V5" in source
    assert "VERIGYM_RUN_RTL_AGENT_EVAL_PILOT_V6" in source
    assert '"automatic_retries": 0' in source
    assert '"benchmark_score_claimed": False' in source
    assert (occupied / "user-data").read_text(encoding="utf-8") == "preserve"


def test_v8_scan_excludes_only_the_frozen_safe_mcp_server_enum() -> None:
    launcher = _launcher_module()
    safe = b'{"failure_subcategory":"scoring_event_mcp_server"}'
    unsafe = b'{"diagnostic":"license_server unavailable"}'

    assert launcher.smoke._COMMERCIAL_DIAGNOSTIC.search(safe)
    assert (
        launcher.smoke._COMMERCIAL_DIAGNOSTIC.search(launcher._without_safe_event_categories(safe))
        is None
    )
    assert launcher.smoke._COMMERCIAL_DIAGNOSTIC.search(
        launcher._without_safe_event_categories(unsafe)
    )


def test_v9_scan_excludes_only_the_fixed_server_category_key() -> None:
    launcher = _launcher_module()
    safe = b'{"mcp_server_category_counts":{"exact_verigym":3}}'
    unsafe = b'{"mcp_server_category_counts":{},"diagnostic":"license_server unavailable"}'

    assert launcher.smoke._COMMERCIAL_DIAGNOSTIC.search(safe)
    assert (
        launcher.smoke._COMMERCIAL_DIAGNOSTIC.search(launcher._without_safe_event_categories(safe))
        is None
    )
    assert launcher.smoke._COMMERCIAL_DIAGNOSTIC.search(
        launcher._without_safe_event_categories(unsafe)
    )
