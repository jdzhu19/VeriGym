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
from verigym.hwe.open_toolchain_build_diagnostic import load_v182_build_diagnostic_manifest
from verigym.hwe.open_toolchain_local_builder import load_v178_local_builder_manifest
from verigym.hwe.open_toolchain_missing_command import load_v184_missing_command_manifest

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from scripts import materialize_hwe_deepseek_harness_v182_bounded_open_build as v182  # noqa: E402
from scripts import materialize_hwe_deepseek_harness_v184_missing_command as runner  # noqa: E402

_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v184_missing_command_disambiguation_v1.json"
)
_PREDECESSOR = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v182_bounded_open_build_diagnostic_v1.json"
)
_BUILDER = _ROOT / "configs/training/qwen35_hwe_deepseek_harness_v178_local_builder_v1.json"


def _successor() -> object:
    return load_v184_missing_command_manifest(_MANIFEST)


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


def _availability(*, missing: str | None = None) -> dict[str, bool]:
    manifest = _successor()
    return {command: command != missing for command in manifest.command_allowlist}


@pytest.mark.parametrize(
    ("result", "sensitive", "missing", "availability_missing", "category"),
    [
        (_result(returncode=0), False, None, None, "success"),
        (_result(), True, None, None, "sensitive_output"),
        (_result(output_within_bound=False), False, None, None, "output_overflow"),
        (_result(timed_out=True), False, None, None, "timeout"),
        (_result(stderr=b"No space left on device"), False, None, None, "storage_exhausted"),
        (
            _result(stderr=b"fatal error: Killed signal terminated program cc1plus"),
            False,
            None,
            None,
            "compiler_killed",
        ),
        (
            _result(stderr=b"No rule to make target 'verilator_exe'"),
            False,
            None,
            None,
            "missing_make_target",
        ),
        (
            _result(stderr=b"#1 /bin/sh: 1: help2man: not found\n"),
            False,
            "help2man",
            "help2man",
            "missing_builder_prerequisite",
        ),
        (
            _result(stderr=b"/bin/sh: 1: verilator_bin: not found\n"),
            False,
            "verilator_bin",
            "verilator_bin",
            "generated_binary_absent_after_prior_build_failure",
        ),
        (
            _result(stderr=b"/bin/sh: 1: python3: not found\n"),
            False,
            "python3",
            "python3",
            "dockerfile_injected_command_absent",
        ),
        (
            _result(stderr=b"/bin/sh: 1: make: not found\n"),
            False,
            "make",
            None,
            "allowlisted_command_present_but_not_found",
        ),
        (
            _result(stderr=b"/bin/sh: 1: private-tool: not found\n"),
            False,
            None,
            None,
            "unknown_missing_executable",
        ),
        (
            _result(stderr=b"make: not found\nhelp2man: not found\n"),
            False,
            None,
            None,
            "multiple_missing_executables",
        ),
        (
            _result(stderr=b"ordinary compiler error"),
            False,
            None,
            None,
            "no_missing_executable_marker",
        ),
    ],
)
def test_v184_disambiguates_only_allowlisted_commands(
    result: SimpleNamespace,
    sensitive: bool,
    missing: str | None,
    availability_missing: str | None,
    category: str,
) -> None:
    manifest = _successor()
    resolved = runner._classify_build_result(  # noqa: SLF001
        result,
        sensitive=sensitive,
        successor=manifest,
        availability=_availability(missing=availability_missing),
    )

    assert resolved["category"] == category
    assert resolved["missing_command"] == missing


def test_v184_repeated_same_allowlisted_command_is_one_exact_identity() -> None:
    manifest = _successor()
    result = _result(stderr=b"help2man: not found\nhelp2man: command not found\n")

    resolved = runner._classify_build_result(  # noqa: SLF001
        result,
        sensitive=False,
        successor=manifest,
        availability=_availability(missing="help2man"),
    )

    assert resolved["category"] == "missing_builder_prerequisite"
    assert resolved["missing_command"] == "help2man"
    assert resolved["marker_count"] == 2
    assert resolved["distinct_allowlisted_count"] == 1


def test_v184_diagnostic_never_persists_sensitive_or_arbitrary_output() -> None:
    successor = _successor()
    predecessor = load_v182_build_diagnostic_manifest(_PREDECESSOR)
    secret = b"sensitive-value-123"
    receipt = runner._diagnostic_receipt(  # noqa: SLF001
        successor,
        predecessor=predecessor,
        result=_result(stderr=secret),
        category="sensitive_output",
        sensitive=True,
        missing_command=None,
        marker_count=0,
        distinct_allowlisted_count=0,
        unknown_marker_present=False,
        command_available_before_build=None,
    )

    serialized = json.dumps(receipt)
    assert receipt["output_hashes_persisted"] is False
    assert receipt["stderr_sha256"] == runner._EMPTY_SHA256  # noqa: SLF001
    assert receipt["raw_matching_line_persisted"] is False
    assert secret.decode() not in serialized


