from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from verigym.core.hashing import hash_bytes
from verigym.tools.yosys.opensta import (
    LATCH_MAPPING_FLOW_TEMPLATE_CONTRACT,
    LATCH_MAPPING_FLOW_TEMPLATE_ID,
)


@lru_cache(maxsize=1)
def _launcher() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "qualify_rtllm_ppa3_dual_backend.py"
    spec = importlib.util.spec_from_file_location("rtllm_ppa3_qualification_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


@lru_cache(maxsize=1)
def _profile_preparer() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "prepare_rtllm_ppa47_profiles.py"
    spec = importlib.util.spec_from_file_location("rtllm_ppa47_profile_preparer_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_partition_and_task_matrix_is_exact() -> None:
    launcher = _launcher()

    assert launcher.PPA_DIAGNOSTIC3_TASK_NAMES == (
        "radix2_div",
        "multi_pipe_8bit",
        "LIFObuffer",
    )
    assert launcher._BACKENDS == {
        "open": "yosys.synth",
        "commercial": "synopsys.dc.mcp",
    }
    assert launcher._FORMAT_ID == "rtllm_ppa3_dual_backend_qualification_v1"
    ppa47 = launcher._CATALOGS["ppa47"]
    assert ppa47.variant == "v2-agent-eval-functional-ppa47-v1"
    assert len(ppa47.task_names) == 47
    assert ppa47.conformance_cases_per_task == 13


def test_named_paths_require_exact_nonduplicated_task_coverage(tmp_path: Path) -> None:
    launcher = _launcher()
    paths = {}
    for name in launcher.PPA_DIAGNOSTIC3_TASK_NAMES:
        path = tmp_path / f"{name}.yaml"
        path.write_text("profile", encoding="utf-8")
        paths[name] = path

    parsed = launcher._named_paths(
        [f"{name}={paths[name]}" for name in launcher.PPA_DIAGNOSTIC3_TASK_NAMES],
        "profiles",
    )
    assert parsed == {name: path.resolve() for name, path in paths.items()}

    with pytest.raises(Exception, match="cover exactly"):
        launcher._named_paths([f"radix2_div={paths['radix2_div']}"], "profiles")
    with pytest.raises(Exception, match="unique"):
        launcher._named_paths(
            [
                f"radix2_div={paths['radix2_div']}",
                f"radix2_div={paths['radix2_div']}",
            ],
            "profiles",
        )


def test_metric_shape_records_contract_presence_without_raw_values() -> None:
    launcher = _launcher()
    shape = launcher._metric_shape(
        SimpleNamespace(
            mapped_area_raw=123.0,
            mapped_area_unit="um^2",
            critical_path_delay_raw=4.0,
            worst_negative_slack_raw=-0.5,
            timing_unit="ns",
            total_power_raw=9.0,
            power_unit="uW",
            synthesis_ok=True,
        )
    )

    assert shape == {
        "area_present": True,
        "area_unit": "um^2",
        "delay_present": True,
        "wns_present": True,
        "timing_unit": "ns",
        "power_present": True,
        "power_unit": "uW",
        "synthesis_ok": True,
    }
    assert all(not isinstance(value, float) for value in shape.values())


def test_ppa47_metric_gate_requires_positive_cells_and_finite_metrics() -> None:
    launcher = _launcher()
    valid = SimpleNamespace(
        num_cells=12,
        mapped_area_raw=123.0,
        critical_path_delay_raw=4.0,
        worst_negative_slack_raw=-0.5,
        total_power_raw=9.0,
    )
    launcher._validate_metric_contract(valid)

    for field, value in (
        ("num_cells", 0),
        ("mapped_area_raw", float("nan")),
        ("critical_path_delay_raw", float("inf")),
        ("worst_negative_slack_raw", float("nan")),
        ("total_power_raw", 0.0),
    ):
        with pytest.raises(Exception, match="positive finite"):
            launcher._validate_metric_contract(SimpleNamespace(**{**vars(valid), field: value}))


def test_launcher_binds_private_functional_l3_l4_and_zero_model_contracts() -> None:
    source = (
        Path(__file__).parents[2] / "scripts" / "qualify_rtllm_ppa3_dual_backend.py"
    ).read_text(encoding="utf-8")

    assert "PrivateQualificationStaging" in source
    assert "AgentFeedbackController" in source
    assert "execute_synthesis_quality" in source
    assert "build_scorecard" in source
    assert '"model_calls": 0' in source
    assert '"backend_partitions_comparable": False' in source
    assert "PPA_DIAGNOSTIC3_TASK_IDENTITIES_SHA256" in source


def test_ppa47_preparer_pins_parser_compatible_opensta_flow() -> None:
    preparer = _profile_preparer()
    payload = {
        "flow": {"template_id": "verigym-yosys-opensta-atp-v2"},
        "scripts": [
            {
                "name": "old-flow",
                "source_kind": "generated",
                "content_hash": "0" * 64,
                "version": "2.0.0",
            }
        ],
    }

    preparer._bind_opensta_compatibility_flow(payload)

    assert payload["flow"]["template_id"] == LATCH_MAPPING_FLOW_TEMPLATE_ID
    assert payload["scripts"][0]["name"] == LATCH_MAPPING_FLOW_TEMPLATE_ID
    assert payload["scripts"][0]["content_hash"] == hash_bytes(
        (LATCH_MAPPING_FLOW_TEMPLATE_CONTRACT + "\n").encode()
    )
