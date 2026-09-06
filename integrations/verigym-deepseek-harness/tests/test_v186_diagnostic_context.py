from __future__ import annotations

import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.open_toolchain_build_diagnostic import load_v182_build_diagnostic_manifest
from verigym.hwe.open_toolchain_diagnostic_context import load_v186_diagnostic_context_manifest
from verigym.hwe.open_toolchain_local_builder import load_v178_local_builder_manifest
from verigym.hwe.open_toolchain_missing_command import load_v184_missing_command_manifest

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from scripts import materialize_hwe_deepseek_harness_v182_bounded_open_build as v182  # noqa: E402
from scripts import materialize_hwe_deepseek_harness_v184_missing_command as v184  # noqa: E402
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v186_diagnostic_context as runner,
)

_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v186_diagnostic_context_refinement_v1.json"
)
_V184_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v184_missing_command_disambiguation_v1.json"
)
_V182_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v182_bounded_open_build_diagnostic_v1.json"
)
_BUILDER = _ROOT / "configs/training/qwen35_hwe_deepseek_harness_v178_local_builder_v1.json"


def _successor() -> object:
    return load_v186_diagnostic_context_manifest(_MANIFEST)


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
    return {command: command != missing for command in manifest.command_dictionary}


@pytest.mark.parametrize(
    ("stderr", "missing", "availability_missing", "context", "category"),
    [
        (
            b"#9 /bin/sh: 1: help2man: not found\n",
            "help2man",
            "help2man",
            "posix_sh_command_not_found",
            "missing_builder_prerequisite",
        ),
        (
            b"/bin/bash: line 2: ccache: command not found\n",
            "ccache",
            "ccache",
            "bash_command_not_found",
            "missing_builder_prerequisite",
        ),
        (
            b"make[2]: ccache: not found\n",
            "ccache",
            "ccache",
            "make_command_not_found",
            "missing_builder_prerequisite",
        ),
        (
            b"/bin/sh: 1: verilator_bin_dbg: not found\n",
            "verilator_bin_dbg",
            "verilator_bin_dbg",
            "posix_sh_command_not_found",
            "generated_binary_absent_after_prior_build_failure",
        ),
        (
            b"/bin/sh: 1: python3: not found\n",
            "python3",
            "python3",
            "posix_sh_command_not_found",
            "dockerfile_injected_command_absent",
        ),
        (
            b"/bin/sh: 1: make: not found\n",
            "make",
            None,
            "posix_sh_command_not_found",
            "allowlisted_command_present_but_not_found",
        ),
        (
            b"/bin/sh: 1: private-tool: not found\n",
            None,
            None,
            "posix_sh_command_not_found",
            "unknown_closed_dictionary_command",
        ),
        (
            b"help2man: not found\n",
            None,
            None,
            "unscoped_colon_not_found",
            "unscoped_colon_not_found",
        ),
        (
            b"/bin/sh: 1: help2man: not found\nccache: not found\n",
            None,
            None,
            "mixed",
            "mixed_diagnostic_contexts",
        ),
        (
            b"/bin/sh: 1: help2man: not found\n/bin/sh: 2: ccache: not found\n",
            None,
            None,
            "posix_sh_command_not_found",
            "multiple_closed_dictionary_commands",
        ),
    ],
)
def test_v186_classifies_only_closed_dictionary_commands_in_fixed_contexts(
    stderr: bytes,
    missing: str | None,
    availability_missing: str | None,
    context: str,
    category: str,
) -> None:
    manifest = _successor()
    resolved = runner._classify_build_result(  # noqa: SLF001
        _result(stderr=stderr),
        sensitive=False,
        successor=manifest,
        availability=_availability(missing=availability_missing),
    )

    assert resolved["category"] == category
    assert resolved["missing_command"] == missing
    assert resolved["diagnostic_context"] == context


@pytest.mark.parametrize(
    ("result", "sensitive", "category"),
    [
        (_result(returncode=0), False, "success"),
        (_result(), True, "sensitive_output"),
        (_result(output_within_bound=False), False, "output_overflow"),
        (_result(timed_out=True), False, "timeout"),
        (_result(stderr=b"No space left on device"), False, "storage_exhausted"),
        (
            _result(stderr=b"fatal error: Killed signal terminated program cc1plus"),
            False,
            "compiler_killed",
        ),
        (
            _result(stderr=b"No rule to make target 'verilator_exe'"),
            False,
            "missing_make_target",
        ),
        (_result(stderr=b"ordinary compiler error"), False, "no_command_context_marker"),
    ],
)
def test_v186_preserves_bounded_failure_precedence(
    result: SimpleNamespace,
    sensitive: bool,
    category: str,
) -> None:
    resolved = runner._classify_build_result(  # noqa: SLF001
        result,
        sensitive=sensitive,
        successor=_successor(),
        availability=_availability(),
    )

    assert resolved["category"] == category
    assert resolved["missing_command"] is None


def test_v186_repeated_same_contextual_command_is_one_exact_identity() -> None:
    result = _result(
        stderr=(b"/bin/sh: 1: help2man: not found\n/bin/sh: 2: help2man: command not found\n")
    )

    resolved = runner._classify_build_result(  # noqa: SLF001
        result,
        sensitive=False,
        successor=_successor(),
        availability=_availability(missing="help2man"),
    )

    assert resolved["category"] == "missing_builder_prerequisite"
    assert resolved["missing_command"] == "help2man"
    assert resolved["marker_count"] == 2
    assert resolved["contextual_marker_count"] == 2
    assert resolved["distinct_dictionary_count"] == 1


