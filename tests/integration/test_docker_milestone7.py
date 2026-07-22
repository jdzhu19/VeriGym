from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from verigym.cli.app import app
from verigym.core.hashing import hash_directory
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.core.sampling import regenerate_sample_report
from verigym.models.static import StaticModelClient
from verigym.registry.collections import build_registries
from verigym.runtimes.docker.cleanup import inspect_owned_resources
from verigym.runtimes.docker.engine import DockerCliEngine
from verigym.runtimes.docker.errors import DockerRuntimeError
from verigym.runtimes.docker.image import inspect_backend, resolve_image
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode, RuntimeDescriptor
from verigym.schemas.model import ModelRequest, ModelResponse, ModelRunConfig
from verigym.schemas.run import RunConfig, RunManifest
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.tool import CommandSpec

RUN_DOCKER = os.environ.get("VERIGYM_RUN_DOCKER_TESTS") == "1"
DOCKER_IMAGE = os.environ.get("VERIGYM_DOCKER_IMAGE", "verigym/rtl-iverilog:12.0")
VERILOG_EVAL_SOURCE = os.environ.get("VERIGYM_VERILOG_EVAL_ROOT")
SYNTHETIC_SOURCE = Path(__file__).parents[1] / "fixtures" / "verilog_eval_v2_synthetic"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker,
    pytest.mark.skipif(
        not RUN_DOCKER,
        reason="set VERIGYM_RUN_DOCKER_TESTS=1 to run real Docker integration tests",
    ),
]


class CountingInvocationModel(StaticModelClient):
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        super().__init__(name="m7-counting-invocation", responses=["not reached"])

    def clone_for_run(
        self,
        configuration: ModelRunConfig | None = None,
    ) -> CountingInvocationModel:
        del configuration
        return CountingInvocationModel(self.calls)

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request.request_id)
        return super().generate(request)


@pytest.fixture(scope="module")
def docker_image() -> str:
    """Require a usable daemon and a prebuilt local image when Docker tests are explicit."""

    engine = DockerCliEngine()
    try:
        inspect_backend(engine)
        identity = resolve_image(engine, DockerRuntimeConfig(image=DOCKER_IMAGE))
    except DockerRuntimeError as exc:
        pytest.fail(f"explicit Docker integration requirement is unavailable: {exc}")
    finally:
        engine.close()
    assert identity.resolved_image_id.startswith("sha256:")
    return DOCKER_IMAGE


def _service() -> VeriGym:
    return VeriGym(build_registries(discover_external=False))


def _docker_config(image: str, **updates: Any) -> DockerRuntimeConfig:
    return DockerRuntimeConfig.model_validate({"image": image, **updates})


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
def toy_runs(
    docker_image: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Any, Any, tuple[set[str], set[str]]]:
    root = tmp_path_factory.mktemp("m7-docker-toy")
    before = _owned_resources()
    service = _service()
    good = service.run(
        RunConfig(
            task_id="toy-rtl/counter-basic",
            agent="scripted",
            runtime="docker",
            docker_config=_docker_config(docker_image),
            output=root / "good",
        )
    )
    _assert_no_new_owned(before)
    bad = service.run(
        RunConfig(
            task_id="toy-rtl/counter-basic",
            agent="scripted-bad",
            runtime="docker",
            docker_config=_docker_config(docker_image),
            output=root / "bad",
        )
    )
    _assert_no_new_owned(before)
    return good, bad, before


