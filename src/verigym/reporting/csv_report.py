"""Deterministic, spreadsheet-safe run-level CSV rendering."""

from __future__ import annotations

import csv
import io
from typing import Any

from verigym.core.sampling import classify_sample_outcome
from verigym.reporting.loader import LoadedReportInputs, ValidatedRun

CSV_COLUMNS = [
    "experiment_id",
    "plan_index",
    "plan_item_id",
    "attempt",
    "run_id",
    "relative_run_path",
    "suite",
    "suite_version",
    "release_id",
    "task_id",
    "task_hash",
    "category",
    "difficulty",
    "interaction_mode",
    "system_id",
    "model_id",
    "agent_id",
    "base_seed",
    "sample_index",
    "child_seed",
    "runtime_id",
    "isolation_level",
    "image_id",
    "declared_profile_id",
    "declared_profile_hash",
    "resolved_profile_hash",
    "status",
    "resolved",
    "evaluable",
    "infrastructure_error",
    "failure_category",
    "termination_reason",
    "compile_status",
    "tests_passed",
    "tests_total",
    "ppa_eligible",
    "area",
    "area_unit",
    "reference_area",
    "area_ratio",
    "delay",
    "timing_unit",
    "clock_period",
    "reference_delay",
    "delay_ratio",
    "worst_negative_slack",
    "reference_worst_negative_slack",
    "worst_negative_slack_delta",
    "power",
    "power_unit",
    "reference_power",
    "power_ratio",
    "wall_time_s",
    "model_input_tokens",
    "model_output_tokens",
    "total_tokens",
    "model_cost",
    "cost_currency",
    "turns",
    "tool_calls",
    "failed_tool_calls",
    "changed_files",
    "diff_lines",
    "edit_similarity",
    "warning_count",
    "artifact_validation_status",
]

CODEX_CLI_CSV_COLUMNS = [
    *CSV_COLUMNS,
    "integration_track",
    "cli_version",
    "cli_executable_sha256",
    "capability_fingerprint",
    "requested_model_id",
    "observed_model_id",
    "identity_confidence",
    "requested_reasoning_effort",
    "effective_reasoning_effort",
    "reasoning_effort_source",
    "inherited_reasoning_effort_allowed",
    "auth_mode_label",
    "requested_auth_mode",
    "resolved_auth_mode",
    "auth_semantic_id",
    "auth_alias_used",
    "sandbox_policy",
    "approval_policy",
    "execution_surface",
    "interaction_class",
    "harness_id",
    "model_client_kind",
    "agent_harness_kind",
    "tool_availability_policy",
    "tool_use_policy",
    "tool_event_count",
    "side_effecting_tool_event_count",
    "read_only_tool_event_count",
    "external_network_tool_event_count",
    "mcp_tool_event_count",
    "workspace_write_count",
    "chat_eval_compatible",
    "pure_api_model_eval",
    "direct_api_benchmark",
    "external_model_call_count",
    "external_tool_call_count",
    "external_command_count",
    "external_file_read_count",
    "external_file_write_count",
    "external_patch_count",
    "cli_process_wall_time_s",
    "external_input_tokens",
    "external_output_tokens",
    "external_total_tokens",
    "external_cost",
    "external_cost_currency",
]

REPOSITORY_CSV_COLUMNS = [
    "repository_manifest_hash",
    "repository_task_bundle_hash",
    "repository_source_identity_hash",
    "repository_license_file_hash",
    "base_repository_hash",
    "repository_public_assets_hash",
    "repository_hidden_verifier_hash",
    "candidate_repository_hash",
    "repository_patch_hash",
    "patch_reapply_exact",
    "repository_changed_file_count",
    "repository_created_file_count",
    "repository_deleted_file_count",
    "repository_added_lines",
    "repository_deleted_lines",
    "public_test_ids",
    "public_test_passed_ids",
    "public_test_failed_ids",
    "public_tests_passed",
    "public_tests_total",
    "public_test_failure_count",
    "public_tool_invocation_count",
    "hidden_verifier_reached",
    "workspace_policy_status",
    "policy_failure_category",
]

