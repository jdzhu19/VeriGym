"""Resolve and import the wheel in a clean venv from a hashed offline wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_environment() -> dict[str, str]:
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
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": "",
        }
    )
    return environment


def _run(
    phase: str,
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[bytes]:
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
    print(result.stdout.decode("utf-8", errors="replace"))
    if result.returncode != 0:
        print(f"clean install phase failed: {phase}; exit_code={result.returncode}")
    return result


def _wheelhouse_inventory(wheelhouse: Path) -> dict[str, Any]:
    files = sorted(path for path in wheelhouse.iterdir() if path.is_file())
    if not files:
        raise ValueError("dependency wheelhouse is empty")
    if any(path.is_symlink() for path in files):
        raise ValueError("dependency wheelhouse must not contain symlinks")
    entries = [
        {
            "name": path.name,
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for path in files
    ]
    encoded = json.dumps(entries, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return {
        "file_count": len(entries),
        "inventory_sha256": hashlib.sha256(encoded).hexdigest(),
        "files": entries,
    }


def _write_result(path: Path | None, result: dict[str, Any]) -> None:
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(payload)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--expected-python")
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    wheel = arguments.wheel.resolve()
    wheelhouse = arguments.wheelhouse.resolve()
    interpreter = arguments.python.resolve()
    source_root = arguments.source_root.resolve()
    if not wheel.is_file():
        parser.error("wheel is not a file")
    if not wheelhouse.is_dir():
        parser.error("wheelhouse is not a directory")
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        parser.error("Python interpreter is not executable")
    try:
        wheelhouse_inventory = _wheelhouse_inventory(wheelhouse)
    except ValueError as error:
        parser.error(str(error))

    environment = _safe_environment()
    with tempfile.TemporaryDirectory(prefix="verigym-clean-install-") as temporary:
        root = Path(temporary)
        environment_root = root / "venv"
        create = _run(
            "venv_create",
            [str(interpreter), "-m", "venv", str(environment_root)],
            cwd=root,
            environment=environment,
            timeout=180,
        )
        if create.returncode != 0:
            return create.returncode
        python = environment_root / "bin" / "python"
        install = _run(
            "pip_install",
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(wheelhouse),
                str(wheel),
            ],
            cwd=root,
            environment=environment,
            timeout=300,
        )
        if install.returncode != 0:
            return install.returncode
        check = _run(
            "pip_check",
            [str(python), "-m", "pip", "check"],
            cwd=root,
            environment=environment,
            timeout=60,
        )
        if check.returncode != 0:
            return check.returncode
        inspection_code = """
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
import verigym
print(json.dumps({
    "base_prefix": str(Path(sys.base_prefix).resolve()),
    "implementation": platform.python_implementation(),
    "module_path": str(Path(verigym.__file__).resolve()),
    "prefix": str(Path(sys.prefix).resolve()),
    "python": platform.python_version(),
    "verigym": importlib.metadata.version("verigym"),
}, sort_keys=True))
"""
        imported = _run(
            "external_import",
            [str(python), "-c", inspection_code],
            cwd=root,
            environment=environment,
            timeout=60,
        )
        if imported.returncode != 0:
            return imported.returncode
        try:
            inspection = json.loads(imported.stdout)
            module_path = Path(inspection["module_path"]).resolve()
            prefix = Path(inspection["prefix"]).resolve()
            base_prefix = Path(inspection["base_prefix"]).resolve()
            actual_python = str(inspection["python"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"clean install inspection is invalid: {error}")
            return 1
        if prefix == base_prefix or not module_path.is_relative_to(prefix):
            print("clean install did not import VeriGym from the isolated venv")
            return 1
        if module_path.is_relative_to(source_root):
            print("clean install imported VeriGym from the source tree")
            return 1
        if arguments.expected_python is not None and actual_python.split(".", maxsplit=2)[
            :2
        ] != arguments.expected_python.split(".", maxsplit=1):
            print(
                "clean install Python version mismatch: "
                f"expected {arguments.expected_python}, observed {actual_python}"
            )
            return 1

        inspection["module_path"] = "<isolated-venv>/site-packages/verigym/__init__.py"
        inspection["prefix"] = "<isolated-venv>"
        inspection["base_prefix"] = "<selected-python>"
        result = {
            "schema_version": "1.0",
            "status": "passed",
            "wheel": {
                "name": wheel.name,
                "sha256": _sha256(wheel),
            },
            "wheelhouse": wheelhouse_inventory,
            "inspection": inspection,
            "isolated_venv": True,
            "inherited_site_packages": False,
            "pip_check": "passed",
            "output_hashes": {
                "pip_install": hashlib.sha256(install.stdout).hexdigest(),
                "pip_check": hashlib.sha256(check.stdout).hexdigest(),
                "external_import": hashlib.sha256(imported.stdout).hexdigest(),
            },
        }
        _write_result(arguments.output.resolve() if arguments.output else None, result)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
