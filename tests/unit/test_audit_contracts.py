"""Build, documentation, distribution, and release-audit contract tests."""

from __future__ import annotations

import io
import json
import os
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from scripts.audit_distribution import inspect_distributions
from scripts.reproducible_build import reproducible_build
from scripts.run_frozen_experiment import _replay_integrity_status
from scripts.run_release_audit import AuditRunner, _build_frontend_environment
from verigym.core.replay import ReplaySummary
from verigym.provenance import _live_provenance
from verigym.release_audit import evaluate_gate, validate_bundle
from verigym.schemas.integrity import IntegrityValidation
from verigym.schemas.provenance import BuildProvenance


def test_frozen_experiment_replay_reads_nested_integrity_status() -> None:
    summary = cast(
        ReplaySummary,
        SimpleNamespace(integrity=IntegrityValidation(status="verified")),
    )
    assert _replay_integrity_status(summary) == "verified"


def test_clean_and_dirty_source_identity_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("one\n", encoding="utf-8")
    dirty = False

    def fake_git(root: Path, arguments: list[str]) -> bytes:
        assert root == tmp_path
        if arguments[0] == "rev-parse":
            return b"a" * 40 + b"\n"
        if arguments[0] == "ls-files":
            return b"source.txt\0"
        if arguments[0] == "status":
            return b" M source.txt\0" if dirty else b""
        raise AssertionError(arguments)

    monkeypatch.setattr("verigym.provenance._git", fake_git)
    clean = _live_provenance(tmp_path)
    assert clean.dirty is False
    assert clean.source_commit == "a" * 40
    first_hash = clean.source_tree_hash

    dirty = True
    source.write_text("two\n", encoding="utf-8")
    changed = _live_provenance(tmp_path)
    assert changed.dirty is True
    assert changed.source_tree_hash != first_hash


def test_unknown_provenance_and_missing_evidence_fail_release_gate() -> None:
    unknown = BuildProvenance(
        package_version="0.1.0",
        provenance_method="unknown",
        source_tree_path_policy="test",
        unknown_reason="fixture",
    )
    gate, reasons = evaluate_gate([], unknown, ["required"])
    assert gate == "FAIL"
    assert any("no evidence" in reason for reason in reasons)
    assert any("provenance" in reason for reason in reasons)


def _write_test_archives(
    tmp_path: Path,
    *,
    extra_sdist_members: dict[str, bytes] | None = None,
) -> tuple[Path, Path]:
    wheel = tmp_path / "verigym-0.1.0-py3-none-any.whl"
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: verigym\n"
        "Version: 0.1.0\n"
        "Requires-Python: >=3.11\n"
        "License-Expression: Apache-2.0\n"
        "Project-URL: Repository, https://example.invalid/verigym\n\n"
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("verigym/__init__.py", "")
        archive.writestr("verigym/_build_provenance.json", "{}")
        archive.writestr("verigym/public_test_launcher.py", "")
        archive.writestr("verigym/profiles/builtins/assets/NOTICE", "first-party")
        archive.writestr("verigym/profiles/builtins/assets/toy_cells.lib", "library(test) {}")
        archive.writestr(
            "verigym/suites/repo_rtl/assets/arbiter_reset_recovery/LICENSE",
            "Apache-2.0",
        )
        archive.writestr(
            "verigym/suites/repo_rtl/assets/counter_wrap/task.yaml",
            "schema_version: '1.0'\n",
        )
        archive.writestr(
            "verigym/suites/repo_rtl/assets/counter_wrap/public/test-contract.json",
            "{}",
        )
        archive.writestr(
            "verigym/suites/repo_rtl/assets/counter_wrap/hidden/tb_counter_hidden.sv",
            "module tb_counter_hidden; endmodule\n",
        )
        archive.writestr(
            (
                "verigym/suites/repo_rtl/assets/"
                "pipeline_stall_backpressure/reference/reference.patch"
            ),
            "",
        )
        archive.writestr(
            "verigym/suites/toy_rtl/assets/and_gate_basic/task.yaml",
            "schema_version: '1.0'\n",
        )
        archive.writestr("verigym-0.1.0.dist-info/METADATA", metadata)
        archive.writestr("verigym-0.1.0.dist-info/licenses/LICENSE", "Apache-2.0")
        archive.writestr("verigym-0.1.0.dist-info/licenses/NOTICE", "VeriGym")

    sdist = tmp_path / "verigym-0.1.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        contents = {
            "verigym-0.1.0/pyproject.toml": b"[project]\nname='verigym'\n",
            "verigym-0.1.0/.github/workflows/ci.yml": b"name: test\n",
            "verigym-0.1.0/build_backend/verigym_build_backend.py": b"",
            "verigym-0.1.0/docker/codex-exec-server/SOURCE_IDENTITIES": b"",
            "verigym-0.1.0/docker/codex-repository-agent/SOURCE_IDENTITIES": b"",
            "verigym-0.1.0/examples/plugins/conformance/pyproject.toml": b"",
            "verigym-0.1.0/scripts/build_codex_agent_image.sh": b"",
            "verigym-0.1.0/scripts/build_codex_repository_agent_image.sh": b"",
            "verigym-0.1.0/scripts/run_release_audit.py": b"",
            (
                "verigym-0.1.0/tests/fixtures/verilog_eval_v2_synthetic/VERIGYM_SYNTHETIC_FIXTURE"
            ): b"first-party synthetic fixture\n",
            "verigym-0.1.0/tests/fixtures/verilog_eval_v2_synthetic/LICENSE": b"MIT\n",
            "verigym-0.1.0/examples/plugins/conformance/LICENSE": b"Apache-2.0\n",
        }
        contents.update(extra_sdist_members or {})
        for name, payload in contents.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return wheel, sdist