API_AGENT_CSV_COLUMNS = [
    *CSV_COLUMNS,
    "provider_id",
    "api_protocol",
    "api_endpoint_origin",
    "api_normalized_base_url",
    "api_base_url_hash",
    "api_request_parameters_hash",
    "api_prompt_payload_hash",
    "api_prompt_policy_hash",
    "api_agent_configuration_hash",
    "safe_provider_request_id",
    "safe_provider_request_ids",
    "observed_provider_model_id",
    "system_fingerprint",
    "model_latency_s",
    "model_latency_total_s",
    "model_latency_mean_s",
    "usage_missing",
    "usage_missing_count",
    "api_request_count",
    "authentication_mode",
    "credential_env_name",
    "credential_persisted",
    "credential_hashed",
    "agent_execution_backend",
    "action_protocol_id",
    "action_protocol_version",
    "action_transport",
    "action_protocol_fingerprint",
    "action_registry_hash",
    "action_prompt_contract_hash",
    "protocol_turn_count",
    "protocol_accepted_turn_count",
    "protocol_canonical_acceptance_count",
    "protocol_normalized_acceptance_count",
    "protocol_rejection_reasons",
    "protocol_accepted_actions",
    "protocol_error_subcategory",
]


def build_run_rows(inputs: LoadedReportInputs) -> list[dict[str, Any]]:
    valid = {(run.plan_index, run.attempt): run for run in inputs.valid_runs}
    rows: list[dict[str, Any]] = []
    if inputs.source_kind == "experiment":
        records = sorted(inputs.index_records, key=lambda item: (item.plan_index, item.attempt))
        record_keys = {(record.plan_index, record.attempt) for record in records}
        for record in records:
            run = valid.get((record.plan_index, record.attempt))
            if run is not None:
                rows.append(_valid_row(inputs.experiment_id, run))
            else:
                plan = next(
                    (item for item in inputs.plan_items if item.plan_index == record.plan_index),
                    None,
                )
                plan_fields = (
                    _plan_fields(inputs.experiment_id, plan)
                    if plan is not None
                    else {
                        "experiment_id": inputs.experiment_id,
                        "plan_index": record.plan_index,
                        "plan_item_id": record.plan_item_id,
                    }
                )
                rows.append(
                    {
                        **plan_fields,
                        "attempt": record.attempt,
                        "run_id": record.child_run_id,
                        "relative_run_path": record.relative_child_path,
                        "status": record.terminal_status,
                        "resolved": record.resolved,
                        "evaluable": record.evaluable,
                        "infrastructure_error": record.infrastructure_error,
                        "failure_category": record.child_exit_category,
                        "artifact_validation_status": record.artifact_validation_status,
                    }
                )
        started_indices = {record.plan_index for record in records}
        for plan in inputs.plan_items:
            if plan.plan_index not in started_indices:
                rows.append(
                    {
                        **_plan_fields(inputs.experiment_id, plan),
                        "attempt": 0,
                        "status": "missing",
                        "artifact_validation_status": "missing",
                    }
                )
        for run in inputs.valid_runs:
            if (run.plan_index, run.attempt) not in record_keys:
                rows.append(_valid_row(inputs.experiment_id, run))
    else:
        rows.extend(_valid_row(inputs.experiment_id, run) for run in inputs.valid_runs)
    ordered = sorted(rows, key=lambda row: (int(row["plan_index"]), int(row["attempt"])))
    columns = _columns_for_rows(ordered)
    return [{column: row.get(column) for column in columns} for row in ordered]


def render_csv(rows: list[dict[str, Any]]) -> str:
    columns = _columns_for_rows(rows)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _csv_value(row.get(column)) for column in columns})
    return stream.getvalue()


def _columns_for_rows(rows: list[dict[str, Any]]) -> list[str]:
    repository = any(row.get("repository_manifest_hash") for row in rows)
    if any(row.get("integration_track") for row in rows):
        return [*CODEX_CLI_CSV_COLUMNS, *(REPOSITORY_CSV_COLUMNS if repository else [])]
    if any(row.get("api_protocol") for row in rows):
        return [*API_AGENT_CSV_COLUMNS, *(REPOSITORY_CSV_COLUMNS if repository else [])]
    return [*CSV_COLUMNS, *(REPOSITORY_CSV_COLUMNS if repository else [])]


