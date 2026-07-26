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
    if any(row.get("integration_track") for row in rows):
        return CODEX_CLI_CSV_COLUMNS
    return CSV_COLUMNS


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
        "warning_count": len(score.warnings),
        "artifact_validation_status": "valid",
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
        codex = {
            "integration_track": "codex_cli_external_agent",
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
        }
    return {}


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
    "CODEX_CLI_CSV_COLUMNS",
    "CSV_COLUMNS",
    "build_run_rows",
    "render_csv",
]
