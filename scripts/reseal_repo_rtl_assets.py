#!/usr/bin/env python3
"""Regenerate only deterministic identities for the committed repo-RTL fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from verigym.core.hashing import hash_bytes, hash_directory
from verigym.core.repository_candidate import build_repository_patch


def _asset_root() -> Path:
    return (
        Path(__file__).resolve().parents[1] / "src" / "verigym" / "suites" / "repo_rtl" / "assets"
    )


def _hash_public_files(public_root: Path, files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        encoded = relative.encode("utf-8")
        data = (public_root / relative).read_bytes()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def reseal(root: Path) -> None:
    task_path = root / "task.yaml"
    payload = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    public = root / "public"
    asset_files = payload["public_tests"]["asset_files"]
    for relative in sorted(asset_files):
        asset_files[relative] = hash_bytes((public / relative).read_bytes())
    payload["public_tests"]["public_assets_hash"] = _hash_public_files(public, asset_files)
    repository_hash = hash_directory(root / "repository")
    payload["source"]["repository_hash"] = repository_hash
    payload["source"]["license_file_hash"] = hash_bytes(
        (root / "repository" / payload["source"]["license_file"]).read_bytes()
    )
    payload["task"]["source"]["content_hash"] = repository_hash
    payload["issue_hash"] = hash_bytes((root / payload["issue_file"]).read_bytes())
    payload["verification"]["hidden_verifier_hash"] = hash_directory(root / "hidden")
    reference_root = root / "reference" / "repository"
    payload["verification"]["reference_candidate_hash"] = hash_directory(reference_root)
    patch = build_repository_patch(root / "repository", reference_root)
    patch_path = root / "reference" / "reference.patch"
    patch_path.write_text(patch, encoding="utf-8")
    payload["verification"]["reference_patch_hash"] = hash_bytes(patch.encode("utf-8"))
    (public / "test-contract.json").write_text(
        json.dumps(payload["public_tests"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload["source"]["task_bundle_hash"] = hash_directory(root, excluded_names={"task.yaml"})
    task_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8",
    )


def main() -> None:
    for root in sorted(path for path in _asset_root().iterdir() if path.is_dir()):
        reseal(root)


if __name__ == "__main__":
    main()