def _valid_row(experiment_id: str, run: ValidatedRun) -> dict[str, Any]:
    manifest = run.manifest
    score = run.scorecard
    plan = run.plan_item
    ppa = score.quality.ppa
    infrastructure = bool(
        score.status == "error"
        or score.correctness.infrastructure_error
        or (score.failure is not None and score.failure.infrastructure)
    )
    evaluable = not infrastructure and score.status != "cancelled"
    failure = (
        score.failure.category
        if score.failure is not None
        else next(
            (
                result.error_category.value
                for result in score.verifier_results
                if result.status.value in {"failed", "error"}
            ),
            "resolved" if score.resolved else classify_sample_outcome(score)[0].value,
        )
    )
    codex = _codex_dimensions(manifest)
    api = _api_dimensions(manifest)
    action_protocol = _action_protocol_dimensions(manifest, score)
    repository = manifest.repository_candidate
    repository_identity = manifest.repository_task_identity
    public_tests = manifest.repository_public_tests
    cli_accounting = run.codex_cli_accounting
    return {
        "experiment_id": experiment_id,
        "plan_index": run.plan_index,
        "plan_item_id": manifest.plan_item_id or (plan.plan_item_id if plan else None),
        "attempt": run.attempt,
        "run_id": manifest.run_id,
        "relative_run_path": run.relative_path,
        "suite": manifest.suite,
        "suite_version": manifest.suite_version,
        "release_id": manifest.release_id,
        "task_id": manifest.task_id,
        "task_hash": manifest.task_hash,
        "category": plan.category if plan else None,
        "difficulty": plan.difficulty if plan else None,
        "interaction_mode": manifest.interaction_mode,
        "system_id": manifest.system_id or (plan.system.system_id if plan else None),
        **codex,
        **api,
        **action_protocol,
        "model_id": manifest.model.model_id if manifest.model else None,
        "agent_id": manifest.agent.name,
        "base_seed": manifest.base_seed if manifest.base_seed is not None else manifest.seed,
        "sample_index": manifest.sample_index,
        "child_seed": manifest.seed,
        "runtime_id": manifest.runtime.name,
        "isolation_level": manifest.runtime.isolation_level,
        "image_id": manifest.runtime.image.resolved_image_id if manifest.runtime.image else None,
        "declared_profile_id": manifest.requested_toolchain_profile_id,
        "declared_profile_hash": manifest.declared_profile_hash,
        "resolved_profile_hash": manifest.resolved_profile_hash,
        "status": score.status,
        "resolved": score.resolved,
        "evaluable": evaluable,
        "infrastructure_error": infrastructure,
        "failure_category": failure,
        "termination_reason": score.termination_reason,
        "compile_status": score.correctness.compile_status,
        "tests_passed": score.correctness.tests_passed,
        "tests_total": score.correctness.tests_total,
        "ppa_eligible": ppa.eligible if ppa else None,
        "area": ppa.area if ppa else None,
        "area_unit": ppa.area_unit if ppa else None,
        "reference_area": ppa.reference_area if ppa else None,
        "area_ratio": ppa.area_ratio if ppa else None,
        "delay": ppa.delay if ppa else None,
        "timing_unit": ppa.timing_unit if ppa else None,
        "clock_period": ppa.clock_period if ppa else None,
        "reference_delay": ppa.reference_delay if ppa else None,
        "delay_ratio": ppa.delay_ratio if ppa else None,
        "worst_negative_slack": ppa.worst_negative_slack if ppa else None,
        "reference_worst_negative_slack": (ppa.reference_worst_negative_slack if ppa else None),
        "worst_negative_slack_delta": ppa.worst_negative_slack_delta if ppa else None,
        "power": ppa.power if ppa else None,
        "power_unit": ppa.power_unit if ppa else None,
        "reference_power": ppa.reference_power if ppa else None,
        "power_ratio": ppa.power_ratio if ppa else None,
        "wall_time_s": score.efficiency.wall_time_s,
        "model_input_tokens": score.efficiency.model_input_tokens,
        "model_output_tokens": score.efficiency.model_output_tokens,
        "total_tokens": score.efficiency.total_tokens,
        "model_cost": score.efficiency.model_api_cost,
        "cost_currency": (
            score.efficiency.model_api_cost_currency
            or (
                f"unit:{score.efficiency.model_api_cost_unit}"
                if score.efficiency.model_api_cost_unit is not None
                else None
            )
        ),
        "turns": score.efficiency.turns,
        "tool_calls": score.efficiency.tool_calls,
        "failed_tool_calls": score.efficiency.failed_tool_calls,
        "external_model_call_count": (
            cli_accounting.model_call_count
            if cli_accounting is not None
            else score.efficiency.external_model_call_count
        ),
        "external_tool_call_count": (
            cli_accounting.external_tool_call_count
            if cli_accounting is not None
            else score.efficiency.external_tool_call_count
        ),
        "external_command_count": (
            cli_accounting.external_command_count
            if cli_accounting is not None
            else score.efficiency.external_command_count
        ),
        "external_file_read_count": (
            cli_accounting.external_file_read_count
            if cli_accounting is not None
            else score.efficiency.external_file_read_count
        ),
        "external_file_write_count": (
            cli_accounting.external_file_write_count
            if cli_accounting is not None
            else score.efficiency.external_file_write_count
        ),
        "external_patch_count": (
            cli_accounting.external_patch_count
            if cli_accounting is not None
            else score.efficiency.external_patch_count
        ),
        "cli_process_wall_time_s": (
            cli_accounting.process_wall_time_s if cli_accounting is not None else None
        ),
        "external_input_tokens": score.efficiency.external_input_tokens,
        "external_output_tokens": score.efficiency.external_output_tokens,
        "external_total_tokens": score.efficiency.external_total_tokens,
        "external_cost": score.efficiency.external_cost,
        "external_cost_currency": score.efficiency.external_cost_currency,
        "changed_files": len(score.patch.changed_files),
        "diff_lines": score.patch.total_diff_lines,
        "edit_similarity": score.patch.edit_similarity,
        "warning_count": len(score.warnings),
        "artifact_validation_status": "valid",
        "repository_manifest_hash": (
            repository_identity.manifest_hash if repository_identity is not None else None
        ),
        "repository_task_bundle_hash": (
            repository_identity.task_bundle_hash if repository_identity is not None else None
        ),
        "repository_source_identity_hash": (
            repository_identity.source_identity_hash if repository_identity is not None else None
        ),
        "repository_license_file_hash": (
            repository_identity.license_file_hash if repository_identity is not None else None
        ),
        "base_repository_hash": (
            repository.patch.base_repository_hash if repository is not None else None
        ),
        "repository_public_assets_hash": (
            repository_identity.public_assets_hash if repository_identity is not None else None
        ),
        "repository_hidden_verifier_hash": (
            repository_identity.hidden_verifier_hash if repository_identity is not None else None
        ),
        "candidate_repository_hash": (
            repository.patch.candidate_repository_hash if repository is not None else None
        ),
        "repository_patch_hash": repository.patch.patch_hash if repository is not None else None,
        "patch_reapply_exact": repository.patch.reapply_exact if repository is not None else None,
        "repository_changed_file_count": (
            len(repository.patch.changed_files) if repository is not None else None
        ),
        "repository_created_file_count": (
            repository.patch.created_file_count if repository is not None else None
        ),
        "repository_deleted_file_count": (
            repository.patch.deleted_file_count if repository is not None else None
        ),
        "repository_added_lines": (
            repository.patch.added_lines if repository is not None else None
        ),
        "repository_deleted_lines": (
            repository.patch.deleted_lines if repository is not None else None
        ),
        "public_test_ids": ";".join(sorted(result.test_id for result in public_tests)),
        "public_test_passed_ids": ";".join(
            sorted(result.test_id for result in public_tests if result.passed)
        ),
        "public_test_failed_ids": ";".join(
            sorted(result.test_id for result in public_tests if not result.passed)
        ),
        "public_tests_passed": sum(result.passed for result in public_tests),
        "public_tests_total": len(public_tests),
        "public_test_failure_count": sum(not result.passed for result in public_tests),
        "public_tool_invocation_count": manifest.repository_public_tool_invocation_count,
        "hidden_verifier_reached": any(
            result.status.value != "skipped" for result in score.verifier_results
        ),
        "workspace_policy_status": (
            "failed_contained"
            if score.failure is not None and score.failure.kind == "policy"
            else "passed"
        ),
        "policy_failure_category": (
            score.failure.category
            if score.failure is not None and score.failure.kind == "policy"
            else None
        ),
    }


