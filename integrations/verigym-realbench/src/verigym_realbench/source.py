"""Explicit, hash-bound public/hidden projection; never download, decrypt, or execute upstream."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from verigym_cadence.protocol import Digest, bounded_read, relative_path, unique_json

from verigym.plugin_api import StrictModel, content_hash, hash_bytes

UPSTREAM = "https://github.com/IPRC-DIP/RealBench"
PINNED_COMMIT = "9bc9a6ac058b3a3acb09b9e7623526737bbf8312"
CATALOG_SHA256 = "b74ce72ba50675e2f353a848394622b649483b2fc4f5273d8f95b7601542f501"
LICENSE_SHA256 = "29648311da61a019317db725dadc1f3052a0afc11e42b46aa546c3dc15403e1a"
LOCK_NAME = "verigym-realbench.lock.json"
VARIANT: Literal["module-slice-draft-v1"] = "module-slice-draft-v1"
Role = Literal[
    "spec", "image", "stub", "public_dependency", "verification", "reference", "template"
]


class SourceAsset(StrictModel):
    path: str
    sha256: Digest
    role: Role
    destination: str | None = None

    @field_validator("path", "destination")
    @classmethod
    def safe_path(cls, value: str | None) -> str | None:
        return relative_path(value) if value is not None else None

    @model_validator(mode="after")
    def visibility(self) -> SourceAsset:
        public = self.role in {"spec", "image", "stub", "public_dependency"}
        if public != (self.destination is not None):
            raise ValueError("only explicitly public assets have workspace destinations")
        if self.destination is not None:
            suffixes = {
                "spec": {".md"},
                "image": {".png", ".jpg", ".jpeg", ".webp"},
                "stub": {".v", ".sv"},
                "public_dependency": {".v", ".sv", ".vh", ".svh"},
            }
            if Path(self.destination).suffix.lower() not in suffixes[self.role]:
                raise ValueError("public destination has the wrong asset type")
            if not self.destination.startswith("repository/"):
                raise ValueError("public assets must be under repository/")
        return self


class ModuleTask(StrictModel):
    native_id: str = Field(pattern=r"^[A-Za-z0-9_]+/[A-Za-z0-9_]+$")
    top: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    kind: Literal["combinational", "sequential", "hierarchical"]
    assets: list[SourceAsset] = Field(min_length=4, max_length=256)

    @model_validator(mode="after")
    def partition(self) -> ModuleTask:
        paths = [a.path for a in self.assets]
        destinations = [a.destination for a in self.assets if a.destination is not None]
        if len(paths) != len(set(paths)) or len(destinations) != len(set(destinations)):
            raise ValueError("task assets require unique paths and destinations")
        required = {"spec", "stub", "reference", "verification", "template"}
        if not required.issubset({a.role for a in self.assets}):
            raise ValueError(
                "task requires explicit spec, stub, reference, verification and template"
            )
        public_hashes = {a.sha256 for a in self.assets if a.destination is not None}
        hidden_hashes = {a.sha256 for a in self.assets if a.destination is None}
        if public_hashes & hidden_hashes:
            raise ValueError("hidden content must not be aliased into the public workspace")
        return self


class SourceLock(StrictModel):
    version: Literal["1"] = "1"
    variant: Literal["module-slice-draft-v1"] = VARIANT
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    license_path: str
    license_sha256: Digest
    catalog_path: str = "benchmark_info.py"
    catalog_sha256: Digest
    visibility_audit: str = Field(min_length=1, max_length=4096)
    synthetic_fixture: bool = False
    tasks: list[ModuleTask] = Field(min_length=1, max_length=3)

    @field_validator("license_path", "catalog_path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return relative_path(value)

    @model_validator(mode="after")
    def task_ids(self) -> SourceLock:
        ids = [t.native_id for t in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate task id")
        if not self.synthetic_fixture and self.commit != PINNED_COMMIT:
            raise ValueError("external source revision is not the pinned RealBench revision")
        if not self.synthetic_fixture and (
            self.catalog_sha256 != CATALOG_SHA256 or self.license_sha256 != LICENSE_SHA256
        ):
            raise ValueError("external catalog/license differs from the pinned upstream identity")
        return self

    @property
    def identity(self) -> str:
        return content_hash(self)


def load_source(root: Path) -> SourceLock:
    lock = SourceLock.model_validate(
        unique_json(bounded_read(root / LOCK_NAME, 1024 * 1024).decode())
    )
    bindings = {lock.license_path: lock.license_sha256, lock.catalog_path: lock.catalog_sha256}
    for task in lock.tasks:
        for asset in task.assets:
            if asset.path in bindings and bindings[asset.path] != asset.sha256:
                raise ValueError("conflicting source identity")
            bindings[asset.path] = asset.sha256
    total = 0
    for path, digest in bindings.items():
        data = bounded_read(root / path)
        total += len(data)
        if total > 128 * 1024 * 1024 or hash_bytes(data) != digest:
            raise ValueError("bounded external source identity mismatch")
    if not lock.synthetic_fixture:
        # Parse only the pinned literal; never import the benchmark's executable Python.
        tree = ast.parse(bounded_read(root / lock.catalog_path).decode("utf-8"))
        catalogs = {
            target.id: ast.literal_eval(statement.value)
            for statement in tree.body
            if isinstance(statement, ast.Assign)
            for target in statement.targets
            if isinstance(target, ast.Name)
        }
        modules = catalogs["benchmark_info"]
        systems = catalogs["system_info"]
        native_ids = {
            f"{system}/{module}" for system, entries in modules.items() for module in entries
        }
        if len(native_ids) != 60 or len(systems) != 4:
            raise ValueError("upstream task catalog cardinality mismatch")
        if any(
            task.native_id not in native_ids or task.top != task.native_id.split("/")[1]
            for task in lock.tasks
        ):
            raise ValueError("selected module is outside the pinned native catalog")
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0 or completed.stdout.strip() != lock.commit:
            raise ValueError("external checkout revision mismatch")
    return lock
