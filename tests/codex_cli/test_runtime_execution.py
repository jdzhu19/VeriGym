from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest
from verigym_codex_cli.capabilities import runtime_capabilities
from verigym_codex_cli.config import (
    agent_settings,
    readonly_agent_settings,
    settings_for_execution_backend,
)
from verigym_codex_cli.memory_builder import (
    execute_memory_synthesis,
    memory_builder_identity_hashes,
    memory_runtime_binding_hashes,
)
from verigym_codex_cli.runtime_execution import (
    build_runtime_process_request,
    execute_runtime_process,
    resolve_runtime_process_invocation_spec,
)

from verigym.core.external_process_identity import (
    bind_external_process_payload,
    preview_external_process_identity,
)
from verigym.core.hashing import content_hash
from verigym.evolution.memory import build_memory_pack
from verigym.evolution.memory_builder import (
    MEMORY_BUILDER_PROMPT_CONTRACT_ID,
    MEMORY_BUILDER_PROMPT_TEMPLATE_HASH,
    build_memory_builder_input,
    build_memory_synthesis_plan,
    render_memory_builder_prompt,
)
from verigym.runtimes.docker.external_process import (
    external_process_configuration_fingerprint,
)
from verigym.schemas.evolution import (
    MemoryPack,
    RewardVector,
    SanitizedTrainingEpisode,
    SanitizedTrainingSummary,
)
from verigym.schemas.external_agent import (
    ExternalAgentAccounting,
    ExternalProcessRequest,
    ExternalProcessResult,
    ExternalProcessRuntimeIdentity,
    ExternalProcessSecurityEvidence,
)
from verigym.schemas.runtime import DockerExternalAgentRuntimeConfig

pytestmark = [pytest.mark.codex_cli]

IMAGE_A = "sha256:" + "a" * 64
IMAGE_B = "sha256:" + "b" * 64


class RuntimeBridge:
    execution_backend = "docker_outer_runtime_delegated"
    logical_workspace_root = "/workspace"
    editable_globs = ("rtl/**",)
    readonly_globs = ("README.md", "visible/**")

    def __init__(self, root: Path) -> None:
        self.workspace_root = root
        self.artifact_root = root / "artifacts"
        self.isolation_level = "docker_standard"
        self.requests: list[ExternalProcessRequest] = []

    def execute_process(self, request: ExternalProcessRequest) -> ExternalProcessResult:
        self.requests.append(request)
        return ExternalProcessResult(
            exit_code=0,
            stdout=(
                '{"type":"thread.started","model":"fake-model"}\n'
                '{"type":"item.completed","item":{"type":"agent_message",'
                '"text":"module TopModule; endmodule"}}\n'
                '{"type":"turn.completed","status":"completed"}\n'
            ),
            stderr="",
            duration_s=0.25,
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
                protocol="codex_app_server_remote_environment_v1",
                verifier_image_id=IMAGE_A,
                agent_image_id=IMAGE_B,
                agent_image_reference="agent:test",
                agent_image_os="linux",
                agent_image_architecture="amd64",
                agent_image_user="10001:10001",
                agent_executable_name="codex",
                agent_executable_sha256="c" * 64,
                agent_executable_version="codex-cli 0.144.6",
                container_id="d" * 64,
                host_executable_name=request.executable_name,
                host_executable_sha256=request.executable_sha256,
                host_executable_version=request.executable_version,
                capability_fingerprint=request.capability_fingerprint,
                configuration_fingerprint="e" * 64,
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
                memory_bytes=512 * 1024 * 1024,
                cpus=1.0,
                pids_limit=128,
                tmpfs_bytes=64 * 1024 * 1024,
                output_limit_bytes=request.max_output_bytes,
                effective_timeout_s=request.timeout_s,
            ),
        )

    def emit_event(self, event_type: str, payload: dict[str, object]) -> None:
        del event_type, payload

    def record_accounting(self, accounting: ExternalAgentAccounting) -> None:
        del accounting


def _training_summary() -> SanitizedTrainingSummary:
    reward = RewardVector(
        outcome_kind="resolved_candidate",
        infrastructure_valid=1,
        policy_compliance=1,
        public_test_reached=1,
        public_test_passed=1,
        patch_reproducible=1,
        candidate_compile_passed=1,
        hidden_regression_passed=1,
        task_resolved=1,
    )
    episode = SanitizedTrainingEpisode(
        public_task_category="repository_rtl_repair",
        observable_action_summary=["public_test", "candidate_freeze"],
        public_test_outcomes=[True],
        patch_metrics={
            "changed_file_count": 1,
            "added_lines": 1,
            "deleted_lines": 1,
            "public_tool_calls": 1,
        },
        outcome_kind="resolved_candidate",
        reward=reward,
        compile_passed=True,
        hidden_regression_passed=True,
        generalized_failure_labels=[],
    )
    base = {
        "schema_version": "1.0",
        "summary_id": "m10b-training-summary",
        "split_manifest_hash": "a" * 64,
        "trajectory_dataset_hash": "b" * 64,
        "episodes": [episode.model_dump(mode="json")],
        "hidden_assets_included": False,
        "references_included": False,
        "private_reasoning_included": False,
        "heldout_assets_included": False,
    }
    return SanitizedTrainingSummary.model_validate({**base, "summary_hash": content_hash(base)})


