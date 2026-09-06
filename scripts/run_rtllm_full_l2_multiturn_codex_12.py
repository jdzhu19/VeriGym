#!/usr/bin/env python3
"""Qualify and run the frozen twelve-task RTLLM full-L2 Codex contrast."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

from verigym_codex_cli import CodexCliFunctionalV3HighAgentEvalAdapter
from verigym_codex_cli.functional_v3_agenteval_config import (
    FUNCTIONAL_V3_HIGH_IDENTITY,
    FUNCTIONAL_V3_PROMPT_HASH,
    FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
)
from verigym_rtllm.adapter import (
    FULL_FUNCTIONAL_TASK_IDENTITIES_SHA256,
    FULL_FUNCTIONAL_VARIANT,
)
from verigym_rtllm.manifest import TASK_MANIFESTS

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.registry.base import PluginOrigin
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.tool import CommandSpec


def _load_private_base() -> ModuleType:
    """Load the reusable fail-closed engine without mutating another launcher profile."""
    name = "_verigym_rtllm_full_l2_12_base"
    path = Path(__file__).with_name("run_rtllm_l1_multiturn_codex_12.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("RTLLM L1 launcher engine is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load_private_base()

_CAMPAIGN_ID = "rtllm-full-l2-codex-gpt54-xhigh-12task-contrast-v1"
_BASELINE_CAMPAIGN_ID = "rtllm-full-l1-codex-gpt54-xhigh-12task-pilot-v1"
_OUTPUT = Path(f"/data/jzhu484/Agent/experiments/{_CAMPAIGN_ID}")
_OPT_IN = "VERIGYM_RUN_RTLLM_FULL_L2_12"
_PROCESS_COUNT = 12
_SOURCE_KEY = "rtllm_l2_full"
_PUBLIC_FEEDBACK_LEVEL = "L2_candidate_only_functional_smoke"
_QUALIFICATION_PROFILE = "reference_plus_four_known_bad_public_and_hidden_v1"
_MODEL_ID = FUNCTIONAL_V3_HIGH_IDENTITY.model_id
_REASONING_EFFORT = FUNCTIONAL_V3_HIGH_IDENTITY.reasoning_effort
_AGENT_NAME = FUNCTIONAL_V3_HIGH_IDENTITY.agent_name
_PROMPT_CONTRACT_ID = "repository_action_v2_prompt_v8"

# Freeze the exact task order from the completed L1 pilot before installing this profile into
# its fail-closed launcher implementation.
_TASK_NAMES = tuple(base._TASK_NAMES)

_base_dynamic: Any = base
_BASE_BUILD_PLAN = base._build_plan
_BASE_VALIDATE_EXISTING_PLAN = base._validate_existing_plan
_BASE_REGISTRIES = _base_dynamic.smoke._registries

_BATCH_RUNNER = r"""from __future__ import annotations

import json
import subprocess
from pathlib import Path