def _plan_fields(experiment_id: str, plan: Any) -> dict[str, Any]:
    codex: dict[str, Any] = {}
    if plan.system.model_descriptor is not None:
        configuration = plan.system.model_descriptor.configuration
        if configuration.get("integration_track") == "codex_cli_model_proxy":
            codex = {
                "integration_track": "codex_cli_model_proxy",
                "cli_version": configuration.get("cli_version"),
                "cli_executable_sha256": configuration.get("cli_executable_sha256"),
                "capability_fingerprint": configuration.get("capability_fingerprint"),
                "requested_model_id": plan.system.model_descriptor.model_id,
                "requested_reasoning_effort": configuration.get("requested_reasoning_effort"),
                "effective_reasoning_effort": configuration.get("effective_reasoning_effort"),
                "reasoning_effort_source": configuration.get("reasoning_effort_source"),
                "inherited_reasoning_effort_allowed": configuration.get(
                    "inherited_reasoning_effort_allowed"
                ),
                "auth_mode_label": configuration.get("auth_mode_label"),
                "requested_auth_mode": (
                    configuration.get("requested_auth_mode") or configuration.get("auth_mode_label")
                ),
                "resolved_auth_mode": configuration.get("resolved_auth_mode"),
                "auth_semantic_id": configuration.get("auth_semantic_id"),
                "auth_alias_used": configuration.get("auth_alias_used"),
                "sandbox_policy": configuration.get("sandbox_policy"),
                "approval_policy": configuration.get("approval_policy"),
            }
    elif "external_coding_agent" in plan.system.agent_descriptor.capabilities:
        readonly = plan.system.agent_id == "codex-cli-readonly-agent"
        codex = {
            "integration_track": (
                "codex_cli_readonly_single_turn_agent" if readonly else "codex_cli_external_agent"
            ),
            "requested_model_id": plan.system.agent_options.get("model_id"),
            "requested_reasoning_effort": plan.system.agent_options.get("reasoning_effort"),
            "effective_reasoning_effort": plan.system.agent_options.get("reasoning_effort"),
            "reasoning_effort_source": (
                "verigym_explicit_cli_override"
                if plan.system.agent_options.get("reasoning_effort")
                else None
            ),
            "inherited_reasoning_effort_allowed": (
                False if plan.system.agent_options.get("reasoning_effort") else None
            ),
            "sandbox_policy": plan.system.agent_options.get("sandbox"),
            "approval_policy": plan.system.agent_options.get("approval_policy"),
            "execution_surface": "codex_cli",
            "interaction_class": (
                "cli_agent_single_turn_readonly" if readonly else "cli_agent_workspace_writing"
            ),
            "model_client_kind": "cli_agent_mediated",
            "agent_harness_kind": "codex_cli",
            "tool_availability_policy": (
                "codex_cli_builtin_tools_readonly_sandboxed"
                if readonly
                else "codex_cli_visible_workspace_tools"
            ),
            "tool_use_policy": (
                "typed_readonly_empty_workdir_v1"
                if readonly
                else "visible_task_workspace_policy_v1"
            ),
            "chat_eval_compatible": False,
            "pure_api_model_eval": False,
            "direct_api_benchmark": False,
        }
    api: dict[str, Any] = {}
    if (
        plan.system.model_descriptor is not None
        and "api_backed_repository_agent" in plan.system.agent_descriptor.capabilities
    ):
        configuration = plan.system.model_descriptor.configuration
        api = {
            "provider_id": plan.system.model_descriptor.provider,
            "api_protocol": configuration.get("protocol"),
            "api_endpoint_origin": configuration.get("base_url"),
            "authentication_mode": configuration.get("authentication_mode"),
            "credential_env_name": configuration.get("credential_env_name"),
            "credential_persisted": configuration.get("credential_persisted"),
            "credential_hashed": configuration.get("credential_hashed"),
            "agent_execution_backend": "docker_outer_runtime_delegated",
        }
    return {
        "experiment_id": experiment_id,
        "plan_index": plan.plan_index,
        "plan_item_id": plan.plan_item_id,
        "suite": plan.suite,
        "suite_version": plan.suite_version,
        "release_id": plan.release_id,
        "task_id": plan.task_id,
        "task_hash": plan.task_hash,
        "category": plan.category,
        "difficulty": plan.difficulty,
        "interaction_mode": plan.interaction_mode.value,
        "system_id": plan.system.system_id,
        **codex,
        **api,
        "model_id": plan.system.model_descriptor.model_id if plan.system.model_descriptor else None,
        "agent_id": plan.system.agent_id,
        "base_seed": plan.base_seed,
        "sample_index": plan.sample_index,
        "child_seed": plan.child_seed,
        "runtime_id": plan.runtime_id,
        "isolation_level": plan.runtime_descriptor.isolation_level,
        "image_id": (
            plan.runtime_descriptor.image.resolved_image_id
            if plan.runtime_descriptor.image
            else None
        ),
        "declared_profile_id": plan.requested_profile_id,
        "declared_profile_hash": plan.declared_profile_hash,
        "resolved_profile_hash": plan.resolved_profile_hash,
        "repository_manifest_hash": (
            plan.repository_task_identity.manifest_hash
            if plan.repository_task_identity is not None
            else None
        ),
        "repository_task_bundle_hash": (
            plan.repository_task_identity.task_bundle_hash
            if plan.repository_task_identity is not None
            else None
        ),
        "repository_source_identity_hash": (
            plan.repository_task_identity.source_identity_hash
            if plan.repository_task_identity is not None
            else None
        ),
        "repository_license_file_hash": (
            plan.repository_task_identity.license_file_hash
            if plan.repository_task_identity is not None
            else None
        ),
        "base_repository_hash": (
            plan.repository_task_identity.base_repository_hash
            if plan.repository_task_identity is not None
            else None
        ),
        "repository_public_assets_hash": (
            plan.repository_task_identity.public_assets_hash
            if plan.repository_task_identity is not None
            else None
        ),
        "repository_hidden_verifier_hash": (
            plan.repository_task_identity.hidden_verifier_hash
            if plan.repository_task_identity is not None
            else None
        ),
    }