def _memory_values() -> dict[str, list[str]]:
    return {
        "principles": ["Confirm observable behavior before making a focused change."],
        "public_test_strategy": ["Use bounded public feedback before finalizing."],
        "workspace_policy_reminders": ["Keep edits inside the declared editable workspace."],
        "debugging_checklist": ["Check reset, control priority, boundaries, and recovery."],
        "patch_discipline": ["Review a minimal coherent diff before finishing."],
    }


class MemoryRuntimeBridge(RuntimeBridge):
    def execute_process(self, request: ExternalProcessRequest) -> ExternalProcessResult:
        result = super().execute_process(request)
        final = json.dumps(_memory_values(), sort_keys=True)
        stdout = (
            '{"type":"thread.started","model":"fake-model"}\n'
            + json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": final},
                },
                separators=(",", ":"),
            )
            + "\n"
            + '{"type":"turn.completed","status":"completed",'
            '"usage":{"input_tokens":10,"output_tokens":5}}\n'
        )
        return result.model_copy(update={"stdout": stdout})


class PolicyRejectedMemoryRuntimeBridge(MemoryRuntimeBridge):
    def execute_process(self, request: ExternalProcessRequest) -> ExternalProcessResult:
        result = super().execute_process(request)
        values = _memory_values()
        values["principles"] = ["Inspect hidden details before making a focused change."]
        final = json.dumps(values, sort_keys=True)
        stdout = (
            '{"type":"thread.started","model":"fake-model"}\n'
            + json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": final},
                },
                separators=(",", ":"),
            )
            + "\n"
            + '{"type":"turn.completed","status":"completed"}\n'
        )
        return result.model_copy(update={"stdout": stdout})


@pytest.mark.parametrize(
    ("track", "workspace_mode", "reasoning_effort"),
    [
        ("readonly", "fresh_empty", "xhigh"),
        ("agent", "visible_task_workspace", "xhigh"),
        ("agent", "visible_task_workspace", "max"),
    ],
)
def test_plugin_delegates_model_process_to_runtime_without_launching_fake_codex(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
    track: Literal["readonly", "agent"],
    workspace_mode: Literal["fresh_empty", "visible_task_workspace"],
    reasoning_effort: Literal["xhigh", "max"],
) -> None:
    _executable_path, log, _scenario = fake_codex
    executable, capabilities = runtime_capabilities()
    options: dict[str, object] = {
        "model_id": "fake-model",
        "sandbox": "read-only" if track == "readonly" else "workspace-write",
        "approval_policy": "never",
        "reasoning_effort": reasoning_effort,
        "max_process_time_s": 300,
    }
    settings = (
        readonly_agent_settings(options, capabilities, task_wall_time_s=300)
        if track == "readonly"
        else agent_settings(options, capabilities, task_wall_time_s=300)
    )
    settings = settings_for_execution_backend(
        settings,
        "docker_outer_runtime_delegated",
    )
    if track == "agent":
        assert settings.tool_use_policy == "docker_runtime_isolated_workspace_policy_v3"
    bridge = RuntimeBridge(tmp_path)
    outcome = execute_runtime_process(
        bridge=bridge,
        executable=executable,
        capabilities=capabilities,
        settings=settings,
        prompt="Return one RTL candidate.",
        workspace_mode=workspace_mode,
    )

    assert outcome.process.arguments == ("<runtime-owned-codex-app-server>",)
    assert outcome.process.exit_code == 0
    assert len(bridge.requests) == 1
    request = bridge.requests[0]
    assert request.argv == [
        "/usr/local/bin/codex",
        "exec-server",
        "--listen",
        "stdio://",
    ]
    assert request.logical_cwd == "/workspace"
    assert request.stdin_text == "Return one RTL candidate."
    assert request.network_policy == "none"
    assert request.mount_policy == "task_workspace_only"
    assert request.requested_model_id == "fake-model"
    assert request.requested_reasoning_effort == reasoning_effort
    assert request.timeout_s == 300
    assert request.container_environment_names == []
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert records
    assert all(record["kind"] == "diagnostic" for record in records)


