"""Hash-bound protocol for disposable agent-feedback synthesis workers."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from verigym.plugin_api import StrictModel

from .worker_release import COMMERCIAL_WORKER_RELEASE_PROTOCOL, CommercialWorkerRelease

AGENT_WORKER_PROTOCOL = "verigym.synopsys.dc.agent_worker.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class AgentWorkerIsolationContract(StrictModel):
    """Sanitized site promise resolved before any model call."""

    protocol: Literal["verigym.synopsys.dc.agent_worker.v1"] = "verigym.synopsys.dc.agent_worker.v1"
    isolation_kind: Literal["lsf_job", "container", "vm"]
    launcher_version: str
    code_identity_hash: str
    isolation_profile_hash: str
    disposable_worker: Literal[True] = True
    one_candidate_per_worker: Literal[True] = True
    cleanup_before_response: Literal[True] = True
    credential_scope: Literal["worker_only"] = "worker_only"
    network_policy: Literal["site_license_controlled", "none"]
    raw_artifacts_returned: Literal[False] = False
    max_wall_seconds: int = Field(ge=1, le=7200)
    memory_mb: int = Field(ge=256, le=1_048_576)
    cores: int = Field(ge=1, le=256)
    release_protocol: Literal["commercial_worker_release.v1"] | None = None
    release_hash: str | None = None

    @field_validator("code_identity_hash", "isolation_profile_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("worker isolation profile requires a lowercase SHA-256")
        return value

    @field_validator("release_hash")
    @classmethod
    def validate_release_hash(cls, value: str | None) -> str | None:
        if value is not None and _SHA256.fullmatch(value) is None:
            raise ValueError("worker release identity must be a lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_release_pair(self) -> AgentWorkerIsolationContract:
        if (self.release_protocol is None) != (self.release_hash is None):
            raise ValueError("worker release protocol and hash must be supplied together")
        if self.release_protocol not in {None, COMMERCIAL_WORKER_RELEASE_PROTOCOL}:
            raise ValueError("unsupported worker release protocol")
        return self


class AgentWorkerDescribeRequest(StrictModel):
    operation: Literal["describe"] = "describe"


class AgentWorkerDescribeResponse(StrictModel):
    protocol: Literal["verigym.synopsys.dc.agent_worker.v1"] = "verigym.synopsys.dc.agent_worker.v1"
    contract: AgentWorkerIsolationContract
    release: CommercialWorkerRelease | None = None


class AgentWorkerLaunchRequest(StrictModel):
    operation: Literal["execute"] = "execute"
    contract_hash: str
    code_identity_hash: str
    isolation_profile_hash: str
    request_hash: str
    source_bundle_hash: str
    synthesis: dict[str, Any]
    expected_release_hash: str | None = None

    @field_validator(
        "contract_hash",
        "code_identity_hash",
        "isolation_profile_hash",
        "request_hash",
        "source_bundle_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("worker request identity must be a lowercase SHA-256")
        return value

    @field_validator("expected_release_hash")
    @classmethod
    def validate_expected_release_hash(cls, value: str | None) -> str | None:
        if value is not None and _SHA256.fullmatch(value) is None:
            raise ValueError("expected worker release hash must be a lowercase SHA-256")
        return value


class AgentWorkerReceipt(StrictModel):
    contract_hash: str
    code_identity_hash: str
    isolation_profile_hash: str
    request_hash: str
    source_bundle_hash: str
    dispatch_id_hash: str
    scheduler_dispatched: bool
    worker_started: bool
    worker_completed: bool
    cleanup_complete: Literal[True] = True
    lifecycle: Literal[
        "completed_clean",
        "candidate_failed_clean",
        "infrastructure_failed_clean",
    ]
    duration_s: float = Field(ge=0, le=7200)
    release_protocol: Literal["commercial_worker_release.v1"] | None = None
    release_hash: str | None = None

    @field_validator(
        "contract_hash",
        "code_identity_hash",
        "isolation_profile_hash",
        "request_hash",
        "source_bundle_hash",
        "dispatch_id_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("worker receipt identity must be a lowercase SHA-256")
        return value

    @field_validator("release_hash")
    @classmethod
    def validate_receipt_release_hash(cls, value: str | None) -> str | None:
        if value is not None and _SHA256.fullmatch(value) is None:
            raise ValueError("worker receipt release hash must be a lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_receipt_release_pair(self) -> AgentWorkerReceipt:
        if (self.release_protocol is None) != (self.release_hash is None):
            raise ValueError("worker receipt release protocol and hash must be paired")
        if self.release_protocol not in {None, COMMERCIAL_WORKER_RELEASE_PROTOCOL}:
            raise ValueError("unsupported worker receipt release protocol")
        return self

    @model_validator(mode="after")
    def validate_lifecycle(self) -> AgentWorkerReceipt:
        if self.worker_completed and not self.worker_started:
            raise ValueError("completed worker receipt was never started")
        if self.worker_started and not self.scheduler_dispatched:
            raise ValueError("started worker receipt was never dispatched")
        if self.lifecycle == "completed_clean" and not self.worker_completed:
            raise ValueError("successful worker lifecycle did not complete")
        return self


class AgentWorkerEnvelope(StrictModel):
    protocol: Literal["verigym.synopsys.dc.agent_worker.v1"] = "verigym.synopsys.dc.agent_worker.v1"
    success: bool
    receipt: AgentWorkerReceipt
    synthesis: dict[str, Any] | None = None
    failure_category: Literal["scheduler", "worker", "response"] | None = None

    @model_validator(mode="after")
    def validate_result(self) -> AgentWorkerEnvelope:
        if self.success != (self.synthesis is not None):
            raise ValueError("worker success flag differs from its synthesis payload")
        if self.success != (self.failure_category is None):
            raise ValueError("worker failure category differs from its success flag")
        return self


__all__ = [
    "AGENT_WORKER_PROTOCOL",
    "AgentWorkerDescribeRequest",
    "AgentWorkerDescribeResponse",
    "AgentWorkerEnvelope",
    "AgentWorkerIsolationContract",
    "AgentWorkerLaunchRequest",
    "AgentWorkerReceipt",
]
