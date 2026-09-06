#!/usr/bin/env python3
"""Qualify and run the frozen remaining 38 RTLLM full-L2 Codex diagnostics."""

from __future__ import annotations

import argparse
import importlib.util
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
from verigym_rtllm.manifest import ALL_TASK_NAMES, TASK_MANIFESTS

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.experiments.private_staging import PrivateQualificationStaging
from verigym.registry.base import PluginOrigin
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.tool import CommandSpec


def _load_private_contrast() -> ModuleType:
    """Load the frozen 12-task profile without mutating its launcher module."""

    name = "_verigym_rtllm_full_l2_remaining38_contrast"
    path = Path(__file__).with_name("run_rtllm_full_l2_multiturn_codex_12.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("RTLLM full-L2 contrast launcher is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contrast = _load_private_contrast()
base = contrast.base

_CAMPAIGN_ID = "rtllm-full-l2-codex-gpt54-xhigh-remaining38-diagnostic-v1"
_COMPLETED_CAMPAIGN_ID = "rtllm-full-l2-codex-gpt54-xhigh-12task-contrast-v1"
_OUTPUT = Path(f"/data/jzhu484/Agent/experiments/{_CAMPAIGN_ID}")
_OPT_IN = "VERIGYM_RUN_RTLLM_FULL_L2_REMAINING38"
_PROCESS_COUNT = 38
_SOURCE_KEY = "rtllm_l2_full_remaining38"
_PUBLIC_FEEDBACK_LEVEL = "L2_candidate_only_functional_smoke"
_QUALIFICATION_PROFILE = "reference_plus_four_known_bad_private_staging_v2"
_MODEL_ID = FUNCTIONAL_V3_HIGH_IDENTITY.model_id
_REASONING_EFFORT = FUNCTIONAL_V3_HIGH_IDENTITY.reasoning_effort
_AGENT_NAME = FUNCTIONAL_V3_HIGH_IDENTITY.agent_name
_PROMPT_CONTRACT_ID = "repository_action_v2_prompt_v8"
_COMPLETED_TASK_NAMES = (
    "adder_32bit",
    "fixed_point_substractor",
    "div_16bit",
    "multi_booth_8bit",
    "adder_pipe_64bit",
    "JC_counter",
    "sequence_detector",
    "LFSR",
    "synchronizer",
    "RAM",
    "freq_divbyodd",
    "serial2parallel",
)
_TASK_NAMES = (
    "accu",
    "adder_16bit",
    "adder_8bit",
    "adder_bcd",
    "comparator_3bit",
    "comparator_4bit",
    "radix2_div",
    "multi_16bit",
    "multi_8bit",
    "multi_pipe_4bit",
    "multi_pipe_8bit",
    "fixed_point_adder",
    "float_multi",
    "sub_64bit",
    "counter_12",
    "ring_counter",
    "up_down_counter",
    "fsm",
    "asyn_fifo",
    "LIFObuffer",
    "barrel_shifter",
    "right_shifter",
    "freq_div",
    "freq_divbyeven",
    "freq_divbyfrac",
    "calendar",
    "edge_detect",
    "parallel2serial",
    "pulse_detect",
    "traffic_light",
    "width_8to16",
    "ROM",
    "alu",
    "clkgenerator",
    "instr_reg",
    "pe",
    "signal_generator",
    "square_wave",
)
_COMPLETED_TASK_NAMES_SHA256 = "d80119ec8135fa4b1cc23967df5d2c49ec9031c8c75c31d064ccf14af349ee5e"
_TASK_NAMES_SHA256 = "02aa62181ea52eaf4766dc315a1a854474b945d423b820389350bf2cfa727eb0"
_TASK_IDENTITIES_SHA256 = "0457f7f4328c041be0001ed1550f2864d993fa07d6f853c5821aea15868e3894"

_BASE_BUILD_PLAN = contrast._BASE_BUILD_PLAN
_BASE_VALIDATE_EXISTING_PLAN = contrast._BASE_VALIDATE_EXISTING_PLAN
_BASE_REGISTRIES = contrast._BASE_REGISTRIES
_BATCH_RUNNER = contrast._BATCH_RUNNER


def _validate_partition() -> None:
    if (
        len(_TASK_NAMES) != _PROCESS_COUNT
        or set(_TASK_NAMES).intersection(_COMPLETED_TASK_NAMES)
        or set(_TASK_NAMES).union(_COMPLETED_TASK_NAMES) != set(ALL_TASK_NAMES)
        or content_hash(_TASK_NAMES) != _TASK_NAMES_SHA256
        or content_hash(_COMPLETED_TASK_NAMES) != _COMPLETED_TASK_NAMES_SHA256
    ):
        raise ConfigurationError("RTLLM full-L2 12+38 task partition drifted")


_validate_partition()


def _run_specs() -> tuple[Any, ...]:
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--output", type=Path, default=_OUTPUT)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument(
        "--broker-root",
        type=Path,
        default=Path("/data/jzhu484/Agent/.verigym-tmp/r38b"),
    )
    parser.add_argument("--rtllm-source", type=Path, required=True)
    parser.add_argument("--image", default=base.smoke._IMAGE)
    parser.add_argument("--codex-binary", default="codex")
    return parser


