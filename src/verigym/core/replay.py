"""Offline trace validation and optional verifier-only re-execution."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from verigym.core.errors import ArtifactIntegrityError, ReplayError
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.integrity import verify_artifact_manifest
from verigym.core.loaders import dump_json, load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.repository_candidate import (
    repository_plan_identity,
    verify_frozen_repository_candidate_offline,
)
from verigym.core.synthesis import execute_synthesis_quality
from verigym.core.trace import read_trace
from verigym.core.verifier_dag import has_infrastructure_error
from verigym.core.workspace import normalize_relative_path
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.protocols.repository_action import (
    RepositoryActionProtocolViolation,
    bounded_tool_result_identity,
    extract_transport_action,
    repository_action_state_failure,
    task_requires_public_test,
    validate_canonical_action,
)
from verigym.provenance import get_build_provenance
from verigym.schemas.action_protocol import ProviderNativeToolCall, RepositoryProtocolError
from verigym.schemas.common import ToolchainProfile
from verigym.schemas.integrity import IntegrityValidation
from verigym.schemas.replay import ReplayEvidence
from verigym.schemas.run import RunManifest
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.synthesis import SynthesisMetrics
from verigym.schemas.task import VeriTask
from verigym.schemas.tool import ToolResult
from verigym.schemas.trace import EpisodeEvent
from verigym.schemas.verifier import VerifierResult, VerifierStatus
from verigym.tools.base import SynthesisBackendPlugin


@dataclass(frozen=True)
class ReplaySummary:
    manifest: RunManifest
    scorecard: ScoreCard
    events: list[EpisodeEvent]
    integrity: IntegrityValidation
    reverified_results: list[VerifierResult] | None = None
    reverified_candidate_synthesis: SynthesisMetrics | None = None
    reverified_reference_synthesis: SynthesisMetrics | None = None

    @property
    def reverified_resolved(self) -> bool | None:
        if self.reverified_results is None:
            return None
        return all(result.status == VerifierStatus.PASSED for result in self.reverified_results)


def replay_run(
    run_dir: Path,
    *,
    verify: bool = False,
    service: VeriGym | None = None,
    verification_artifact_root: Path | None = None,
) -> ReplaySummary:
    """Validate stored hashes and events; never invoke an agent or model."""

    run_dir = run_dir.expanduser().resolve()
    if verification_artifact_root is not None and not verify:
        raise ReplayError("a verifier replay artifact root requires verify=True")
    replay_artifacts = run_dir / "artifacts" / "replay-verification"
    if verification_artifact_root is not None:
        requested_root = verification_artifact_root.expanduser()
        if requested_root.exists() or requested_root.is_symlink():
            raise ReplayError("verifier replay artifact root must be new")
        replay_artifacts = requested_root.resolve(strict=False)
        if replay_artifacts.is_relative_to(run_dir):
            raise ReplayError("external verifier replay artifacts cannot modify the source run")
        if not replay_artifacts.parent.is_dir() or replay_artifacts.parent.is_symlink():
            raise ReplayError("verifier replay artifact parent is unsafe")
    required = [
        "run_manifest.json",
        "task_snapshot.json",
        "trace.jsonl",
        "scorecard.json",
        "workspace_diff.patch",
        "candidate",
        "logs",
        "artifacts",
    ]
    missing = [name for name in required if not (run_dir / name).exists()]
    if missing:
        raise ReplayError(f"run directory is incomplete; missing: {', '.join(missing)}")
    try:
        integrity = verify_artifact_manifest(run_dir, expected_scope="run")
    except ArtifactIntegrityError as exc:
        if "candidate/" in str(exc):
            raise ArtifactIntegrityError(
                f"candidate snapshot failed artifact integrity: {exc}"
            ) from exc
        raise
    manifest = load_model(run_dir / "run_manifest.json", RunManifest)
    if (manifest.prompt_policy is None) != (manifest.prompt_policy_hash is None):
        raise ReplayError("run manifest prompt descriptor and hash are inconsistent")
    if (
        manifest.prompt_policy is not None
        and manifest.prompt_policy_hash != manifest.prompt_policy.configuration_fingerprint
    ):
        raise ReplayError("run manifest prompt policy hash is inconsistent")
    if (
        manifest.prompt_policy is not None
        and manifest.prompt_policy.resolver_id == "agent_execution_prompt_policy_v1"
        and manifest.agent_configuration_hash is None
    ):
        raise ReplayError("resolved agent prompt lacks its execution configuration identity")
    if manifest.action_protocol is None and manifest.action_protocol_records:
        raise ReplayError("run manifest contains action records without a protocol identity")
    if manifest.action_protocol is not None:
        if manifest.action_protocol.configuration_fingerprint != content_hash(
            manifest.action_protocol.model_dump(
                mode="json", exclude={"schema_version", "configuration_fingerprint"}
            )
        ):
            raise ReplayError("run manifest repository action protocol hash is inconsistent")
        expected_turn = 0
        for record in manifest.action_protocol_records:
            if record.turn_index != expected_turn:
                raise ReplayError("repository action protocol records are not contiguous")
            expected_turn += 1
    task = load_model(run_dir / "task_snapshot.json", VeriTask)
    try:
        task_payload = json.loads((run_dir / "task_snapshot.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError("task snapshot is not valid JSON") from exc
    scorecard = load_model(run_dir / "scorecard.json", ScoreCard)
    if scorecard.run_id != manifest.run_id or scorecard.task_id != manifest.task_id:
        raise ReplayError("scorecard identity does not match the run manifest")
    if content_hash(task_payload) != manifest.task_hash:
        raise ReplayError("task_snapshot.json does not match the manifest task hash")
    if repository_plan_identity(task) != manifest.repository_task_identity:
        raise ReplayError("repository task identity does not match the run manifest")
    candidate_hash = hash_directory(run_dir / "candidate")
    if manifest.candidate_hash is None or candidate_hash != manifest.candidate_hash:
        raise ReplayError("candidate snapshot does not match the manifest candidate hash")
    if scorecard.reproducibility.candidate_hash != candidate_hash:
        raise ReplayError("scorecard candidate hash does not match the frozen candidate")
    if scorecard.reproducibility.task_hash != manifest.task_hash:
        raise ReplayError("scorecard task hash does not match the run manifest")
    if scorecard.reproducibility.run_config_hash != manifest.run_config_hash:
        raise ReplayError("scorecard run-config hash does not match the run manifest")
    if content_hash(task_payload.get("verifier")) != manifest.verifier_hash:
        raise ReplayError("verifier graph does not match the manifest verifier hash")
    if scorecard.reproducibility.verifier_hash != manifest.verifier_hash:
        raise ReplayError("scorecard verifier hash does not match the run manifest")
    if manifest.repository_candidate is not None:
        try:
            raw_repository = task.metadata.get("repository_repair")
            if not isinstance(raw_repository, dict) or not isinstance(
                raw_repository.get("workspace_contract"),
                dict,
            ):
                raise ValueError("repository task snapshot lacks its workspace contract")
            from verigym.schemas.repository import RepositoryWorkspaceContract

            contract = RepositoryWorkspaceContract.model_validate(
                raw_repository["workspace_contract"]
            )
            verify_frozen_repository_candidate_offline(
                candidate_repository=run_dir / "candidate" / contract.repository_root,
                patch_file=run_dir / "repository.patch",
                record=manifest.repository_candidate,
                contract=contract,
            )
        except Exception as exc:
            raise ReplayError(f"repository candidate replay failed: {exc}") from exc
    profile_path = run_dir / "artifacts" / "toolchain_profile.json"
    stored_profile: ToolchainProfile | None = None
    stored_resolved_profile: ResolvedToolchainProfile | None = None
    if profile_path.is_file() and manifest.toolchain_profiles:
        stored_profile = load_model(profile_path, ToolchainProfile)
        try:
            profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayError("stored toolchain profile is not valid JSON") from exc
        profile_ref = manifest.toolchain_profiles[0]
        if (
            stored_profile.id != profile_ref.id
            or stored_profile.version != profile_ref.version
            or content_hash(profile_payload) != profile_ref.content_hash
        ):
            raise ReplayError("stored toolchain profile does not match its manifest reference")
    resolved_profile_path = run_dir / "artifacts" / "resolved_toolchain_profile.json"
    if manifest.resolved_profile_hash is not None:
        if stored_profile is None or not resolved_profile_path.is_file():
            raise ReplayError("profile-enabled run lacks its declared or resolved profile artifact")
        stored_resolved_profile = load_model(resolved_profile_path, ResolvedToolchainProfile)
        if (
            stored_resolved_profile.resolved_profile_hash != manifest.resolved_profile_hash
            or stored_resolved_profile.declared_profile_hash != manifest.declared_profile_hash
            or content_hash(stored_resolved_profile.identity_payload())
            != stored_resolved_profile.resolved_profile_hash
            or content_hash(stored_profile) != stored_resolved_profile.declared_profile_hash
        ):
            raise ReplayError("resolved toolchain profile identity does not match the manifest")
        if (
            manifest.resolved_toolchain_profile is not None
            and manifest.resolved_toolchain_profile != stored_resolved_profile
        ):
            raise ReplayError("inline and artifact resolved toolchain profiles differ")
        _validate_stored_synthesis_artifacts(run_dir, manifest, scorecard)
    elif resolved_profile_path.exists():
        raise ReplayError("run has a resolved profile artifact but no manifest identity")
    events = read_trace(run_dir / "trace.jsonl", expected_run_id=manifest.run_id)
    if not events or events[0].event_type != "episode_started":
        raise ReplayError("trace does not begin with episode_started")
    if events[-1].event_type != "episode_terminated":
        raise ReplayError("trace does not end with episode_terminated")
    _validate_provider_request_identities(manifest, events)
    _validate_repository_action_protocol_replay(manifest, events, task)

    reverified: list[VerifierResult] | None = None
    replay_candidate_synthesis: SynthesisMetrics | None = None
    replay_reference_synthesis: SynthesisMetrics | None = None
    if verify:
        if verification_artifact_root is not None:
            replay_artifacts.mkdir(mode=0o700)
        service = service or VeriGym()
        suite_id = manifest.task_id.split("/", 1)[0]
        suite = service.registries.suites.get(suite_id)
        if manifest.suite_source is not None:
            frozen_source = manifest.suite_source
            suite = suite.with_source(
                SuiteSourceConfig(
                    source_root=Path(frozen_source.source_root),
                    variant=frozen_source.variant,
                    strict_compatibility=frozen_source.strict_compatibility,
                )
            )
            current_source = suite.source_snapshot()
            if (
                current_source is None
                or current_source.dataset_content_hash != frozen_source.dataset_content_hash
                or current_source.configuration_fingerprint
                != frozen_source.configuration_fingerprint
            ):
                raise ReplayError("external suite source differs from the frozen manifest")
        assets = suite.resolve_assets(task)
        runtime_plugin = service.registries.runtimes.get(manifest.runtime.name)
        runtime = runtime_plugin.configure_for_replay(manifest.runtime)
        runtime.prepare(f"{manifest.run_id}-replay-{uuid.uuid4().hex[:8]}")
        try:
            replay_resolved_profile: ResolvedToolchainProfile | None = None
            synthesis_backend: SynthesisBackendPlugin | None = None
            if stored_resolved_profile is not None:
                assert stored_profile is not None
                assert stored_profile.flow is not None
                candidate_backend = service.registries.tools.get(stored_profile.flow.backend_plugin)
                if not isinstance(candidate_backend, SynthesisBackendPlugin):
                    raise ReplayError("stored profile backend is not a synthesis backend")
                synthesis_backend = candidate_backend
                reference = suite.reference_solution(task)
                replay_resolved_profile = resolve_toolchain_profile(
                    stored_profile,
                    runtime,
                    source_paths=list(task.workspace.entrypoints),
                    top_module=stored_resolved_profile.top_module,
                    reference_candidate_hash=(
                        content_hash(reference) if reference is not None else None
                    ),
                    expected=stored_resolved_profile,
                    backend=synthesis_backend,
                )
            reverified = service._verify_candidate(
                suite=suite,
                task=task,
                assets=assets,
                runtime=runtime,
                candidate_dir=run_dir / "candidate",
                artifact_root=replay_artifacts,
            )
            if replay_resolved_profile is not None:
                assert stored_profile is not None
                assert synthesis_backend is not None
                by_id = {result.node_id: result for result in reverified}
                correctness_passed = all(
                    by_id.get(node_id) is not None
                    and by_id[node_id].status == VerifierStatus.PASSED
                    for node_id in task.scoring.correctness_required_nodes
                ) and not has_infrastructure_error(reverified)
                synthesis = execute_synthesis_quality(
                    suite=suite,
                    task=task,
                    candidate_dir=run_dir / "candidate",
                    runtime=runtime,
                    profile=stored_profile,
                    resolved=replay_resolved_profile,
                    artifact_root=replay_artifacts,
                    plugin=synthesis_backend,
                    correctness_passed=correctness_passed,
                )
                reverified.extend(synthesis.results)
                replay_candidate_synthesis = synthesis.candidate
                replay_reference_synthesis = synthesis.reference
                _validate_replayed_quality(
                    scorecard,
                    replay_candidate_synthesis,
                    replay_reference_synthesis,
                )
        finally:
            runtime.close()
        dump_json(
            replay_artifacts / "runtime_descriptor.json",
            runtime.descriptor,
        )
        dump_json(
            replay_artifacts / "replay_evidence.json",
            ReplayEvidence(
                run_id=manifest.run_id,
                created_at_utc=datetime.now(UTC),
                verifier_reexecuted=True,
                stored_integrity_status=integrity.status,
                original_artifact_manifest_hash=integrity.manifest_hash,
                reverified_result_hash=(
                    content_hash(reverified) if reverified is not None else None
                ),
                runtime=runtime.descriptor,
                build_provenance=get_build_provenance(),
            ),
        )
    return ReplaySummary(
        manifest=manifest,
        scorecard=scorecard,
        events=events,
        integrity=integrity,
        reverified_results=reverified,
        reverified_candidate_synthesis=replay_candidate_synthesis,
        reverified_reference_synthesis=replay_reference_synthesis,
    )


def _validate_provider_request_identities(
    manifest: RunManifest,
    events: list[EpisodeEvent],
) -> None:
    provider_observations = [
        observation
        for observation in manifest.model_observations
        if observation.provider_request is not None
    ]
    if not provider_observations:
        return
    if manifest.model is None:
        raise ReplayError("provider request identity lacks a model descriptor")
    requests = {
        str(event.payload.get("request", {}).get("request_id")): event
        for event in events
        if event.event_type == "model_request" and isinstance(event.payload.get("request"), dict)
    }
    for observation in provider_observations:
        identity = observation.provider_request
        assert identity is not None
        if identity.credential_persisted or identity.credential_hashed:
            raise ReplayError("provider request identity claims unsafe credential handling")
        if (
            identity.provider_id != manifest.model.provider
            or identity.requested_model_id != manifest.model.model_id
        ):
            raise ReplayError("provider request identity differs from the model descriptor")
        configuration = manifest.model.configuration
        base_url = configuration.get("base_url")
        if (
            not isinstance(base_url, str)
            or identity.normalized_base_url != base_url
            or identity.base_url_hash != content_hash(base_url)
        ):
            raise ReplayError("provider base URL identity differs from the model descriptor")
        if (
            identity.prompt_policy_hash != manifest.prompt_policy_hash
            or identity.agent_configuration_hash != manifest.agent_configuration_hash
        ):
            raise ReplayError("provider request prompt or agent binding differs from the run")
        expected_action_protocol_hash = (
            manifest.action_protocol.configuration_fingerprint
            if manifest.action_protocol is not None
            else None
        )
        if identity.action_protocol_hash != expected_action_protocol_hash:
            raise ReplayError("provider request action-protocol binding differs from the run")
        event = requests.get(observation.request_id)
        if event is None or event.payload.get("content_truncated") is True:
            raise ReplayError("provider request trace is missing or truncated")
        request = event.payload.get("request")
        assert isinstance(request, dict)
        messages = request.get("messages")
        if not isinstance(messages, list):
            raise ReplayError("provider request trace has no message list")
        normalized_messages: list[dict[str, str]] = []
        for message in messages:
            if (
                not isinstance(message, dict)
                or not isinstance(message.get("role"), str)
                or not isinstance(message.get("content"), str)
            ):
                raise ReplayError("provider request trace contains an invalid message")
            normalized_messages.append(
                {
                    "role": message["role"],
                    "content": message["content"],
                }
            )
        if identity.prompt_payload_hash != content_hash(normalized_messages):
            raise ReplayError("provider request prompt payload hash cannot be reproduced")
        parameters = {
            "temperature": request.get("temperature"),
            "top_p": request.get("top_p"),
            "max_output_tokens": request.get("max_output_tokens"),
            "stop": request.get("stop"),
        }
        thinking_mode = configuration.get("thinking_mode")
        if thinking_mode is not None:
            if thinking_mode not in {"disabled", "enabled"}:
                raise ReplayError("provider request has an invalid thinking-mode identity")
            parameters["thinking_mode"] = thinking_mode
        if identity.request_parameters_hash != content_hash(parameters):
            raise ReplayError("provider request parameter hash cannot be reproduced")


def _validate_repository_action_protocol_replay(
    manifest: RunManifest,
    events: list[EpisodeEvent],
    task: VeriTask,
) -> None:
    descriptor = manifest.action_protocol
    if descriptor is None:
        return
    authorizations = [event for event in events if event.event_type == "model_call_authorized"]
    requests = [event for event in events if event.event_type == "model_request"]
    response_list = [event for event in events if event.event_type == "model_response"]
    if not (
        len(authorizations)
        == len(requests)
        == len(response_list)
        == len(manifest.model_observations)
    ):
        raise ReplayError("repository action model-call ledger accounting is incomplete")
    for ordinal, (authorization, request, response) in enumerate(
        zip(authorizations, requests, response_list, strict=True),
        1,
    ):
        request_payload = request.payload.get("request")
        request_id = (
            request_payload.get("request_id") if isinstance(request_payload, dict) else None
        )
        if (
            authorization.payload.get("ordinal") != ordinal
            or authorization.payload.get("request_id") != request_id
            or response.payload.get("request_id") != request_id
            or authorization.payload.get("action_protocol_hash")
            != descriptor.configuration_fingerprint
            or authorization.payload.get("retry") is not False
            or authorization.payload.get("session_reuse") is not False
            or not request.sequence < authorization.sequence < response.sequence
        ):
            raise ReplayError("repository action model-call authorization cannot be reproduced")
    responses: dict[str, EpisodeEvent] = {}
    parsed_events: dict[str, EpisodeEvent] = {}
    rejected_events: dict[str, EpisodeEvent] = {}
    for event in events:
        request_id = event.payload.get("request_id")
        if not isinstance(request_id, str):
            continue
        target = (
            responses
            if event.event_type == "model_response"
            else parsed_events
            if event.event_type == "agent_action_parsed"
            else rejected_events
            if event.event_type == "agent_action_rejected"
            else None
        )
        if target is not None:
            if request_id in target:
                raise ReplayError("repository action trace contains duplicate request decisions")
            target[request_id] = event
    state = "awaiting_action"
    patch_applied = False
    public_observed = False
    diff_observed = False
    records = manifest.action_protocol_records
    for index, record in enumerate(records):
        if record.turn_index != index or record.state_before != state:
            raise ReplayError("repository action state or turn index cannot be reproduced")
        response_event = responses.get(record.request_id)
        if response_event is None:
            raise ReplayError("repository action record lacks its model response")
        payload = response_event.payload
        text = payload.get("text")
        if not isinstance(text, str):
            raise ReplayError("repository action response trace lacks bounded text")
        text_bytes = text.encode("utf-8")
        stored_bytes = payload.get("text_bytes")
        stored_hash = payload.get("text_sha256")
        if not isinstance(stored_bytes, int) or not isinstance(stored_hash, str):
            raise ReplayError("repository action response lacks raw text identity")
        if payload.get("content_truncated") is not True and (
            stored_bytes != len(text_bytes) or stored_hash != hash_bytes(text_bytes)
        ):
            raise ReplayError("repository action raw response identity cannot be reproduced")
        raw_calls = payload.get("native_tool_calls")
        if not isinstance(raw_calls, list):
            raise ReplayError("repository action response lacks native-call transport evidence")
        try:
            native_calls = [ProviderNativeToolCall.model_validate(value) for value in raw_calls]
        except Exception as exc:
            raise ReplayError("repository action native-call evidence is invalid") from exc
        if payload.get("native_tool_calls_hash") != content_hash(
            [call.model_dump(mode="json") for call in native_calls]
        ):
            raise ReplayError("repository action native-call identity cannot be reproduced")
        failure: RepositoryProtocolError | None = None
        normalization = None
        raw = None
        envelope = None
        arguments = None
        finish_reason = payload.get("finish_reason")
        if finish_reason == "length":
            failure = "agent_response_oversized"
        elif finish_reason in {"content_filter", "error"}:
            failure = "agent_unsupported_transport"
        elif payload.get("content_truncated") is True:
            if stored_bytes > descriptor.max_response_bytes:
                failure = "agent_response_oversized"
            else:
                raise ReplayError("bounded action response cannot reproduce protocol parsing")
        else:
            try:
                raw, normalization = extract_transport_action(
                    transport=descriptor.action_transport,
                    text=text,
                    native_tool_calls=native_calls,
                    max_response_bytes=descriptor.max_response_bytes,
                )
                envelope, arguments = validate_canonical_action(raw, task=task)
                failure = repository_action_state_failure(
                    envelope.action,
                    state_machine_id=descriptor.state_machine_id,
                    public_test_required=task_requires_public_test(task),
                    patch_applied=patch_applied,
                    public_observed=public_observed,
                    diff_observed=diff_observed,
                    finished=state == "finished",
                )
            except RepositoryActionProtocolViolation as exc:
                failure = exc.subcategory
        if record.normalization != normalization:
            raise ReplayError("repository action normalization decision cannot be reproduced")
        expected_envelope_hash = content_hash(raw) if raw is not None else None
        if record.action_envelope_hash != expected_envelope_hash:
            raise ReplayError("repository action envelope hash cannot be reproduced")
        if record.accepted:
            if failure is not None or envelope is None or arguments is None:
                raise ReplayError("accepted repository action cannot be reproduced")
            if record.action_name != envelope.action:
                raise ReplayError("repository action name differs from its frozen record")
            if record.arguments_hash != content_hash(envelope.arguments):
                raise ReplayError("repository action arguments hash cannot be reproduced")
            parsed = parsed_events.get(record.request_id)
            parsed_payload = parsed.payload.get("action") if parsed is not None else None
            if not isinstance(parsed_payload, dict) or parsed_payload.get(
                "action"
            ) != envelope.model_dump(mode="json"):
                raise ReplayError("repository action parsed-event linkage is inconsistent")
            if envelope.action == "finish":
                if record.tool_result_hash is not None or record.state_after != "finished":
                    raise ReplayError("repository finish record has invalid terminal evidence")
                state = "finished"
                continue
            next_sequence = (
                responses[records[index + 1].request_id].sequence
                if index + 1 < len(records) and records[index + 1].request_id in responses
                else 2**63
            )
            result_events = [
                event
                for event in events
                if event.event_type == "tool_result"
                and response_event.sequence < event.sequence < next_sequence
            ]
            if len(result_events) != 1:
                raise ReplayError("repository action tool-result linkage is ambiguous")
            try:
                result = ToolResult.model_validate(result_events[0].payload)
            except Exception as exc:
                raise ReplayError("repository action tool-result evidence is invalid") from exc
            if record.tool_result_hash != content_hash(bounded_tool_result_identity(result)):
                raise ReplayError("repository action tool-result hash cannot be reproduced")
            if result.success and envelope.action == "apply_patch":
                patch_applied = True
                state = "candidate_modified"
            elif envelope.action == "run_public_test":
                public_observed = True
                state = "public_test_observed"
            elif envelope.action == "inspect_diff":
                diff_observed = True
                state = "diff_observed"
            if record.state_after != state:
                raise ReplayError("repository action state transition cannot be reproduced")
        else:
            if record.error_subcategory != failure:
                raise ReplayError("repository action rejection reason cannot be reproduced")
            rejected = rejected_events.get(record.request_id)
            if rejected is None or rejected.payload.get("category") != failure:
                raise ReplayError("repository action rejection-event linkage is inconsistent")
        if record.termination_reason is not None:
            terminal_reason = events[-1].payload.get("termination_reason")
            if record.termination_reason != terminal_reason:
                raise ReplayError("repository action terminal reason cannot be reproduced")


def _normalized_synthesis(metrics: SynthesisMetrics | None) -> dict[str, object] | None:
    if metrics is None:
        return None
    return {
        "status": metrics.status,
        "synthesis_ok": metrics.synthesis_ok,
        "top": metrics.top,
        "num_wires": metrics.num_wires,
        "num_wire_bits": metrics.num_wire_bits,
        "num_memories": metrics.num_memories,
        "num_memory_bits": metrics.num_memory_bits,
        "num_processes": metrics.num_processes,
        "num_cells": metrics.num_cells,
        "cells_by_type": metrics.cells_by_type,
        "mapped_area_raw": metrics.mapped_area_raw,
        "mapped_area_unit": metrics.mapped_area_unit,
        "mapped_area_source_hash": metrics.mapped_area_source_hash,
        "critical_path_delay_raw": metrics.critical_path_delay_raw,
        "worst_negative_slack_raw": metrics.worst_negative_slack_raw,
        "timing_unit": metrics.timing_unit,
        "clock_period": metrics.clock_period,
        "timing_constraints_hash": metrics.timing_constraints_hash,
        "total_power_raw": metrics.total_power_raw,
        "power_unit": metrics.power_unit,
        "power_activity_mode": metrics.power_activity_mode,
        "resolved_profile_hash": metrics.resolved_profile_hash,
        "generated_script_hash": metrics.generated_script_hash,
        "failure_category": metrics.failure_category,
    }


def _validate_stored_synthesis_artifacts(
    run_dir: Path,
    manifest: RunManifest,
    scorecard: ScoreCard,
) -> None:
    candidate = scorecard.quality.synthesis
    if candidate is None:
        raise ReplayError("profile-enabled scorecard has no candidate synthesis record")
    backend_root = _resolve_synthesis_backend_artifact_root(run_dir, manifest, candidate)
    artifact_root = backend_root / "candidate" if backend_root is not None else None
    for artifact in candidate.artifacts:
        if artifact.visibility != "public":
            raise ReplayError("candidate synthesis artifact has an invalid visibility")
        relative = normalize_relative_path(artifact.path)
        if artifact_root is None:
            raise ReplayError(f"stored candidate synthesis artifact is missing: {relative}")
        path = artifact_root / relative
        if not path.is_file():
            raise ReplayError(f"stored candidate synthesis artifact is missing: {relative}")
        payload = path.read_bytes()
        if len(payload) != artifact.size_bytes or hash_bytes(payload) != artifact.content_hash:
            raise ReplayError(f"stored candidate synthesis artifact changed: {relative}")
    flow = next(
        (artifact for artifact in candidate.artifacts if artifact.role == "generated_script"),
        None,
    )
    if candidate.synthesis_ok:
        if flow is None or flow.content_hash != candidate.generated_script_hash:
            raise ReplayError("stored candidate synthesis script identity is inconsistent")
        if manifest.synthesis_flow_script_hash != candidate.generated_script_hash:
            raise ReplayError("manifest and candidate synthesis script hashes differ")
    if scorecard.quality.reference_synthesis is not None:
        if scorecard.quality.reference_synthesis.artifacts:
            raise ReplayError("hidden reference synthesis artifacts were exported")
    summary_path = backend_root / "reference_summary.json" if backend_root is not None else None
    if manifest.reference_summary_hash is None:
        if summary_path is not None and summary_path.exists():
            raise ReplayError("reference summary exists without a manifest hash")
        return
    if summary_path is None or not summary_path.is_file():
        raise ReplayError("manifest reference summary is missing")
    summary_bytes = summary_path.read_bytes()
    if hash_bytes(summary_bytes) != manifest.reference_summary_hash:
        raise ReplayError("reference summary changed after the original run")
    try:
        summary = json.loads(summary_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplayError("reference summary is not valid JSON") from exc
    if not isinstance(summary, dict):
        raise ReplayError("reference summary is not a JSON object")
    # Milestone 8 summaries predate the additive explicit version field.
    if (
        summary.get("schema_version") not in {None, "1.0"}
        or summary.get("resolved_profile_hash") != manifest.resolved_profile_hash
        or summary.get("reference_candidate_hash") != manifest.reference_candidate_hash
        or summary.get("reference_rtl_exported") is not False
        or summary.get("reference_netlist_exported") is not False
    ):
        raise ReplayError("reference summary identity or visibility contract is invalid")


def _resolve_synthesis_backend_artifact_root(
    run_dir: Path,
    manifest: RunManifest,
    candidate: SynthesisMetrics,
) -> Path | None:
    """Resolve a tool-neutral backend namespace from sealed artifact structure."""

    artifacts_root = run_dir / "artifacts"
    backend_roots: list[Path] = []
    for entry in sorted(artifacts_root.iterdir()):
        candidate_root = entry / "candidate"
        if entry.is_symlink() or not entry.is_dir():
            continue
        if candidate_root.is_symlink() or not candidate_root.is_dir():
            continue
        backend_roots.append(entry)

    if candidate.artifacts:
        relatives = [normalize_relative_path(artifact.path) for artifact in candidate.artifacts]
        complete = [
            root
            for root in backend_roots
            if all((root / "candidate" / relative).is_file() for relative in relatives)
        ]
        if len(complete) == 1:
            return complete[0]
        if len(complete) > 1:
            raise ReplayError("stored synthesis backend artifact root is ambiguous")
        if len(backend_roots) == 1:
            return backend_roots[0]
        first = relatives[0]
        raise ReplayError(f"stored candidate synthesis artifact is missing: {first}")

    if manifest.reference_summary_hash is not None:
        summaries = [root for root in backend_roots if (root / "reference_summary.json").is_file()]
        if len(summaries) == 1:
            return summaries[0]
        if len(summaries) > 1:
            raise ReplayError("stored synthesis backend artifact root is ambiguous")
        raise ReplayError("manifest reference summary is missing")
    return None


def _validate_replayed_quality(
    scorecard: ScoreCard,
    candidate: SynthesisMetrics,
    reference: SynthesisMetrics,
) -> None:
    if _normalized_synthesis(scorecard.quality.synthesis) != _normalized_synthesis(candidate):
        raise ReplayError("replayed candidate synthesis metrics differ from the stored scorecard")
    if _normalized_synthesis(scorecard.quality.reference_synthesis) != _normalized_synthesis(
        reference
    ):
        raise ReplayError("replayed reference synthesis metrics differ from the stored scorecard")
    ppa = scorecard.quality.ppa
    if ppa is None:
        raise ReplayError("profile-enabled scorecard has no PPA eligibility record")
    if ppa.eligible:
        if candidate.mapped_area_raw is None or reference.mapped_area_raw is None:
            raise ReplayError("eligible stored PPA could not be reproduced")
        ratio = reference.mapped_area_raw / candidate.mapped_area_raw
        if (
            ppa.area != candidate.mapped_area_raw
            or ppa.reference_area != reference.mapped_area_raw
            or ppa.area_ratio != ratio
        ):
            raise ReplayError("replayed correctness-gated area projection differs")
    elif any(value is not None for value in (ppa.area, ppa.reference_area, ppa.area_ratio)):
        raise ReplayError("stored ineligible PPA unexpectedly contains ranked values")
