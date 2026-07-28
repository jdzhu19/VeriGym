from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
import yaml

from verigym.agents.parsing import parse_single_turn_rtl
from verigym.core.hashing import content_hash
from verigym.core.orchestrator import VeriGym
from verigym.models.static import StaticModelClient
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunResult
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig
from verigym.suites.verilog_eval.schemas import IcarusCompatibility
from verigym.suites.verilog_eval.toolchain import detect_icarus

pytestmark = [
    pytest.mark.codex_cli,
    pytest.mark.codex_cli_pilot,
    pytest.mark.requires_iverilog,
    pytest.mark.external_benchmark,
]

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ENV = "VERIGYM_VERILOG_EVAL_ROOT"
SOURCE = os.environ.get(SOURCE_ENV)
FORENSIC_CANDIDATES = ROOT / "tests" / "fixtures" / "codex_cli" / "f6b159b_track_b_candidates.json"
requires_pilot_source = pytest.mark.skipif(
    SOURCE is None,
    reason=f"{SOURCE_ENV} is required for exact frozen-pilot candidate conformance",
)

VALID_CANDIDATES = {
    "Prob014_andgate": """
module TopModule(input logic a, input logic b, output logic out);
  always_comb out = a && b;
endmodule
""",
    "Prob024_hadd": """
module TopModule(input logic a, input logic b, output logic sum, output logic cout);
  always_comb begin
    sum = a ^ b;
    cout = a & b;
  end
endmodule
""",
    "Prob035_count1to10": """
module TopModule(input logic clk, input logic reset, output logic [3:0] q);
  always_ff @(posedge clk) begin
    if (reset) q <= 4'd1;
    else if (q == 4'd10) q <= 4'd1;
    else q <= q + 4'd1;
  end
endmodule
""",
    "Prob085_shift4": """
module TopModule(
  input logic clk, input logic areset, input logic load, input logic ena,
  input logic [3:0] data, output logic [3:0] q
);
  always_ff @(posedge clk or posedge areset) begin
    if (areset) q <= 4'b0;
    else if (load) q <= data;
    else if (ena) q <= {1'b0, q[3:1]};
  end
endmodule
""",
    "Prob107_fsm1s": """
module TopModule(input logic clk, input logic reset, input logic in, output logic out);
  localparam logic A = 1'b0;
  localparam logic B = 1'b1;
  logic state, next_state;
  always_comb begin
    if (state == B) next_state = in ? B : A;
    else next_state = in ? A : B;
  end
  always_ff @(posedge clk) begin
    if (reset) state <= B;
    else state <= next_state;
  end
  assign out = (state == B);
endmodule
""",
}