def test_distribution_policy_scan_accepts_declared_fixture_and_rejects_private_member(
    tmp_path: Path,
) -> None:
    wheel, sdist = _write_test_archives(tmp_path)
    assert inspect_distributions(wheel, sdist)["status"] == "passed"
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("verigym/.env", "TOKEN=not-a-real-secret")
    result = inspect_distributions(wheel, sdist)
    assert result["status"] == "failed"
    assert any("forbidden" in issue for issue in result["issues"])


@pytest.mark.parametrize(
    "member",
    [
        "verigym-0.1.0/examples/plugins/conformance/build/lib/plugin.py",
        "verigym-0.1.0/examples/plugins/conformance/src/plugin.egg-info/PKG-INFO",
    ],
)
def test_distribution_policy_scan_rejects_generated_plugin_members(
    tmp_path: Path,
    member: str,
) -> None:
    wheel, sdist = _write_test_archives(
        tmp_path,
        extra_sdist_members={member: b"generated\n"},
    )

    result = inspect_distributions(wheel, sdist)

    assert result["status"] == "failed"
    assert any(member in issue for issue in result["issues"])


def test_required_documentation_and_adrs_exist_and_examples_compile() -> None:
    required = [
        "README.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "docs/architecture.md",
        "docs/task_ir.md",
        "docs/artifact_contract.md",
        "docs/schema_compatibility.md",
        "docs/python_api.md",
        "docs/plugin_api.md",
        "docs/adding_a_suite.md",
        "docs/adding_a_tool.md",
        "docs/adding_an_agent.md",
        "docs/adding_a_runtime.md",
        "docs/ppa_profiles.md",
        "docs/commercial_tools.md",
        "docs/verilog_eval.md",
        "docs/docker_runtime.md",
        "docs/yosys.md",
        "docs/experiments.md",
        "docs/batch_runner.md",
        "docs/reporting.md",
        "docs/repository_rtl_repair.md",
        "docs/benchmark_governance.md",
        "docs/build_provenance.md",
        "docs/packaging_policy.md",
    ]
    required.extend(f"docs/adr/{number:04d}-" for number in range(1, 11))
    required.append("docs/adr/0013-repository-level-rtl-repair.md")
    files = [path.as_posix() for path in Path(".").rglob("*") if path.is_file()]
    for expected in required:
        assert any(item == expected or item.startswith(expected) for item in files), expected
    example = Path("examples/python_api_mvp.py").read_text(encoding="utf-8")
    compile(example, "examples/python_api_mvp.py", "exec")
    for schema in Path("docs/schemas").glob("*.schema.json"):
        if schema.name == "docker-runtime-config.schema.json":
            # This is an exported nested configuration object, not a persistent top-level record.
            continue
        assert "schema_version" in json.dumps(json.loads(schema.read_text(encoding="utf-8")))


