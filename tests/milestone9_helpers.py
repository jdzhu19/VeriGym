from __future__ import annotations

from pathlib import Path
from types import MethodType
from typing import Any

from verigym.core.orchestrator import VeriGym
from verigym.experiments.schemas import ExperimentConfig
from verigym.models.base import ModelClient
from verigym.registry.collections import build_registries
from verigym.schemas.common import ErrorCategory
from verigym.schemas.tool import HealthCheckResult, ToolResult


def _healthy(_plugin: Any, _context: Any = None) -> HealthCheckResult:
    return HealthCheckResult(
        healthy=True,
        message="deterministic in-process test tool",
        version="test-1.0",
        executable="in-process",
    )


def _compile(_plugin: Any, request: dict[str, Any], context: Any) -> ToolResult:
    output = str(request.get("output", ".verigym_internal/test/simv"))
    context.session.write_file(output, b"in-process-verifier\n")
    return ToolResult(
        tool="iverilog.compile",
        success=True,
        category=ErrorCategory.SUCCESS,
        message="synthetic compile passed",
        metadata={"executable": output},
    )


def _hidden_run(_plugin: Any, _request: dict[str, Any], context: Any) -> ToolResult:
    root = context.session.root
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted((root / "rtl").glob("*.v"))
    )
    passed = "assign y = a & b;" in source or "q <= q + 8'h01;" in source
    return ToolResult(
        tool="iverilog.run",
        success=passed,
        category=ErrorCategory.SUCCESS if passed else ErrorCategory.TEST_FAILED,
        message="synthetic hidden regression passed" if passed else "candidate failed tests",
        stdout="VERIGYM_PASS\n" if passed else "VERIGYM_FAIL\n",
        exit_code=0 if passed else 1,
        metadata={
            "candidate_failure": not passed,
            "tests_passed": int(passed),
            "tests_total": 1,
        },
    )


def _visible_run(_plugin: Any, _request: dict[str, Any], _context: Any) -> ToolResult:
    return ToolResult(
        tool="iverilog.simulate_visible",
        success=True,
        category=ErrorCategory.SUCCESS,
        message="synthetic visible regression passed",
        stdout="VERIGYM_PASS\n",
        exit_code=0,
        metadata={"tests_passed": 1, "tests_total": 1},
    )


def offline_service(*models: ModelClient) -> VeriGym:
    """Return a normal VeriGym service with only RTL subprocesses replaced in-process."""

    registries = build_registries(discover_external=False)
    replacements = {
        "iverilog.compile": _compile,
        "iverilog.run": _hidden_run,
        "iverilog.simulate_visible": _visible_run,
    }
    for name, execute in replacements.items():
        plugin = registries.tools.get(name)
        plugin.health_check = MethodType(_healthy, plugin)
        plugin.execute = MethodType(execute, plugin)
    for model in models:
        registries.models.register(model)
    return VeriGym(registries)


def experiment_config(
    output: Path,
    *,
    tasks: list[str] | None = None,
    systems: list[dict[str, object]] | None = None,
    seeds: list[int] | None = None,
    samples: int = 1,
    pass_k: list[int] | None = None,
    mode: str = "agent",
    max_workers: int = 1,
    name: str = "unit experiment",
) -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {
            "schema_version": "1.0",
            "name": name,
            "suite": {
                "id": "toy-rtl",
                "tasks": {
                    "include": tasks or ["and-gate-basic", "counter-basic"],
                    "exclude": [],
                },
            },
            "runs": {
                "mode": mode,
                "seeds": seeds or [0, 1],
                "samples_per_task": samples,
                "pass_k": pass_k or [1],
            },
            "systems": systems
            or [
                {"id": "good", "agent": {"id": "scripted"}},
                {"id": "bad", "agent": {"id": "scripted-bad"}},
            ],
            "runtime": {"id": "local"},
            "execution": {
                "max_workers": max_workers,
                "continue_on_infrastructure_error": True,
            },
            "output": {"root": output},
        }
    )
