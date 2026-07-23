"""Attempt a dependency-resolving wheel install without network or inherited packages."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    arguments = parser.parse_args()
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
    with tempfile.TemporaryDirectory(prefix="verigym-clean-install-") as temporary:
        root = Path(temporary)
        environment_root = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment_root)
        python = environment_root / "bin" / "python"
        install = subprocess.run(
            [str(python), "-m", "pip", "install", str(arguments.wheel.resolve())],
            cwd=root,
            env=environment,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
        )
        print(install.stdout.decode("utf-8", errors="replace"))
        if install.returncode != 0:
            return install.returncode
        check = subprocess.run(
            [str(python), "-m", "pip", "check"],
            cwd=root,
            env=environment,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )
        print(check.stdout.decode("utf-8", errors="replace"))
        if check.returncode != 0:
            return check.returncode
        imported = subprocess.run(
            [str(python), "-c", "import verigym; print(verigym.__version__)"],
            cwd=root,
            env=environment,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )
        print(imported.stdout.decode("utf-8", errors="replace"))
        return imported.returncode


if __name__ == "__main__":
    raise SystemExit(main())