def test_release_frontend_uses_supplied_wheelhouse_without_an_index(tmp_path: Path) -> None:
    updates, identities = _build_frontend_environment(tmp_path, 1_784_712_454)
    assert updates == {
        "PIP_FIND_LINKS": str(tmp_path.resolve()),
        "PIP_NO_INDEX": "1",
        "SOURCE_DATE_EPOCH": "1784712454",
    }
    assert identities == {"build_dependency_resolution": "offline_hashed_wheelhouse"}


def test_ci_opt_in_commands_override_the_default_marker_filter() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    normalized = " ".join(workflow.replace("\\\n", " ").split())
    selections = [
        ("docker", "tests/integration/test_docker_codex_external_agent.py"),
        ("docker", "tests/integration/test_docker_repository_agent.py"),
        ("docker", "tests/integration/test_docker_api_repository_agent.py"),
        (
            "external_benchmark",
            (
                "tests/codex_cli/test_verilog_eval_pilot_candidates.py::"
                "test_f6b159b_track_b_forensic_candidates_reach_exact_hidden_verifier"
            ),
        ),
    ]

    for marker, target in selections:
        assert f"pytest -q -m {marker} {target}" in normalized


def test_release_audit_sanitizes_host_tool_roots_and_temporary_paths(tmp_path: Path) -> None:
    runner = object.__new__(AuditRunner)
    runner.output = tmp_path / "audit"
    runner.root = tmp_path / "workspace"
    runner.verilog_eval_root = None
    runner.wheelhouse = None
    python_root = tmp_path / "cpython-3.12"
    runner.python_interpreters = {"3.12": python_root / "bin" / "python3.12"}
    runner.codex_binary = tmp_path / "codex" / "bin" / "codex"

    sanitized = runner._sanitize(
        (
            f'{{"base_prefix":"{python_root}","module_path":"/tmp/install/lib/python/site.py"}}}}'
        ).encode()
    )

    assert str(python_root) not in sanitized
    assert "/tmp/" not in sanitized
    assert "<python-3.12-root>" in sanitized
    assert "<tmp>" in sanitized


def test_repository_agent_image_build_context_honors_scoped_tmpdir() -> None:
    script = Path("scripts/build_codex_repository_agent_image.sh").read_text(encoding="utf-8")
    assert 'build_context_parent=$(realpath "${TMPDIR:-/tmp}")' in script
    assert 'mktemp -d "$build_context_parent/verigym-codex-repository-image.XXXXXXXX"' in script
    assert '"$build_context_parent"/verigym-codex-repository-image.*)' in script
    assert 'rm -rf -- "$build_context"' in script


def test_repository_agent_image_provisions_public_launcher_standard_library() -> None:
    dockerfile = Path("docker/codex-repository-agent/Dockerfile").read_text(encoding="utf-8")
    assert "apt-get install --yes --no-install-recommends python3" in dockerfile
    assert dockerfile.index("USER root") < dockerfile.index("apt-get install")
    assert dockerfile.rindex("USER 10001:10001") > dockerfile.index("apt-get install")


@pytest.mark.reproducible_build
@pytest.mark.skipif(
    os.environ.get("VERIGYM_RUN_REPRODUCIBLE_BUILD_TESTS") != "1",
    reason="set VERIGYM_RUN_REPRODUCIBLE_BUILD_TESTS=1 for archive rebuilds",
)
def test_reproducible_package_builds(tmp_path: Path) -> None:
    result = reproducible_build(Path.cwd(), tmp_path / "packages", 1_784_712_454)
    assert result["status"] == "passed"
    assert result["wheel_byte_identical"]
    assert result["sdist_byte_identical"]


@pytest.mark.release_audit
@pytest.mark.skipif(
    not os.environ.get("VERIGYM_RELEASE_AUDIT_ROOT"),
    reason="VERIGYM_RELEASE_AUDIT_ROOT is not configured",
)
def test_generated_release_audit_bundle_is_hash_bound() -> None:
    manifest, bundle_hash = validate_bundle(Path(os.environ["VERIGYM_RELEASE_AUDIT_ROOT"]))
    assert manifest.gate_result in {"PASS", "FAIL"}
    assert len(bundle_hash) == 64