def _codex_dimensions(manifest: Any) -> dict[str, Any]:
    if manifest.external_agent_observations:
        identity = manifest.external_agent_observations[-1]
        return {
            "integration_track": identity.integration_track or "codex_cli_external_agent",
            "cli_version": identity.executable_version,
            "cli_executable_sha256": identity.executable_sha256,
            "capability_fingerprint": identity.capability_fingerprint,
            "requested_model_id": identity.requested_model_id,
            "observed_model_id": identity.observed_model_id,
            "identity_confidence": identity.identity_confidence,
            "requested_reasoning_effort": identity.requested_reasoning_effort,
            "effective_reasoning_effort": identity.effective_reasoning_effort,
            "reasoning_effort_source": identity.reasoning_effort_source,
            "inherited_reasoning_effort_allowed": identity.inherited_reasoning_effort_allowed,
            "auth_mode_label": identity.auth_mode_label,
            "requested_auth_mode": (identity.requested_auth_mode or identity.auth_mode_label),
            "resolved_auth_mode": identity.resolved_auth_mode,
            "auth_semantic_id": identity.auth_semantic_id,
            "auth_alias_used": identity.auth_alias_used,
            "sandbox_policy": identity.sandbox_policy,
            "approval_policy": identity.approval_policy,
            "execution_surface": identity.execution_surface,
            "interaction_class": identity.interaction_class,
            "harness_id": identity.harness_id,
            "model_client_kind": identity.model_client_kind,
            "agent_harness_kind": identity.agent_harness_kind,
            "tool_availability_policy": identity.tool_availability_policy,
            "tool_use_policy": identity.tool_use_policy,
            "tool_event_count": identity.tool_event_count,
            "side_effecting_tool_event_count": identity.side_effecting_tool_event_count,
            "read_only_tool_event_count": identity.read_only_tool_event_count,
            "external_network_tool_event_count": identity.external_network_tool_event_count,
            "mcp_tool_event_count": identity.mcp_tool_event_count,
            "workspace_write_count": identity.workspace_write_count,
            "chat_eval_compatible": identity.chat_eval_compatible,
            "pure_api_model_eval": identity.pure_api_model_eval,
            "direct_api_benchmark": identity.direct_api_benchmark,
        }
    if (
        manifest.model is not None
        and manifest.model.configuration.get("integration_track") == "codex_cli_model_proxy"
    ):
        configuration = manifest.model.configuration
        observation = manifest.model_observations[-1] if manifest.model_observations else None
        return {
            "integration_track": "codex_cli_model_proxy",
            "cli_version": configuration.get("cli_version"),
            "cli_executable_sha256": configuration.get("cli_executable_sha256"),
            "capability_fingerprint": configuration.get("capability_fingerprint"),
            "requested_model_id": manifest.model.model_id,
            "observed_model_id": (
                observation.observed_provider_model_id if observation is not None else None
            ),
            "identity_confidence": (
                observation.identity_confidence if observation is not None else "unknown"
            ),
            "requested_reasoning_effort": configuration.get("requested_reasoning_effort"),
            "effective_reasoning_effort": configuration.get("effective_reasoning_effort"),
            "reasoning_effort_source": configuration.get("reasoning_effort_source"),
            "inherited_reasoning_effort_allowed": configuration.get(
                "inherited_reasoning_effort_allowed"
            ),
            "auth_mode_label": configuration.get("auth_mode_label"),
            "requested_auth_mode": (
                configuration.get("requested_auth_mode") or configuration.get("auth_mode_label")
            ),
            "resolved_auth_mode": configuration.get("resolved_auth_mode"),
            "auth_semantic_id": configuration.get("auth_semantic_id"),
            "auth_alias_used": configuration.get("auth_alias_used"),
            "sandbox_policy": configuration.get("sandbox_policy"),
            "approval_policy": configuration.get("approval_policy"),
            "execution_surface": configuration.get("execution_surface"),
            "interaction_class": configuration.get("interaction_class"),
            "harness_id": configuration.get("harness_id"),
            "model_client_kind": configuration.get("model_client_kind"),
            "agent_harness_kind": configuration.get("agent_harness_kind"),
            "tool_availability_policy": configuration.get("tool_availability_policy"),
            "tool_use_policy": configuration.get("tool_use_policy"),
            "tool_event_count": configuration.get("tool_event_count"),
            "side_effecting_tool_event_count": configuration.get("side_effecting_tool_event_count"),
            "read_only_tool_event_count": configuration.get("read_only_tool_event_count"),
            "external_network_tool_event_count": configuration.get(
                "external_network_tool_event_count"
            ),
            "mcp_tool_event_count": configuration.get("mcp_tool_event_count"),
            "workspace_write_count": configuration.get("workspace_write_count"),
            "chat_eval_compatible": configuration.get("chat_eval_compatible"),
            "pure_api_model_eval": configuration.get("pure_api_model_eval"),
            "direct_api_benchmark": configuration.get("direct_api_benchmark"),
        }
    return {}