def test_memory_builder_uses_one_fresh_empty_runtime_process_and_safe_evidence(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    _executable_path, log, _scenario = fake_codex
    executable, capabilities = runtime_capabilities()
    model_hash, codex_hash = memory_builder_identity_hashes(
        capabilities,
        model_id="fake-model",
        reasoning_effort="xhigh",
    )
    runtime_hash, image_hash = memory_runtime_binding_hashes(
        verifier_image_id=IMAGE_A,
        agent_image_id=IMAGE_B,
        configuration_fingerprint="e" * 64,
    )
    request = build_memory_builder_input(
        training_summary=_training_summary(),
        model_identity_hash=model_hash,
        codex_identity_hash=codex_hash,
        auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        runtime_identity_hash=runtime_hash,
        image_identity_hash=image_hash,
        requested_model_id="fake-model",
        reasoning_effort="xhigh",
        output_schema_hash=content_hash(MemoryPack.model_json_schema(mode="serialization")),
        max_output_bytes=131_072,
    )
    bridge = MemoryRuntimeBridge(tmp_path)
    settings = readonly_agent_settings(
        {
            "model_id": "fake-model",
            "reasoning_effort": "xhigh",
            "max_process_time_s": 300,
            "max_output_bytes": 131_072,
            "expected_execution_backend": "docker_outer_runtime_delegated",
        },
        capabilities,
        task_wall_time_s=300,
    )
    settings = settings_for_execution_backend(
        settings,
        "docker_outer_runtime_delegated",
    )
    spec = resolve_runtime_process_invocation_spec(
        bridge=bridge,
        executable=executable,
        capabilities=capabilities,
        settings=settings,
        workspace_mode="fresh_empty",
        prompt_contract_id=MEMORY_BUILDER_PROMPT_CONTRACT_ID,
        expected_output_schema_hash=request.output_schema_hash,
    )
    preview = preview_external_process_identity(spec)
    prompt = render_memory_builder_prompt(request)
    binding = bind_external_process_payload(
        spec,
        prompt,
        template_hash=MEMORY_BUILDER_PROMPT_TEMPLATE_HASH,
        input_dataset_hash=request.training_summary.trajectory_dataset_hash,
    )
    plan = build_memory_synthesis_plan(
        request=request,
        invocation_spec=spec,
        identity_preview=preview,
        payload_binding=binding,
        training_dataset_hash=request.training_summary.trajectory_dataset_hash,
        training_run_ids=["synthetic-training-run"],
        training_source_identities={"synthetic-training-run": "9" * 64},
        reward_profile_hash="8" * 64,
        reward_vector_schema_hash="7" * 64,
    )
    evidence = tmp_path / "memory-evidence"
    outcome = execute_memory_synthesis(
        bridge=bridge,
        request=request,
        agent_options={
            "model_id": "fake-model",
            "reasoning_effort": "xhigh",
            "max_process_time_s": 300,
            "max_output_bytes": 131_072,
            "expected_execution_backend": "docker_outer_runtime_delegated",
        },
        process_ledger_record_hash="f" * 64,
        artifact_root=evidence,
        synthesis_plan=plan,
    )
    assert outcome.result.status == "success"
    assert outcome.result.failure_reason is None
    assert outcome.result.model_processes_started == 1
    assert outcome.result.memory_pack == build_memory_pack(_memory_values())
    assert outcome.event_policy is not None and outcome.event_policy.policy_passed
    assert len(bridge.requests) == 1
    assert bridge.requests[0].workspace_mode == "fresh_empty"
    assert bridge.requests[0].network_policy == "none"
    assert bridge.requests[0].invocation_spec_hash == spec.invocation_spec_hash
    assert bridge.requests[0].payload_binding_hash == binding.payload_binding_hash
    assert outcome.result.memory_synthesis_plan_hash == plan.plan_hash
    assert not log.exists() or all(
        json.loads(line)["kind"] == "diagnostic"
        for line in log.read_text(encoding="utf-8").splitlines()
    )
    assert (evidence / "memory-pack.json").is_file()
    assert (evidence / "memory-synthesis-plan.json").is_file()
    assert not (evidence / "raw_stdout.jsonl").exists()
    process = json.loads((evidence / "process-evidence.json").read_text(encoding="utf-8"))
    assert process["raw_output_persisted"] is False
    assert process["proxy_values_persisted"] is False
    assert process["credential_values_persisted"] is False
    normalized = (evidence / "normalized-events.jsonl").read_text(encoding="utf-8")
    assert "Confirm observable behavior" not in normalized

    rejected_evidence = tmp_path / "rejected-memory-evidence"
    rejected = execute_memory_synthesis(
        bridge=PolicyRejectedMemoryRuntimeBridge(tmp_path / "rejected"),
        request=request,
        agent_options={
            "model_id": "fake-model",
            "reasoning_effort": "xhigh",
            "max_process_time_s": 300,
            "max_output_bytes": 131_072,
            "expected_execution_backend": "docker_outer_runtime_delegated",
        },
        process_ledger_record_hash="e" * 64,
        artifact_root=rejected_evidence,
        synthesis_plan=plan,
    )
    assert rejected.result.status == "content_policy_rejected"
    assert rejected.result.failure_reason == "memory_policy_hidden_or_reference"
    rejected_json = (rejected_evidence / "memory-builder-result.json").read_text(encoding="utf-8")
    assert "Inspect hidden details" not in rejected_json
    assert "memory_policy_hidden_or_reference" in rejected_json


def test_runtime_request_forwards_only_uppercase_transport_proxy_names(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _executable_path, _log, _scenario = fake_codex
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8443")
    monkeypatch.setenv("NO_PROXY", "private.invalid")
    monkeypatch.setenv("http_proxy", "http://ignored-lower.invalid:8080")
    monkeypatch.setenv("https_proxy", "http://ignored-lower.invalid:8443")
    monkeypatch.setenv("no_proxy", "ignored.lower.invalid")
    monkeypatch.setenv("ALL_PROXY", "http://ignored-all.invalid:1080")
    executable, capabilities = runtime_capabilities()
    settings = agent_settings(
        {
            "model_id": "fake-model",
            "sandbox": "workspace-write",
            "approval_policy": "never",
            "reasoning_effort": "xhigh",
            "max_process_time_s": 300,
            "allow_proxy_environment": True,
        },
        capabilities,
        task_wall_time_s=300,
    )
    settings = settings_for_execution_backend(
        settings,
        "docker_outer_runtime_delegated",
    )
    bridge = RuntimeBridge(tmp_path)

    execute_runtime_process(
        bridge=bridge,
        executable=executable,
        capabilities=capabilities,
        settings=settings,
        prompt="Return one RTL candidate.",
        workspace_mode="visible_task_workspace",
    )

    request = bridge.requests[0]
    assert request.forwarded_proxy_environment_names == [
        "HTTP_PROXY",
        "HTTPS_PROXY",
    ]
    assert settings.runtime_forwarded_proxy_environment_names == (
        "HTTP_PROXY",
        "HTTPS_PROXY",
    )


def test_external_process_configuration_fingerprint_is_precomputable(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _executable_path, _log, _scenario = fake_codex
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8443")
    executable, capabilities = runtime_capabilities()
    settings = readonly_agent_settings(
        {
            "model_id": "fake-model",
            "reasoning_effort": "xhigh",
            "allow_proxy_environment": True,
            "max_process_time_s": 300,
            "max_output_bytes": 131_072,
            "expected_execution_backend": "docker_outer_runtime_delegated",
        },
        capabilities,
        task_wall_time_s=300,
    )
    settings = settings_for_execution_backend(
        settings,
        "docker_outer_runtime_delegated",
    )
    bridge = RuntimeBridge(tmp_path)
    request = build_runtime_process_request(
        bridge=bridge,
        executable=executable,
        capabilities=capabilities,
        settings=settings,
        prompt="first prompt",
        workspace_mode="fresh_empty",
    )
    second = request.model_copy(update={"stdin_text": "different bounded prompt"})
    config = DockerExternalAgentRuntimeConfig(
        image="agent:test",
        expected_image_id=IMAGE_B,
        expected_executable_name="codex",
        expected_executable_path="/usr/local/bin/codex",
        expected_executable_version="codex-cli 0.144.6",
        expected_executable_sha256="c" * 64,
        process_argv=["/usr/local/bin/codex", "exec-server"],
        protocol="codex_app_server_remote_environment_v1",
        required_image_labels={"org.verigym.test": "true"},
        run_as_user="10001:10001",
    )
    first_hash = external_process_configuration_fingerprint(
        agent_config=config,
        agent_image_id=IMAGE_B,
        verifier_image_id=IMAGE_A,
        request=request,
        synthesized_environment_names=["NO_PROXY", "no_proxy"],
        mandatory_loopback_bypass_present=True,
    )
    second_hash = external_process_configuration_fingerprint(
        agent_config=config,
        agent_image_id=IMAGE_B,
        verifier_image_id=IMAGE_A,
        request=second,
        synthesized_environment_names=["NO_PROXY", "no_proxy"],
        mandatory_loopback_bypass_present=True,
    )
    assert first_hash == second_hash
