"""One bounded Docker-delegated Codex process for Evolve-Context memory synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.hashing import canonical_json, content_hash
from verigym.evolution.memory_builder import (
    build_memory_builder_result,
    parse_memory_builder_output,
    render_memory_builder_prompt,
    validate_memory_builder_input,
)
from verigym.plugin_api import ExternalAgentBridge, JsonValue
from verigym.schemas.evolution import MemoryBuilderInput, MemoryBuilderResult
from verigym.schemas.external_agent import ExternalProcessResult

from .capabilities import CapabilityReport, runtime_capabilities
from .config import readonly_agent_settings, settings_for_execution_backend
from .event_policy import EventPolicyContext, EventPolicyResult, evaluate_event_policy
from .events import EventParseError, ParsedEventStream, parse_event_stream
from .readonly_agent import _runtime_security_complete
from .runtime_execution import execute_runtime_process
from .util import atomic_json, atomic_jsonl, safe_regular_directory


@dataclass(frozen=True)
class MemorySynthesisOutcome:
    result: MemoryBuilderResult
    runtime_result: ExternalProcessResult
    event_policy: EventPolicyResult | None


def memory_builder_identity_hashes(
    capabilities: CapabilityReport,
    *,
    model_id: str,
    reasoning_effort: str,
) -> tuple[str, str]:
    """Return the exact pre-process model and Codex identities used by the request."""

    model_hash = content_hash(
        {
            "requested_model_id": model_id,
            "reasoning_effort": reasoning_effort,
            "execution_surface": "codex_cli_memory_builder",
        }
    )
    codex_hash = content_hash(
        {
            "version_output": capabilities.version_output,
            "executable_sha256": capabilities.executable_sha256,
            "capability_fingerprint": capabilities.capability_fingerprint,
        }
    )
    return model_hash, codex_hash


def memory_runtime_binding_hashes(
    *,
    verifier_image_id: str,
    agent_image_id: str,
    configuration_fingerprint: str,
    protocol: str = "codex_app_server_remote_environment_v1",
) -> tuple[str, str]:
    """Bind immutable role images and the effective runtime process configuration."""

    images = {
        "verifier_image_id": verifier_image_id,
        "agent_image_id": agent_image_id,
    }
    runtime = {
        **images,
        "configuration_fingerprint": configuration_fingerprint,
        "execution_backend": "docker_outer_runtime_delegated",
        "protocol": protocol,
    }
    return content_hash(runtime), content_hash(images)


def _observed_runtime_hashes(result: ExternalProcessResult) -> tuple[str, str]:
    identity = result.runtime_identity
    return memory_runtime_binding_hashes(
        verifier_image_id=identity.verifier_image_id,
        agent_image_id=identity.agent_image_id,
        configuration_fingerprint=identity.configuration_fingerprint,
        protocol=identity.protocol,
    )


def _safe_process_evidence(
    result: ExternalProcessResult,
    *,
    parsed: ParsedEventStream | None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "exit_code": result.exit_code,
        "duration_s": result.duration_s,
        "timed_out": result.timed_out,
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
        "stdout_bytes": len(result.stdout.encode("utf-8")),
        "stderr_bytes": len(result.stderr.encode("utf-8")),
        "terminal_event_seen": result.terminal_event_seen,
        "process_group_cleaned": result.process_group_cleaned,
        "cleanup_complete": result.cleanup_complete,
        "runtime_identity": result.runtime_identity.model_dump(mode="json"),
        "security": result.security.model_dump(mode="json"),
        "parsed_event_count": len(parsed.events) if parsed is not None else 0,
        "raw_output_persisted": False,
        "proxy_values_persisted": False,
        "credential_values_persisted": False,
    }


def execute_memory_synthesis(
    *,
    bridge: ExternalAgentBridge,
    request: MemoryBuilderInput,
    agent_options: dict[str, JsonValue],
    process_ledger_record_hash: str,
    artifact_root: Path,
    heldout_only_tokens: tuple[str, ...] = (),
) -> MemorySynthesisOutcome:
    """Run exactly one process and preserve a safe terminal result without retrying."""

    validate_memory_builder_input(request)
    executable, capabilities = runtime_capabilities()
    settings = readonly_agent_settings(
        agent_options,
        capabilities,
        task_wall_time_s=request.timeout_s,
    )
    settings = settings_for_execution_backend(settings, bridge.execution_backend)
    expected_model, expected_codex = memory_builder_identity_hashes(
        capabilities,
        model_id=settings.model_id,
        reasoning_effort=settings.effective_reasoning_effort,
    )
    if (
        request.requested_model_id != settings.model_id
        or request.reasoning_effort != settings.effective_reasoning_effort
        or request.timeout_s != settings.effective_process_timeout_s
        or request.max_output_bytes != settings.max_output_bytes
        or request.auth_semantic_id != settings.auth_semantic_id
        or request.model_identity_hash != expected_model
        or request.codex_identity_hash != expected_codex
    ):
        raise ValueError("memory-builder process settings differ from the frozen input")

    outcome = execute_runtime_process(
        bridge=bridge,
        executable=executable,
        capabilities=capabilities,
        settings=settings,
        prompt=render_memory_builder_prompt(request),
        workspace_mode="fresh_empty",
    )
    process = outcome.process
    runtime_result = outcome.runtime_result
    observed_runtime, observed_images = _observed_runtime_hashes(runtime_result)
    if (
        request.runtime_identity_hash != observed_runtime
        or request.image_identity_hash != observed_images
    ):
        raise ValueError("memory-builder runtime or role-image identity mutated")

    parsed: ParsedEventStream | None = None
    policy: EventPolicyResult | None = None
    memory = None
    if (
        process.timed_out
        or process.stdout_truncated
        or process.stderr_truncated
        or process.exit_code != 0
        or not _runtime_security_complete(runtime_result)
    ):
        status = "process_failure"
    else:
        try:
            parsed = parse_event_stream(process.stdout, roots=(Path("/workspace"),))
        except EventParseError:
            status = "parser_error"
        else:
            policy = evaluate_event_policy(
                parsed,
                EventPolicyContext(
                    working_directory=Path("/workspace"),
                    working_directory_identity="fresh_empty_memory_builder_workspace",
                    sandbox_identity=settings.sandbox_policy,
                    network_policy="disabled",
                    mcp_policy="disabled",
                ),
                policy_id="typed_readonly_empty_workdir_v1",
            )
            if not parsed.terminal_event_seen or not parsed.final_messages or parsed.error_messages:
                status = "parser_error"
            elif (
                not policy.policy_passed
                or runtime_result.security.workspace_empty_before is not True
                or runtime_result.security.workspace_empty_after is not True
                or runtime_result.security.workspace_changed_paths
            ):
                status = "content_policy_rejected"
            else:
                try:
                    memory = parse_memory_builder_output(
                        parsed.final_messages[-1],
                        heldout_only_tokens=heldout_only_tokens,
                    )
                except ValueError as exc:
                    status = (
                        "content_policy_rejected"
                        if "policy rejected" in str(exc) or "held-out-only" in str(exc)
                        else "parser_error"
                    )
                else:
                    status = "success"

    process_identity = {
        "model_identity_hash": request.model_identity_hash,
        "codex_identity_hash": request.codex_identity_hash,
        "auth_semantic_id": request.auth_semantic_id,
        "runtime_identity_hash": observed_runtime,
        "image_identity_hash": observed_images,
        "requested_model_id": request.requested_model_id,
        "reasoning_effort": request.reasoning_effort,
    }
    safe_output = (
        canonical_json({section.section: section.items for section in memory.sections})
        if memory is not None
        else f"withheld:{status}"
    )
    result = build_memory_builder_result(
        request=request,
        status=status,
        redacted_output=safe_output,
        process_identity_hash=content_hash(process_identity),
        process_ledger_record_hash=process_ledger_record_hash,
        memory_pack=memory,
        wall_time_s=process.duration_s,
        input_tokens=parsed.input_tokens if parsed is not None else None,
        output_tokens=parsed.output_tokens if parsed is not None else None,
    )

    destination = safe_regular_directory(artifact_root, create=True)
    atomic_json(destination / "memory-builder-input.json", request.model_dump(mode="json"))
    atomic_json(destination / "memory-builder-result.json", result.model_dump(mode="json"))
    atomic_json(
        destination / "process-evidence.json", _safe_process_evidence(runtime_result, parsed=parsed)
    )
    atomic_json(destination / "process-identity.json", process_identity)
    atomic_json(
        destination / "event-policy.json",
        (
            policy.safe_dict()
            if policy is not None
            else {
                "schema_version": "1.0",
                "policy_id": "typed_readonly_empty_workdir_v1",
                "policy_evidence_available": False,
            }
        ),
    )
    atomic_jsonl(
        destination / "normalized-events.jsonl",
        [
            {
                "schema_version": "1.0",
                "sequence": event.sequence,
                "category": event.category,
                "upstream_type": event.upstream_type,
                "payload_persisted": False,
            }
            for event in parsed.events
        ]
        if parsed is not None
        else [],
    )
    if memory is not None:
        atomic_json(destination / "memory-pack.json", memory.model_dump(mode="json"))
    return MemorySynthesisOutcome(
        result=result,
        runtime_result=runtime_result,
        event_policy=policy,
    )


__all__ = [
    "MemorySynthesisOutcome",
    "execute_memory_synthesis",
    "memory_builder_identity_hashes",
    "memory_runtime_binding_hashes",
]
