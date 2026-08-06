"""Run an installed-wheel, zero-model smoke against a synthetic external source."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from verigym.api import ReportService, RunConfig, VeriGym, build_registries, replay_run
from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentAdapter,
    AgentContext,
    AgentDescriptor,
    EpisodeResult,
    FinalSubmissionAction,
    InteractionMode,
    Observation,
    SuiteSourceConfig,
)

SUITE = "verilog-eval-code-complete"
VARIANT = "v2-code-complete-iccad2023"
TASK = "Demo001_and"
CANDIDATE = """module TopModule(input logic a, input logic b, output logic y);
  assign y = a & b;
endmodule
"""


class SyntheticSmokeAgent(AgentAdapter):
    """Submit one fixed synthetic candidate without invoking a model or provider."""

    supported_modes = frozenset({InteractionMode.CHAT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="verilog-eval-code-complete-zero-model-smoke",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-plugin-conformance",
        capabilities=["deterministic", "offline", "zero_model", "synthetic_only"],
    )

    def __init__(self) -> None:
        self._started = False
        self._submitted = False

    def start(self, context: AgentContext) -> None:
        if context.task.id != f"{SUITE}/{VARIANT}/{TASK}":
            raise ValueError(f"synthetic smoke agent does not support {context.task.id}")
        self._started = True
        self._submitted = False

    def act(self, observation: Observation) -> FinalSubmissionAction:
        del observation
        if not self._started or self._submitted:
            raise RuntimeError("synthetic smoke agent was called outside its single action")
        self._submitted = True
        return FinalSubmissionAction(
            message="Submit the deterministic synthetic conformance candidate.",
            files={"rtl/TopModule.sv": CANDIDATE},
        )

    def finish(self, result: EpisodeResult) -> None:
        del result


def _write_source(root: Path) -> None:
    dataset = root / "dataset_code-complete-iccad2023"
    dataset.mkdir(parents=True)
    (root / "LICENSE").write_text(
        "MIT License\n\nPermission is hereby granted, free of charge, "
        "to any person obtaining a copy\n",
        encoding="utf-8",
    )
    (root / "VERIGYM_SYNTHETIC_FIXTURE").write_text(
        "Synthetic layout-conformance fixture; not benchmark data.\n",
        encoding="utf-8",
    )
    interface = "module TopModule(input logic a, input logic b, output logic y);\n"
    contents = {
        "_prompt.txt": f"Implement a two-input AND gate.\n\n{interface}",
        "_ifc.txt": interface,
        "_ref.sv": (
            "module RefModule(input logic a, input logic b, output logic y);\n"
            "  assign y = a & b;\n"
            "endmodule\n"
        ),
        "_test.sv": """`timescale 1ns/1ps
module tb;
  logic a, b;
  logic y_ref, y_dut;
  integer mismatches = 0;
  RefModule reference(.a(a), .b(b), .y(y_ref));
  TopModule candidate(.a(a), .b(b), .y(y_dut));
  initial begin
    a = 0; b = 0; #1; if (y_ref !== y_dut) mismatches = mismatches + 1;
    a = 0; b = 1; #1; if (y_ref !== y_dut) mismatches = mismatches + 1;
    a = 1; b = 0; #1; if (y_ref !== y_dut) mismatches = mismatches + 1;
    a = 1; b = 1; #1; if (y_ref !== y_dut) mismatches = mismatches + 1;
    $display("Mismatches: %0d in 4 samples", mismatches);
    $finish;
  end
endmodule
""",
    }
    for suffix, content in contents.items():
        (dataset / f"{TASK}{suffix}").write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    output = arguments.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        parser.error("--output must not already exist")

    with tempfile.TemporaryDirectory(prefix="verigym-plugin-synthetic-source-") as temporary:
        source = Path(temporary)
        _write_source(source)
        registries = build_registries()
        registries.agents.register(SyntheticSmokeAgent())
        service = VeriGym(registries)
        result = service.run(
            RunConfig(
                task_id=f"{SUITE}/{VARIANT}/{TASK}",
                mode=InteractionMode.CHAT,
                agent=SyntheticSmokeAgent.descriptor.name,
                suite_source=SuiteSourceConfig(source_root=source, variant=VARIANT),
                runtime="local",
                output=output,
            )
        )
        replay = replay_run(result.run_dir, verify=True, service=service)
        reports = ReportService().generate_all(output)

    if not result.scorecard.resolved or replay.reverified_resolved is not True:
        raise RuntimeError("synthetic plugin smoke did not resolve and replay")
    if result.scorecard.efficiency.model_calls != 0:
        raise RuntimeError("synthetic plugin smoke unexpectedly made a model call")
    if reports.aggregate.coverage.resolved_runs != 1:
        raise RuntimeError("synthetic plugin smoke report did not contain one resolved run")
    print(
        json.dumps(
            {
                "model_calls": result.scorecard.efficiency.model_calls,
                "report": str(reports.aggregate_path),
                "resolved": result.scorecard.resolved,
                "reverified": replay.reverified_resolved,
                "run_dir": str(result.run_dir),
                "synthetic": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