root = Path("/workspace")
records = json.loads((root / "qualification.json").read_text(encoding="utf-8"))
issues = []
counts = {"public": 0, "hidden": 0}
for record in records:
    case_root = root / record["relative_root"]
    for kind in ("public", "hidden"):
        counts[kind] += 1
        source = "public-smoke.sv" if kind == "public" else "hidden-testbench.v"
        top = "public_smoke" if kind == "public" else record["hidden_top"]
        executable = root / ".verigym_internal" / f"{record['case']}-{kind}.vvp"
        try:
            compiled = subprocess.run(
                [
                    "iverilog",
                    "-g2012",
                    "-s",
                    top,
                    "-o",
                    str(executable),
                    record["candidate"],
                    source,
                ],
                cwd=case_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            issues.append({"case": record["case"], "kind": kind, "status": "compile-timeout"})
            continue
        if compiled.returncode != 0:
            issues.append({"case": record["case"], "kind": kind, "status": "compile-failed"})
            continue
        try:
            executed = subprocess.run(
                ["vvp", str(executable)],
                cwd=case_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            issues.append({"case": record["case"], "kind": kind, "status": "run-timeout"})
            continue
        output = executed.stdout + executed.stderr
        pass_marker = record["public_pass"] if kind == "public" else record["hidden_pass"]
        fail_marker = "VERIGYM_PUBLIC_FAIL" if kind == "public" else record["hidden_fail"]
        passed = (
            executed.returncode == 0
            and pass_marker in output
            and (not fail_marker or fail_marker not in output)
        )
        if passed != record["expected"]:
            issues.append(
                {
                    "case": record["case"],
                    "kind": kind,
                    "status": "unexpected-pass" if passed else "unexpected-rejection",
                }
            )
if issues:
    print(json.dumps({"counts": counts, "issues": issues}, sort_keys=True))
    raise SystemExit(1)
print(
    "RTLLM_DOCKER_SELECTED_L2_PASS "
    f"public={counts['public']} hidden={counts['hidden']} cases={len(records)}"
)
"""


def _run_specs() -> tuple[base.RunSpec, ...]:
    return tuple(
        base.RunSpec(
            ordinal=ordinal,
            run_id=f"{ordinal:02d}-{name.lower().replace('_', '-')}",
            task_name=name,
            task_id=f"rtllm/{FULL_FUNCTIONAL_VARIANT}/{name}",
        )
        for ordinal, name in enumerate(_TASK_NAMES, start=1)
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
        raise ConfigurationError("RTLLM full-L2 contrast source qualification failed")
    refs = {ref.native_id: ref for ref in suite.discover()}
    if not set(_TASK_NAMES).issubset(refs):
        raise ConfigurationError("RTLLM full-L2 contrast task set is unavailable")
    if (
        content_hash({name: content_hash(suite.load_task(refs[name])) for name in refs})
        != FULL_FUNCTIONAL_TASK_IDENTITIES_SHA256
    ):
        raise ConfigurationError("RTLLM full-L2 task identities differ from the frozen aggregate")

    batch_records: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
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
            raise ConfigurationError(f"RTLLM full-L2 contract drifted for {task.id}")
        manifest = TASK_MANIFESTS[spec.task_name]
        visible = Path(assets.visible_root)
        visible_files = {
            path.relative_to(visible).as_posix(): path.read_text(encoding="utf-8")
            for path in visible.rglob("*")
            if path.is_file()
        }
        hidden_contents = {asset.content for asset in assets.hidden_assets}
        if hidden_contents.intersection(visible_files.values()) or any(
            "verifier" in Path(path).parts for path in visible_files
        ):
            raise ConfigurationError("RTLLM full-L2 workspace exposes a verifier-only asset")
        hidden_by_mount = {asset.mount_path: asset.content for asset in assets.hidden_assets}
        hidden_testbench = hidden_by_mount.get("verifier/testbench.v")
        if hidden_testbench is None:
            raise ConfigurationError("RTLLM full-L2 hidden testbench is unavailable")
        cases = list(suite_item.public_conformance_cases(task))
        if (
            len(cases) != 5
            or cases[0].expected_resolved is not True
            or any(case.expected_resolved for case in cases[1:])
        ):
            raise ConfigurationError("RTLLM full-L2 qualification cases drifted")
        expected_candidate_path = f"repository/rtl/{spec.task_name}.v"
        for index, case in enumerate(cases):
            if set(case.candidate.files) != {expected_candidate_path}:
                raise ConfigurationError("RTLLM full-L2 qualification candidate path drifted")
            relative_root = Path(spec.task_name) / f"case-{index + 1}"
            case_root = scratch / relative_root
            case_root.mkdir(parents=True)
            candidate_path = f"{spec.task_name}.v"
            (case_root / candidate_path).write_text(
                case.candidate.files[expected_candidate_path], encoding="utf-8"
            )
            (case_root / "public-smoke.sv").write_text(
                suite_item._public_smoke(spec.task_name), encoding="utf-8"
            )
            (case_root / "hidden-testbench.v").write_text(hidden_testbench, encoding="utf-8")
            for auxiliary in manifest.auxiliary_files:
                content = hidden_by_mount.get(auxiliary)
                if content is None:
                    raise ConfigurationError(
                        "RTLLM full-L2 auxiliary verifier asset is unavailable"
                    )
                destination = case_root / auxiliary
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
            batch_records.append(
                {
                    "case": f"{spec.task_name}-{index + 1}",
                    "relative_root": relative_root.as_posix(),
                    "candidate": candidate_path,
                    "hidden_top": manifest.testbench_top,
                    "hidden_pass": manifest.pass_marker,
                    "hidden_fail": manifest.fail_marker,
                    "public_pass": "VERIGYM_PUBLIC_PASS",
                    "expected": case.expected_resolved,
                }
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

    if len(batch_records) != _PROCESS_COUNT * 5:
        raise ConfigurationError("RTLLM full-L2 batched qualification count drifted")
    (scratch / "qualification.json").write_text(
        json.dumps(batch_records, sort_keys=True), encoding="utf-8"
    )
    (scratch / "qualification.py").write_text(_BATCH_RUNNER, encoding="utf-8")

    runtime = service.registries.runtimes.get("docker").configure(docker_config)
    runtime.prepare("rtllm-full-l2-codex-12-batched-preflight")
    session = None
    try:
        image = runtime.descriptor.image
        if image is None or image.iverilog_version is None or "12." not in image.iverilog_version:
            raise ConfigurationError("RTLLM full-L2 contrast requires the frozen Icarus 12 image")
        session = runtime.create_session(
            SessionSpec(source_dir=str(scratch), label="verifier", max_output_bytes=1_000_000)
        )
        completed = session.execute(
            CommandSpec(argv=["python3", "qualification.py"], timeout_s=900)
        )
        marker = (
            f"RTLLM_DOCKER_SELECTED_L2_PASS public={len(batch_records)} "
            f"hidden={len(batch_records)} cases={len(batch_records)}"
        )
        if completed.exit_code != 0 or marker not in completed.stdout:
            raise ConfigurationError("RTLLM full-L2 batched functional qualification failed")
        return runtime.descriptor, {
            "passed": True,
            "model_calls": 0,
            "task_count": len(records),
            "known_bad_categories_per_task": 4,
            "public_paths_checked": len(batch_records),
            "hidden_paths_checked": len(batch_records),
            "records": records,
        }
    finally:
        try:
            if session is not None:
                session.close()
        finally:
            try:
                runtime.close()
            finally:
                shutil.rmtree(scratch)


def _build_plan(**kwargs: Any) -> dict[str, Any]:
    plan = _BASE_BUILD_PLAN(**kwargs)
    plan["public_feedback_level"] = _PUBLIC_FEEDBACK_LEVEL
    plan["qualification_profile"] = _QUALIFICATION_PROFILE
    plan["comparison_baseline"] = {
        "campaign_id": _BASELINE_CAMPAIGN_ID,
        "controlled_dimensions": [
            "task_names_and_order",
            "model_id",
            "reasoning_effort",
            "seed",
            "samples_per_task",
            "serial_execution",
            "automatic_retries",
            "ppa_enabled",
        ],
        "intended_difference": "L1_compile_only_to_L2_candidate_only_functional_smoke",
        "agent_contract_note": (
            "functional_v3_identity_required_for_L2_feedback_and_repair_evidence"
        ),
    }
    return plan


def _validate_existing_plan(plan: Any) -> None:
    qualification = plan.get("qualification") if isinstance(plan, dict) else None
    records = qualification.get("records") if isinstance(qualification, dict) else None
    expected_comparison = {
        "campaign_id": _BASELINE_CAMPAIGN_ID,
        "controlled_dimensions": [
            "task_names_and_order",
            "model_id",
            "reasoning_effort",
            "seed",
            "samples_per_task",
            "serial_execution",
            "automatic_retries",
            "ppa_enabled",
        ],
        "intended_difference": "L1_compile_only_to_L2_candidate_only_functional_smoke",
        "agent_contract_note": (
            "functional_v3_identity_required_for_L2_feedback_and_repair_evidence"
        ),
    }
    if (
        not isinstance(plan, dict)
        or plan.get("public_feedback_level") != _PUBLIC_FEEDBACK_LEVEL
        or plan.get("qualification_profile") != _QUALIFICATION_PROFILE
        or plan.get("comparison_baseline") != expected_comparison
        or not isinstance(qualification, dict)
        or qualification.get("known_bad_categories_per_task") != 4
        or qualification.get("public_paths_checked") != _PROCESS_COUNT * 5
        or qualification.get("hidden_paths_checked") != _PROCESS_COUNT * 5
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
        raise ConfigurationError("existing RTLLM full-L2 plan differs from the frozen campaign")

    compatible = deepcopy(plan)
    compatible["public_feedback_level"] = "L1_candidate_only_compile"
    compatible.pop("qualification_profile", None)
    compatible.pop("comparison_baseline", None)
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
    _base_dynamic._TASK_NAMES = _TASK_NAMES
    _base_dynamic._RUN_SPECS = _RUN_SPECS
    _base_dynamic._RUN_IDS = _RUN_IDS
    _base_dynamic.ALL_AGENT_EVAL_VARIANT = FULL_FUNCTIONAL_VARIANT
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

_execute_exactly_twelve = base._execute_exactly_twelve
_campaign_summary = base._campaign_summary
_hidden_execution_valid = base._hidden_execution_valid
_provider_usage_valid = base._provider_usage_valid


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
