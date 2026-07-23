"""Install the sdist offline with audited host dependencies and import it externally."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=environment,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
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
            "PIP_NO_CACHE_DIR": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONPATH": "",
        }
    )
    with tempfile.TemporaryDirectory(prefix="verigym-sdist-conformance-") as temporary:
        root = Path(temporary)
        target = root / "site"
        install = _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-build-isolation",
                "--target",
                str(target),
                str(arguments.sdist.resolve()),
            ],
            cwd=root,
            environment=environment,
        )
        check = _run(
            [sys.executable, "-m", "pip", "check"],
            cwd=root,
            environment=environment,
        )
        import_environment = dict(environment)
        import_environment["PYTHONPATH"] = str(target)
        imported = _run(
            [
                sys.executable,
                "-c",
                (
                    "import json,verigym;"
                    "from verigym.provenance import get_build_provenance;"
                    "print(json.dumps({'module':verigym.__file__,"
                    "'version':verigym.__version__,"
                    "'provenance':get_build_provenance().model_dump(mode='json')},"
                    "sort_keys=True))"
                ),
            ],
            cwd=root,
            environment=import_environment,
        )
        inspection = json.loads(imported.stdout)
        if str(target.resolve()) not in inspection["module"]:
            raise RuntimeError("sdist conformance did not import from the isolated target")
        inspection["module"] = "<isolated-target>/verigym/__init__.py"
        result = {
            "schema_version": "1.0",
            "status": "passed",
            "sdist": arguments.sdist.name,
            "offline_dependency_resolution": (
                "sdist built/installed into an isolated target with the audited host backend; "
                "host dependencies separately passed pip check; clean resolution is a separate gate"
            ),
            "inspection": inspection,
            "pip_install_output_bytes": len(install.stdout),
            "pip_check_output": check.stdout.decode("utf-8", errors="replace").strip(),
        }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