def _api_dimensions(manifest: Any) -> dict[str, Any]:
    if manifest.model is None or "api_backed_repository_agent" not in manifest.agent.capabilities:
        return {}
    observation = manifest.model_observations[-1] if manifest.model_observations else None
    request = observation.provider_request if observation is not None else None
    configuration = manifest.model.configuration
    observations = manifest.model_observations
    latencies = [item.latency_s for item in observations if item.latency_s is not None]
    safe_request_ids = sorted(
        item.safe_provider_request_id
        for item in observations
        if item.safe_provider_request_id is not None
    )
    return {
        "provider_id": request.provider_id if request is not None else manifest.model.provider,
        "api_protocol": request.protocol if request is not None else configuration.get("protocol"),
        "api_endpoint_origin": (
            request.endpoint_origin if request is not None else configuration.get("base_url")
        ),
        "api_normalized_base_url": (
            request.normalized_base_url if request is not None else configuration.get("base_url")
        ),
        "api_base_url_hash": request.base_url_hash if request is not None else None,
        "api_request_parameters_hash": (
            request.request_parameters_hash if request is not None else None
        ),
        "api_prompt_payload_hash": request.prompt_payload_hash if request is not None else None,
        "api_prompt_policy_hash": request.prompt_policy_hash if request is not None else None,
        "api_agent_configuration_hash": (
            request.agent_configuration_hash if request is not None else None
        ),
        "safe_provider_request_id": (
            observation.safe_provider_request_id if observation is not None else None
        ),
        "safe_provider_request_ids": ";".join(safe_request_ids),
        "observed_provider_model_id": (
            observation.observed_provider_model_id if observation is not None else None
        ),
        "system_fingerprint": observation.system_fingerprint if observation is not None else None,
        "model_latency_s": observation.latency_s if observation is not None else None,
        "model_latency_total_s": sum(latencies) if latencies else None,
        "model_latency_mean_s": sum(latencies) / len(latencies) if latencies else None,
        "usage_missing": observation.usage_missing if observation is not None else None,
        "usage_missing_count": sum(item.usage_missing is True for item in observations),
        "api_request_count": len(manifest.model_observations),
        "authentication_mode": (
            request.authentication_mode
            if request is not None
            else configuration.get("authentication_mode")
        ),
        "credential_env_name": (
            request.credential_env_name
            if request is not None
            else configuration.get("credential_env_name")
        ),
        "credential_persisted": (
            request.credential_persisted
            if request is not None
            else configuration.get("credential_persisted")
        ),
        "credential_hashed": (
            request.credential_hashed
            if request is not None
            else configuration.get("credential_hashed")
        ),
        "agent_execution_backend": manifest.environment_summary.get("agent_execution_backend"),
    }


