from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.util import atomic_json

from verigym.core.integrity import verify_artifact_manifest
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig
from verigym.registry.collections import build_registries
from verigym.reporting.service import ReportService
from verigym.runtimes.docker.external_process import DockerExternalProcessExecutor
from verigym.schemas.external_agent import (
    ExternalProcessRequest,
    ExternalProcessResult,
    ExternalProcessRuntimeIdentity,
    ExternalProcessSecurityEvidence,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker,
    pytest.mark.external_benchmark,
    pytest.mark.codex_cli,
    pytest.mark.codex_cli_pilot,
]

ROOT = Path(__file__).resolve().parents[2]


def _runner() -> ModuleType:
    path = ROOT / "scripts" / "run_codex_cli_pilot.py"
    spec = importlib.util.spec_from_file_location("verigym_fake_docker_pilot_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_runtime_result(
    executor: DockerExternalProcessExecutor,
    request: ExternalProcessRequest,
    visible_workspace: Path,
) -> ExternalProcessResult:
    del visible_workspace
    agent = executor._agent_image  # noqa: SLF001 - bounded fake-runtime acceptance harness
    verifier = executor._verifier_image  # noqa: SLF001
    agent_config = executor._agent_config  # noqa: SLF001
    message = (
        "module TopModule; endmodule"
        if request.workspace_mode == "fresh_empty"
        else "External workspace inspection complete."
    )
    stdout = "\n".join(
        (
            json.dumps(
                {
                    "type": "thread.started",
                    "thread_id": "fake-docker-zero-call",
                    "model": request.requested_model_id,
                }
            ),
            json.dumps({"type": "turn.started"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": message},
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                }
            ),
            "",
        )
    )
    container_id = hashlib.sha256(
        f"{request.integration_track}:{request.executable_sha256}".encode()
    ).hexdigest()
    return ExternalProcessResult(
        exit_code=0,
        stdout=stdout,
        stderr="",
        duration_s=0.001,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        output_limit_hit=False,
        oom_killed=False,
        process_group_cleaned=True,
        cleanup_complete=True,
        terminal_event_seen=True,
        runtime_identity=ExternalProcessRuntimeIdentity(
            execution_owner="verigym_runtime",
            execution_backend="docker_outer_runtime_delegated",
            protocol=request.protocol,
            verifier_image_id=verifier.resolved_image_id,
            agent_image_id=agent.resolved_image_id,
            agent_image_reference=agent.requested_reference,
            agent_image_os=agent.os,
            agent_image_architecture=agent.architecture,
            agent_image_user=agent.effective_user or "",
            agent_executable_name=agent_config.expected_executable_name,
            agent_executable_sha256=agent_config.expected_executable_sha256,
            agent_executable_version=agent_config.expected_executable_version,
            container_id=container_id,
            host_executable_name=request.executable_name,
            host_executable_sha256=request.executable_sha256,
            host_executable_version=request.executable_version,
            capability_fingerprint=request.capability_fingerprint,
            configuration_fingerprint=hashlib.sha256(
                b"verigym-zero-call-fake-docker-process-v1"
            ).hexdigest(),
            logical_workspace_root="/workspace",
        ),
        security=ExternalProcessSecurityEvidence(
            boundary="docker_outer_runtime",
            network_mode="none",
            read_only_rootfs=True,
            non_root=True,
            cap_drop=["ALL"],
            no_new_privileges=True,
            init=True,
            private_pid_namespace=True,
            private_ipc_namespace=True,
            mount_destinations=["/workspace"],
            writable_destinations=["/workspace", "/tmp"],
            environment_names=["CODEX_HOME", "HOME", "LANG", "LC_ALL", "PATH", "TMPDIR"],
            credential_environment_names_in_container=[],
            proxy_environment_names_in_container=[],
            control_plane_proxy_forwarding_enabled=request.allow_proxy_environment,
            control_plane_forwarded_proxy_environment_names=(
                request.forwarded_proxy_environment_names
            ),
            control_plane_synthesized_environment_names=(
                ["NO_PROXY", "no_proxy"] if request.allow_proxy_environment else []
            ),
            control_plane_mandatory_loopback_bypass_present=True,
            host_home_mounted=False,
            source_repository_mounted=False,
            hidden_verifier_mounted=False,
            docker_socket_mounted=False,
            credential_files_mounted=False,
            api_key_environment_forwarded=False,
            credential_contents_accessed_by_verigym=False,
            user_config_contents_accessed_by_verigym=False,
            user_config_metadata_unchanged=True,
            provider_network_in_container=False,
            broker_transport="loopback_websocket_to_container_stdio",
            broker_listen_scope="127.0.0.1",
            effective_controls_verified=True,
            container_exit_inspected=True,
            cleanup_verified=True,
            container_removed=True,
            broker_stopped=True,
            process_group_cleaned=True,
            workspace_empty_before=(True if request.workspace_mode == "fresh_empty" else None),
            workspace_empty_after=(True if request.workspace_mode == "fresh_empty" else None),
            workspace_changed_paths=[],
            memory_bytes=agent_config.memory_bytes,
            cpus=agent_config.cpus,
            pids_limit=agent_config.pids_limit,
            tmpfs_bytes=agent_config.tmpfs_bytes,
            output_limit_bytes=min(request.max_output_bytes, agent_config.max_output_bytes),
            effective_timeout_s=min(
                request.timeout_s,
                float(agent_config.max_process_time_s),
            ),
        ),
    )


