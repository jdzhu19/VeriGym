"""Exercise the wheel, public API, and external plugin from an isolated import path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Literal

ConformancePhase = Literal[
    "plugin_build",
    "pip_install",
    "pip_check",
    "cli_help",
    "doctor",
    "public_api_example",
    "plugin_inspection",
]

_MAX_DIAGNOSTIC_CHARACTERS = 8_192
_SECRET_MARKERS = ("token", "key", "secret", "password", "credential", "auth")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([a-z0-9_.-]*(?:token|key|secret|password|credential|authorization)"
    r"[a-z0-9_.-]*)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_URI_CREDENTIALS = re.compile(r"(://)[^/@\s:]+:[^/@\s]+@")


class InstalledConformanceError(RuntimeError):
    """A phase-labelled installed-distribution conformance failure."""

    def __init__(
        self,
        phase: ConformancePhase,
        message: str,
        *,
        classification: str = "conformance_error",
    ) -> None:
        self.phase = phase
        self.classification = classification
        super().__init__(
            f"installed conformance phase failed: {phase}\n"
            f"classification: {classification}\n"
            f"{message}"
        )


class ConformanceSubprocessError(InstalledConformanceError):
    """A child command failure with bounded, sanitized diagnostics."""

    def __init__(
        self,
        phase: ConformancePhase,
        argv: list[str],
        exit_code: int | None,
        output: bytes,
    ) -> None:
        exit_text = "timeout" if exit_code is None else str(exit_code)
        super().__init__(
            phase,
            "\n".join(
                (
                    f"argv: {_sanitize_argv(argv)}",
                    f"exit_code: {exit_text}",
                    "combined_stdout_stderr:",
                    _bounded_diagnostic(output),
                )
            ),
        )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.lower() for marker in _SECRET_MARKERS)
    }


def _sanitize_text(value: str) -> str:
    sanitized = _URI_CREDENTIALS.sub(r"\1<redacted>@", value)
    return _SECRET_ASSIGNMENT.sub(r"\1\2<redacted>", sanitized)


def _sanitize_argv(argv: list[str]) -> str:
    sanitized: list[str] = []
    redact_next = False
    for argument in argv:
        lowered = argument.lower()
        if redact_next:
            sanitized.append("<redacted>")
            redact_next = False
            continue
        if argument.startswith("-") and any(marker in lowered for marker in _SECRET_MARKERS):
            if "=" in argument:
                sanitized.append(f"{argument.split('=', maxsplit=1)[0]}=<redacted>")
            else:
                sanitized.append(argument)
                redact_next = True
            continue
        sanitized.append(_sanitize_text(argument))
    return shlex.join(sanitized)


def _bounded_diagnostic(payload: bytes) -> str:
    decoded = _sanitize_text(payload.decode("utf-8", errors="replace"))
    if len(decoded) <= _MAX_DIAGNOSTIC_CHARACTERS:
        return decoded.rstrip() or "<no output>"
    half = (_MAX_DIAGNOSTIC_CHARACTERS - 80) // 2
    omitted = len(decoded) - (half * 2)
    return (
        decoded[:half].rstrip()
        + f"\n... <{omitted} diagnostic characters omitted> ...\n"
        + decoded[-half:].lstrip()
    )


def _run(
    phase: ConformancePhase,
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: int = 180,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=environment,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        output = error.stdout or b""
        if error.stderr:
            output += error.stderr
        raise ConformanceSubprocessError(phase, argv, None, output) from error
    if result.returncode != 0:
        raise ConformanceSubprocessError(phase, argv, result.returncode, result.stdout)
    return result


def _preflight_rtl_tools(
    *,
    cwd: Path,
    environment: dict[str, str],
) -> dict[str, dict[str, str]]:
    resolved = {
        tool: shutil.which(tool, path=environment.get("PATH")) for tool in ("iverilog", "vvp")
    }
    missing = [tool for tool, path in resolved.items() if path is None]
    if missing:
        raise InstalledConformanceError(
            "public_api_example",
            "installed public-API MVP conformance requires Icarus Verilog; "
            f"missing: {', '.join(missing)}",
            classification="infrastructure_error",
        )

    versions: dict[str, dict[str, str]] = {}
    for tool, executable in resolved.items():
        assert executable is not None
        result = _run(
            "public_api_example",
            [executable, "-V"],
            cwd=cwd,
            environment=environment,
        )
        versions[tool] = {
            "version_output": _bounded_diagnostic(result.stdout),
            "output_sha256": _sha256_bytes(result.stdout),
        }
    return versions


def _run_public_api_example(
    *,
    root: Path,
    python: Path,
    cwd: Path,
    environment: dict[str, str],
) -> tuple[subprocess.CompletedProcess[bytes], dict[str, dict[str, str]]]:
    rtl_tools = _preflight_rtl_tools(cwd=cwd, environment=environment)
    example = _run(
        "public_api_example",
        [str(python), str(root / "examples/python_api_mvp.py")],
        cwd=cwd,
        environment=environment,
    )
    return example, rtl_tools


def _validate_inspection(root: Path, inspected: dict[str, object]) -> None:
    module_path = inspected.get("module_path")
    if not isinstance(module_path, str):
        raise InstalledConformanceError(
            "plugin_inspection",
            "plugin inspection did not report a valid module path",
        )
    if str(root.resolve()) in module_path:
        raise InstalledConformanceError(
            "plugin_inspection",
            "installed conformance imported VeriGym from the source tree",
        )
    if inspected.get("external_tool_allowed_by_fixture_task") is not False:
        raise InstalledConformanceError(
            "plugin_inspection",
            "plugin fixture unexpectedly allows its external tool",
        )


def _stage_plugin_source(plugin_root: Path, destination: Path) -> Path:
    staged = destination / "plugin-source"
    try:
        shutil.copytree(
            plugin_root,
            staged,
            ignore=shutil.ignore_patterns(
                "build",
                "dist",
                "*.egg-info",
                "__pycache__",
                "*.pyc",
            ),
        )
    except OSError as error:
        raise InstalledConformanceError(
            "plugin_build",
            f"could not stage the plugin fixture: {error}",
        ) from error
    return staged


def installed_conformance(
    root: Path,
    wheel: Path,
    plugin_root: Path,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="verigym-installed-conformance-") as temporary:
        temporary_root = Path(temporary)
        plugin_dist = temporary_root / "plugin-dist"
        plugin_dist.mkdir()
        staged_plugin_root = _stage_plugin_source(plugin_root, temporary_root)
        environment = _safe_environment()
        environment.update(
            {
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INDEX": "1",
                "PYTHONPATH": "",
            }
        )
        plugin_build = _run(
            "plugin_build",
            [
                sys.executable,
                "-c",
                (
                    "from setuptools import build_meta;"
                    "import sys;"
                    "print(build_meta.build_wheel(sys.argv[1]))"
                ),
                str(plugin_dist),
            ],
            cwd=staged_plugin_root,
            environment=environment,
        )
        plugin_wheels = sorted(plugin_dist.glob("*.whl"))
        if len(plugin_wheels) != 1:
            raise InstalledConformanceError(
                "plugin_build",
                "plugin build did not produce exactly one wheel",
            )
        plugin_wheel = plugin_wheels[0]

        environment_root = temporary_root / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment_root)
        python = environment_root / "bin" / "python"
        executable = environment_root / "bin" / "verigym"

        install = _run(
            "pip_install",
            [
                str(python),
                "-m",
                "pip",
                "install",
                str(wheel),
                str(plugin_wheel),
            ],
            cwd=temporary_root,
            environment=environment,
        )
        pip_check = _run(
            "pip_check",
            [str(python), "-m", "pip", "check"],
            cwd=temporary_root,
            environment=environment,
        )
        help_result = _run(
            "cli_help",
            [str(executable), "--help"],
            cwd=temporary_root,
            environment=environment,
        )
        doctor = _run(
            "doctor",
            [str(executable), "doctor"],
            cwd=temporary_root,
            environment=environment,
        )
        example, rtl_tools = _run_public_api_example(
            root=root,
            python=python,
            cwd=temporary_root,
            environment=environment,
        )
        inspection_code = """