def _launcher_hash() -> str:
    return hash_bytes(Path(__file__).resolve(strict=True).read_bytes())


def _launcher_dependency_hashes() -> dict[str, str]:
    paths = {
        "l1_engine": Path(base.__file__).resolve(strict=True),
        "full_l2_contrast": Path(contrast.__file__).resolve(strict=True),
        "private_staging": Path(__file__).resolve().parents[1]
        / "src/verigym/experiments/private_staging.py",
    }
    return {
        name: hash_bytes(path.resolve(strict=True).read_bytes()) for name, path in paths.items()
    }


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
    suite = service.registries.suites.get("rtllm").with_source(source_config)
    report = suite.validate_source()
    if not report.valid:
        raise ConfigurationError("RTLLM remaining-38 source qualification failed")
    refs = {ref.native_id: ref for ref in suite.discover()}
    if set(refs) != set(ALL_TASK_NAMES) or not set(_TASK_NAMES).issubset(refs):
        raise ConfigurationError("RTLLM remaining-38 task set is unavailable")
    all_identities = {name: content_hash(suite.load_task(refs[name])) for name in refs}
    if content_hash(all_identities) != FULL_FUNCTIONAL_TASK_IDENTITIES_SHA256:
        raise ConfigurationError("RTLLM full-L2 task identities differ from the frozen aggregate")
    selected_identities = {name: all_identities[name] for name in _TASK_NAMES}
    if content_hash(selected_identities) != _TASK_IDENTITIES_SHA256:
        raise ConfigurationError("RTLLM remaining-38 task identities drifted")

    records: list[dict[str, Any]] = []
    batch_records: list[dict[str, Any]] = []
    staging = PrivateQualificationStaging(scratch)
    with staging:
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
                raise ConfigurationError(f"RTLLM remaining-38 contract drifted for {task.id}")
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
                raise ConfigurationError("RTLLM remaining-38 workspace exposes a hidden asset")
            hidden = {asset.mount_path: asset.content for asset in assets.hidden_assets}
            hidden_testbench = hidden.get("verifier/testbench.v")
            if hidden_testbench is None:
                raise ConfigurationError("RTLLM remaining-38 hidden testbench is unavailable")
            cases = list(suite_item.public_conformance_cases(task))
            if (
                len(cases) != 5
                or cases[0].expected_resolved is not True
                or any(case.expected_resolved for case in cases[1:])
            ):
                raise ConfigurationError("RTLLM remaining-38 qualification cases drifted")
            expected_candidate = f"repository/rtl/{spec.task_name}.v"
            for index, case in enumerate(cases, start=1):
                if set(case.candidate.files) != {expected_candidate}:
                    raise ConfigurationError(
                        "RTLLM remaining-38 qualification candidate path drifted"
                    )
                relative_root = Path(spec.task_name) / f"case-{index}"
                candidate_name = f"{spec.task_name}.v"
                staging.write_text(
                    relative_root / candidate_name,
                    case.candidate.files[expected_candidate],
                )
                staging.write_text(
                    relative_root / "public-smoke.sv",
                    suite_item._public_smoke(spec.task_name),
                )
                staging.write_text(relative_root / "hidden-testbench.v", hidden_testbench)
                for auxiliary in manifest.auxiliary_files:
                    content = hidden.get(auxiliary)
                    if content is None:
                        raise ConfigurationError(
                            "RTLLM remaining-38 auxiliary hidden asset is unavailable"
                        )
                    staging.write_text(relative_root / auxiliary, content)
                batch_records.append(
                    {
                        "case": f"{spec.task_name}-{index}",
                        "relative_root": relative_root.as_posix(),
                        "candidate": candidate_name,
                        "hidden_top": manifest.testbench_top,
                        "hidden_pass": manifest.pass_marker,
                        "hidden_fail": manifest.fail_marker,
                        "public_pass": (
                            "PUBLIC_SMOKE_PASS"
                            if spec.task_name in {"counter_12", "up_down_counter"}
                            else "VERIGYM_PUBLIC_PASS"
                        ),
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
            raise ConfigurationError("RTLLM remaining-38 batched qualification count drifted")
        staging.write_json("qualification.json", batch_records)
        staging.write_text("qualification.py", _BATCH_RUNNER)

        runtime = service.registries.runtimes.get("docker").configure(docker_config)
        session = None
        try:
            runtime.prepare("rtllm-full-l2-remaining38-batched-preflight")
            image = runtime.descriptor.image
            if (
                image is None
                or image.iverilog_version is None
                or "12." not in image.iverilog_version
            ):
                raise ConfigurationError("RTLLM remaining-38 requires the frozen Icarus 12 image")
            session = runtime.create_session(
                SessionSpec(
                    source_dir=str(staging.root),
                    label="verifier",
                    max_output_bytes=4_000_000,
                )
            )
            completed = session.execute(
                CommandSpec(argv=["python3", "qualification.py"], timeout_s=900)
            )
            marker = (
                f"RTLLM_DOCKER_SELECTED_L2_PASS public={len(batch_records)} "
                f"hidden={len(batch_records)} cases={len(batch_records)}"
            )
            if completed.exit_code != 0 or marker not in completed.stdout:
                raise ConfigurationError("RTLLM remaining-38 functional qualification failed")
        finally:
            if session is not None:
                session.close()
            runtime.close()
        runtime_descriptor = runtime.descriptor
        if runtime_descriptor.cleanup is None or not runtime_descriptor.cleanup.complete:
            raise ConfigurationError(
                "RTLLM remaining-38 Docker qualification cleanup is incomplete"
            )
        cleanup_receipt = staging.cleanup()

    return runtime_descriptor, {
        "passed": True,
        "model_calls": 0,
        "task_count": len(records),
        "known_bad_categories_per_task": 4,
        "public_paths_checked": len(batch_records),
        "hidden_paths_checked": len(batch_records),
        "task_names_sha256": _TASK_NAMES_SHA256,
        "task_identities_sha256": _TASK_IDENTITIES_SHA256,
        "runtime_cleanup": runtime_descriptor.cleanup.model_dump(mode="json"),
        "staging_cleanup": cleanup_receipt,
        "records": records,
    }


def _build_plan(**kwargs: Any) -> dict[str, Any]:
    plan = _BASE_BUILD_PLAN(**kwargs)
    plan["public_feedback_level"] = _PUBLIC_FEEDBACK_LEVEL
    plan["qualification_profile"] = _QUALIFICATION_PROFILE
    plan["launcher_dependency_sha256"] = _launcher_dependency_hashes()
    plan["coverage_partition"] = {
        "completed_campaign_id": _COMPLETED_CAMPAIGN_ID,
        "completed_task_count": len(_COMPLETED_TASK_NAMES),
        "completed_task_names_sha256": _COMPLETED_TASK_NAMES_SHA256,
        "selected_task_count": len(_TASK_NAMES),
        "selected_task_names_sha256": _TASK_NAMES_SHA256,
        "selected_task_identities_sha256": _TASK_IDENTITIES_SHA256,
        "disjoint": True,
        "union_task_count": len(ALL_TASK_NAMES),
    }
    return plan


def _validate_existing_plan(plan: Any) -> None:
    qualification = plan.get("qualification") if isinstance(plan, dict) else None
    records = qualification.get("records") if isinstance(qualification, dict) else None
    staging = qualification.get("staging_cleanup") if isinstance(qualification, dict) else None
    runtime_cleanup = (
        qualification.get("runtime_cleanup") if isinstance(qualification, dict) else None
    )
    expected_partition = {
        "completed_campaign_id": _COMPLETED_CAMPAIGN_ID,
        "completed_task_count": len(_COMPLETED_TASK_NAMES),
        "completed_task_names_sha256": _COMPLETED_TASK_NAMES_SHA256,
        "selected_task_count": len(_TASK_NAMES),
        "selected_task_names_sha256": _TASK_NAMES_SHA256,
        "selected_task_identities_sha256": _TASK_IDENTITIES_SHA256,
        "disjoint": True,
        "union_task_count": len(ALL_TASK_NAMES),
    }
    if (
        not isinstance(plan, dict)
        or plan.get("public_feedback_level") != _PUBLIC_FEEDBACK_LEVEL
        or plan.get("qualification_profile") != _QUALIFICATION_PROFILE
        or plan.get("launcher_dependency_sha256") != _launcher_dependency_hashes()
        or plan.get("coverage_partition") != expected_partition
        or not isinstance(qualification, dict)
        or qualification.get("known_bad_categories_per_task") != 4
        or qualification.get("public_paths_checked") != _PROCESS_COUNT * 5
        or qualification.get("hidden_paths_checked") != _PROCESS_COUNT * 5
        or qualification.get("task_names_sha256") != _TASK_NAMES_SHA256
        or qualification.get("task_identities_sha256") != _TASK_IDENTITIES_SHA256
        or not isinstance(runtime_cleanup, dict)
        or runtime_cleanup.get("complete") is not True
        or not isinstance(staging, dict)
        or staging.get("format_id") != "verigym_private_qualification_staging_receipt_v1"
        or staging.get("private_directory_mode") != "0700"
        or staging.get("private_file_mode") != "0600"
        or staging.get("stale_state_rejected") is not True
        or staging.get("cleanup_complete") is not True
        or staging.get("residual_paths") != 0
        or not isinstance(records, list)
        or len(records) != _PROCESS_COUNT
        or [record.get("task_id") for record in records] != [spec.task_id for spec in _RUN_SPECS]
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
        raise ConfigurationError(
            "existing RTLLM remaining-38 plan differs from the frozen campaign"
        )

    compatible = deepcopy(plan)
    compatible["public_feedback_level"] = "L1_candidate_only_compile"
    compatible.pop("qualification_profile", None)
    compatible.pop("launcher_dependency_sha256", None)
    compatible.pop("coverage_partition", None)
    compatible["qualification"] = {
        "passed": qualification.get("passed"),
        "model_calls": qualification.get("model_calls"),
        "task_count": qualification.get("task_count"),
        "records": [
            {
                "task_id": record["task_id"],
                "public_reference_passed": True,
                "public_missing_module_rejected": True,
                "hidden_reference_passed": True,
                "hidden_missing_module_rejected": True,
                "ppa_supported": False,
            }
            for record in records
        ],
    }
    _BASE_VALIDATE_EXISTING_PLAN(compatible)


def _install_profile() -> None:
    dynamic: Any = base
    dynamic._CAMPAIGN_ID = _CAMPAIGN_ID
    dynamic._OUTPUT = _OUTPUT
    dynamic._OPT_IN = _OPT_IN
    dynamic._PROCESS_COUNT = _PROCESS_COUNT
    dynamic._SOURCE_KEY = _SOURCE_KEY
    dynamic._TASK_NAMES = _TASK_NAMES
    dynamic._RUN_SPECS = _RUN_SPECS
    dynamic._RUN_IDS = _RUN_IDS
    dynamic.ALL_AGENT_EVAL_VARIANT = FULL_FUNCTIONAL_VARIANT
    dynamic._MODEL_ID = _MODEL_ID
    dynamic._REASONING_EFFORT = _REASONING_EFFORT
    dynamic._AGENT_NAME = _AGENT_NAME
    dynamic._PROMPT_CONTRACT_ID = _PROMPT_CONTRACT_ID
    dynamic.AGENTEVAL_AGENT_VERSION_ID = FUNCTIONAL_V3_HIGH_IDENTITY.agent_version_id
    dynamic.AGENTEVAL_AGENT_VERSION_HASH = FUNCTIONAL_V3_HIGH_IDENTITY.agent_version_hash
    dynamic.AGENTEVAL_PROMPT_HASH = FUNCTIONAL_V3_PROMPT_HASH
    dynamic.AGENTEVAL_TOOL_POLICY_FINGERPRINT = FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT
    dynamic._parser = _parser
    dynamic._launcher_hash = _launcher_hash
    dynamic._no_model_qualification = _no_model_qualification
    dynamic._build_plan = _build_plan
    dynamic._validate_existing_plan = _validate_existing_plan
    dynamic.smoke._registries = _registries


_install_profile()

_execute_exactly_twelve = base._execute_exactly_twelve
_campaign_summary = base._campaign_summary
_hidden_execution_valid = base._hidden_execution_valid
_provider_usage_valid = base._provider_usage_valid


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
