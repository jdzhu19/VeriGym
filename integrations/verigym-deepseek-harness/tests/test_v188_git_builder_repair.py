from __future__ import annotations

import json
import os
import shutil
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.open_toolchain_git_builder_repair import (
    load_v188_git_builder_repair_manifest,
)

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from scripts import (  # noqa: E402
    launch_hwe_deepseek_harness_v188_git_builder_repair as launcher,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v172_open_toolchain as v172,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v178_local_builder as v178,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v182_bounded_open_build as v182,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v184_missing_command as v184,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v186_diagnostic_context as v186,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v188_git_builder_repair as runner,
)

_MANIFEST = _ROOT / ("configs/training/qwen35_hwe_deepseek_harness_v188_git_builder_repair_v1.json")


def _successor() -> object:
    return load_v188_git_builder_repair_manifest(_MANIFEST)


def _result(
    *,
    returncode: int = 0,
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


def test_v188_completed_git_archive_passes_exact_offline_validation() -> None:
    receipt = runner._git_package_archive_receipt(_successor())  # noqa: SLF001

    assert receipt["package_count"] == 6
    assert receipt["download_command_count"] == 1
    assert receipt["registry_accessed"] is False
    assert receipt["hwe_image_used"] is False
    assert receipt["partial_input_present"] is False


def test_v188_package_archive_hash_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = _successor()
    original = runner._hash_file  # noqa: SLF001

    def changed(path: Path) -> str:
        if path == Path(successor.git_package_archive_path):
            return "0" * 64
        return original(path)

    monkeypatch.setattr(runner, "_hash_file", changed)
    with pytest.raises(ConfigurationError, match="archive identity"):
        runner._git_package_archive_receipt(successor)  # noqa: SLF001


def test_v188_builder_build_command_is_offline_and_exact() -> None:
    successor = _successor()
    command = runner._builder_build_command(  # noqa: SLF001
        successor,
        context=Path("/data2/context"),
        docker_host="unix:///data2/docker.sock",
    )

    assert command[:4] == ["docker", "--host", "unix:///data2/docker.sock", "build"]
    assert command[command.index("--network") + 1] == "none"
    assert "--pull=false" in command
    assert successor.derived_builder_tag in command
    assert str(_ROOT / successor.builder_repair_dockerfile) in command
    assert not any("http://" in item or "https://" in item for item in command)


def test_v188_exact_final_dockerfile_uses_the_repaired_builder_only() -> None:
    successor = _successor()
    text = (_ROOT / successor.exact_final_dockerfile).read_text(encoding="utf-8")
    repair = (_ROOT / successor.builder_repair_dockerfile).read_text(encoding="utf-8")

    assert f"FROM {successor.final_builder_tag} AS verilator-builder" in text
    assert "FROM verigym/open-rtl-tools:v178-builder" in repair
    assert "dpkg --install /inputs/git/*.deb" in repair
    assert "RUN curl" not in repair
    assert "RUN wget" not in repair
    assert "apt-get" not in repair


def test_v188_command_delta_allows_only_git_to_change() -> None:
    before = json.loads(
        (
            runner.V186_RESULT_ROOT / "command-dictionary-probe.json"  # noqa: SLF001
        ).read_text(encoding="utf-8")
    )["command_availability"]
    after = dict(before)
    after["git"] = True

    runner._validate_command_delta(after)  # noqa: SLF001
    after["ccache"] = True
    with pytest.raises(ConfigurationError, match="more than"):
        runner._validate_command_delta(after)  # noqa: SLF001


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (_result(returncode=1, stderr=b"ordinary failure"), "builder_repair_failed"),
        (_result(returncode=1, stderr=b"No space left on device"), "storage_exhausted"),
    ],
)
def test_v188_builder_failure_receipt_never_persists_raw_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    result: SimpleNamespace,
    expected: str,
) -> None:
    successor = _successor()
    builder = SimpleNamespace(local_builder_image_id=successor.base_builder_image_id)
    monkeypatch.setattr(runner.v176, "_run_bounded_process", lambda *args, **kwargs: result)
    monkeypatch.setattr(runner.v182, "_contains_sensitive_output", lambda *args, **kwargs: False)
    image_id, receipt = runner._build_git_builder(  # noqa: SLF001
        successor,
        builder=builder,
        scratch=tmp_path,
        docker_host="unix:///unused.sock",
        active_sensitive_values=(),
    )
    assert image_id is None
    assert receipt["category"] == expected
    assert receipt["raw_output_persisted"] is False


