from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "installed_conformance.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("installed_conformance_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_rtl_tools(root: Path) -> Path:
    tools = root / "tools"
    tools.mkdir()
    for name, version in (
        ("iverilog", "Icarus Verilog version test-12.0"),
        ("vvp", "Icarus Verilog runtime version test-12.0"),
    ):
        executable = tools / name
        executable.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\n", encoding="utf-8")
        executable.chmod(0o755)
    return tools


def test_child_failure_includes_phase_exit_and_bounded_redacted_output(
    tmp_path: Path,
) -> None:
    module = _load_script()
    command = [
        sys.executable,
        "-c",
        (
            "import sys;"
            "print('visible child diagnostic');"
            "print('token=do-not-disclose');"
            "print('OPENAI_API_KEY=also-do-not-disclose');"
            "print('x' * 12000);"
            "sys.exit(7)"
        ),
        "--api-token",
        "argv-secret",
    ]

    with pytest.raises(module.ConformanceSubprocessError) as captured:
        module._run(
            "pip_check",
            command,
            cwd=tmp_path,
            environment=module._safe_environment(),
        )

    message = str(captured.value)
    assert "installed conformance phase failed: pip_check" in message
    assert "exit_code: 7" in message
    assert "visible child diagnostic" in message
    assert "diagnostic characters omitted" in message
    assert "token=<redacted>" in message
    assert "do-not-disclose" not in message
    assert "also-do-not-disclose" not in message
    assert "argv-secret" not in message


def test_main_prints_child_diagnostics_without_an_opaque_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()

    def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise module.ConformanceSubprocessError(
            "public_api_example",
            ["python", "example.py"],
            3,
            b"observable child output\n",
        )

    monkeypatch.setattr(module, "installed_conformance", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--wheel",
            str(tmp_path / "verigym.whl"),
            "--output",
            str(tmp_path / "report.json"),
        ],
    )

    assert module.main() == 1
    stderr = capsys.readouterr().err
    assert "public_api_example" in stderr
    assert "exit_code: 3" in stderr
    assert "observable child output" in stderr


def test_missing_rtl_tools_are_an_explicit_infrastructure_error(tmp_path: Path) -> None:
    module = _load_script()

    with pytest.raises(module.InstalledConformanceError) as captured:
        module._preflight_rtl_tools(cwd=tmp_path, environment={"PATH": str(tmp_path)})

    assert captured.value.phase == "public_api_example"
    assert captured.value.classification == "infrastructure_error"
    assert "missing: iverilog, vvp" in str(captured.value)
    assert captured.value.classification != "candidate_failure"


def test_present_rtl_tools_are_versioned_before_the_example_completes(
    tmp_path: Path,
) -> None:
    module = _load_script()
    tools = _fake_rtl_tools(tmp_path)
    example_root = tmp_path / "example-root"
    examples = example_root / "examples"
    examples.mkdir(parents=True)
    (examples / "python_api_mvp.py").write_text(
        "print('public API example completed')\n",
        encoding="utf-8",
    )
    environment = module._safe_environment()
    environment["PATH"] = os.pathsep.join((str(tools), environment.get("PATH", "")))
    environment["PYTHONPATH"] = ""

    result, versions = module._run_public_api_example(
        root=example_root,
        python=Path(sys.executable),
        cwd=tmp_path,
        environment=environment,
    )

    assert result.stdout == b"public API example completed\n"
    assert "Icarus Verilog version test-12.0" in versions["iverilog"]["version_output"]
    assert "Icarus Verilog runtime version test-12.0" in versions["vvp"]["version_output"]


def test_inspection_rejects_source_import_and_plugin_policy_bypass(
    tmp_path: Path,
) -> None:
    module = _load_script()
    valid = {
        "module_path": "/isolated/site-packages/verigym/__init__.py",
        "external_tool_allowed_by_fixture_task": False,
    }
    module._validate_inspection(tmp_path, valid)

    with pytest.raises(module.InstalledConformanceError, match="source tree"):
        module._validate_inspection(
            tmp_path,
            {
                "module_path": str(tmp_path / "src/verigym/__init__.py"),
                "external_tool_allowed_by_fixture_task": False,
            },
        )
    with pytest.raises(module.InstalledConformanceError, match="external tool"):
        module._validate_inspection(
            tmp_path,
            {
                "module_path": "/isolated/site-packages/verigym/__init__.py",
                "external_tool_allowed_by_fixture_task": True,
            },
        )


def test_plugin_build_uses_a_clean_temporary_source_copy(tmp_path: Path) -> None:
    module = _load_script()
    source = tmp_path / "fixture"
    (source / "src" / "plugin").mkdir(parents=True)
    (source / "src" / "plugin" / "__init__.py").write_text("", encoding="utf-8")
    (source / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
    (source / "build").mkdir()
    (source / "build" / "stale.py").write_text("stale = True\n", encoding="utf-8")
    (source / "src" / "fixture.egg-info").mkdir()
    (source / "src" / "fixture.egg-info" / "PKG-INFO").write_text(
        "generated\n",
        encoding="utf-8",
    )

    staged = module._stage_plugin_source(source, tmp_path / "temporary")

    assert staged != source
    assert (staged / "pyproject.toml").is_file()
    assert (staged / "src" / "plugin" / "__init__.py").is_file()
    assert not (staged / "build").exists()
    assert not (staged / "src" / "fixture.egg-info").exists()


def test_full_public_api_example_contract_is_preserved() -> None:
    source = (ROOT / "examples" / "python_api_mvp.py").read_text(encoding="utf-8")

    for required_fragment in (
        "service.run(",
        "replay_run(run.run_dir)",
        "service.run_samples(",
        "pass_k=[1, 2]",
        '"samples_per_task": 1',
        '"max_workers": 1',
        "BatchRunner(",
        "ReportService().generate_all(",
    ):
        assert required_fragment in source


def test_package_ci_alone_provisions_icarus_for_full_conformance() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    ordinary = workflow.split("  ordinary:\n", maxsplit=1)[1].split("  package:\n", maxsplit=1)[0]
    package = workflow.split("  package:\n", maxsplit=1)[1].split(
        "  reproducible-build:\n", maxsplit=1
    )[0]

    assert "apt-get install" not in ordinary
    assert "not requires_iverilog" in ordinary
    assert "sudo apt-get install --yes --no-install-recommends iverilog" in package
    assert "iverilog -V" in package
    assert "vvp -V" in package
    assert "pytest -m requires_iverilog" in package
    assert "scripts/installed_conformance.py" in package


def test_openhands_ci_freezes_and_scans_the_python312_plugin() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    openhands = workflow.split("  openhands:\n", maxsplit=1)[1].split("  package:\n", maxsplit=1)[0]

    assert 'python-version: "3.12"' in openhands
    assert "openhands_sdk_1.42.1_constraints.txt" in openhands
    assert 'version("openhands-sdk") == "1.42.1"' in openhands
    assert 'version("litellm") == "1.93.0"' in openhands
    assert 'version("tiktoken") == "0.11.0"' in openhands
    assert 'version("tiktoken") == "0.7.0"' in openhands
    assert 'version("verigym-deepseek-harness") == "0.3.0"' in openhands
    assert "verigym-tiktoken-0.7-overlay" in openhands
    assert "env -u PIP_CONSTRAINT" in openhands
    assert "MYPYPATH: integrations/verigym-openhands/src" in openhands
    assert "-p verigym_openhands" in openhands
    assert '-m "not openhands_real"' in openhands
    assert "audit_optional_plugin_distribution.py" in openhands
    assert "--policy openhands" in openhands