def test_v184_diagnostic_rejects_command_category_mismatch() -> None:
    successor = _successor()
    predecessor = load_v182_build_diagnostic_manifest(_PREDECESSOR)

    with pytest.raises(ConfigurationError, match="disagree"):
        runner._diagnostic_receipt(  # noqa: SLF001
            successor,
            predecessor=predecessor,
            result=_result(stderr=b"not retained"),
            category="missing_builder_prerequisite",
            sensitive=False,
            missing_command=None,
            marker_count=1,
            distinct_allowlisted_count=1,
            unknown_marker_present=False,
            command_available_before_build=False,
        )


def test_v184_command_probe_create_is_networkless_readonly_nonroot_and_mountless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = _successor()
    predecessor = load_v182_build_diagnostic_manifest(_PREDECESSOR)
    runtime = runner._runtime_manifest(successor, predecessor)  # noqa: SLF001
    observed: list[list[str]] = []
    bits = b"1" * len(successor.command_allowlist) + b"\n"

    def fake_control(
        command: list[str], *, timeout: int, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        observed.append(command)
        stdout = b"container-id\n" if "create" in command else b""
        return subprocess.CompletedProcess(command, 0, stdout, b"")

    monkeypatch.setattr(v182, "_run_control", fake_control)
    monkeypatch.setattr(runner, "_inspect_command_probe", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        runner.v176,
        "_run_bounded_process",
        lambda *args, **kwargs: _result(returncode=0, stdout=bits),
    )
    monkeypatch.setattr(v182, "_contains_sensitive_output", lambda *args, **kwargs: False)

    availability, receipt = runner._probe_builder_commands(  # noqa: SLF001
        successor,
        runtime=runtime,
        docker_host="unix:///bounded/docker.sock",
        active_sensitive_values=(),
    )

    create = observed[0]
    assert create[create.index("--network") + 1] == "none"
    assert "--read-only" in create
    assert create[create.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert create[create.index("--cap-drop") + 1] == "ALL"
    assert "--mount" not in create and "--volume" not in create
    assert all(availability.values())
    assert receipt["raw_probe_output_persisted"] is False


def test_v184_execute_always_writes_terminal_report_after_controller_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    successor = _successor()
    predecessor = load_v182_build_diagnostic_manifest(_PREDECESSOR)
    runtime = runner._runtime_manifest(successor, predecessor)  # noqa: SLF001
    builder = load_v178_local_builder_manifest(_BUILDER)
    root = tmp_path / "result"
    scratch = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    scratch.mkdir(mode=0o700)

    monkeypatch.setattr(v182, "_headroom_receipt", lambda: {"receipt_hash": "1" * 64})

    def fail_transfer(*args: object, **kwargs: object) -> object:
        raise ConfigurationError("controlled")

    monkeypatch.setattr(v182, "_save_transfer_inputs", fail_transfer)
    monkeypatch.setattr(
        v182,
        "_cleanup",
        lambda *args, **kwargs: {
            "format_id": "old",
            "identity": "old",
            "category": "completed",
            "cleanup_complete": True,
            "cleanup_hash": "2" * 64,
        },
    )

    report = runner._execute(  # noqa: SLF001
        Namespace(post_merge_main_run_id=successor.predecessor_audit_post_merge_main_run_id + 1),
        successor=successor,
        predecessor=predecessor,
        runtime=runtime,
        builder=builder,
        root=root,
        scratch=scratch,
        source_commit="3" * 40,
        active_sensitive_values=(),
        archive_receipt={"archive_structure_passed": True},
    )

    assert report["status"] == "stopped_controller_error"
    assert report["diagnostic_category"] == "controller_error"
    assert report["provider_calls"] == 0
    assert (root / "missing-command-diagnostic.json").is_file()
    assert (root / "cleanup.json").is_file()
    assert (root / "zero-provider-report.json").is_file()
    assert os.stat(root).st_mode & 0o777 == 0o700
    assert all(os.stat(path).st_mode & 0o777 == 0o600 for path in root.iterdir())


def test_v184_execution_boundary_rejects_provider_and_old_main(
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


def test_v184_launcher_removes_provider_and_docker_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import launch_hwe_deepseek_harness_v184_missing_command as launcher

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

    assert captured["executable"] == ["env"]
    assert f"{launcher.SANITIZED_CHILD_ENV}=1" in captured["arguments"]
    assert "DOCKER_HOST" in captured["arguments"]
    assert "DOCKER_CONTEXT" in captured["arguments"]
    assert str(launcher.RUNNER) in captured["arguments"]


def test_v184_runtime_patch_restores_historical_module() -> None:
    before = (v182.IDENTITY, v182.OUTPUT_ROOT, v182.OWNER)
    with runner._patched_v182_runtime():  # noqa: SLF001
        assert v182.IDENTITY == runner.IDENTITY
        assert v182.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert v182.OWNER == runner.OWNER
    assert (v182.IDENTITY, v182.OUTPUT_ROOT, v182.OWNER) == before