def _action_protocol_dimensions(manifest: Any, score: Any) -> dict[str, Any]:
    descriptor = manifest.action_protocol
    if descriptor is None:
        return {}
    records = manifest.action_protocol_records
    accepted = [record for record in records if record.accepted]
    rejection_reasons = sorted(
        record.error_subcategory for record in records if record.error_subcategory is not None
    )
    action_names = [record.action_name for record in accepted if record.action_name is not None]
    return {
        "action_protocol_id": descriptor.protocol_id,
        "action_protocol_version": descriptor.protocol_version,
        "action_transport": descriptor.action_transport,
        "action_protocol_fingerprint": descriptor.configuration_fingerprint,
        "action_registry_hash": descriptor.action_registry_hash,
        "action_prompt_contract_hash": descriptor.prompt_contract_hash,
        "protocol_turn_count": len(records),
        "protocol_accepted_turn_count": len(accepted),
        "protocol_canonical_acceptance_count": sum(
            not record.permitted_normalization_used for record in accepted
        ),
        "protocol_normalized_acceptance_count": sum(
            record.permitted_normalization_used for record in accepted
        ),
        "protocol_rejection_reasons": ";".join(rejection_reasons),
        "protocol_accepted_actions": ";".join(action_names),
        "protocol_error_subcategory": (
            score.failure.protocol_error_subcategory if score.failure is not None else None
        ),
    }


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).replace("\r", "\\r").replace("\n", "\\n")
    text = "".join(
        character if ord(character) >= 32 and ord(character) != 127 else " " for character in text
    )
    if text.startswith(("=", "+", "-", "@")):
        text = "'" + text
    return text[:4096]


__all__ = [
    "API_AGENT_CSV_COLUMNS",
    "CODEX_CLI_CSV_COLUMNS",
    "CSV_COLUMNS",
    "REPOSITORY_CSV_COLUMNS",
    "build_run_rows",
    "render_csv",
]
