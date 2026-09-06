from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from verigym.schemas.run import RunConfig


@lru_cache(maxsize=1)
def _launcher() -> ModuleType:
    path = (
        Path(__file__).parents[2] / "scripts" / "run_rtllm_full_l2_remaining38_multiturn_codex.py"
    )
    spec = importlib.util.spec_from_file_location("rtllm_full_l2_remaining38_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def _qualification(launcher: ModuleType) -> dict[str, object]:
    return {
        "passed": True,
        "model_calls": 0,
        "task_count": 38,
        "known_bad_categories_per_task": 4,
        "public_paths_checked": 190,
        "hidden_paths_checked": 190,
        "task_names_sha256": launcher._TASK_NAMES_SHA256,
        "task_identities_sha256": launcher._TASK_IDENTITIES_SHA256,
        "runtime_cleanup": {"complete": True},
        "staging_cleanup": {
            "format_id": "verigym_private_qualification_staging_receipt_v1",
            "private_directory_mode": "0700",
            "private_file_mode": "0600",
            "directories_created": 230,
            "files_created": 600,
            "stale_state_rejected": True,
            "cleanup_attempted": True,
            "cleanup_complete": True,
            "residual_paths": 0,
        },
        "records": [
            {
                "task_id": spec.task_id,
                "public_reference_passed": True,
                "public_known_bad_rejected_count": 4,
                "hidden_reference_passed": True,
                "hidden_known_bad_rejected_count": 4,
                "gym_qualification_level": "L2_functional_smoke",
                "ppa_supported": False,
            }
            for spec in launcher._RUN_SPECS
        ],
    }


def _plan(launcher: ModuleType) -> dict[str, object]:
    capability = SimpleNamespace(
        version_output=launcher.base.smoke._EXPECTED_CLI_VERSION,
        executable_sha256=launcher.base.smoke._EXPECTED_CODEX_SHA256,
        capability_fingerprint="a" * 64,
    )
    auth = SimpleNamespace(safe_dict=lambda: {})
    runtime = SimpleNamespace(
        model_dump=lambda mode: {
            "image": {"resolved_image_id": launcher.base._EXPECTED_RUNTIME_IMAGE_ID},
            "cleanup": {"complete": True},
        }
    )
    configs = [
        RunConfig(task_id=spec.task_id, output=Path("runs"), run_id=spec.run_id)
        for spec in launcher._RUN_SPECS
    ]
    plan = launcher._build_plan(
        capability=capability,
        auth=auth,
        runtime_descriptor=runtime,
        qualification=_qualification(launcher),
        configs=configs,
    )
    return cast(dict[str, object], plan)


def test_matrix_is_exact_disjoint_38_task_remainder() -> None:
    launcher = _launcher()

    assert launcher._PROCESS_COUNT == len(launcher._RUN_SPECS) == 38
    assert tuple(spec.task_name for spec in launcher._RUN_SPECS) == launcher._TASK_NAMES
    assert not set(launcher._TASK_NAMES).intersection(launcher._COMPLETED_TASK_NAMES)
    assert set(launcher._TASK_NAMES).union(launcher._COMPLETED_TASK_NAMES) == set(
        launcher.ALL_TASK_NAMES
    )
    assert len({spec.run_id for spec in launcher._RUN_SPECS}) == 38
    assert all(
        spec.task_id == f"rtllm/{launcher.FULL_FUNCTIONAL_VARIANT}/{spec.task_name}"
        for spec in launcher._RUN_SPECS
    )
    assert launcher._MODEL_ID == "gpt-5.4"
    assert launcher._REASONING_EFFORT == "xhigh"
    assert launcher._OPT_IN == "VERIGYM_RUN_RTLLM_FULL_L2_REMAINING38"


def test_profile_is_installed_with_hardened_private_qualification() -> None:
    launcher = _launcher()

    assert launcher.base._PROCESS_COUNT == 38
    assert launcher.base._RUN_SPECS == launcher._RUN_SPECS
    assert launcher.base.ALL_AGENT_EVAL_VARIANT == launcher.FULL_FUNCTIONAL_VARIANT
    assert launcher.base._parser is launcher._parser
    assert launcher.base._no_model_qualification is launcher._no_model_qualification
    assert launcher.base._validate_existing_plan is launcher._validate_existing_plan


def test_plan_freezes_partition_dependencies_cleanup_no_ppa_and_zero_retry() -> None:
    launcher = _launcher()
    plan = _plan(launcher)

    assert plan["planned_codex_processes"] == 38
    assert plan["public_feedback_level"] == "L2_candidate_only_functional_smoke"
    assert plan["qualification_profile"] == ("reference_plus_four_known_bad_private_staging_v2")
    assert plan["coverage_partition"]["completed_task_count"] == 12  # type: ignore[index]
    assert plan["coverage_partition"]["selected_task_count"] == 38  # type: ignore[index]
    assert plan["coverage_partition"]["union_task_count"] == 50  # type: ignore[index]
    assert set(plan["launcher_dependency_sha256"]) == {  # type: ignore[arg-type]
        "l1_engine",
        "full_l2_contrast",
        "private_staging",
    }
    assert plan["ppa_enabled"] is False
    assert plan["automatic_retries"] == 0
    assert plan["automatic_retries_authorized"] is False
    launcher._validate_existing_plan(plan)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("coverage_partition", "selected_task_count"), 37),
        (("launcher_dependency_sha256", "private_staging"), "0" * 64),
        (("qualification", "task_identities_sha256"), "0" * 64),
        (("qualification", "runtime_cleanup", "complete"), False),
        (("qualification", "staging_cleanup", "private_directory_mode"), "0755"),
        (("qualification", "staging_cleanup", "cleanup_complete"), False),
        (("qualification", "staging_cleanup", "residual_paths"), 1),
        (("qualification", "public_paths_checked"), 189),
        (("qualification", "records", 0, "hidden_known_bad_rejected_count"), 3),
        (("ppa_enabled",), True),
        (("automatic_retries",), 1),
    ],
)
def test_existing_plan_rejects_partition_identity_cleanup_or_policy_drift(
    path: tuple[str | int, ...], value: object
) -> None:
    launcher = _launcher()
    changed = deepcopy(_plan(launcher))
    target: object = changed
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(Exception, match="remaining-38|frozen identities|frozen campaign"):
        launcher._validate_existing_plan(changed)


def test_launcher_source_uses_private_staging_and_no_retry_ppa_contract() -> None:
    source = (
        Path(__file__).parents[2] / "scripts" / "run_rtllm_full_l2_remaining38_multiturn_codex.py"
    ).read_text(encoding="utf-8")

    assert "PrivateQualificationStaging" in source
    assert '"runtime_cleanup"' in source
    assert '"staging_cleanup"' in source
    assert '"ppa_supported": False' in source
    assert '"model_calls": 0' in source
    assert "_TASK_IDENTITIES_SHA256" in source