def test_v186_unknown_command_text_is_never_serialized() -> None:
    successor = _successor()
    predecessor = load_v182_build_diagnostic_manifest(_V182_MANIFEST)
    private_name = b"private-tool"
    result = _result(stderr=b"/bin/sh: 1: " + private_name + b": not found\n")
    resolution = runner._classify_build_result(  # noqa: SLF001
        result,
        sensitive=False,
        successor=successor,
        availability=_availability(),
    )
    receipt = runner._diagnostic_receipt(  # noqa: SLF001
        successor,
        predecessor=predecessor,
        result=result,
        category=resolution["category"],
        sensitive=False,
        resolution=resolution,
    )

    serialized = json.dumps(receipt)
    assert receipt["category"] == "unknown_closed_dictionary_command"
    assert receipt["missing_command"] is None
    assert receipt["arbitrary_token_persisted"] is False
    assert receipt["arbitrary_token_hash_persisted"] is False
    assert private_name.decode() not in serialized


def test_v186_receipt_never_persists_sensitive_or_arbitrary_output() -> None:
    successor = _successor()
    predecessor = load_v182_build_diagnostic_manifest(_V182_MANIFEST)
    secret = b"sensitive-value-123"
    receipt = runner._diagnostic_receipt(  # noqa: SLF001
        successor,
        predecessor=predecessor,
        result=_result(stderr=secret),
        category="sensitive_output",
        sensitive=True,
        resolution={**runner._base_resolution(), "category": "sensitive_output"},  # noqa: SLF001
    )

    serialized = json.dumps(receipt)
    assert receipt["output_hashes_persisted"] is False
    assert receipt["stderr_sha256"] == runner._EMPTY_SHA256  # noqa: SLF001
    assert receipt["raw_matching_line_persisted"] is False
    assert receipt["arbitrary_token_hash_persisted"] is False
    assert secret.decode() not in serialized


def test_v186_receipt_rejects_command_category_mismatch() -> None:
    successor = _successor()
    predecessor = load_v182_build_diagnostic_manifest(_V182_MANIFEST)

    with pytest.raises(ConfigurationError, match="disagree"):
        runner._diagnostic_receipt(  # noqa: SLF001
            successor,
            predecessor=predecessor,
            result=_result(stderr=b"not retained"),
            category="missing_builder_prerequisite",
            sensitive=False,
            resolution=runner._base_resolution(),  # noqa: SLF001
        )


def test_v186_execute_always_writes_terminal_report_after_controller_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    successor = _successor()
    predecessor = load_v182_build_diagnostic_manifest(_V182_MANIFEST)
    inherited = load_v184_missing_command_manifest(_V184_MANIFEST)
    proxy = inherited.model_copy(update={"command_allowlist": successor.command_dictionary})
    runtime = v184._runtime_manifest(proxy, predecessor)  # noqa: SLF001
    builder = load_v178_local_builder_manifest(_BUILDER)
    root = tmp_path / "result"
    scratch = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    scratch.mkdir(mode=0o700)

    monkeypatch.setattr(runner, "_headroom_receipt", lambda manifest: {"receipt_hash": "1" * 64})

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
        probe_proxy=proxy,
    )

    assert report["status"] == "stopped_controller_error"
    assert report["diagnostic_category"] == "controller_error"
    assert report["provider_calls"] == 0
    assert (root / "diagnostic-context.json").is_file()
    assert (root / "cleanup.json").is_file()
    assert (root / "zero-provider-report.json").is_file()
    assert os.stat(root).st_mode & 0o777 == 0o700
    assert all(os.stat(path).st_mode & 0o777 == 0o600 for path in root.iterdir())


def test_v186_execution_boundary_rejects_provider_and_old_main(
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


def test_v186_launcher_removes_provider_and_docker_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import launch_hwe_deepseek_harness_v186_diagnostic_context as launcher

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


def test_v186_runtime_patch_restores_historical_modules() -> None:
    before_v184 = (v184.IDENTITY, v184.OUTPUT_ROOT, v184.OWNER)
    before_v182 = (v182.IDENTITY, v182.OUTPUT_ROOT, v182.OWNER)
    with runner._patched_inherited_runtime():  # noqa: SLF001
        assert v184.IDENTITY == runner.IDENTITY
        assert v184.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert v184.OWNER == runner.OWNER
        assert v182.IDENTITY == runner.IDENTITY
        assert v182.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert v182.OWNER == runner.OWNER
    assert (v184.IDENTITY, v184.OUTPUT_ROOT, v184.OWNER) == before_v184
    assert (v182.IDENTITY, v182.OUTPUT_ROOT, v182.OWNER) == before_v182


def test_v186_headroom_uses_manifest_bound_split_filesystem_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _successor()
    usage = SimpleNamespace(total=100, used=1, free=manifest.control_root_min_available_bytes)
    data2_usage = SimpleNamespace(total=100, used=1, free=manifest.data2_min_available_bytes)
    monkeypatch.setattr(
        runner.shutil,
        "disk_usage",
        lambda path: usage if path == "/" else data2_usage,
    )
    monkeypatch.setattr(runner.os, "statvfs", lambda path: SimpleNamespace(f_bavail=100))

    receipt = runner._headroom_receipt(manifest)  # noqa: SLF001

    assert receipt["capacity_satisfied"] is True
    assert receipt["all_bulk_storage_on_data2"] is True
    assert receipt["control_root_min_available_bytes"] == 9 * 1024**3


def test_v186_headroom_fails_below_either_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _successor()
    usage = SimpleNamespace(
        total=100,
        used=1,
        free=manifest.control_root_min_available_bytes - 1,
    )
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda path: usage)
    monkeypatch.setattr(runner.os, "statvfs", lambda path: SimpleNamespace(f_bavail=100))

    with pytest.raises(ConfigurationError, match="headroom"):
        runner._headroom_receipt(manifest)  # noqa: SLF001
