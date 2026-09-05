from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.open_toolchain_build_diagnostic import (
    load_v182_build_diagnostic_manifest,
)
from verigym.hwe.open_toolchain_local_builder import load_v178_local_builder_manifest

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v182_bounded_open_build as runner,
)

_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v182_bounded_open_build_diagnostic_v1.json"
)
_BUILDER_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v178_local_builder_v1.json"
)


def _successor() -> object:
    return load_v182_build_diagnostic_manifest(_MANIFEST)


def _result(
    *,
    returncode: int = 1,
    stdout: bytes = b"",
    stderr: bytes = b"",
    timed_out: bool = False,
    output_within_bound: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        output_within_bound=output_within_bound,
    )


def test_v182_uses_exact_v180_dockerfile_without_hwe_task_operations() -> None:
    manifest = _successor()
    context = Path("/bounded/context")
    command = runner._build_command(  # noqa: SLF001
        manifest,
        context=context,
        docker_host="unix:///bounded/docker.sock",
    )
    source = Path(runner.__file__).read_text(encoding="utf-8")

    assert command[0:4] == ["docker", "--host", "unix:///bounded/docker.sock", "build"]
    assert "--progress=plain" in command
    assert command[command.index("--network") + 1] == "none"
    assert "--pull=false" in command
    assert "--quiet" not in command
    assert command[command.index("--file") + 1].endswith(
        "docker/open-rtl-tools-hwe/Dockerfile.v180"
    )
    assert command[-1] == str(context)
    assert "inspect_offline_image_archive" not in source
    assert "official_verifier" not in source
    assert 'atomic_dump_json(root / "qualification-contract.json"' not in source


@pytest.mark.parametrize(
    ("result", "sensitive", "category"),
    [
        (_result(returncode=0), False, "success"),
        (_result(), True, "sensitive_output"),
        (_result(output_within_bound=False), False, "output_overflow"),
        (_result(timed_out=True), False, "timeout"),
        (_result(stderr=b"No space left on device"), False, "storage_exhausted"),
        (
            _result(stderr=b"g++: fatal error: Killed signal terminated program cc1plus"),
            False,
            "compiler_killed",
        ),
        (_result(stderr=b"src.cpp:8: error: bad expression"), False, "compiler_error"),
        (_result(stderr=b"collect2: error: ld returned 1 exit status"), False, "linker_error"),
        (_result(stderr=b"No rule to make target 'verilator_exe'"), False, "missing_make_target"),
        (_result(stderr=b"autoconf: command not found"), False, "missing_executable"),
        (
            _result(stderr=b"Cannot connect to the Docker daemon"),
            False,
            "docker_daemon_error",
        ),
        (_result(stderr=b"opaque failure"), False, "unknown_nonzero"),
    ],
)
def test_v182_build_diagnostic_uses_fixed_categories(
    result: SimpleNamespace, sensitive: bool, category: str
) -> None:
    assert runner._classify_build_result(result, sensitive=sensitive) == category  # noqa: SLF001


def test_v182_sensitive_output_is_not_hashed_or_persisted() -> None:
    manifest = _successor()
    secret = b"sensitive-value-123"
    result = _result(stderr=b"prefix " + secret)

    assert runner._contains_sensitive_output(  # noqa: SLF001
        result.stdout,
        result.stderr,
        active_sensitive_values=(secret,),
    )
    receipt = runner._diagnostic_receipt(  # noqa: SLF001
        manifest,
        result=result,
        category="sensitive_output",
        sensitive=True,
    )

    assert receipt["output_hashes_persisted"] is False
    assert receipt["stderr_sha256"] == runner._EMPTY_SHA256  # noqa: SLF001
    assert receipt["raw_output_persisted"] is False
    assert secret.decode() not in json.dumps(receipt)


def test_v182_cleanup_helper_is_networkless_and_least_capability() -> None:
    manifest = _successor()
    command = runner._cleanup_helper_command("helper", manifest)  # noqa: SLF001

    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--user") + 1] == "0:0"
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert [command[index + 1] for index, value in enumerate(command) if value == "--cap-add"] == [
        "CHOWN",
        "DAC_OVERRIDE",
        "FOWNER",
    ]
    assert command[command.index("--security-opt") + 1] == "no-new-privileges"
    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    assert mounts == [f"type=bind,src={runner.BACKING_PARENT},dst=/campaign"]
    assert command[command.index("--entrypoint") + 1] == "/bin/sh"
    assert command[command.index("--entrypoint") + 2] == manifest.accepted_open_tools_image_id


