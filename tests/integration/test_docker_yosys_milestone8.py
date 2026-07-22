from __future__ import annotations

import math
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import hash_bytes
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.profiles.registry import ToolchainProfileRegistry
from verigym.registry.collections import build_registries
from verigym.runtimes.docker.cleanup import inspect_owned_resources
from verigym.runtimes.docker.engine import DockerCliEngine
from verigym.runtimes.docker.errors import DockerRuntimeError
from verigym.runtimes.docker.image import inspect_backend, resolve_image
from verigym.schemas.common import InteractionMode, RuntimeDescriptor
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerRuntimeConfig

RUN_DOCKER_YOSYS = os.environ.get("VERIGYM_RUN_DOCKER_YOSYS_TESTS") == "1"
DOCKER_YOSYS_IMAGE = os.environ.get(
    "VERIGYM_DOCKER_YOSYS_IMAGE",
    "verigym/open-rtl-tools:iverilog12-yosys067",
)
PROFILE_ID = "open-yosys-toy-area-v1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_yosys,
    pytest.mark.skipif(
        not RUN_DOCKER_YOSYS,
        reason="set VERIGYM_RUN_DOCKER_YOSYS_TESTS=1 to run Docker-Yosys tests",
    ),
]


def _config(image: str) -> DockerRuntimeConfig:
    return DockerRuntimeConfig(image=image, pull_policy="never")


def _owned_resources() -> tuple[set[str], set[str]]:
    engine = DockerCliEngine()
    try:
        owned = inspect_owned_resources(engine)
        return set(owned.container_ids), set(owned.volume_names)
    finally:
        engine.close()


def _assert_no_new_owned(before: tuple[set[str], set[str]]) -> None:
    assert _owned_resources() == before


@pytest.fixture(scope="module")
def docker_yosys_image() -> str:
    engine = DockerCliEngine()
    try:
        inspect_backend(engine)
        identity = resolve_image(engine, _config(DOCKER_YOSYS_IMAGE))
    except DockerRuntimeError as exc:
        pytest.fail(f"explicit Docker-Yosys test image is unavailable: {exc}")
    finally:
        engine.close()
    assert identity.resolved_image_id.startswith("sha256:")
    return DOCKER_YOSYS_IMAGE


@pytest.fixture(scope="module")
def profile_runs(
    docker_yosys_image: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Any, Any, tuple[set[str], set[str]]]:
    before = _owned_resources()
    service = VeriGym(build_registries(discover_external=False))
    root = tmp_path_factory.mktemp("m8-docker-yosys")
    good = service.run(
        RunConfig(
            task_id="toy-rtl/counter-basic",
            agent="scripted",
            runtime="docker",
            docker_config=_config(docker_yosys_image),
            toolchain_profile=PROFILE_ID,
            output=root / "good",
        )
    )
    _assert_no_new_owned(before)
    bad = service.run(
        RunConfig(
            task_id="toy-rtl/counter-basic",
            agent="scripted-bad",
            runtime="docker",
            docker_config=_config(docker_yosys_image),
            toolchain_profile=PROFILE_ID,
            output=root / "bad",
        )
    )
    _assert_no_new_owned(before)
    return good, bad, before


def test_good_candidate_profile_area_reference_and_artifact_contract(
    profile_runs: tuple[Any, Any, tuple[set[str], set[str]]],
) -> None:
    good, _bad, before = profile_runs
    assert good.scorecard.status == "completed"
    assert good.scorecard.resolved
    assert not good.scorecard.correctness.infrastructure_error
    synthesis = good.scorecard.quality.synthesis
    reference = good.scorecard.quality.reference_synthesis
    ppa = good.scorecard.quality.ppa
    assert synthesis is not None and synthesis.synthesis_ok
    assert reference is not None and reference.synthesis_ok
    assert ppa is not None and ppa.eligible
    assert ppa.scope == "synthesis_area_only"
    assert ppa.area is not None and ppa.area > 0
    assert ppa.reference_area is not None and ppa.reference_area > 0
    assert ppa.area_ratio == ppa.reference_area / ppa.area
    assert math.isfinite(ppa.area_ratio)
    assert all(
        value is None
        for value in (
            ppa.delay,
            ppa.frequency,
            ppa.power,
            ppa.worst_negative_slack,
            ppa.total_negative_slack,
        )
    )

    resolved = load_model(
        good.run_dir / "artifacts/resolved_toolchain_profile.json",
        ResolvedToolchainProfile,
    )
    assert good.manifest.resolved_toolchain_profile == resolved
    assert synthesis.resolved_profile_hash == reference.resolved_profile_hash
    assert synthesis.resolved_profile_hash == resolved.resolved_profile_hash
    assert resolved.runtime_identity.resolved_image_id is not None
    assert resolved.runtime_identity.resolved_image_id.startswith("sha256:")
    tools = {tool.logical_name: tool for tool in resolved.tool_identities}
    assert tools["yosys"].version == "0.67"
    assert tools["yosys"].git_hash
    assert tools["yosys-abc"].version_output
    assert tools["yosys-abc"].git_hash == "e026ed5380f3bdc3beea2ff9ffc23236fc549d5b"

    candidate_artifacts = good.run_dir / "artifacts/yosys/candidate"
    for artifact in synthesis.artifacts:
        path = candidate_artifacts / artifact.path
        assert artifact.visibility == "public"
        assert path.is_file()
        assert hash_bytes(path.read_bytes()) == artifact.content_hash
    assert {item.path for item in synthesis.artifacts} >= {
        "flow.ys",
        "yosys.log",
        "stat.json",
        "netlist.json",
        "netlist.v",
    }
    assert reference.artifacts == []
    summary = (good.run_dir / "artifacts/yosys/reference_summary.json").read_text(encoding="utf-8")
    assert '"reference_rtl_exported": false' in summary
    assert '"reference_netlist_exported": false' in summary
    assert not (good.run_dir / "artifacts/yosys/reference_private").exists()
    assert not list((good.run_dir / "candidate").rglob("tb_counter.sv"))
    _assert_no_new_owned(before)