def test_toy_good_bad_topology_provenance_and_scorecard(
    toy_runs: tuple[Any, Any, tuple[set[str], set[str]]],
) -> None:
    good, bad, before = toy_runs
    assert good.scorecard.resolved
    assert good.scorecard.status == "completed"
    assert good.scorecard.quality.ppa is None
    assert good.scorecard.quality.synthesis is None
    assert good.manifest.runtime.isolation_level == "docker_standard"
    assert good.manifest.runtime.image is not None
    image = good.manifest.runtime.image
    assert image.requested_reference == DOCKER_IMAGE
    assert image.resolved_image_id.startswith("sha256:")
    assert image.repository_digests is None or all(
        "@sha256:" in item for item in image.repository_digests
    )
    assert image.observed_uid not in {None, 0}
    assert image.observed_gid is not None
    assert image.iverilog_version and "12.0" in image.iverilog_version
    assert image.vvp_version and "12.0" in image.vvp_version
    assert image.compatibility_status == "canonical_or_reference_compatible"

    runtime = good.manifest.runtime
    assert runtime.backend is not None
    assert runtime.backend.backend_type == "docker_cli"
    assert runtime.cleanup is not None and runtime.cleanup.complete
    assert runtime.security is not None
    assert runtime.security.network_mode == "none"
    assert runtime.security.read_only_rootfs
    assert runtime.security.cap_drop == ["ALL"]
    assert runtime.security.no_new_privileges
    assert not runtime.security.docker_socket_mounted
    assert not runtime.security.host_home_mounted
    assert runtime.resources is not None
    assert runtime.resources.memory_bytes == 512 * 1024 * 1024
    assert runtime.resources.cpus == 1.0
    assert runtime.resources.pids_limit == 128
    assert runtime.resources.tmpfs_bytes == 64 * 1024 * 1024
    assert runtime.resources.max_output_bytes == good.manifest.budget.max_output_bytes_per_tool

    agent = next(record for record in runtime.sessions if record.role == "agent")
    verifier = next(record for record in runtime.sessions if record.role == "verifier")
    assert agent.session_id != verifier.session_id
    assert agent.frozen
    assert agent.resolved_image_id == verifier.resolved_image_id == image.resolved_image_id
    assert agent.container_ids
    assert verifier.container_ids
    assert set(agent.container_ids).isdisjoint(verifier.container_ids)
    assert agent.cleanup_complete and verifier.cleanup_complete

    assert not bad.scorecard.resolved
    assert bad.scorecard.status == "completed"
    assert not bad.scorecard.correctness.infrastructure_error
    assert bad.scorecard.verifier_results[-1].status.value == "failed"
    assert bad.scorecard.quality.ppa is None
    assert bad.manifest.runtime.cleanup is not None and bad.manifest.runtime.cleanup.complete
    _assert_no_new_owned(before)


def test_hidden_assets_never_enter_agent_or_model_visible_artifacts(
    toy_runs: tuple[Any, Any, tuple[set[str], set[str]]],
) -> None:
    good, _bad, _before = toy_runs
    hidden_root = (
        Path(__file__).parents[2]
        / "src"
        / "verigym"
        / "suites"
        / "toy_rtl"
        / "assets"
        / "counter_basic"
        / "hidden"
    )
    hidden_files = [path.read_bytes() for path in hidden_root.iterdir() if path.is_file()]
    candidate = good.run_dir / "candidate"
    assert not (candidate / "hidden").exists()
    assert not list(candidate.rglob("tb_counter.sv"))
    model_visible = [
        good.run_dir / "trace.jsonl",
        good.run_dir / "logs" / "agent.log",
        good.run_dir / "workspace_diff.patch",
        *(path for path in candidate.rglob("*") if path.is_file()),
    ]
    for path in model_visible:
        payload = path.read_bytes()
        assert b"tb_counter.sv" not in payload
        assert b"check_result.py" not in payload
        assert all(hidden not in payload for hidden in hidden_files)
    verifier_request = good.run_dir / "artifacts" / "compile_hidden" / "request.json"
    assert "hidden/tb_counter.sv" in verifier_request.read_text(encoding="utf-8")


