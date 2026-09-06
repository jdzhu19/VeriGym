"""Behavioral gates for the single-task open-tool research continuation."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_hwe_pr1816_open_research as research


def test_receipt_tampering_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    value = {"repair_succeeded": True}
    value["receipt_hash"] = research.content_hash(value)
    path.write_text(json.dumps(value))
    assert research._receipt(path, "receipt_hash")["repair_succeeded"] is True
    value["repair_succeeded"] = False
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="hash mismatch"):
        research._receipt(path, "receipt_hash")


@pytest.mark.parametrize("qualified,consumed", [(False, False), (True, True)])
def test_canary_gate_precedes_runtime_and_provider_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qualified: bool, consumed: bool
) -> None:
    marker = tmp_path / "consumed.json"
    if consumed:
        marker.write_text("{}")
    monkeypatch.setattr(research, "CONSUMPTION", marker)

    def forbidden(**kwargs: object) -> None:
        pytest.fail("Canary gate must reject before Docker or provider preparation")

    monkeypatch.setattr(research.dind, "_ensure_inner_image", forbidden)
    with pytest.raises(ValueError, match="unqualified|consumed"):
        research.run_canary(None, None, {"both_routes_qualified": qualified}, "unused", "unused")


def test_qualification_environment_removes_and_restores_provider_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERIGYM_DEEPSEEK_API_KEY", "synthetic-secret")
    monkeypatch.setenv("DOCKER_HOST", "unix:///synthetic.sock")
    with research._without_provider_environment():
        assert "VERIGYM_DEEPSEEK_API_KEY" not in os.environ
        assert "DOCKER_HOST" not in os.environ
    assert os.environ["VERIGYM_DEEPSEEK_API_KEY"] == "synthetic-secret"
    assert os.environ["DOCKER_HOST"] == "unix:///synthetic.sock"


def test_runtime_keeps_open_commands_separate_from_workspace_and_network() -> None:
    lock = SimpleNamespace(
        image_id="sha256:" + "1" * 64,
        effective_user="1000:1000",
        binary_sha256={"rg": "2" * 64},
        agent_toolchain_id="verigym-open-rtl-tools-v1",
    )
    config = research.runtime_config(lock)
    command = config.command_image
    assert command is not None
    assert command.image == lock.image_id != config.image
    assert command.network_mode == config.network_mode == "none"
    assert command.execution_backend == "episode_container_exec_v1"
    assert command.required_image_labels["org.verigym.official-verifier-included"] == "false"


def test_runtime_probe_tempfiles_are_visible_to_nested_docker(tmp_path: Path) -> None:
    previous = tempfile.tempdir
    previous_env = os.environ.get("TMPDIR")
    scratch = tmp_path / "shared-scratch"
    with research._runtime_temporary_directory(scratch):
        with tempfile.TemporaryDirectory() as probe:
            assert Path(probe).is_relative_to(scratch)
        assert os.environ["TMPDIR"] == str(scratch)
    assert tempfile.tempdir == previous
    assert os.environ.get("TMPDIR") == previous_env


def test_open_test_bind_mount_uses_supported_docker_syntax_and_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = research.qualification
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> bytes:
        commands.append(command)
        return b"container-id"

    def run_result(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, b"TEST: debug_cause_haltreq ... PASS", b"")

    monkeypatch.setattr(module, "_run", run)
    monkeypatch.setattr(module, "_run_result", run_result)
    monkeypatch.setattr(
        module,
        "_inspect_container",
        lambda *a, **kw: {
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapAdd": [],
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
            },
            "Config": {"User": f"{os.getuid()}:{os.getgid()}"},
            "Mounts": [{"Source": str(tmp_path), "Destination": "/home/ibex", "RW": True}],
        },
    )
    result = module._run_open_public_test(
        docker_host="unix:///test.sock",
        image_id="sha256:" + "1" * 64,
        repository=tmp_path,
        role="reference",
    )
    create = commands[0]
    assert create[create.index("--mount") + 1] == f"type=bind,src={tmp_path},dst=/home/ibex"
    assert result["pass_sentinel"] is True
    assert any(
        command[-4:] == ["container", "rm", "--force", "container-id"] for command in commands
    )


def test_open_comparison_applies_reference_to_the_executed_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = research.qualification
    source = tmp_path / "source"
    repository = source / "workspaces/task/repository"
    (repository / "rtl").mkdir(parents=True)
    (repository / "rtl/core.sv").write_text("base")
    suite = SimpleNamespace(
        with_source=lambda config: suite,
        discover=lambda: [SimpleNamespace(native_id="task")],
        load_task=lambda reference: SimpleNamespace(id="task"),
        reference_solution=lambda task: SimpleNamespace(files={"repository/rtl/core.sv": "fixed"}),
    )
    monkeypatch.setattr(module, "HweBenchSuite", lambda **kwargs: suite)

    def run(**kwargs):
        workspace = kwargs["repository"]
        fixed = (workspace / "rtl/core.sv").read_text() == "fixed"
        assert not (workspace / "repository").exists()
        return {"returncode": 0 if fixed else 1, "pass_sentinel": fixed, "fail_sentinel": not fixed}

    monkeypatch.setattr(module, "_run_open_public_test", run)
    result = module._run_open_comparison(
        source=source,
        instance=SimpleNamespace(tb_script="synthetic test"),
        image_id="unused",
        docker_host="unused",
        root=tmp_path,
    )
    assert result["base_failed"] and result["reference_passed"]
