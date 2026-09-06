"""Opt-in synthetic execution checks the real runtime API without benchmark inputs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from verigym_cadence.protocol import Asset
from verigym_realbench.functional import FunctionalProfile, run_functional

from verigym.plugin_api import hash_bytes
from verigym.schemas.runtime import DockerRuntimeConfig


@pytest.mark.docker
def test_synthetic_real_docker_functional_contract(tmp_path: Path) -> None:
    if os.environ.get("VERIGYM_RUN_DOCKER_TESTS") != "1":
        pytest.skip("explicit real Docker opt-in required")
    image = os.environ.get("VERIGYM_REALBENCH_FUNCTIONAL_IMAGE")
    digest = os.environ.get("VERIGYM_REALBENCH_FUNCTIONAL_IMAGE_ID")
    if not image or not digest:
        pytest.skip("explicit functional image and image ID required")
    files = {
        "top_ref.sv": "module ref_top; endmodule\n",
        "top_stimulus_gen.sv": "module stimulus_gen; endmodule\n",
        "top_testbench.sv": """module tb;
wire y;
top dut(.a(1'b1), .y(y));
initial begin
    #1;
    if (y == 1'b1) $display("Hint: Output 'y' has no mismatches.");
    else $display("Hint: Output 'y' has 1 mismatches. First mismatch occurred at time 1.");
    $finish;
end
endmodule
""",
    }
    assets = []
    for name, text in files.items():
        path = tmp_path / name
        path.write_text(text)
        assets.append(Asset(role=name, path=str(path), sha256=hash_bytes(text.encode())))
    profile = FunctionalProfile(
        id="synthetic-docker-functional-v1",
        task_id="synthetic/functional",
        top="top",
        sources=["repository/rtl/top.sv"],
        outputs=["y"],
        assets=assets,
        docker=DockerRuntimeConfig(
            image=image,
            expected_image_id=digest,
            run_as_user=f"{os.getuid()}:{os.getgid()}",
            memory_bytes=4 * 1024**3,
            cpus=2,
            max_command_time_s=300,
        ),
    )
    result = run_functional(
        profile, {profile.sources[0]: b"module top(input a, output y); assign y=a; endmodule"}
    )
    assert result.status == "passed", result.model_dump()
    assert result.cleanup_complete
