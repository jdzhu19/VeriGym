"""Run one non-scored official task with a fixed offline conformance response."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from verigym.api import ReportService, RunConfig, VeriGym, build_registries, replay_run
from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    ModelClient,
    ModelDescriptor,
    ModelFinishReason,
    ModelRequest,
    ModelResponse,
    ModelRunConfig,
    NormalizedModelUsage,
    SuiteSourceConfig,
)

SUITE = "verilog-eval-code-complete"
VARIANT = "v2-code-complete-iccad2023"
TASK = "Prob001_zero"
SOURCE = """module TopModule (
  output zero
);
  assign zero = 1'b0;
endmodule
"""


class OfflineSmokeModel(ModelClient):
    """Deterministic known-answer fixture; never use its result as a benchmark score."""

    descriptor = ModelDescriptor(
        schema_version=SCHEMA_VERSION,
        name="verilog-eval-code-complete-offline-smoke",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-plugin-conformance",
        capabilities=["offline", "deterministic", "known_answer_smoke_only"],
        model_id="offline-known-answer-smoke",
        client_name="fixed-response",
        client_version="0.1.0",
        configuration_fingerprint=hashlib.sha256(SOURCE.encode()).hexdigest(),
        configuration={"scored": False, "task": TASK},
    )

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            request_id=request.request_id,
            response_id="offline-smoke-0000",
            text=SOURCE,
            finish_reason=ModelFinishReason.STOP,
            usage=NormalizedModelUsage(input_tokens=0, output_tokens=0, total_tokens=0),
        )

    def clone_for_run(self, configuration: ModelRunConfig | None = None) -> OfflineSmokeModel:
        del configuration
        return OfflineSmokeModel()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", choices=("local", "docker"), default="local")
    parser.add_argument("--docker-image")
    args = parser.parse_args()
    if args.runtime == "docker" and not args.docker_image:
        parser.error("--runtime docker requires --docker-image")
    if args.runtime == "local" and args.docker_image:
        parser.error("--docker-image requires --runtime docker")

    registries = build_registries()
    registries.models.register(OfflineSmokeModel())
    service = VeriGym(registries)
    config = RunConfig.model_validate(
        {
            "task_id": f"{SUITE}/{VARIANT}/{TASK}",
            "mode": "chat",
            "agent": "single-turn",
            "model": OfflineSmokeModel.descriptor.name,
            "suite_source": SuiteSourceConfig(
                source_root=args.source,
                variant=VARIANT,
            ),
            "runtime": args.runtime,
            "docker_config": (
                {"image": args.docker_image, "pull_policy": "never"}
                if args.runtime == "docker"
                else None
            ),
            "output": args.output,
        }
    )
    result = service.run(config)
    replay = replay_run(result.run_dir, verify=True, service=service)
    reports = ReportService().generate_all(args.output)
    if not result.scorecard.resolved or replay.reverified_resolved is not True:
        raise RuntimeError("official code-completion smoke did not resolve and replay")
    if reports.aggregate.coverage.resolved_runs != 1:
        raise RuntimeError("offline report did not include exactly one resolved smoke run")
    print(
        json.dumps(
            {
                "scored": False,
                "run_dir": str(result.run_dir),
                "resolved": result.scorecard.resolved,
                "reverified": replay.reverified_resolved,
                "report": str(reports.aggregate_path),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
