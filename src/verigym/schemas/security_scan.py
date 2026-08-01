"""Persistent schemas for context-aware artifact security scanning."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from verigym.schemas.base import StrictModel

ArtifactContentClass = Literal[
    "runtime_artifact",
    "trajectory_dataset",
    "memory_pack",
    "allowed_synthesis_corpus",
    "schema_or_contract",
    "documentation",
    "security_scan_fixture",
    "binary_build_artifact",
    "unknown",
]
StructuredFieldRole = Literal[
    "field_name",
    "environment_variable_name",
    "authentication_mode",
    "execution_boundary_enum",
    "boolean_policy",
    "null_policy",
    "known_hash_or_digest",
    "known_identifier",
    "normalized_base_url",
    "enum_or_identifier",
    "boolean_or_null_policy",
    "known_hash_identity",
    "known_path_identity",
    "documentation_text",
    "runtime_value",
    "credential_value_candidate",
    "unknown_value",
]
SecuritySeverity = Literal[
    "hard_secret_leak",
    "diagnostic_security_metadata",
    "diagnostic_security_vocabulary",
    "scanner_error",
]
SecretEvidenceCategory = Literal[
    "authorization_bearer",
    "provider_api_token",
    "session_or_cookie",
    "private_key",
    "credential_bearing_uri",
    "persisted_secret_assignment",
    "unknown_sensitive_high_entropy",
    "persisted_proxy_value",
    "raw_host_path",
    "diagnostic_security_metadata",
    "conceptual_security_vocabulary",
    "malformed_structured_artifact",
    "unsafe_filesystem_entry",
    "unsupported_or_oversized_artifact",
]
ArtifactParser = Literal[
    "json",
    "jsonl",
    "yaml",
    "toml",
    "csv",
    "markdown",
    "text",
    "binary",
]


class SecurityScanPolicy(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    policy_id: str = Field(min_length=1, max_length=100)
    max_files: int = Field(ge=1, le=1_000_000)
    max_file_bytes: int = Field(ge=1, le=1024 * 1024 * 1024)
    max_total_bytes: int = Field(ge=1, le=8 * 1024 * 1024 * 1024)
    provider_token_min_length: int = Field(ge=12, le=256)
    unknown_sensitive_min_length: int = Field(ge=16, le=4096)
    unknown_sensitive_min_entropy_bits_per_character: float = Field(ge=2.0, le=8.0)
    structured_extensions: tuple[str, ...]
    placeholder_policy: Literal["fixture_provenance_only"]
    private_value_reporting: Literal["length_and_sha256_only", "length_only_never_hash"]
    proxy_value_reporting: Literal["presence_only_never_hash"]
    malformed_structured_policy: Literal["fail_closed"]
    unknown_finding_policy: Literal["fail_closed"]
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SecurityFinding(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    relative_path: str = Field(min_length=1, max_length=4096)
    artifact_content_class: ArtifactContentClass
    structured_field_path: str | None = Field(default=None, max_length=4096)
    field_role: StructuredFieldRole
    evidence_category: SecretEvidenceCategory
    severity: SecuritySeverity
    value_length: int | None = Field(default=None, ge=0)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    redacted: Literal[True] = True
    recoverable_fragment_exported: Literal[False] = False
    rationale_code: str = Field(min_length=1, max_length=160)

    @field_validator("relative_path")
    @classmethod
    def _relative_path_only(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or ".." in value.replace("\\", "/").split("/"):
            raise ValueError("security finding paths must be relative and traversal-free")
        return value

    @model_validator(mode="after")
    def _proxy_values_are_never_hashed(self) -> SecurityFinding:
        if self.evidence_category == "persisted_proxy_value" and self.evidence_sha256 is not None:
            raise ValueError("proxy values must never be persisted or hashed")
        if (
            self.severity in {"diagnostic_security_metadata", "diagnostic_security_vocabulary"}
            and self.evidence_sha256 is not None
        ):
            raise ValueError("diagnostic security metadata must not hash source vocabulary")
        return self


class ArtifactSecurityScan(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    relative_path: str = Field(min_length=1, max_length=4096)
    artifact_content_class: ArtifactContentClass
    parser: ArtifactParser
    size_bytes: int = Field(ge=0)
    structured: bool
    fields_examined: int = Field(ge=0)
    hard_secret_leak_count: int = Field(ge=0)
    diagnostic_security_vocabulary_count: int = Field(ge=0)
    scanner_error_count: int = Field(ge=0)
    scan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SecurityScanReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(min_length=1, max_length=160)
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    root_count: int = Field(ge=1)
    scanned_files: int = Field(ge=0)
    scanned_bytes: int = Field(ge=0)
    structured_files: int = Field(ge=0)
    binary_files: int = Field(ge=0)
    hard_secret_leak_count: int = Field(ge=0)
    diagnostic_security_vocabulary_count: int = Field(ge=0)
    scanner_error_count: int = Field(ge=0)
    proxy_values_persisted_or_hashed: Literal[False] = False
    raw_suspected_values_exported: Literal[False] = False
    findings: tuple[SecurityFinding, ...]
    artifacts: tuple[ArtifactSecurityScan, ...]
    gate: Literal["pass", "fail"]
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _counts_and_gate_match(self) -> SecurityScanReport:
        hard = sum(item.severity == "hard_secret_leak" for item in self.findings)
        diagnostic = sum(
            item.severity in {"diagnostic_security_metadata", "diagnostic_security_vocabulary"}
            for item in self.findings
        )
        errors = sum(item.severity == "scanner_error" for item in self.findings)
        if (
            hard != self.hard_secret_leak_count
            or diagnostic != self.diagnostic_security_vocabulary_count
            or errors != self.scanner_error_count
        ):
            raise ValueError("security scan finding counts are inconsistent")
        expected_gate = "pass" if hard == 0 and errors == 0 else "fail"
        if self.gate != expected_gate:
            raise ValueError("security scan gate is inconsistent with findings")
        return self


__all__ = [
    "ArtifactContentClass",
    "ArtifactParser",
    "ArtifactSecurityScan",
    "SecretEvidenceCategory",
    "SecurityFinding",
    "SecurityScanPolicy",
    "SecurityScanReport",
    "SecuritySeverity",
    "StructuredFieldRole",
]
