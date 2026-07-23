"""Exercise the wheel, public API, and external plugin from an isolated import path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _run(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: int = 180,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=environment,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def installed_conformance(
    root: Path,
    wheel: Path,
    plugin_root: Path,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="verigym-installed-conformance-") as temporary:
        temporary_root = Path(temporary)
        plugin_dist = temporary_root / "plugin-dist"
        plugin_dist.mkdir()
        plugin_build = _run(
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
            cwd=plugin_root,
            environment=dict(os.environ),
        )
        plugin_wheels = sorted(plugin_dist.glob("*.whl"))
        if len(plugin_wheels) != 1:
            raise RuntimeError("plugin build did not produce exactly one wheel")
        plugin_wheel = plugin_wheels[0]

        environment = {
            key: value
            for key, value in os.environ.items()
            if not any(
                marker in key.upper()
                for marker in ("TOKEN", "KEY", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")
            )
        }
        environment.update(
            {
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INDEX": "1",
                "PYTHONPATH": "",
            }
        )
        environment_root = temporary_root / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment_root)
        python = environment_root / "bin" / "python"
        executable = environment_root / "bin" / "verigym"

        install = _run(
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
            [str(python), "-m", "pip", "check"],
            cwd=temporary_root,
            environment=environment,
        )
        help_result = _run(
            [str(executable), "--help"],
            cwd=temporary_root,
            environment=environment,
        )
        doctor = _run(
            [str(executable), "doctor"],
            cwd=temporary_root,
            environment=environment,
        )
        example = _run(
            [str(python), str(root / "examples/python_api_mvp.py")],
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
            [str(python), "-c", inspection_code],
            cwd=temporary_root,
            environment=environment,
        )
        inspected = json.loads(inspection.stdout)
        if str(root.resolve()) in inspected["module_path"]:
            raise RuntimeError("installed conformance imported VeriGym from the source tree")
        if inspected["external_tool_allowed_by_fixture_task"]:
            raise RuntimeError("plugin fixture unexpectedly allows its external tool")
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
    result = installed_conformance(
        arguments.root.resolve(),
        arguments.wheel.resolve(),
        arguments.plugin_root.resolve(),
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
