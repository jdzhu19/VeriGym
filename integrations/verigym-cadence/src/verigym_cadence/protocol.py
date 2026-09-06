"""Bounded candidate-only protocol. Site assets and executable choices are server-owned."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from verigym.plugin_api import StrictModel, content_hash, hash_bytes

PROTOCOL: Literal["verigym.cadence.jaspergold.sec.mcp.v1"] = "verigym.cadence.jaspergold.sec.mcp.v1"
VERSION: Literal["0.1.0"] = "0.1.0"
MCP_VERSION = "2024-11-05"
SERVER_NAME = "verigym-cadence"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_REQUEST_BYTES = 48 * 1024 * 1024
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Status = Literal[
    "proven",
    "counterexample",
    "inconclusive",
    "candidate_compile_failure",
    "timeout",
    "license_unavailable",
    "tool_unavailable",
    "infrastructure_failure",
]


def relative_path(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", value):
        raise ValueError("unsafe relative path")
    if any(part in {".", ".."} or part.startswith(".") for part in value.split("/")):
        raise ValueError("unsafe relative path component")
    return value


def bounded_read(path: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    """Reject symlinks in every component, special files, and oversized assets."""
    absolute = path.absolute()
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ValueError("symlink asset is forbidden")
    if not absolute.is_file() or absolute.stat().st_size > limit:
        raise ValueError("asset must be a bounded regular file")
    with absolute.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("asset grew beyond its byte bound")
    return payload


def asset_digest(path: Path) -> str:
    """Hash large tool binaries incrementally; candidate payloads retain the smaller bound."""
    absolute = path.absolute()
    limit = 512 * 1024 * 1024
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ValueError("symlink asset is forbidden")
    if not absolute.is_file() or absolute.stat().st_size > limit:
        raise ValueError("site asset must be a bounded regular file")
    digest = hashlib.sha256()
    count = 0
    with absolute.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            if count > limit:
                raise ValueError("site asset grew beyond its bound")
            digest.update(chunk)
    return digest.hexdigest()


def unique_json(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=pairs)


class Source(StrictModel):
    path: str
    sha256: Digest
    content_base64: str = Field(max_length=12 * 1024 * 1024)

    @field_validator("path")
    @classmethod
    def source_path(cls, value: str) -> str:
        relative_path(value)
        if Path(value).suffix not in {".v", ".sv", ".vh", ".svh"}:
            raise ValueError("candidate input must be RTL")
        return value

    def decode(self) -> bytes:
        payload = base64.b64decode(self.content_base64, validate=True)
        if len(payload) > MAX_FILE_BYTES or hash_bytes(payload) != self.sha256:
            raise ValueError("candidate content identity mismatch")
        if base64.b64encode(payload).decode("ascii") != self.content_base64:
            raise ValueError("noncanonical base64")
        return payload


class IdentityRequest(StrictModel):
    profile_id: str
    declared_profile_hash: Digest
    contract_hash: Digest
    expected_resolved_profile_hash: Digest | None = None


class VerifyRequest(IdentityRequest):
    task_id: str
    top: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    candidate_hash: Digest
    sources: list[Source] = Field(min_length=1, max_length=64)

    def candidate(self) -> dict[str, bytes]:
        decoded: dict[str, bytes] = {}
        total = 0
        for item in self.sources:
            if item.path in decoded:
                raise ValueError("duplicate candidate path")
            payload = item.decode()
            total += len(payload)
            if total > MAX_TOTAL_BYTES:
                raise ValueError("candidate exceeds aggregate byte bound")
            decoded[item.path] = payload
        if content_hash({"sources": {k: hash_bytes(v) for k, v in decoded.items()}}) != (
            self.candidate_hash
        ):
            raise ValueError("candidate bundle identity mismatch")
        return decoded


class Asset(StrictModel):
    """Private approved asset; only its role and content hash enter the public contract."""

    role: str
    path: str
    sha256: Digest

    @field_validator("path")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("site asset paths must be absolute")
        return value


class ServerProfile(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    version: str
    task_id: str
    top: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    sources: list[str] = Field(min_length=1, max_length=64)
    tool_version: str
    yosys_version: str
    worker: Asset
    assets: list[Asset] = Field(min_length=1, max_length=128)
    timeout_s: int = Field(default=300, ge=1, le=3600)
    # MVP intentionally accepts only pre-audited candidates, not arbitrary generated RTL.
    approved_candidate_hashes: list[Digest] = Field(min_length=1, max_length=256)

    @field_validator("sources")
    @classmethod
    def source_paths(cls, values: list[str]) -> list[str]:
        for value in values:
            Source.source_path(value)
        if len(set(values)) != len(values):
            raise ValueError("duplicate profile source")
        return values

    @model_validator(mode="after")
    def unique_roles(self) -> ServerProfile:
        roles = [asset.role for asset in self.assets]
        if len(roles) != len(set(roles)):
            raise ValueError("duplicate asset role")
        return self

    def contract(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL,
            "server_version": VERSION,
            **self.model_dump(exclude={"worker", "assets"}),
            "worker_sha256": self.worker.sha256,
            "assets": [{"role": a.role, "sha256": a.sha256} for a in self.assets],
        }

    def resolve(self) -> Summary:
        for asset in [self.worker, *self.assets]:
            if asset_digest(Path(asset.path)) != asset.sha256:
                raise ValueError("server asset identity mismatch")
        if not os.access(self.worker.path, os.X_OK):
            raise ValueError("fixed worker is not executable")
        release = content_hash(
            {
                path.name: hash_bytes(bounded_read(path))
                for path in sorted(Path(__file__).parent.glob("*.py"))
            }
        )
        # Site path and environment values are neither disclosed nor hashed.
        contract_hash = content_hash(self.contract())
        return Summary(
            profile_id=self.id,
            task_id=self.task_id,
            tool_version=self.tool_version,
            yosys_version=self.yosys_version,
            sources=self.sources,
            top=self.top,
            declared_profile_hash=contract_hash,
            contract_hash=contract_hash,
            resolved_profile_hash=content_hash({"contract": contract_hash, "release": release}),
            server_release_hash=release,
        )


class Summary(StrictModel):
    protocol: Literal["verigym.cadence.jaspergold.sec.mcp.v1"] = PROTOCOL
    server_version: Literal["0.1.0"] = VERSION
    profile_id: str
    task_id: str
    tool_version: str
    yosys_version: str
    sources: list[str]
    top: str
    declared_profile_hash: Digest
    contract_hash: Digest
    resolved_profile_hash: Digest
    server_release_hash: Digest


class Outcome(StrictModel):
    status: Status


class VerifyResponse(StrictModel):
    profile: Summary
    candidate_hash: Digest
    outcome: Outcome


def load_profile(path: Path) -> ServerProfile:
    return ServerProfile.model_validate(unique_json(bounded_read(path, 1024 * 1024).decode()))