def _frozen_tasks() -> list[dict[str, object]]:
    config = yaml.safe_load(
        (ROOT / "examples" / "experiments" / "codex-cli-verilog-eval-pilot.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert isinstance(config, dict)
    return config["tasks"]


def _service() -> VeriGym:
    return VeriGym(build_registries(discover_external=False))


def _run_candidate(
    service: VeriGym,
    *,
    task_id: str,
    source: SuiteSourceConfig,
    candidate: str,
    model_name: str,
    output: Path,
) -> RunResult:
    model = StaticModelClient(name=model_name, responses=[candidate])
    service.registries.models.register(model)
    runtime: dict[str, object] = {}
    docker_image = os.environ.get("VERIGYM_DOCKER_IMAGE")
    if docker_image is not None:
        runtime = {
            "runtime": "docker",
            "docker_config": DockerRuntimeConfig(
                image=docker_image,
                pull_policy="never",
            ),
        }
    return service.run(
        RunConfig(
            task_id=task_id,
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model=model_name,
            suite_source=source,
            output=output,
            **runtime,
        )
    )


@requires_pilot_source
def test_exact_reference_and_representative_candidates_pass_all_five_frozen_tasks(
    tmp_path: Path,
) -> None:
    assert SOURCE is not None
    assert detect_icarus("iverilog").compatibility is IcarusCompatibility.REFERENCE_COMPATIBLE
    assert detect_icarus("vvp").compatibility is IcarusCompatibility.REFERENCE_COMPATIBLE
    source = SuiteSourceConfig(source_root=Path(SOURCE), variant="v2-spec-to-rtl")
    service = _service()
    for task_record in _frozen_tasks():
        task_id = str(task_record["id"])
        native_id = task_id.rsplit("/", 1)[1]
        suite, task, _assets = service.load_task(task_id, source)
        assert content_hash(task) == task_record["task_hash"]
        assert task.source.content_hash == task_record["source_hash"]
        snapshot = suite.source_snapshot()
        assert snapshot is not None
        assert snapshot.git_commit == "c498220d0a52248f8e3fdffe279075215bde2da6"
        assert (
            snapshot.dataset_content_hash
            == "432b712cea110d4b5d35521f691db1bc3e726a77c6fc72fc1c916a85361ddbf2"
        )
        reference = suite.reference_solution(task)
        assert reference is not None
        reference_source = reference.files["rtl/TopModule.sv"]
        reference_result = _run_candidate(
            service,
            task_id=task_id,
            source=source,
            candidate=f"```systemverilog\n{reference_source}```",
            model_name=f"pilot-reference-{native_id}",
            output=tmp_path / "reference" / native_id,
        )
        assert reference_result.scorecard.resolved is True
        frozen_reference = (
            reference_result.run_dir / "candidate" / "rtl" / "TopModule.sv"
        ).read_text(encoding="utf-8")
        assert frozen_reference == parse_single_turn_rtl(f"```systemverilog\n{reference_source}```")

        candidate = VALID_CANDIDATES[native_id]
        candidate_result = _run_candidate(
            service,
            task_id=task_id,
            source=source,
            candidate=candidate,
            model_name=f"pilot-representative-{native_id}",
            output=tmp_path / "representative" / native_id,
        )
        assert candidate_result.scorecard.resolved is True
        frozen_candidate = (
            candidate_result.run_dir / "candidate" / "rtl" / "TopModule.sv"
        ).read_text(encoding="utf-8")
        assert frozen_candidate == parse_single_turn_rtl(candidate)


@requires_pilot_source
def test_genuine_invalid_pilot_candidate_remains_evaluable_candidate_failure(
    tmp_path: Path,
) -> None:
    assert SOURCE is not None
    task_id = "verilog-eval/v2-spec-to-rtl/Prob014_andgate"
    result = _run_candidate(
        _service(),
        task_id=task_id,
        source=SuiteSourceConfig(source_root=Path(SOURCE), variant="v2-spec-to-rtl"),
        candidate="module TopModule( this is invalid endmodule\n",
        model_name="pilot-invalid-candidate",
        output=tmp_path / "invalid",
    )
    assert result.scorecard.status == "completed"
    assert result.scorecard.resolved is False
    assert result.scorecard.correctness.infrastructure_error is False
    assert result.scorecard.failure is None
    failed = next(item for item in result.scorecard.verifier_results if item.status == "failed")
    assert failed.metadata["candidate_failure"] is True


@requires_pilot_source
def test_f6b159b_track_b_forensic_candidates_reach_exact_hidden_verifier(
    tmp_path: Path,
) -> None:
    assert SOURCE is not None
    fixture = json.loads(FORENSIC_CANDIDATES.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == "1.0"
    assert fixture["source_commit"] == "f6b159b01050806f9e20ef6626fc755dfa36f048"
    records = fixture["candidates"]
    assert len(records) == 15
    for record in records:
        assert (
            hashlib.sha256(str(record["rtl"]).encode("utf-8")).hexdigest()
            == record["candidate_sha256"]
        )

    secondary_policy_runs = {
        "codex-pilot-codex_cli_external_agent-Prob035_count1to10-0",
        "codex-pilot-codex_cli_external_agent-Prob085_shift4-0",
        "codex-pilot-codex_cli_external_agent-Prob107_fsm1s-0",
    }
    compile_failure_run = "codex-pilot-codex_cli_external_agent-Prob107_fsm1s-1"
    verifier_records = [
        record for record in records if record["run_id"] not in secondary_policy_runs
    ]
    assert len(verifier_records) == 12

    service = _service()
    source = SuiteSourceConfig(
        source_root=Path(SOURCE),
        variant="v2-spec-to-rtl",
    )
    passed = 0
    compile_failed = 0
    for record in verifier_records:
        native_id = str(record["run_id"]).rsplit("-", 1)[0].rsplit("-", 1)[1]
        result = _run_candidate(
            service,
            task_id=f"verilog-eval/v2-spec-to-rtl/{native_id}",
            source=source,
            candidate=str(record["rtl"]),
            model_name=f"f6b159b-forensic-{native_id}-{record['run_id'][-1]}",
            output=tmp_path / str(record["run_id"]),
        )
        assert result.scorecard.status == "completed"
        frozen = (result.run_dir / "candidate" / "rtl" / "TopModule.sv").read_text(encoding="utf-8")
        assert hashlib.sha256(frozen.encode("utf-8")).hexdigest() == record["candidate_sha256"]
        if record["run_id"] == compile_failure_run:
            assert result.scorecard.resolved is False
            assert result.scorecard.correctness.infrastructure_error is False
            assert result.scorecard.failure is None
            failed = next(
                item for item in result.scorecard.verifier_results if item.status == "failed"
            )
            assert failed.metadata["candidate_failure"] is True
            compile_failed += 1
        else:
            assert result.scorecard.resolved is True
            passed += 1
    assert passed == 11
    assert compile_failed == 1
