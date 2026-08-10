"""Strict external-source and image-lock models."""

from __future__ import annotations

import re

from pydantic import Field, field_validator, model_validator
from verigym.plugin_api import SCHEMA_VERSION, StrictModel

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class HweInstance(StrictModel):
    """Minimal official record; hidden fields remain outside the installed distribution."""

    schema_version: str = SCHEMA_VERSION
    org: str
    repo: str
    number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=1024)
    problem_statement: str = Field(min_length=1, max_length=128 * 1024)
    base_commit: str
    fix_patch: str = Field(min_length=1, max_length=4 * 1024 * 1024)
    test_patch: str = Field(default="", max_length=4 * 1024 * 1024)
    tb_script: str = Field(min_length=1, max_length=8 * 1024 * 1024)
    modified_files: list[str] = Field(min_length=1, max_length=256)
    expected_test_ids: list[str] = Field(min_length=1, max_length=256)
    language: str = "SystemVerilog"
    license_id: str = "Apache-2.0"

    @property
    def instance_id(self) -> str:
        return f"{self.org}/{self.repo}:pr-{self.number}"

    @property
    def slug(self) -> str:
        return f"{self.org}__{self.repo}__pr-{self.number}"

    @field_validator("org", "repo")
    @classmethod
    def safe_component(cls, value: str) -> str:
        if not _SAFE_COMPONENT.fullmatch(value):
            raise ValueError("HWE-Bench organization and repository names must be safe")
        return value

    @field_validator("base_commit")
    @classmethod
    def commit_hash(cls, value: str) -> str:
        if not _COMMIT.fullmatch(value):
            raise ValueError("HWE-Bench base commit must be a full Git SHA")
        return value

    @field_validator("modified_files")
    @classmethod
    def canonical_paths(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("modified files must be unique")
        for value in values:
            if not value or value.startswith("/") or "\\" in value or ".." in value.split("/"):
                raise ValueError("modified files must be canonical relative paths")
        return sorted(values)

    @field_validator("expected_test_ids")
    @classmethod
    def canonical_test_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(
            not value or len(value) > 256 for value in values
        ):
            raise ValueError("expected test IDs must be unique bounded strings")
        return sorted(values)


class ImageLockEntry(StrictModel):
    schema_version: str = SCHEMA_VERSION
    instance_id: str
    slug: str
    image_reference: str
    manifest_digest: str
    image_id: str
    repository_home: str
    base_commit: str
    repository_hash: str
    reference_repository_hash: str
    reference_candidate_hash: str
    reference_patch_hash: str
    verifier_payload_hash: str
    task_bundle_hash: str
    license_file_hash: str

    @field_validator(
        "repository_hash",
        "reference_repository_hash",
        "reference_candidate_hash",
        "reference_patch_hash",
        "verifier_payload_hash",
        "task_bundle_hash",
        "license_file_hash",
    )
    @classmethod
    def sha256_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("image-lock content hashes must be lowercase SHA-256")
        return value

    @field_validator("image_id")
    @classmethod
    def exact_image_id(cls, value: str) -> str:
        if not _IMAGE_ID.fullmatch(value):
            raise ValueError("image ID must be an immutable sha256 identifier")
        return value

    @field_validator("manifest_digest")
    @classmethod
    def exact_manifest_digest(cls, value: str) -> str:
        if not _DIGEST.fullmatch(value):
            raise ValueError("manifest digest must be an immutable sha256 digest")
        return value

    @field_validator("base_commit")
    @classmethod
    def base_sha(cls, value: str) -> str:
        if not _COMMIT.fullmatch(value):
            raise ValueError("image-lock base commit must be a full Git SHA")
        return value

    @model_validator(mode="after")
    def bind_identity(self) -> ImageLockEntry:
        if not self.repository_home.startswith("/home/") or ".." in self.repository_home.split("/"):
            raise ValueError("repository home must be a canonical /home path")
        if not self.image_reference.startswith("ghcr.io/pku-liang/"):
            raise ValueError("initial HWE-Bench profile accepts only the official GHCR namespace")
        return self


class ImageLock(StrictModel):
    schema_version: str = SCHEMA_VERSION
    format_id: str = "verigym_hwe_bench_source_v1"
    official_dataset_sha256: str
    official_source_commit: str | None = None
    entries: list[ImageLockEntry] = Field(min_length=1, max_length=417)

    @field_validator("official_dataset_sha256")
    @classmethod
    def dataset_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("official dataset hash must be lowercase SHA-256")
        return value

    @field_validator("official_source_commit")
    @classmethod
    def source_commit(cls, value: str | None) -> str | None:
        if value is not None and not _COMMIT.fullmatch(value):
            raise ValueError("official source commit must be a full Git SHA")
        return value

    @model_validator(mode="after")
    def unique_entries(self) -> ImageLock:
        identities = [entry.instance_id for entry in self.entries]
        if len(identities) != len(set(identities)):
            raise ValueError("image-lock instance IDs must be unique")
        return self


__all__ = ["HweInstance", "ImageLock", "ImageLockEntry"]
