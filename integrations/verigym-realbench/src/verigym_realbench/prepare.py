"""Explicitly freeze three audited AES modules from an already decrypted checkout."""

from __future__ import annotations

import argparse
import ast
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from verigym_cadence.protocol import bounded_read

from verigym.plugin_api import content_hash, hash_bytes

from .source import (
    CATALOG_SHA256,
    LICENSE_SHA256,
    LOCK_NAME,
    PINNED_COMMIT,
    ModuleTask,
    SourceAsset,
    SourceLock,
    load_source,
)

SLICE = {
    "aes_sbox": "combinational",
    "aes_rcon": "sequential",
    "aes_key_expand_128": "hierarchical",
}


def atomic_json(path: Path, payload: Any) -> None:
    """Write owned progress atomically; callers must validate their output boundary."""
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(root: Path, audit: str) -> SourceLock:
    """No golden is used as a stub or public dependency, including other slice targets."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source root must be a real directory")
    destination = root / LOCK_NAME
    if destination.exists() or destination.is_symlink():
        raise ValueError("source lock already exists; do not overwrite a frozen identity")
    tasks = []
    for top, kind in SLICE.items():
        base = f"aes/{top}"
        assets: list[SourceAsset] = []

        def asset(
            path: str,
            role: str,
            destination: str | None = None,
            assets: list[SourceAsset] = assets,
        ) -> None:
            assets.append(
                SourceAsset.model_validate(
                    {
                        "path": path,
                        "role": role,
                        "destination": destination,
                        "sha256": hash_bytes(bounded_read(root / path)),
                    }
                )
            )

        asset(f"{base}/{top}.md", "spec", f"repository/spec/{top}.md")
        for path in sorted((root / base / "figures").iterdir()):
            asset(
                path.relative_to(root).as_posix(), "image", f"repository/spec/figures/{path.name}"
            )
        asset(f"verigym-inputs/{top}.sv", "stub", f"repository/rtl/{top}.sv")
        asset(f"{base}/{top}.v", "reference")
        for path in sorted((root / base / "verification").iterdir()):
            # The upstream DUT slot is replaced, never supplied alongside the candidate.
            if path.name == f"{top}_top.sv":
                continue
            asset(
                path.relative_to(root).as_posix(),
                "reference" if path.name == f"{top}_ref.sv" else "verification",
            )
        for name in ("test.tcl", "ref.f", "top.f"):
            asset(f"formal-template/{name}", "template")
        tasks.append(
            ModuleTask.model_validate(
                {"native_id": f"aes/{top}", "top": top, "kind": kind, "assets": assets}
            )
        )
    lock = SourceLock(
        commit=PINNED_COMMIT,
        license_path="LICENSE",
        license_sha256=LICENSE_SHA256,
        catalog_sha256=CATALOG_SHA256,
        visibility_audit=audit,
        tasks=tasks,
    )
    atomic_json(destination, lock.model_dump(mode="json"))
    return load_source(root)


def inventory(root: Path) -> dict[str, Any]:
    """Content-only catalog of all native task asset trees; no source bytes or sample runs."""
    raw = bounded_read(root / "benchmark_info.py")
    if hash_bytes(raw) != CATALOG_SHA256:
        raise ValueError("catalog differs from the frozen upstream")
    catalogs = {
        target.id: ast.literal_eval(statement.value)
        for statement in ast.parse(raw.decode()).body
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name)
    }
    records = []
    for directory in ("aes", "sdc", "e203_hbirdv2", "system", "formal-template"):
        for path in sorted((root / directory).rglob("*")):
            if path.is_symlink():
                raise ValueError("source inventory contains a symlink")
            if path.is_file():
                data = bounded_read(path)
                records.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "bytes": len(data),
                        "sha256": hash_bytes(data),
                    }
                )
    payload = {
        "kind": "realbench_external_asset_inventory_v1",
        "commit": PINNED_COMMIT,
        "module_count": sum(len(items) for items in catalogs["benchmark_info"].values()),
        "system_count": len(catalogs["system_info"]),
        "records": records,
    }
    return {**payload, "inventory_hash": content_hash(payload)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--visibility-audit", required=True)
    args = parser.parse_args()
    lock = prepare(args.source_root, args.visibility_audit)
    catalog = inventory(args.source_root)
    output = args.source_root / "verigym-asset-inventory.json"
    if output.exists() or output.is_symlink():
        raise ValueError("inventory output already exists")
    atomic_json(output, catalog)
    print(
        json.dumps(
            {
                "source_lock_hash": lock.identity,
                "tasks": len(lock.tasks),
                "inventory_hash": catalog["inventory_hash"],
                "module_count": catalog["module_count"],
                "system_count": catalog["system_count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