def test_zero_model_fake_docker_pilot_is_30_of_30_terminal_and_evaluable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("VERIGYM_RUN_DOCKER_FAKE_PILOT") != "1":
        pytest.skip("set VERIGYM_RUN_DOCKER_FAKE_PILOT=1 for fake 30-run acceptance")
    source_root = Path(os.environ["VERIGYM_VERILOG_EVAL_ROOT"]).resolve(strict=True)
    output = Path(os.environ["VERIGYM_FAKE_DOCKER_PILOT_OUTPUT"]).resolve()
    assert not output.exists() and not output.is_symlink()
    output.mkdir(parents=True)
    runs_root = output / "runs"
    runs_root.mkdir()

    fake_codex = (ROOT / "integrations/verigym-codex-cli/tests/fake_codex.py").resolve()
    fake_log = output / "fake-codex-calls.jsonl"
    capability_path = output / "fake-capabilities.json"
    monkeypatch.setenv("VERIGYM_CODEX_BINARY", str(fake_codex))
    monkeypatch.setenv("VERIGYM_CODEX_TEST_MODE", "1")
    monkeypatch.setenv("VERIGYM_FAKE_CODEX_SCENARIO", "valid")
    monkeypatch.setenv("VERIGYM_FAKE_CODEX_LOG", str(fake_log))
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")
    _identity, capability = discover_capabilities(force=True)
    atomic_json(capability_path, capability.safe_dict())
    monkeypatch.setenv("VERIGYM_CODEX_CAPABILITY_FILE", str(capability_path))
    monkeypatch.setattr(DockerExternalProcessExecutor, "execute", _fake_runtime_result)

    runner = _runner()
    config = yaml.safe_load(
        (ROOT / "examples/experiments/codex-cli-verilog-eval-pilot.yaml").read_text(
            encoding="utf-8"
        )
    )
    service = VeriGym(build_registries())
    source_config, source_snapshot, task_records = runner._freeze_source(
        service,
        config,
        source_root,
    )
    docker_config = runner._docker_runtime_config(max_process_time_s=300)
    runtime_identity, toolchain_identity, references = runner._docker_preflight(
        service,
        docker_config=docker_config,
        source_config=source_config,
        task_records=task_records,
    )
    plan = runner._build_plan(
        config,
        model_id="fake-docker-zero-call",
        capability=capability.safe_dict(),
        source_snapshot=source_snapshot,
        task_records=task_records,
        registries=service.registries,
        toolchain_identity=toolchain_identity,
        runtime_identity=runtime_identity,
        reference_preflight=references,
    )
    atomic_json(output / "fake30-plan.json", plan)

    results = []
    outcomes: list[dict[str, Any]] = []
    for item in plan["items"]:
        run_config = runner._run_config(
            item,
            model_id="fake-docker-zero-call",
            output=runs_root,
            source_config=source_config,
            source_snapshot=source_snapshot,
            task_records=task_records,
            experiment_id=plan["experiment_id"],
            max_process_time_s=300,
            docker_config=docker_config,
        )
        result = service.run(run_config)
        results.append(result)
        outcomes.append(
            {
                "plan_index": item["plan_index"],
                "run_id": result.manifest.run_id,
                "track": item["track"],
                "task_id": item["task_id"],
                "sample_index": item["sample_index"],
                "terminal": True,
                "evaluable": not runner._is_infrastructure(result),
                "resolved": result.scorecard.resolved,
                "status": result.scorecard.status,
            }
        )

    replay = []
    for result in results:
        summary = replay_run(result.run_dir, verify=True)
        replay.append(
            {
                "run_id": result.manifest.run_id,
                "success": True,
                "reverified_resolved": summary.reverified_resolved,
                "codex_process_count": 0,
                "broker_process_count": 0,
                "model_call_count": 0,
            }
        )
    reports = ReportService().generate_all(
        runs_root,
        output_dir=output / "reports",
        group_by=("task", "integration_track"),
    )
    calls = [json.loads(line) for line in fake_log.read_text(encoding="utf-8").splitlines() if line]
    integrity_count = sum(
        verify_artifact_manifest(result.run_dir, expected_scope="run").status == "verified"
        for result in results
    )
    partitions = {
        (outcome["task_id"], outcome["track"]): [
            child
            for child in outcomes
            if child["task_id"] == outcome["task_id"] and child["track"] == outcome["track"]
        ]
        for outcome in outcomes
    }
    acceptance = {
        "schema_version": "1.0",
        "fake_external_process_simulation": True,
        "real_model_process_count": 0,
        "diagnostic_process_count": len(calls),
        "fake_model_process_count": sum(call.get("kind") == "model" for call in calls),
        "planned_count": len(plan["items"]),
        "terminal_count": len(outcomes),
        "evaluable_count": sum(outcome["evaluable"] for outcome in outcomes),
        "replay_success_count": len(replay),
        "replay_cli_broker_model_call_count": 0,
        "integrity_verified_count": integrity_count,
        "reference_preflight": references,
        "docker_runtime_identity": runtime_identity,
        "canonical_partition_count": sum(
            len(children) == 3
            and sorted(child["sample_index"] for child in children) == [0, 1, 2]
            and all(child["evaluable"] for child in children)
            for children in partitions.values()
        ),
        "report_terminal_child_runs": reports.aggregate.coverage.terminal_child_runs,
        "outcomes": outcomes,
        "replay": replay,
    }
    checks = {
        "references_5_of_5": references["passed_count"] == 5,
        "planned_30": acceptance["planned_count"] == 30,
        "terminal_30": acceptance["terminal_count"] == 30,
        "evaluable_30": acceptance["evaluable_count"] == 30,
        "replay_30_zero_call": acceptance["replay_success_count"] == 30,
        "integrity_30": integrity_count == 30,
        "canonical_10_partitions": acceptance["canonical_partition_count"] == 10,
        "supported_reporting_dimension": acceptance["report_terminal_child_runs"] == 30,
        "no_fake_model_subprocesses": acceptance["fake_model_process_count"] == 0,
    }
    acceptance["checks"] = checks
    acceptance["status"] = "PASS" if all(checks.values()) else "FAIL"
    atomic_json(output / "fake30-acceptance.json", acceptance)
    assert acceptance["status"] == "PASS"


