"""Strict repository profiles and external-source image locks."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator
from verigym.plugin_api import SCHEMA_VERSION, StrictModel, content_hash

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REPOSITORY_HOME = re.compile(r"^/home/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ABSOLUTE_MARKER = re.compile(r"^/home/[A-Za-z0-9][A-Za-z0-9._/-]{0,191}$")
_CACHE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$")
_MAVEN_CACHE_PREFIX = "https/repo1.maven.org/maven2/"


def _canonical_relative_path(value: str) -> str:
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("license files must use canonical relative paths")
    return value


def _canonical_marker(value: str) -> str:
    parts = value.split("/")
    if (
        not _ABSOLUTE_MARKER.fullmatch(value)
        or len(parts) < 3
        or parts[:2] != ["", "home"]
        or any(part in {"", ".", ".."} for part in parts[2:])
    ):
        raise ValueError("base marker must be a canonical absolute /home path")
    return value


def _canonical_cache_path(value: str) -> str:
    if (
        not _CACHE_PATH.fullmatch(value)
        or not value.startswith(_MAVEN_CACHE_PREFIX)
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("verifier dependencies must use canonical Maven cache paths")
    return value


def base_commit_marker(repository_home: str) -> str:
    """Return the legacy v1 per-repository HWE-Bench base-commit marker path."""

    if not _REPOSITORY_HOME.fullmatch(repository_home):
        raise ValueError("repository home must be a canonical single-component /home path")
    return f"{repository_home}_base_commit.txt"


class VerifierLimits(StrictModel):
    """Repository-specific bounds accepted by the suite-managed verifier."""

    timeout_s: int = Field(ge=1, le=3600)
    memory_bytes: int = Field(ge=256 * 1024 * 1024, le=64 * 1024 * 1024 * 1024)
    cpus: float = Field(gt=0, le=16)
    pids_limit: int = Field(ge=64, le=16_384)
    max_output_bytes: int = Field(ge=1024, le=128 * 1024 * 1024)
    reference_patch_mode: Literal["in_place_utf8_text"] = "in_place_utf8_text"


class VerifierDependencyFile(StrictModel):
    """One immutable public file required to complete an official image's offline cache."""

    cache_path: str
    sha256: str
    size_bytes: int = Field(ge=1, le=64 * 1024 * 1024)

    @field_validator("cache_path")
    @classmethod
    def canonical_cache_path(cls, value: str) -> str:
        return _canonical_cache_path(value)

    @field_validator("sha256")
    @classmethod
    def hash_value(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("verifier dependency hash must be lowercase SHA-256")
        return value


class RepositoryProfile(StrictModel):
    """Frozen executable behavior for one upstream repository family."""

    schema_version: str = SCHEMA_VERSION
    profile_id: str
    repository_id: str
    repository_home: str
    base_commit_marker: str
    baseline_identity_policy: Literal[
        "official_base_or_bound_synthetic", "digest_locked_runtime_marker"
    ]
    language: str
    license_expression: str
    license_files: list[str] = Field(min_length=1, max_length=16)
    workspace_excluded_paths: list[str] = Field(default_factory=list, max_length=16)
    verifier_dependencies: list[VerifierDependencyFile] = Field(default_factory=list, max_length=16)
    verifier_limits: VerifierLimits
    profile_hash: str

    @field_validator("repository_home")
    @classmethod
    def canonical_home(cls, value: str) -> str:
        if not _REPOSITORY_HOME.fullmatch(value):
            raise ValueError("repository home must be a canonical single-component /home path")
        return value

    @field_validator("base_commit_marker")
    @classmethod
    def canonical_marker(cls, value: str) -> str:
        return _canonical_marker(value)

    @field_validator("license_files", "workspace_excluded_paths")
    @classmethod
    def canonical_license_files(cls, values: list[str]) -> list[str]:
        normalized = [_canonical_relative_path(value) for value in values]
        if len(normalized) != len(set(normalized)) or normalized != sorted(normalized):
            raise ValueError("repository profile paths must be unique and sorted")
        return normalized

    @field_validator("verifier_dependencies")
    @classmethod
    def unique_verifier_dependencies(
        cls, values: list[VerifierDependencyFile]
    ) -> list[VerifierDependencyFile]:
        paths = [item.cache_path for item in values]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("verifier dependencies must be unique and sorted by cache path")
        return values

    @field_validator("profile_hash")
    @classmethod
    def hash_value(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("repository profile hash must be lowercase SHA-256")
        return value


def _profile(**values: object) -> RepositoryProfile:
    base = {"schema_version": SCHEMA_VERSION, **values}
    profile = RepositoryProfile.model_validate({**base, "profile_hash": "0" * 64})
    identity = profile.model_dump(mode="json")
    identity.pop("profile_hash")
    return profile.model_copy(update={"profile_hash": content_hash(identity)}, deep=True)


_DEFAULT_LIMITS = VerifierLimits(
    timeout_s=900,
    memory_bytes=16 * 1024 * 1024 * 1024,
    cpus=4.0,
    pids_limit=4096,
    max_output_bytes=32 * 1024 * 1024,
)

REPOSITORY_PROFILES: dict[str, RepositoryProfile] = {
    profile.repository_id: profile
    for profile in (
        _profile(
            profile_id="hwe-lowrisc-ibex-v1",
            repository_id="lowRISC/ibex",
            repository_home="/home/ibex",
            base_commit_marker="/home/ibex_base_commit.txt",
            baseline_identity_policy="digest_locked_runtime_marker",
            language="SystemVerilog",
            license_expression="Apache-2.0",
            license_files=["LICENSE"],
            workspace_excluded_paths=[],
            verifier_limits=_DEFAULT_LIMITS,
        ),
        _profile(
            profile_id="hwe-openhwgroup-cva6-v1",
            repository_id="openhwgroup/cva6",
            repository_home="/home/cva6",
            base_commit_marker="/home/cva6_base_commit.txt",
            baseline_identity_policy="digest_locked_runtime_marker",
            language="SystemVerilog",
            license_expression="SHL-0.51",
            license_files=["LICENSE"],
            workspace_excluded_paths=["verif/core-v-verif/vendor/riscv/riscv-isa-sim/build"],
            verifier_limits=_DEFAULT_LIMITS,
        ),
        _profile(
            profile_id="hwe-chipsalliance-rocket-chip-v1",
            repository_id="chipsalliance/rocket-chip",
            repository_home="/home/rocket-chip",
            base_commit_marker="/home/base_commit.txt",
            baseline_identity_policy="digest_locked_runtime_marker",
            language="Chisel/Scala",
            license_expression="BSD-3-Clause AND Apache-2.0",
            license_files=["LICENSE.Berkeley", "LICENSE.SiFive", "LICENSE.jtag"],
            workspace_excluded_paths=[],
            verifier_dependencies=[
                VerifierDependencyFile(
                    cache_path=(
                        "https/repo1.maven.org/maven2/org/scala-sbt/"
                        "compiler-bridge_2.12/1.3.5/"
                        "compiler-bridge_2.12-1.3.5-sources.jar"
                    ),
                    sha256="9e689ec3266a5c1a37404b84dcc680f0540c4ab35d59cdf6a81ddefe1851c8f5",
                    size_bytes=48_862,
                ),
                VerifierDependencyFile(
                    cache_path=(
                        "https/repo1.maven.org/maven2/org/scala-sbt/"
                        "util-interface/1.3.0/util-interface-1.3.0.jar"
                    ),
                    sha256="89028234b4621ac92761676a00e2e47598fcf5232a9bb994a7ed6dee94eb5aa2",
                    size_bytes=2_571,
                ),
                VerifierDependencyFile(
                    cache_path=(
                        "https/repo1.maven.org/maven2/org/scala-sbt/"
                        "util-interface/1.3.0/util-interface-1.3.0.pom"
                    ),
                    sha256="984601d455b24a730455bd093dbd81aca7a829fcf003de3ab50309373ec3301e",
                    size_bytes=2_775,
                ),
            ],
            verifier_limits=_DEFAULT_LIMITS,
        ),
    )
}


def repository_profile(repository_id: str) -> RepositoryProfile:
    """Return a copy of one supported profile, rejecting implicit repository behavior."""

    try:
        profile = REPOSITORY_PROFILES[repository_id]
    except KeyError as exc:
        raise ValueError(f"HWE-Bench has no executable profile for {repository_id}") from exc
    identity = profile.model_dump(mode="json")
    expected = identity.pop("profile_hash")
    if content_hash(identity) != expected:
        raise ValueError("built-in HWE-Bench repository profile identity changed")
    return profile.model_copy(deep=True)


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
    def repository_id(self) -> str:
        return f"{self.org}/{self.repo}"

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


class LicenseFileLock(StrictModel):
    path: str
    sha256: str

    @field_validator("path")
    @classmethod
    def canonical_path(cls, value: str) -> str:
        return _canonical_relative_path(value)

    @field_validator("sha256")
    @classmethod
    def hash_value(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("license file hash must be lowercase SHA-256")
        return value


class _ImageLockEntryBase(StrictModel):
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

    @field_validator(
        "repository_hash",
        "reference_repository_hash",
        "reference_candidate_hash",
        "reference_patch_hash",
        "verifier_payload_hash",
        "task_bundle_hash",
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
    def bind_identity(self) -> _ImageLockEntryBase:
        if not _REPOSITORY_HOME.fullmatch(self.repository_home):
            raise ValueError("repository home must be a canonical single-component /home path")
        if not self.image_reference.startswith("ghcr.io/pku-liang/"):
            raise ValueError("HWE-Bench accepts only the official GHCR namespace")
        return self


class ImageLockEntry(_ImageLockEntryBase):
    """Legacy v1 lock entry retained for prepared-source compatibility."""

    license_file_hash: str

    @field_validator("license_file_hash")
    @classmethod
    def license_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("image-lock content hashes must be lowercase SHA-256")
        return value


class ImageLockEntryV2(_ImageLockEntryBase):
    """Profile-bound lock entry with marker and complete license inventory."""

    base_commit_marker: str
    repository_profile_hash: str
    license_inventory: list[LicenseFileLock] = Field(min_length=1, max_length=16)
    verifier_dependencies: list[VerifierDependencyFile] = Field(default_factory=list, max_length=16)

    @field_validator("base_commit_marker")
    @classmethod
    def canonical_marker(cls, value: str) -> str:
        return _canonical_marker(value)

    @field_validator("repository_profile_hash")
    @classmethod
    def profile_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("repository profile hash must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def unique_license_inventory(self) -> ImageLockEntryV2:
        paths = [item.path for item in self.license_inventory]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("license inventory must be unique and sorted by path")
        dependency_paths = [item.cache_path for item in self.verifier_dependencies]
        if dependency_paths != sorted(dependency_paths) or len(dependency_paths) != len(
            set(dependency_paths)
        ):
            raise ValueError("verifier dependencies must be unique and sorted by cache path")
        return self


class ImageLock(StrictModel):
    """Legacy v1 source lock retained exactly for prepared-source compatibility."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_bench_source_v1"] = "verigym_hwe_bench_source_v1"
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


class ImageLockV2(StrictModel):
    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_bench_source_v2"] = "verigym_hwe_bench_source_v2"
    official_dataset_sha256: str
    official_dataset_revision: str | None = None
    official_source_commit: str | None = None
    entries: list[ImageLockEntryV2] = Field(min_length=1, max_length=417)

    @field_validator("official_dataset_sha256")
    @classmethod
    def dataset_hash(cls, value: str) -> str:
        return ImageLock.dataset_hash(value)

    @field_validator("official_dataset_revision", "official_source_commit")
    @classmethod
    def source_commit(cls, value: str | None) -> str | None:
        return ImageLock.source_commit(value)

    @model_validator(mode="after")
    def unique_entries(self) -> ImageLockV2:
        identities = [entry.instance_id for entry in self.entries]
        if len(identities) != len(set(identities)):
            raise ValueError("image-lock instance IDs must be unique")
        return self


ImageLockEntryType = ImageLockEntry | ImageLockEntryV2
ImageLockType = ImageLock | ImageLockV2

__all__ = [
    "HweInstance",
    "ImageLock",
    "ImageLockEntry",
    "ImageLockEntryType",
    "ImageLockEntryV2",
    "ImageLockType",
    "ImageLockV2",
    "LicenseFileLock",
    "REPOSITORY_PROFILES",
    "RepositoryProfile",
    "VerifierLimits",
    "VerifierDependencyFile",
    "base_commit_marker",
    "repository_profile",
]
