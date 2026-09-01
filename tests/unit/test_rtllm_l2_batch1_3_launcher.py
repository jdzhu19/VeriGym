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
    path = Path(__file__).parents[2] / "scripts" / "run_rtllm_l2_batch1_multiturn_codex_3.py"
    spec = importlib.util.spec_from_file_location("rtllm_l2_batch1_3_test_module", path)
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
        "task_count": 3,
        "known_bad_categories_per_task": 4,
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
            "image": {"resolved_image_id": launcher.base._EXPECTED_RUNTIME_IMAGE_ID}
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


def test_matrix_freezes_three_functional_v3_no_ppa_slots() -> None:
    launcher = _launcher()

    assert launcher._PROCESS_COUNT == len(launcher._RUN_SPECS) == 3
    assert tuple(spec.task_name for spec in launcher._RUN_SPECS) == launcher.L2_BATCH1_TASK_NAMES
    assert len({spec.run_id for spec in launcher._RUN_SPECS}) == 3
    assert all(
        spec.task_id.startswith(f"rtllm/{launcher.L2_BATCH1_VARIANT}/")
        for spec in launcher._RUN_SPECS
    )
    assert launcher._MODEL_ID == "gpt-5.4"
    assert launcher._REASONING_EFFORT == "xhigh"
    assert launcher._AGENT_NAME == launcher.FUNCTIONAL_V3_HIGH_IDENTITY.agent_name
    assert launcher._OPT_IN == "VERIGYM_RUN_RTLLM_L2_BATCH1_3"


def test_profile_is_installed_into_reused_fail_closed_launcher() -> None:
    launcher = _launcher()

    assert launcher.base._PROCESS_COUNT == 3
    assert launcher.base.ALL_AGENT_EVAL_VARIANT == launcher.L2_BATCH1_VARIANT
    assert launcher.base._RUN_SPECS == launcher._RUN_SPECS
    assert launcher.base._launcher_hash() == launcher._launcher_hash()
    assert launcher.base._no_model_qualification is launcher._no_model_qualification
    assert launcher.base._validate_existing_plan is launcher._validate_existing_plan


def test_plan_freezes_l2_qualification_functional_identity_and_zero_retry() -> None:
    launcher = _launcher()
    plan = _plan(launcher)

    assert plan["variant"] == launcher.L2_BATCH1_VARIANT
    assert plan["planned_codex_processes"] == 3
    assert plan["public_feedback_level"] == "L2_candidate_only_functional_smoke"
    assert plan["qualification_profile"] == "reference_plus_four_known_bad_public_and_hidden_v1"
    assert plan["ppa_enabled"] is False
    assert plan["automatic_retries"] == 0
    assert plan["automatic_retries_authorized"] is False
    assert plan["codex"]["agent_version_id"] == (  # type: ignore[index]
        launcher.FUNCTIONAL_V3_HIGH_IDENTITY.agent_version_id
    )
    launcher._validate_existing_plan(plan)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("public_feedback_level",), "L1_candidate_only_compile"),
        (("qualification", "model_calls"), 1),
        (("qualification", "known_bad_categories_per_task"), 3),
        (("qualification", "records", 0, "public_known_bad_rejected_count"), 3),
        (("ppa_enabled",), True),
        (("automatic_retries",), 1),
    ],
)
def test_existing_plan_rejects_qualification_identity_or_policy_drift(
    path: tuple[str | int, ...], value: object
) -> None:
    launcher = _launcher()
    changed = deepcopy(_plan(launcher))
    target: object = changed
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(Exception, match="frozen campaign|frozen identities"):
        launcher._validate_existing_plan(changed)


def test_launcher_source_marks_diagnostic_no_ppa_and_no_retry() -> None:
    source = (
        Path(__file__).parents[2] / "scripts" / "run_rtllm_l2_batch1_multiturn_codex_3.py"
    ).read_text(encoding="utf-8")

    assert '"ppa_supported": False' in source
    assert '"model_calls": 0' in source
    assert "known_bad_categories_per_task" in source
    assert "FUNCTIONAL_V3_HIGH_IDENTITY" in source
