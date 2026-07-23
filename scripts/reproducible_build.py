"""Build wheel/sdist twice with fixed inputs and compare archive bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _build_once(root: Path, output: Path, epoch: int) -> tuple[Path, Path]:
    code = (
        "import sys;"
        "from build_backend import verigym_build_backend as backend;"
        "out=sys.argv[1];"
        "print(backend.build_wheel(out));"
        "print(backend.build_sdist(out))"
    )
    environment = dict(os.environ)
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.run(
        [sys.executable, "-c", code, str(output)],
        cwd=root,
        env=environment,
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=300,
    )
    wheels = sorted(output.glob("verigym-*.whl"))
    sdists = sorted(output.glob("verigym-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError("build did not produce exactly one wheel and one sdist")
    return wheels[0], sdists[0]


def _wheel_provenance(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith("/_build_provenance.json")]
        if len(names) != 1:
            raise RuntimeError("wheel does not contain exactly one provenance record")
        return json.loads(archive.read(names[0]))


def reproducible_build(root: Path, package_output: Path, epoch: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="verigym-reproducible-build-") as temporary:
        temporary_root = Path(temporary)
        first_dir = temporary_root / "first"
        second_dir = temporary_root / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        first_wheel, first_sdist = _build_once(root, first_dir, epoch)
        second_wheel, second_sdist = _build_once(root, second_dir, epoch)
        first = {
            "wheel": {"name": first_wheel.name, "sha256": _sha256(first_wheel)},
            "sdist": {"name": first_sdist.name, "sha256": _sha256(first_sdist)},
        }
        second = {
            "wheel": {"name": second_wheel.name, "sha256": _sha256(second_wheel)},
            "sdist": {"name": second_sdist.name, "sha256": _sha256(second_sdist)},
        }
        wheel_equal = first["wheel"]["sha256"] == second["wheel"]["sha256"]  # type: ignore[index]
        sdist_equal = first["sdist"]["sha256"] == second["sdist"]["sha256"]  # type: ignore[index]
        package_output.mkdir(parents=True, exist_ok=True)
        copied_wheel = package_output / first_wheel.name
        copied_sdist = package_output / first_sdist.name
        shutil.copyfile(first_wheel, copied_wheel)
        shutil.copyfile(first_sdist, copied_sdist)
        return {
            "schema_version": "1.0",
            "status": "passed" if wheel_equal and sdist_equal else "failed",
            "source_date_epoch": epoch,
            "first": first,
            "second": second,
            "wheel_byte_identical": wheel_equal,
            "sdist_byte_identical": sdist_equal,
            "embedded_provenance": _wheel_provenance(copied_wheel),
            "package_paths": [copied_wheel.name, copied_sdist.name],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--package-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    arguments = parser.parse_args()
    if arguments.source_date_epoch < 315_532_800:
        parser.error("SOURCE_DATE_EPOCH must be at least 1980-01-01 for wheel timestamps")
    result = reproducible_build(
        arguments.root.resolve(),
        arguments.package_output.resolve(),
        arguments.source_date_epoch,
    )
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