def test_zero_model_fake_docker_pilot_uses_generic_experiment_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if os.environ.get("VERIGYM_RUN_DOCKER_FAKE_PILOT") != "1":
        pytest.skip("set VERIGYM_RUN_DOCKER_FAKE_PILOT=1 for fake 30-run acceptance")
    source_root = Path(os.environ["VERIGYM_VERILOG_EVAL_ROOT"]).resolve(strict=True)
    fake_codex = (ROOT / "integrations/verigym-codex-cli/tests/fake_codex.py").resolve()
    fake_log = tmp_path / "fake-codex-calls.jsonl"
    capability_path = tmp_path / "fake-capabilities.json"
    monkeypatch.setenv("VERIGYM_CODEX_BINARY", str(fake_codex))
    monkeypatch.setenv("VERIGYM_CODEX_TEST_MODE", "1")
    monkeypatch.setenv("VERIGYM_FAKE_CODEX_SCENARIO", "valid")
    monkeypatch.setenv("VERIGYM_FAKE_CODEX_LOG", str(fake_log))
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")
    _identity, capability = discover_capabilities(force=True)
    atomic_json(capability_path, capability.safe_dict())
    monkeypatch.setenv("VERIGYM_CODEX_CAPABILITY_FILE", str(capability_path))
    monkeypatch.setattr(DockerExternalProcessExecutor, "execute", _fake_runtime_result)

    auth = {
        "expected_requested_auth_mode": "chatgpt_cli_session",
        "expected_resolved_auth_mode": "inherited_codex_login",
        "expected_auth_semantic_id": "codex.auth.inherited_chatgpt_session.v1",
    }
    common = {
        "model_id": "fake-docker-zero-call",
        "reasoning_effort": "xhigh",
        "approval_policy": "non-interactive",
        "max_process_time_s": 300,
        "max_output_bytes": 8 * 1024 * 1024,
        "allow_proxy_environment": True,
        "expected_cli_version": capability.version_output,
        "expected_cli_executable_sha256": capability.executable_sha256,
        "expected_capability_fingerprint": capability.capability_fingerprint,
        "expected_execution_backend": "docker_outer_runtime_delegated",
        **auth,
    }
    docker_config = _runner()._docker_runtime_config(max_process_time_s=300)
    config = ExperimentConfig.model_validate(
        {
            "schema_version": "1.0",
            "name": "generic-fake-docker-30",
            "suite": {
                "id": "verilog-eval",
                "source": str(source_root),
                "variant": "v2-spec-to-rtl",
                "tasks": {
                    "include": [
                        "Prob014_andgate",
                        "Prob024_hadd",
                        "Prob035_count1to10",
                        "Prob085_shift4",
                        "Prob107_fsm1s",
                    ],
                    "exclude": [],
                },
            },
            "runs": {
                "mode": "agent",
                "seeds": [0],
                "samples_per_task": 3,
                "pass_k": [1, 2, 3],
            },
            "systems": [
                {
                    "id": "codex-cli-readonly-agent",
                    "agent": {
                        "id": "codex-cli-readonly-agent",
                        "options": {
                            **common,
                            "sandbox": "read-only",
                            "prompt_contract_id": ("codex_cli_readonly_verilog_task_context_v1"),
                        },
                    },
                },
                {
                    "id": "codex-cli-agent",
                    "agent": {
                        "id": "codex-cli-agent",
                        "options": {
                            **common,
                            "sandbox": "workspace-write",
                            "prompt_contract_id": ("codex_cli_workspace_verilog_task_context_v1"),
                        },
                    },
                },
            ],
            "runtime": {
                "id": "docker",
                "docker": docker_config.model_dump(mode="json"),
            },
            "execution": {
                "max_workers": 1,
                "max_plan_items": 30,
                "max_model_processes": 30,
                "resume_model_process_policy": "never_rerun_after_authorization",
                "max_consecutive_identical_shared_infrastructure_failures": 2,
                "max_total_infrastructure_failures": 5,
                "summary_checkpoint_interval": 8,
                "seal_plan_before_execution": True,
                "frozen_campaign_identity": {
                    "campaign": "generic_zero_model_fake_30",
                    "provider": "synthetic_events_only",
                },
            },
            "output": {"root": str(tmp_path / "experiment")},
        }
    )
    service = VeriGym(build_registries())
    planner = ExperimentPlanner(service)
    result = BatchRunner(
        planner=planner,
        service_factory=lambda: VeriGym(build_registries()),
    ).run(planner.build(config))
    assert result.exit_code == 0
    assert result.state.planned_count == 30
    assert result.state.terminal_count == 30
    assert result.state.valid_terminal_count == 30
    assert result.state.authorized_model_process_count == 30
    assert result.state.infrastructure_error_count == 0
    assert (
        len(
            (result.experiment_dir / "process-ledger.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        == 30
    )
    aggregate = json.loads(
        (result.experiment_dir / "reports" / "aggregate.json").read_text(encoding="utf-8")
    )
    assert aggregate["coverage"]["planned_plan_items"] == 30
    assert aggregate["coverage"]["evaluable_candidate_runs"] == 30
    assert aggregate["coverage"]["infrastructure_error_runs"] == 0