def test_effective_security_controls_network_and_environment(
    docker_image: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _owned_resources()
    monkeypatch.setenv("VERIGYM_UNALLOWLISTED_VALUE", "must-not-enter")
    source = tmp_path / "source"
    source.mkdir()
    runtime = DockerRuntime(
        _docker_config(
            docker_image,
            memory_bytes=128 * 1024 * 1024,
            cpus=0.5,
            pids_limit=32,
            tmpfs_bytes=8 * 1024 * 1024,
            max_command_time_s=10,
        )
    )
    runtime.prepare("m7-effective-security")
    session = runtime.create_session(
        SessionSpec(source_dir=str(source), label="agent", max_output_bytes=32 * 1024)
    )
    script = """
import os, socket
status = {}
status['uid'] = os.getuid()
status['gid'] = os.getgid()
status['home'] = os.environ.get('HOME')
status['secret_present'] = 'VERIGYM_UNALLOWLISTED_VALUE' in os.environ
status['docker_socket'] = os.path.exists('/var/run/docker.sock')
try:
    open('/etc/verigym-rootfs-probe', 'w').close()
    status['rootfs_read_only'] = False
except OSError:
    status['rootfs_read_only'] = True
open('workspace-probe.txt', 'w').write('ok')
open('/tmp/tmpfs-probe.txt', 'w').write('ok')
status['workspace_writable'] = os.path.isfile('workspace-probe.txt')
status['tmp_writable'] = os.path.isfile('/tmp/tmpfs-probe.txt')
sock = socket.socket()
sock.settimeout(1.0)
try:
    sock.connect(('203.0.113.1', 9))
    status['network_blocked'] = False
except OSError:
    status['network_blocked'] = True
finally:
    sock.close()
values = {}
for line in open('/proc/self/status', encoding='utf-8'):
    if line.startswith(('CapEff:', 'NoNewPrivs:')):
        name, value = line.split(':', 1)
        values[name] = value.strip()
status['cap_eff'] = values.get('CapEff')
status['no_new_privileges'] = values.get('NoNewPrivs')
for name in sorted(status):
    print(f'{name}={status[name]}')
"""
    try:
        completed = session.execute(CommandSpec(argv=["python3", "-c", script], timeout_s=5))
        assert completed.exit_code == 0, completed.stderr
        status = dict(line.split("=", 1) for line in completed.stdout.splitlines())
        assert status == {
            "cap_eff": "0000000000000000",
            "docker_socket": "False",
            "gid": "10001",
            "home": "/workspace/.verigym_internal",
            "network_blocked": "True",
            "no_new_privileges": "1",
            "rootfs_read_only": "True",
            "secret_present": "False",
            "tmp_writable": "True",
            "uid": "10001",
            "workspace_writable": "True",
        }
        limits = completed.metadata["resource_limits"]
        assert limits["memory_bytes"] == 128 * 1024 * 1024
        assert limits["cpus"] == 0.5
        assert limits["pids_limit"] == 32
        assert limits["tmpfs_bytes"] == 8 * 1024 * 1024
    finally:
        session.close()
        runtime.close()
    assert runtime.descriptor.cleanup is not None and runtime.descriptor.cleanup.complete
    _assert_no_new_owned(before)


def test_real_timeout_oom_and_output_limit_are_structured_and_cleaned(
    docker_image: str,
    tmp_path: Path,
) -> None:
    before = _owned_resources()
    source = tmp_path / "source"
    source.mkdir()
    runtime = DockerRuntime(
        _docker_config(
            docker_image,
            memory_bytes=64 * 1024 * 1024,
            cpus=0.5,
            pids_limit=32,
            tmpfs_bytes=8 * 1024 * 1024,
            max_command_time_s=10,
        )
    )
    runtime.prepare("m7-resource-failures")
    session = runtime.create_session(
        SessionSpec(source_dir=str(source), label="agent", max_output_bytes=128)
    )
    try:
        timeout = session.execute(
            CommandSpec(
                argv=[
                    "python3",
                    "-c",
                    "import time; print('started', flush=True); time.sleep(10)",
                ],
                timeout_s=1,
            )
        )
        assert timeout.timed_out
        assert not timeout.oom_killed
        assert timeout.failure_reason == "timeout"
        assert timeout.failure_origin == "candidate_process"
        assert timeout.metadata["effective_timeout_s"] == 1
        assert "started" in timeout.stdout

        oom = session.execute(
            CommandSpec(
                argv=[
                    "python3",
                    "-c",
                    "payload=bytearray(128*1024*1024); print(len(payload))",
                ],
                timeout_s=10,
            )
        )
        assert oom.oom_killed
        assert not oom.timed_out
        assert oom.exit_code == 137
        assert oom.failure_reason == "out_of_memory"
        assert oom.failure_origin == "candidate_process"
        assert oom.metadata["oom_evidence"]["docker_state_oom_killed"] is True
        assert oom.metadata["memory_limit_bytes"] == 64 * 1024 * 1024

        bounded = session.execute(
            CommandSpec(argv=["python3", "-c", "print('x'*4096)"], timeout_s=5)
        )
        assert bounded.output_truncated
        assert len(bounded.stdout) == 128
    finally:
        session.close()
        runtime.close()
    descriptor = runtime.descriptor
    assert descriptor.cleanup is not None and descriptor.cleanup.complete
    assert all(record.cleanup_complete for record in descriptor.sessions)
    _assert_no_new_owned(before)


def test_exact_image_replay_is_verifier_only_and_model_free(
    toy_runs: tuple[Any, Any, tuple[set[str], set[str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, _bad, before = toy_runs
    original_manifest = (good.run_dir / "run_manifest.json").read_bytes()
    original_trace = (good.run_dir / "trace.jsonl").read_bytes()
    service = _service()

    def reject_model_lookup(_name: str) -> Any:
        raise AssertionError("Docker replay attempted a model lookup")

    monkeypatch.setattr(service.registries.models, "get", reject_model_lookup)
    replay = replay_run(good.run_dir, verify=True, service=service)
    assert replay.reverified_resolved is True
    assert (good.run_dir / "run_manifest.json").read_bytes() == original_manifest
    assert (good.run_dir / "trace.jsonl").read_bytes() == original_trace
    replay_descriptor = load_model(
        good.run_dir / "artifacts" / "replay-verification" / "runtime_descriptor.json",
        RuntimeDescriptor,
    )
    assert [record.role for record in replay_descriptor.sessions] == ["verifier"]
    assert replay_descriptor.image is not None
    assert good.manifest.runtime.image is not None
    assert (
        replay_descriptor.image.resolved_image_id == good.manifest.runtime.image.resolved_image_id
    )
    assert replay_descriptor.cleanup is not None and replay_descriptor.cleanup.complete
    _assert_no_new_owned(before)


def test_doctor_inspects_without_pull_build_or_secret_output(
    docker_image: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _owned_resources()
    monkeypatch.setenv("DOCTOR_API_TOKEN", "must-never-print")
    result = CliRunner().invoke(app, ["doctor", "--docker-image", docker_image])
    assert result.exit_code == 0, result.output
    assert "docker:daemon" in result.output
    assert "docker:image" in result.output
    assert "docker:iverilog" in result.output
    assert "12.0" in result.output
    assert "must-never-print" not in result.output
    _assert_no_new_owned(before)


def test_docker_sampling_remains_independent_and_homogeneous(
    docker_image: str,
    tmp_path: Path,
) -> None:
    before = _owned_resources()
    service = _service()
    result = service.run_samples(
        RunConfig(
            task_id="verilog-eval/Prob900_fixture_and",
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model="static-verilog-eval-fixture-mixed",
            suite_source=SuiteSourceConfig(
                source_root=SYNTHETIC_SOURCE,
                variant="v2-spec-to-rtl",
            ),
            runtime="docker",
            docker_config=_docker_config(docker_image),
            output=tmp_path / "samples",
        ),
        samples=2,
        pass_k=[1, 2],
    )
    assert result.report.canonical_valid
    assert result.report.resolved_count == 1
    assert result.report.candidate_failure_count == 1
    assert result.report.homogeneous
    image_ids: set[str] = set()
    for child in result.report.child_runs:
        manifest = load_model(
            result.group_dir / child.relative_path / "run_manifest.json", RunManifest
        )
        assert manifest.runtime.image is not None
        image_ids.add(manifest.runtime.image.resolved_image_id)
    assert len(image_ids) == 1
    regenerated = regenerate_sample_report(result.group_dir)
    assert regenerated.report == result.report
    _assert_no_new_owned(before)


@pytest.mark.skipif(
    VERILOG_EVAL_SOURCE is None,
    reason="set VERIGYM_VERILOG_EVAL_ROOT for optional external Docker conformance",
)
def test_optional_external_verilog_eval_reference_and_bad_candidate(
    docker_image: str,
    tmp_path: Path,
) -> None:
    assert VERILOG_EVAL_SOURCE is not None
    source_root = Path(VERILOG_EVAL_SOURCE).expanduser().resolve()
    source = SuiteSourceConfig(source_root=source_root, variant="v2-spec-to-rtl")
    before_source = hash_directory(source_root)
    before_owned = _owned_resources()
    service = _service()
    suite = service.registries.suites.get("verilog-eval").with_source(source)
    reference_id = suite.discover()[0].id
    _loaded_suite, task, assets = service.load_task(reference_id, source)
    reference = suite.reference_solution(task)
    assert reference is not None
    reference_model = StaticModelClient(
        name="m7-external-reference",
        responses=[reference.files["rtl/TopModule.sv"]],
    )
    bad_model = StaticModelClient(
        name="m7-external-bad",
        responses=["module TopModule; this is invalid endmodule\n"],
    )
    service.registries.models.register(reference_model)
    service.registries.models.register(bad_model)

    def run_model(name: str, output: Path) -> Any:
        return service.run(
            RunConfig(
                task_id=reference_id,
                mode=InteractionMode.CHAT,
                agent="single-turn",
                model=name,
                suite_source=source,
                runtime="docker",
                docker_config=_docker_config(docker_image),
                output=output,
            )
        )

    good = run_model(reference_model.descriptor.name, tmp_path / "reference")
    bad = run_model(bad_model.descriptor.name, tmp_path / "bad")
    assert good.scorecard.resolved
    assert not bad.scorecard.resolved
    assert bad.scorecard.status == "completed"
    assert good.manifest.runtime.image is not None
    assert good.manifest.runtime.image.iverilog_version is not None
    assert good.manifest.runtime.image.compatibility_status == ("canonical_or_reference_compatible")
    hidden_contents = [
        asset.content.encode("utf-8") for asset in assets.hidden_assets if asset.content is not None
    ]
    model_visible = [
        good.run_dir / "trace.jsonl",
        good.run_dir / "logs" / "agent.log",
        good.run_dir / "workspace_diff.patch",
        *(path for path in (good.run_dir / "candidate").rglob("*") if path.is_file()),
    ]
    for path in model_visible:
        payload = path.read_bytes()
        assert str(source_root).encode() not in payload
        assert all(hidden not in payload for hidden in hidden_contents)
    assert hash_directory(source_root) == before_source
    _assert_no_new_owned(before_owned)


def test_missing_image_is_infrastructure_failure_before_model_invocation(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    registries = build_registries(discover_external=False)
    model = CountingInvocationModel(calls)
    registries.models.register(model)
    service = VeriGym(registries)
    before = _owned_resources()
    with pytest.raises(DockerRuntimeError):
        service.run(
            RunConfig(
                task_id="toy-rtl/counter-basic",
                mode=InteractionMode.CHAT,
                agent="single-turn",
                model=model.descriptor.name,
                runtime="docker",
                docker_config=_docker_config("verigym/definitely-missing-m7-image:does-not-exist"),
                output=tmp_path,
            )
        )
    assert calls == []
    _assert_no_new_owned(before)