def test_bad_candidate_is_normal_failure_and_has_no_ranked_area(
    profile_runs: tuple[Any, Any, tuple[set[str], set[str]]],
) -> None:
    _good, bad, before = profile_runs
    assert bad.scorecard.status == "completed"
    assert not bad.scorecard.resolved
    assert not bad.scorecard.correctness.infrastructure_error
    ppa = bad.scorecard.quality.ppa
    assert ppa is not None and not ppa.eligible
    assert "correctness_gate_failed" in ppa.ineligible_reasons
    assert ppa.area is None
    assert ppa.reference_area is None
    assert ppa.area_ratio is None
    assert ppa.delay is None and ppa.frequency is None and ppa.power is None
    assert bad.scorecard.quality.synthesis is not None
    assert bad.scorecard.quality.synthesis.status == "skipped"
    _assert_no_new_owned(before)


def test_exact_image_replay_is_model_free_verifier_only_and_normalized(
    profile_runs: tuple[Any, Any, tuple[set[str], set[str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, _bad, before = profile_runs
    immutable_files = {
        path: path.read_bytes()
        for path in (
            good.run_dir / "run_manifest.json",
            good.run_dir / "trace.jsonl",
            good.run_dir / "scorecard.json",
            good.run_dir / "artifacts/toolchain_profile.json",
            good.run_dir / "artifacts/resolved_toolchain_profile.json",
            good.run_dir / "artifacts/yosys/candidate/flow.ys",
            good.run_dir / "artifacts/yosys/candidate/stat.json",
            good.run_dir / "artifacts/yosys/reference_summary.json",
        )
    }
    service = VeriGym(build_registries(discover_external=False))

    def reject_model_lookup(_name: str) -> Any:
        raise AssertionError("profile replay attempted a model lookup")

    monkeypatch.setattr(service.registries.models, "get", reject_model_lookup)
    replay = replay_run(good.run_dir, verify=True, service=service)
    assert replay.reverified_resolved is True
    assert replay.reverified_candidate_synthesis is not None
    assert replay.reverified_reference_synthesis is not None
    assert (
        replay.reverified_candidate_synthesis.mapped_area_raw
        == good.scorecard.quality.synthesis.mapped_area_raw
    )
    assert (
        replay.reverified_reference_synthesis.mapped_area_raw
        == good.scorecard.quality.reference_synthesis.mapped_area_raw
    )
    replay_runtime = load_model(
        good.run_dir / "artifacts/replay-verification/runtime_descriptor.json",
        RuntimeDescriptor,
    )
    assert replay_runtime.image is not None and good.manifest.runtime.image is not None
    assert replay_runtime.image.resolved_image_id == good.manifest.runtime.image.resolved_image_id
    assert replay_runtime.sessions
    assert all(record.role == "verifier" for record in replay_runtime.sessions)
    assert replay_runtime.cleanup is not None and replay_runtime.cleanup.complete
    assert all(path.read_bytes() == payload for path, payload in immutable_files.items())
    _assert_no_new_owned(before)


def test_profile_image_mismatch_fails_before_model_lookup_and_cleans_up(
    docker_yosys_image: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _owned_resources()
    registries = build_registries(discover_external=False)
    profile = registries.profiles.get(PROFILE_ID)
    profile.runtime.requested_image = "verigym/incompatible-profile-image:never"
    profile.container_image = profile.runtime.requested_image
    registries.profiles = ToolchainProfileRegistry([profile])
    lookups: list[str] = []

    def record_model_lookup(name: str) -> Any:
        lookups.append(name)
        raise AssertionError("model lookup must not occur after profile mismatch")

    monkeypatch.setattr(registries.models, "get", record_model_lookup)
    with pytest.raises(ConfigurationError, match="requires Docker image reference"):
        VeriGym(registries).run(
            RunConfig(
                task_id="toy-rtl/counter-basic",
                mode=InteractionMode.CHAT,
                agent="single-turn",
                model="static-counter-good",
                runtime="docker",
                docker_config=_config(docker_yosys_image),
                toolchain_profile=PROFILE_ID,
                output=tmp_path,
            )
        )
    assert lookups == []
    _assert_no_new_owned(before)


def test_missing_image_is_structured_and_creates_no_resources(tmp_path: Path) -> None:
    before = _owned_resources()
    missing = f"verigym/m8-image-does-not-exist:{uuid.uuid4().hex}"
    with pytest.raises(DockerRuntimeError) as failure:
        VeriGym(build_registries(discover_external=False)).run(
            RunConfig(
                task_id="toy-rtl/counter-basic",
                agent="scripted",
                runtime="docker",
                docker_config=_config(missing),
                toolchain_profile=PROFILE_ID,
                output=tmp_path,
            )
        )
    assert failure.value.subreason == "image_missing"
    _assert_no_new_owned(before)