import json
from dataclasses import asdict
from importlib import metadata, resources
from pathlib import Path
import verigym
from verigym.provenance import get_build_provenance
from verigym.registry import default_registries
r = default_registries()
task = r.suites.get("external-conformance").load_task(
    next(iter(r.suites.get("external-conformance").discover()))
)
print(json.dumps({
    "module_path": str(Path(verigym.__file__).resolve()),
    "distribution_version": metadata.version("verigym"),
    "suite_origin": asdict(r.suites.origin("external-conformance")),
    "tool_origin": asdict(r.tools.origin("external-conformance.health")),
    "agent_origin": asdict(r.agents.origin("external-conformance-agent")),
    "suite_valid": r.suites.get("external-conformance").validate_source().valid,
    "plugin_asset_present": resources.files("verigym_conformance_plugin")
        .joinpath("assets/task.json").is_file(),
    "external_tool_allowed_by_fixture_task": (
        "external-conformance.health" in task.interaction.allowed_tools
    ),
    "provenance": get_build_provenance().model_dump(mode="json"),
}, sort_keys=True))
"""
        inspection = _run(
            "plugin_inspection",
            [str(python), "-c", inspection_code],
            cwd=temporary_root,
            environment=environment,
        )
        try:
            inspected = json.loads(inspection.stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise InstalledConformanceError(
                "plugin_inspection",
                f"plugin inspection returned invalid JSON: {error}",
            ) from error
        if not isinstance(inspected, dict):
            raise InstalledConformanceError(
                "plugin_inspection",
                "plugin inspection did not return a JSON object",
            )
        _validate_inspection(root, inspected)
        inspected["module_path"] = "<isolated-venv>/site-packages/verigym/__init__.py"
        return {
            "schema_version": "1.0",
            "status": "passed",
            "wheel": wheel.name,
            "plugin_wheel": plugin_wheel.name,
            "offline_dependency_resolution": (
                "system-site packages, pip --no-index, pip check passed"
            ),
            "inspection": inspected,
            "rtl_tools": rtl_tools,
            "output_hashes": {
                "plugin_build": _sha256_bytes(plugin_build.stdout),
                "pip_install": _sha256_bytes(install.stdout),
                "pip_check": _sha256_bytes(pip_check.stdout),
                "cli_help": _sha256_bytes(help_result.stdout),
                "doctor": _sha256_bytes(doctor.stdout),
                "public_api_example": _sha256_bytes(example.stdout),
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=Path("examples/plugins/conformance"),
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = installed_conformance(
            arguments.root.resolve(),
            arguments.wheel.resolve(),
            arguments.plugin_root.resolve(),
        )
    except InstalledConformanceError as error:
        print(error, file=sys.stderr)
        return 1
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
