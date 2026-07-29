"""Strict schemas for repository-level RTL repair tasks and candidates."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.task import VeriTask

_HASH = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _relative_path(value: str, *, root_allowed: bool = False) -> str:
    if (
        not value
        or value != value.strip()
        or "\x00" in value
        or "\\" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("repository paths must be nonempty canonical POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("repository paths must be relative and may not traverse parents")
    normalized = PurePosixPath(*(part for part in path.parts if part not in {"", "."})).as_posix()
    if normalized == "." and not root_allowed:
        raise ValueError("repository path must name a file or directory")
    if normalized != value:
        raise ValueError("repository paths must already be normalized")
    return value


def _glob(value: str) -> str:
    return _relative_path(value)


class RepositorySourceIdentity(StrictModel):
    """Frozen visible base-repository provenance."""

    schema_version: str = SCHEMA_VERSION
    source_kind: Literal["package_resource", "user_path"]
    repository_hash: str
    task_bundle_hash: str
    upstream_url: str | None = None
    upstream_revision: str | None = None
    license: str
    license_file: str
    license_file_hash: str
    attribution: str
    redistributable: bool

    @field_validator("repository_hash", "task_bundle_hash", "license_file_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("repository source hashes must be lowercase SHA-256")
        return value

    @field_validator("license_file")
    @classmethod
    def validate_license_file(cls, value: str) -> str:
        return _relative_path(value)

    @field_validator("upstream_url")
    @classmethod
    def validate_upstream_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            value != value.strip()
            or not value.startswith(("https://", "ssh://"))
            or "@" in value.partition("://")[2].partition("/")[0]
            or any(marker in value.lower() for marker in ("token=", "key=", "password="))
        ):
            raise ValueError("upstream URL must be sanitized, credential-free metadata")
        return value


class RepositoryWorkspaceContract(StrictModel):
    """Visible path classes and fail-closed repository patch limits."""

    schema_version: str = SCHEMA_VERSION
    repository_root: Literal["repository"] = "repository"
    editable_globs: list[str] = Field(min_length=1)
    read_only_globs: list[str] = Field(min_length=1)
    runtime_generated_globs: list[str] = Field(default_factory=list)
    forbidden_globs: list[str] = Field(min_length=1)
    max_changed_files: int = Field(ge=1, le=256)
    max_patch_lines: int = Field(ge=1, le=100_000)
    max_candidate_bytes: int = Field(ge=1, le=256 * 1024 * 1024)
    max_file_bytes: int = Field(ge=1, le=64 * 1024 * 1024)
    allow_file_addition: bool = False
    allow_file_deletion: bool = False
    allow_file_rename: Literal[False] = False
    allow_mode_change: Literal[False] = False
    allow_binary_files: Literal[False] = False
    case_sensitive_paths: Literal[True] = True

    @field_validator(
        "editable_globs",
        "read_only_globs",
        "runtime_generated_globs",
        "forbidden_globs",
    )
    @classmethod
    def validate_globs(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("repository workspace globs must be unique")
        return sorted(_glob(value) for value in values)

    @model_validator(mode="after")
    def validate_path_classes(self) -> RepositoryWorkspaceContract:
        if any(not value.startswith("repository/") for value in self.editable_globs):
            raise ValueError("repository editable globs must remain below repository/")
        classes = {
            "editable": set(self.editable_globs),
            "read_only": set(self.read_only_globs),
            "runtime_generated": set(self.runtime_generated_globs),
            "forbidden": set(self.forbidden_globs),
        }
        for left_name, left in classes.items():
            for right_name, right in classes.items():
                if left_name >= right_name:
                    continue
                if left & right:
                    raise ValueError(
                        f"repository {left_name} and {right_name} globs may not overlap exactly"
                    )
        return self


class PublicTestCommand(StrictModel):
    """One shell-free, hash-bound public-test subprocess."""

    argv: list[str] = Field(min_length=1, max_length=64)
    cwd: Literal["repository", "build"] = "repository"
    timeout_s: int = Field(ge=1, le=300)
    expected_exit_code: int = Field(default=0, ge=0, le=255)

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, values: list[str]) -> list[str]:
        if any(
            not value or len(value) > 4096 or "\x00" in value or "\r" in value or "\n" in value
            for value in values
        ):
            raise ValueError("public-test argv contains an invalid argument")
        if values[0] not in {"iverilog", "vvp"}:
            raise ValueError("public tests may invoke only exact Icarus 12 executables")
        for value in values[1:]:
            if value.startswith("/"):
                raise ValueError("public-test argv may not contain undeclared absolute paths")
            if ("{" in value or "}" in value) and not value.startswith(
                ("{repository}/", "{public}/", "{build}/")
            ):
                raise ValueError("public-test argv contains an unknown path placeholder")
        return values


class PublicTestCase(StrictModel):
    id: str
    title: str
    commands: list[PublicTestCommand] = Field(min_length=1, max_length=16)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("public-test IDs must use the safe identifier vocabulary")
        return value


class RepositoryPublicTestContract(StrictModel):
    """Trusted launcher contract mounted read-only at a fixed path."""

    schema_version: str = SCHEMA_VERSION
    protocol: Literal["verigym_public_test_v1"] = "verigym_public_test_v1"
    contract_file: Literal["test-contract.json"] = "test-contract.json"
    mount_destination: Literal["/verigym-public"] = "/verigym-public"
    public_assets_hash: str
    asset_files: dict[str, str] = Field(min_length=1, max_length=256)
    max_feedback_bytes: int = Field(default=64 * 1024, ge=1024, le=1024 * 1024)
    max_build_bytes: int = Field(default=32 * 1024 * 1024, ge=1024, le=512 * 1024 * 1024)
    tests: list[PublicTestCase] = Field(min_length=1, max_length=64)

    @field_validator("public_assets_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("public-assets hash must be lowercase SHA-256")
        return value

    @field_validator("asset_files")
    @classmethod
    def validate_asset_files(cls, values: dict[str, str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for path, digest in values.items():
            normalized = _relative_path(path)
            if not normalized.startswith("assets/"):
                raise ValueError("public-test assets must remain below assets/")
            if not _HASH.fullmatch(digest):
                raise ValueError("public-test asset hashes must be lowercase SHA-256")
            result[normalized] = digest
        return dict(sorted(result.items()))

    @model_validator(mode="after")
    def unique_tests(self) -> RepositoryPublicTestContract:
        identifiers = [test.id for test in self.tests]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("public-test IDs must be unique")
        return self


class RepositoryVerificationContract(StrictModel):
    schema_version: str = SCHEMA_VERSION
    hidden_verifier_hash: str
    verifier_image_profile: Literal["iverilog12_network_none"]
    reference_candidate_hash: str
    reference_patch_hash: str

    @field_validator(
        "hidden_verifier_hash",
        "reference_candidate_hash",
        "reference_patch_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("verification identities must be lowercase SHA-256")
        return value


class RepositoryTaskManifest(StrictModel):
    """Complete repository-task binding used by the generic suite adapter."""

    schema_version: str = SCHEMA_VERSION
    task: VeriTask
    issue_file: Literal["issue.md"] = "issue.md"
    issue_hash: str
    source: RepositorySourceIdentity
    workspace: RepositoryWorkspaceContract
    public_tests: RepositoryPublicTestContract
    verification: RepositoryVerificationContract

    @field_validator("issue_hash")
    @classmethod
    def validate_issue_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("issue hash must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def bind_canonical_task(self) -> RepositoryTaskManifest:
        if self.task.task_type.value != "repo_repair":
            raise ValueError("repository manifests require task_type=repo_repair")
        if (
            self.task.workspace.base.kind != "directory"
            or self.task.workspace.base.path != self.workspace.repository_root
        ):
            raise ValueError("canonical workspace base must be the visible repository root")
        if self.task.source.content_hash != self.source.repository_hash:
            raise ValueError("canonical and repository source hashes disagree")
        if (
            self.task.source.license != self.source.license
            or self.task.source.attribution != self.source.attribution
        ):
            raise ValueError("canonical and repository license provenance disagree")
        if self.task.workspace.editable_globs != self.workspace.editable_globs:
            raise ValueError("canonical and repository editable-glob contracts disagree")
        if self.task.workspace.readonly_globs != self.workspace.read_only_globs:
            raise ValueError("canonical and repository read-only-glob contracts disagree")
        if self.task.workspace.max_changed_files != self.workspace.max_changed_files:
            raise ValueError("canonical and repository changed-file limits disagree")
        if self.task.workspace.max_patch_lines != self.workspace.max_patch_lines:
            raise ValueError("canonical and repository patch-line limits disagree")
        if self.task.budget.max_workspace_bytes != self.workspace.max_candidate_bytes:
            raise ValueError("canonical and repository workspace-byte budgets disagree")
        if (
            [mode.value for mode in self.task.interaction.supported_modes] != ["agent"]
            or self.task.interaction.default_mode.value != "agent"
            or self.task.interaction.allow_general_shell
            or self.task.interaction.network_policy != "none"
        ):
            raise ValueError(
                "repository tasks require agent-only shell-free network-none execution"
            )
        if "repository.public_test" not in self.task.interaction.allowed_tools:
            raise ValueError("repository tasks must expose the trusted public-test tool")
        if self.task.interaction.final_submission.kind != "patch":
            raise ValueError("repository tasks require patch final submission")
        return self


class RepositoryFileIdentity(StrictModel):
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_path(value)

    @field_validator("sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("file identity must contain a lowercase SHA-256")
        return value


class RepositorySnapshot(StrictModel):
    schema_version: str = SCHEMA_VERSION
    repository_hash: str
    total_bytes: int = Field(ge=0)
    files: list[RepositoryFileIdentity]

    @field_validator("repository_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("repository snapshot hash must be lowercase SHA-256")
        return value


class RepositoryPatchSummary(StrictModel):
    schema_version: str = SCHEMA_VERSION
    patch_hash: str
    base_repository_hash: str
    candidate_repository_hash: str
    reapplied_repository_hash: str
    reapply_exact: Literal[True]
    changed_files: list[str]
    added_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    renamed_files: list[str] = Field(default_factory=list)
    mode_changed_files: list[str] = Field(default_factory=list)
    binary_files: list[str] = Field(default_factory=list)
    created_file_count: int = Field(ge=0)
    deleted_file_count: int = Field(ge=0)
    added_lines: int = Field(ge=0)
    deleted_lines: int = Field(ge=0)
    policy_status: Literal["passed"]

    @field_validator(
        "patch_hash",
        "base_repository_hash",
        "candidate_repository_hash",
        "reapplied_repository_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("repository patch identities must be lowercase SHA-256")
        return value

    @field_validator(
        "changed_files",
        "added_files",
        "deleted_files",
        "renamed_files",
        "mode_changed_files",
        "binary_files",
    )
    @classmethod
    def validate_paths(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("repository patch path lists must be unique")
        return sorted(_relative_path(value) for value in values)


class RepositoryCandidateRecord(StrictModel):
    schema_version: str = SCHEMA_VERSION
    task_id: str
    base: RepositorySnapshot
    candidate: RepositorySnapshot
    patch: RepositoryPatchSummary
    public_test_ids: list[str]
    hidden_assets_present: Literal[False]
    reference_patch_used: Literal[False]


class RepositoryPublicTestOutcome(StrictModel):
    """Bounded result from the trusted public-test launcher."""

    schema_version: str = SCHEMA_VERSION
    test_id: str
    passed: bool
    category: str
    exit_code: int | None = None
    duration_s: float = Field(ge=0.0)
    output_truncated: bool
    stdout_sha256: str
    stderr_sha256: str
    launcher_protocol: Literal["verigym_public_test_v1"]
    public_assets_read_only: bool
    network_policy: Literal["none", "host_local_trusted"]

    @field_validator("stdout_sha256", "stderr_sha256")
    @classmethod
    def validate_output_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("public-test output identities must be lowercase SHA-256")
        return value


class RepositoryPlanIdentity(StrictModel):
    """Credential-free repository task identity persisted in plans and runs."""

    schema_version: str = SCHEMA_VERSION
    manifest_hash: str
    task_bundle_hash: str
    source_identity_hash: str
    license_file_hash: str
    base_repository_hash: str
    issue_hash: str
    workspace_contract_hash: str
    public_assets_hash: str
    public_mount_hash: str
    hidden_verifier_hash: str
    reference_candidate_hash: str
    reference_patch_hash: str

    @field_validator(
        "manifest_hash",
        "task_bundle_hash",
        "source_identity_hash",
        "license_file_hash",
        "base_repository_hash",
        "issue_hash",
        "workspace_contract_hash",
        "public_assets_hash",
        "public_mount_hash",
        "hidden_verifier_hash",
        "reference_candidate_hash",
        "reference_patch_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("repository plan identities must be lowercase SHA-256")
        return value


__all__ = [
    "PublicTestCase",
    "PublicTestCommand",
    "RepositoryCandidateRecord",
    "RepositoryFileIdentity",
    "RepositoryPatchSummary",
    "RepositoryPlanIdentity",
    "RepositoryPublicTestContract",
    "RepositoryPublicTestOutcome",
    "RepositorySnapshot",
    "RepositorySourceIdentity",
    "RepositoryTaskManifest",
    "RepositoryVerificationContract",
    "RepositoryWorkspaceContract",
]