def test_v188_headroom_uses_frozen_nine_and_fifty_gibibyte_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = _successor()
    values = iter(
        [
            SimpleNamespace(free=successor.control_root_min_available_bytes),
            SimpleNamespace(free=successor.data2_min_available_bytes),
        ]
    )
    monkeypatch.setattr(shutil, "disk_usage", lambda path: next(values))
    monkeypatch.setattr(os, "statvfs", lambda path: SimpleNamespace(f_bavail=1))

    receipt = runner._headroom_receipt(successor)  # noqa: SLF001
    assert receipt["capacity_satisfied"] is True
    assert receipt["all_bulk_storage_on_data2"] is True


def test_v188_headroom_fails_below_the_control_root_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = _successor()
    values = iter(
        [
            SimpleNamespace(free=successor.control_root_min_available_bytes - 1),
            SimpleNamespace(free=successor.data2_min_available_bytes),
        ]
    )
    monkeypatch.setattr(shutil, "disk_usage", lambda path: next(values))
    monkeypatch.setattr(os, "statvfs", lambda path: SimpleNamespace(f_bavail=1))

    with pytest.raises(ConfigurationError, match="headroom"):
        runner._headroom_receipt(successor)  # noqa: SLF001


def test_v188_runtime_patch_restores_all_inherited_bindings() -> None:
    modules = (v172, v178, v182, v184, v186)
    before = [(module.OWNER, module.IDENTITY) for module in modules]

    with runner._patched_inherited_runtime():  # noqa: SLF001
        assert all(module.OWNER == runner.OWNER for module in modules)
        assert v182.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert v182.SCRATCH_ROOT == runner.SCRATCH_ROOT
        assert v182.DATA_BACKING == runner.DATA_BACKING
        assert v182.SOCKET_BACKING == runner.SOCKET_BACKING

    assert [(module.OWNER, module.IDENTITY) for module in modules] == before


def test_v188_boundary_refuses_provider_or_stale_main_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = _successor()
    arguments = Namespace(
        manifest=_MANIFEST,
        output=runner.OUTPUT_ROOT,
        post_merge_main_run_id=successor.predecessor_audit_post_merge_main_run_id,
    )
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv(runner.SANITIZED_CHILD_ENV, "1")
    for name in runner.ZERO_PROVIDER_CONFIGURATION_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(runner.os, "getuid", lambda: 1004)
    monkeypatch.setattr(runner.os, "getgid", lambda: 100)

    with pytest.raises(ConfigurationError, match="new post-merge"):
        runner._require_execution_boundary(arguments, successor)  # noqa: SLF001


def test_v188_launcher_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(launcher.OPT_IN_ENV, raising=False)
    with pytest.raises(ConfigurationError, match="required"):
        launcher.main()


def test_v188_launcher_unsets_provider_and_docker_endpoint_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    monkeypatch.setenv(launcher.OPT_IN_ENV, "1")
    monkeypatch.delenv(launcher.SANITIZED_CHILD_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["launcher", "--post-merge-main-run-id", "34002140334"])

    def capture(_file: str, arguments: list[str]) -> None:
        captured.extend(arguments)
        raise RuntimeError("captured")

    monkeypatch.setattr(os, "execvp", capture)
    with pytest.raises(RuntimeError, match="captured"):
        launcher.main()

    assert "-u" in captured
    assert "DOCKER_HOST" in captured
    assert "DOCKER_CONTEXT" in captured
    assert f"{launcher.SANITIZED_CHILD_ENV}=1" in captured


