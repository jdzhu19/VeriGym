#!/usr/bin/env python3
"""Qualify and run a frozen three-task RTLLM L2 Codex diagnostic."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import run_rtllm_l1_multiturn_codex_12 as base
from verigym_codex_cli import CodexCliFunctionalV3HighAgentEvalAdapter
from verigym_codex_cli.functional_v3_agenteval_config import (
    FUNCTIONAL_V3_HIGH_IDENTITY,
    FUNCTIONAL_V3_PROMPT_HASH,
    FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
)
from verigym_rtllm.adapter import L2_BATCH1_VARIANT
from verigym_rtllm.manifest import L2_BATCH1_TASK_NAMES, TASK_MANIFESTS

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import hash_bytes
from verigym.core.workspace import copy_tree_safely
from verigym.registry.base import PluginOrigin
from verigym.schemas.verifier import VerifierStatus

_CAMPAIGN_ID = "rtllm-l2-batch1-codex-gpt54-xhigh-3task-diagnostic-v1"
_OUTPUT = Path(f"/data/jzhu484/Agent/experiments/{_CAMPAIGN_ID}")
_OPT_IN = "VERIGYM_RUN_RTLLM_L2_BATCH1_3"
_PROCESS_COUNT = 3
_SOURCE_KEY = "rtllm_l2_batch1"
_PUBLIC_FEEDBACK_LEVEL = "L2_candidate_only_functional_smoke"
_MODEL_ID = FUNCTIONAL_V3_HIGH_IDENTITY.model_id
_REASONING_EFFORT = FUNCTIONAL_V3_HIGH_IDENTITY.reasoning_effort
_AGENT_NAME = FUNCTIONAL_V3_HIGH_IDENTITY.agent_name
_PROMPT_CONTRACT_ID = "repository_action_v2_prompt_v8"

_base_dynamic: Any = base
_BASE_BUILD_PLAN = base._build_plan
_BASE_VALIDATE_EXISTING_PLAN = base._validate_existing_plan
_BASE_REGISTRIES = _base_dynamic.smoke._registries


def _run_specs() -> tuple[base.RunSpec, ...]:
    return tuple(
        base.RunSpec(
            ordinal=ordinal,
            run_id=f"{ordinal:02d}-{name.lower().replace('_', '-')}",
            task_name=name,
            task_id=f"rtllm/{L2_BATCH1_VARIANT}/{name}",
        )
        for ordinal, name in enumerate(L2_BATCH1_TASK_NAMES, start=1)
    )


_RUN_SPECS = _run_specs()
_RUN_IDS = tuple(spec.run_id for spec in _RUN_SPECS)


def _launcher_hash() -> str:
    return hash_bytes(Path(__file__).resolve(strict=True).read_bytes())


def _registries() -> Any:
    registries = _BASE_REGISTRIES()
    if _AGENT_NAME not in registries.agents.names():
        registries.agents.register(
            CodexCliFunctionalV3HighAgentEvalAdapter(),
            origin=PluginOrigin(
                package="verigym-codex-cli",
                version="0.1.0",
                entry_point=None,
                registration="runtime",
            ),
        )
    return registries


def _candidate_tree(root: Path, assets: Any, files: dict[str, str]) -> Path:
    copy_tree_safely(Path(assets.visible_root), root)
    for relative, content in sorted(files.items()):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    return root


def _no_model_qualification(
    service: Any,
    *,
    source_config: Any,
    docker_config: Any,
    scratch: Path,
) -> tuple[Any, dict[str, Any]]:
    scratch.mkdir()
    suite = service.registries.suites.get("rtllm").with_source(source_config)
    report = suite.validate_source()
    if not report.valid:
        raise ConfigurationError("RTLLM L2 batch-one source qualification failed")
    refs = {ref.native_id: ref for ref in suite.discover()}
    if tuple(refs) != L2_BATCH1_TASK_NAMES:
        raise ConfigurationError("RTLLM L2 batch-one task set is unavailable")

    runtime = service.registries.runtimes.get("docker").configure(docker_config)
    runtime.prepare("rtllm-l2-batch1-codex-3-preflight")
    records: list[dict[str, Any]] = []
    try:
        image = runtime.descriptor.image
        if image is None or image.iverilog_version is None or "12." not in image.iverilog_version:
            raise ConfigurationError("RTLLM L2 batch one requires the frozen Icarus 12 image")
        for spec in _RUN_SPECS:
            suite_item, task, assets = service.load_task(spec.task_id, source_config)
            if (
                task.metadata.get("gym_qualification_level") != "L2_functional_smoke"
                or task.metadata.get("diagnostic_only") is not True
                or task.metadata.get("benchmark_score_claimed") is not False
                or task.metadata.get("verification_requires_final_submission") is not True
                or task.metadata.get("agent_eval", {}).get("ppa_supported") is not False
                or task.scoring.ppa_enabled
                or len(assets.read_only_mounts) != 1
            ):
                raise ConfigurationError(f"RTLLM L2 contract drifted for {task.id}")
            manifest = TASK_MANIFESTS[spec.task_name]
            visible = Path(assets.visible_root)
            visible_files = {
                path.relative_to(visible).as_posix()
                for path in visible.rglob("*")
                if path.is_file()
            }
            if any(
                path.startswith("verifier/") or path in manifest.auxiliary_files
                for path in visible_files
            ):
                raise ConfigurationError("RTLLM L2 workspace exposes a verifier-only asset")
            cases = list(suite_item.public_conformance_cases(task))
            if (
                len(cases) != 5
                or cases[0].expected_resolved is not True
                or any(case.expected_resolved for case in cases[1:])
            ):
                raise ConfigurationError("RTLLM L2 qualification cases drifted")
            for case in cases:
                if not _base_dynamic.functional._execute_public_candidate(
                    runtime,
                    task,
                    assets,
                    case.candidate.files,
                    expect_pass=case.expected_resolved,
                ):
                    raise ConfigurationError(
                        f"RTLLM L2 public qualification failed for {task.id}/{case.name}"
                    )
                candidate = _candidate_tree(
                    scratch / spec.task_name / case.name,
                    assets,
                    case.candidate.files,
                )
                hidden = service._verify_candidate(
                    suite=suite_item,
                    task=task,
                    assets=assets,
                    runtime=runtime,
                    candidate_dir=candidate,
                    artifact_root=scratch / "artifacts" / spec.task_name / case.name,
                )
                resolved = bool(hidden) and all(
                    result.status == VerifierStatus.PASSED for result in hidden
                )
                if resolved is not case.expected_resolved:
                    raise ConfigurationError(
                        f"RTLLM L2 hidden qualification failed for {task.id}/{case.name}"
                    )
            records.append(
                {
                    "task_id": task.id,
                    "public_reference_passed": True,
                    "public_known_bad_rejected_count": 4,
                    "hidden_reference_passed": True,
                    "hidden_known_bad_rejected_count": 4,
                    "gym_qualification_level": "L2_functional_smoke",
                    "ppa_supported": False,
                }
            )
        return runtime.descriptor, {
            "passed": True,
            "model_calls": 0,
            "task_count": len(records),
            "known_bad_categories_per_task": 4,
            "records": records,
        }
    finally:
        runtime.close()


def _build_plan(**kwargs: Any) -> dict[str, Any]:
    plan = _BASE_BUILD_PLAN(**kwargs)
    plan["public_feedback_level"] = _PUBLIC_FEEDBACK_LEVEL
    plan["qualification_profile"] = "reference_plus_four_known_bad_public_and_hidden_v1"
    return plan


def _validate_existing_plan(plan: Any) -> None:
    qualification = plan.get("qualification") if isinstance(plan, dict) else None
    records = qualification.get("records") if isinstance(qualification, dict) else None
    if (
        not isinstance(plan, dict)
        or plan.get("public_feedback_level") != _PUBLIC_FEEDBACK_LEVEL
        or plan.get("qualification_profile") != "reference_plus_four_known_bad_public_and_hidden_v1"
        or not isinstance(qualification, dict)
        or qualification.get("known_bad_categories_per_task") != 4
        or not isinstance(records, list)
        or len(records) != _PROCESS_COUNT
        or any(
            not isinstance(record, dict)
            or record.get("public_reference_passed") is not True
            or record.get("public_known_bad_rejected_count") != 4
            or record.get("hidden_reference_passed") is not True
            or record.get("hidden_known_bad_rejected_count") != 4
            or record.get("gym_qualification_level") != "L2_functional_smoke"
            or record.get("ppa_supported") is not False
            for record in records
        )
    ):
        raise ConfigurationError("existing RTLLM L2 plan differs from the frozen campaign")

    compatible = deepcopy(plan)
    compatible["public_feedback_level"] = "L1_candidate_only_compile"
    compatible.pop("qualification_profile", None)
    compatible_qualification = compatible["qualification"]
    compatible_qualification.pop("known_bad_categories_per_task", None)
    compatible_qualification["records"] = [
        {
            "task_id": record["task_id"],
            "public_reference_passed": True,
            "public_missing_module_rejected": True,
            "hidden_reference_passed": True,
            "hidden_missing_module_rejected": True,
            "ppa_supported": False,
        }
        for record in records
    ]
    _BASE_VALIDATE_EXISTING_PLAN(compatible)


def _install_profile() -> None:
    _base_dynamic._CAMPAIGN_ID = _CAMPAIGN_ID
    _base_dynamic._OUTPUT = _OUTPUT
    _base_dynamic._OPT_IN = _OPT_IN
    _base_dynamic._PROCESS_COUNT = _PROCESS_COUNT
    _base_dynamic._SOURCE_KEY = _SOURCE_KEY
    _base_dynamic._TASK_NAMES = L2_BATCH1_TASK_NAMES
    _base_dynamic._RUN_SPECS = _RUN_SPECS
    _base_dynamic._RUN_IDS = _RUN_IDS
    _base_dynamic.ALL_AGENT_EVAL_VARIANT = L2_BATCH1_VARIANT
    _base_dynamic._MODEL_ID = _MODEL_ID
    _base_dynamic._REASONING_EFFORT = _REASONING_EFFORT
    _base_dynamic._AGENT_NAME = _AGENT_NAME
    _base_dynamic._PROMPT_CONTRACT_ID = _PROMPT_CONTRACT_ID
    _base_dynamic.AGENTEVAL_AGENT_VERSION_ID = FUNCTIONAL_V3_HIGH_IDENTITY.agent_version_id
    _base_dynamic.AGENTEVAL_AGENT_VERSION_HASH = FUNCTIONAL_V3_HIGH_IDENTITY.agent_version_hash
    _base_dynamic.AGENTEVAL_PROMPT_HASH = FUNCTIONAL_V3_PROMPT_HASH
    _base_dynamic.AGENTEVAL_TOOL_POLICY_FINGERPRINT = FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT
    _base_dynamic._launcher_hash = _launcher_hash
    _base_dynamic._no_model_qualification = _no_model_qualification
    _base_dynamic._build_plan = _build_plan
    _base_dynamic._validate_existing_plan = _validate_existing_plan
    _base_dynamic.smoke._registries = _registries


_install_profile()

_execute_exactly_three = base._execute_exactly_twelve
_campaign_summary = base._campaign_summary
_hidden_execution_valid = base._hidden_execution_valid
_provider_usage_valid = base._provider_usage_valid


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