def test_v182_cleanup_controller_failure_returns_a_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_cleanup(*args: object, **kwargs: object) -> object:
        raise ConfigurationError("not persisted")

    monkeypatch.setattr(runner, "_cleanup_impl", fail_cleanup)

    receipt = runner._cleanup(  # noqa: SLF001
        _successor(), scratch=tmp_path / "absent", active_sensitive_values=()
    )

    assert receipt["category"] == "cleanup_controller_error"
    assert receipt["cleanup_complete"] is False
    assert receipt["raw_exception_persisted"] is False


def test_v182_execute_always_writes_terminal_report_after_controller_and_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _successor()
    builder = load_v178_local_builder_manifest(_BUILDER_MANIFEST)
    root = tmp_path / "result"
    scratch = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    scratch.mkdir(mode=0o700)
    monkeypatch.setattr(runner, "_headroom_receipt", lambda: {"capacity_satisfied": True})

    def fail_transfer(*args: object, **kwargs: object) -> object:
        raise ConfigurationError("controlled failure")

    monkeypatch.setattr(runner, "_save_transfer_inputs", fail_transfer)
    monkeypatch.setattr(
        runner,
        "_cleanup",
        lambda *args, **kwargs: {
            "cleanup_complete": False,
            "category": "cleanup_helper_failed",
            "cleanup_hash": "1" * 64,
        },
    )

    report = runner._execute(  # noqa: SLF001
        Namespace(post_merge_main_run_id=manifest.predecessor_audit_post_merge_main_run_id + 1),
        successor=manifest,
        builder=builder,
        root=root,
        scratch=scratch,
        source_commit="2" * 40,
        active_sensitive_values=(),
        archive_receipt={"archive_structure_passed": True},
    )

    assert report["status"] == "stopped_cleanup_incomplete"
    assert report["diagnostic_category"] == "controller_error"
    assert report["raw_exception_persisted"] is False
    assert (root / "build-diagnostic.json").is_file()
    assert (root / "cleanup.json").is_file()
    assert (root / "zero-provider-report.json").is_file()
    assert stat_mode(root) == 0o700
    assert all(stat_mode(path) == 0o600 for path in root.iterdir())


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


def test_v182_execution_boundary_rejects_provider_and_old_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _successor()
    for name in runner.ZERO_PROVIDER_CONFIGURATION_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv(runner.SANITIZED_CHILD_ENV, "1")
    monkeypatch.setattr(runner.os, "getuid", lambda: 1004)
    monkeypatch.setattr(runner.os, "getgid", lambda: 100)
    with pytest.raises(ConfigurationError, match="new post-merge"):
        runner._require_execution_boundary(  # noqa: SLF001
            Namespace(post_merge_main_run_id=manifest.predecessor_audit_post_merge_main_run_id),
            manifest,
        )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "never-used")
    with pytest.raises(ConfigurationError, match="provider configuration"):
        runner._require_execution_boundary(  # noqa: SLF001
            Namespace(post_merge_main_run_id=manifest.predecessor_audit_post_merge_main_run_id + 1),
            manifest,
        )


def test_v182_launcher_removes_provider_and_docker_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import launch_hwe_deepseek_harness_v182_bounded_open_build as launcher

    captured: dict[str, list[str]] = {}
    monkeypatch.setenv(launcher.OPT_IN_ENV, "1")
    monkeypatch.delenv(launcher.SANITIZED_CHILD_ENV, raising=False)
    monkeypatch.setattr(
        launcher.os,
        "execvp",
        lambda executable, arguments: captured.update(
            {"executable": [executable], "arguments": arguments}
        ),
    )
    monkeypatch.setattr(launcher.sys, "argv", ["launcher", "--post-merge-main-run-id", "1"])

    with pytest.raises(AssertionError, match="unexpectedly"):
        launcher.main()

    arguments = captured["arguments"]
    assert captured["executable"] == ["env"]
    assert f"{launcher.SANITIZED_CHILD_ENV}=1" in arguments
    assert "DOCKER_HOST" in arguments
    assert "DOCKER_CONTEXT" in arguments
    assert str(launcher.RUNNER) in arguments


def test_v182_control_commands_do_not_use_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner._run_control(["docker", "version"], timeout=1)  # noqa: SLF001

    assert "shell" not in observed or observed["shell"] is False