def test_v188_saved_image_archive_rejects_role_alias(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar"
    archive.write_bytes(b"not a tar")
    with pytest.raises(ConfigurationError, match="malformed"):
        runner._validate_saved_image_archive(  # noqa: SLF001
            archive,
            image_id="sha256:" + "1" * 64,
            tag="verigym/open-rtl-tools:test",
        )


def test_v188_v2_scan_locks_git_without_loading_the_official_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = _successor()
    final_id = "sha256:" + "8" * 64
    derived_id = "sha256:" + "9" * 64
    derived = {"RootFS": {"Layers": ["sha256:base", "sha256:git"]}}
    final = {
        "Id": final_id,
        "Os": "linux",
        "Architecture": "amd64",
        "RootFS": {"Layers": ["sha256:base", "sha256:git", "sha256:runtime"]},
        "Config": {
            "User": f"{os.getuid()}:{os.getgid()}",
            "WorkingDir": "/workspace/repository",
            "Cmd": ["tail", "-f", "/dev/null"],
            "Entrypoint": None,
            "ExposedPorts": None,
            "Volumes": None,
            "Env": ["PATH=/tools"],
            "Labels": {
                "org.verigym.agent-toolchain-id": successor.agent_toolchain_id,
                "org.verigym.role": "agent-only-non-authoritative",
                "org.verigym.official-verifier-included": "false",
            },
        },
    }

    def inspect(reference: str, **kwargs: object) -> object:
        if reference == final_id:
            return final
        if reference == derived_id:
            return derived
        if reference == successor.official_verifier_image and kwargs.get("required") is False:
            return None
        raise AssertionError(reference)

    hashes = {
        name: successor.git_binary_sha256 if name == "git" else "1" * 64
        for name in runner._BINARY_PATHS  # noqa: SLF001
    }
    lines = [
        *(f"{hashes[name]}  {path}" for name, path in runner._BINARY_PATHS.items()),  # noqa: SLF001
        "agent_toolchain_id=verigym-open-rtl-tools-v1",
        "Verilator 5.008",
        "Icarus Verilog version 12.0",
        "Icarus Verilog runtime version 12.0",
        "Yosys 0.67",
        "ripgrep 15.2.0",
        "GNU Make",
        "g++",
        f"git version {successor.git_version}",
    ]
    probe = {
        "returncode": 0,
        "output": ("\n".join(lines) + "\n").encode(),
        "network": "none",
        "read_only_root": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "effective_user": f"{os.getuid()}:{os.getgid()}",
        "mount_count": 0,
        "container_removed": True,
    }
    monkeypatch.setattr(runner.v172, "_inspect_image", inspect)
    monkeypatch.setattr(runner.v172, "_run_secure_container", lambda **kwargs: dict(probe))
    monkeypatch.setattr(runner.v182, "_contains_sensitive_output", lambda *args, **kwargs: False)

    scan, lock = runner._scan_and_lock_open_image(  # noqa: SLF001
        successor,
        image_id=final_id,
        derived_builder_id=derived_id,
        docker_host="unix:///data2/docker.sock",
        active_sensitive_values=(),
    )

    assert scan["scan_passed"] is True
    assert lock.binary_sha256["git"] == successor.git_binary_sha256
    assert lock.hwe_image_loaded is False
    assert lock.official_verifier_image == successor.official_verifier_image
    assert lock.image_id != lock.official_verifier_image


def test_v188_execute_seals_a_terminal_report_on_capacity_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    successor = _successor()
    root = tmp_path / "result"
    scratch = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    scratch.mkdir(mode=0o700)
    monkeypatch.setattr(
        runner,
        "_headroom_receipt",
        lambda manifest: (_ for _ in ()).throw(ConfigurationError("capacity")),
    )
    cleanup_base = {
        "schema_version": "1.0",
        "format_id": "inherited",
        "identity": "inherited",
        "category": "completed",
        "cleanup_complete": True,
    }
    monkeypatch.setattr(
        runner.v182,
        "_cleanup",
        lambda *args, **kwargs: {
            **cleanup_base,
            "cleanup_hash": runner.content_hash(cleanup_base),
        },
    )
    arguments = Namespace(
        manifest=_MANIFEST,
        output=root,
        post_merge_main_run_id=successor.predecessor_audit_post_merge_main_run_id + 1,
    )
    placeholder = SimpleNamespace()

    report = runner._execute(  # noqa: SLF001
        arguments,
        successor=successor,
        predecessor=placeholder,
        runtime=placeholder,
        builder=placeholder,
        root=root,
        scratch=scratch,
        source_commit="a" * 40,
        active_sensitive_values=(),
        archive_receipt={},
        package_receipt={},
        probe_proxy=placeholder,
    )

    assert report["status"] == "stopped_without_repaired_image"
    assert report["repair_category"] == "controller_error"
    assert report["cleanup_complete"] is True
    assert report["provider_calls"] == 0
    assert report["hwe_image_import_count"] == 0
    assert (root / "zero-provider-report.json").is_file()
    assert json.loads((root / "materialization-progress.json").read_text()) == report
