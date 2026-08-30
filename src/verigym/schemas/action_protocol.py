"""Versioned identities and records for canonical repository actions."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

RepositoryActionTransport = Literal["json_content", "native_tool_call"]
RepositoryActionStateMachine = Literal[
    "repository_action_state_machine_v1",
    "repository_action_state_machine_v2",
    "repository_action_state_machine_v3",
]
RepositoryActionState = Literal[
    "awaiting_action",
    "candidate_modified",
    "public_test_observed",
    "compile_observed",
    "ppa_observed",
    "diff_observed",
    "finished",
]
RepositoryProtocolError = Literal[
    "agent_empty_output",
    "agent_malformed_json",
    "agent_non_object_json",
    "agent_extra_prose",
    "agent_multiple_actions",
    "agent_unknown_action",
    "agent_invalid_arguments",
    "agent_unsupported_transport",
    "agent_response_oversized",
    "agent_turn_budget_exhausted",
    "agent_invalid_state_transition",
    "agent_finish_invalid",
]


def _default_transports() -> list[RepositoryActionTransport]:
    return ["json_content", "native_tool_call"]


class RepositoryActionProtocolSpec(StrictModel):
    """Static plugin declaration consumed by the generic resolver."""

    schema_version: str = SCHEMA_VERSION
    protocol_id: Literal["repository_action.v2"] = "repository_action.v2"
    protocol_version: Literal["2.0.0"] = "2.0.0"
    registry_version: Literal["2.0.0"] = "2.0.0"
    prompt_contract_id: Literal[
        "repository_action_v2_prompt_v1",
        "repository_action_v2_prompt_v2",
        "repository_action_v2_prompt_v3",
        "repository_action_v2_prompt_v4",
        "repository_action_v2_prompt_v5",
        "repository_action_v2_prompt_v6",
        "repository_action_v2_prompt_v7",
    ] = "repository_action_v2_prompt_v2"
    normalizer_id: Literal["repository_action_json_representation_v1"] = (
        "repository_action_json_representation_v1"
    )
    state_machine_id: RepositoryActionStateMachine = "repository_action_state_machine_v2"
    default_transport: RepositoryActionTransport = "json_content"
    supported_transports: list[RepositoryActionTransport] = Field(
        default_factory=_default_transports
    )
    default_max_completion_calls: int = Field(default=6, ge=1, le=128)
    default_max_response_bytes: int = Field(default=262_144, ge=1024, le=4 * 1024 * 1024)

    @model_validator(mode="after")
    def validate_prompt_state_pair(self) -> RepositoryActionProtocolSpec:
        expected = {
            "repository_action_state_machine_v1": "repository_action_v2_prompt_v1",
            "repository_action_state_machine_v2": "repository_action_v2_prompt_v2",
            "repository_action_state_machine_v3": "repository_action_v2_prompt_v3",
        }[self.state_machine_id]
        compatible = {expected}
        if self.state_machine_id == "repository_action_state_machine_v3":
            compatible.update(
                {
                    "repository_action_v2_prompt_v4",
                    "repository_action_v2_prompt_v5",
                    "repository_action_v2_prompt_v6",
                    "repository_action_v2_prompt_v7",
                }
            )
        if self.prompt_contract_id not in compatible:
            raise ValueError("repository action prompt and state-machine versions must match")
        return self


class RepositoryActionProtocolDescriptor(StrictModel):
    """Frozen effective protocol identity bound from plan through replay."""

    schema_version: str = SCHEMA_VERSION
    resolver_id: Literal["repository_action_protocol_resolver_v1"] = (
        "repository_action_protocol_resolver_v1"
    )
    protocol_id: Literal["repository_action.v2"] = "repository_action.v2"
    protocol_version: Literal["2.0.0"] = "2.0.0"
    action_transport: RepositoryActionTransport
    one_action_per_turn: Literal[True] = True
    action_registry_hash: str
    prompt_contract_id: str
    prompt_contract_hash: str
    normalizer_id: str
    state_machine_id: RepositoryActionStateMachine
    max_completion_calls: int = Field(ge=1, le=128)
    max_response_bytes: int = Field(ge=1024, le=4 * 1024 * 1024)
    agent_descriptor_hash: str
    task_tool_contract_hash: str
    configuration_fingerprint: str

    @model_validator(mode="after")
    def validate_hashes(self) -> RepositoryActionProtocolDescriptor:
        for value in (
            self.action_registry_hash,
            self.prompt_contract_hash,
            self.agent_descriptor_hash,
            self.task_tool_contract_hash,
            self.configuration_fingerprint,
        ):
            if not _SHA256.fullmatch(value):
                raise ValueError("repository action protocol identity requires SHA-256 hashes")
        return self


class ProviderNativeToolCall(StrictModel):
    """Provider-neutral native tool-call value; its schema_version is protocol-bound."""

    call_id: str | None = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    arguments_json: str = Field(max_length=4 * 1024 * 1024)


class CanonicalRepositoryAction(StrictModel):
    """One strict canonical action; ``protocol`` carries its schema_version."""

    protocol: Literal["repository_action.v2"]
    action: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any]


class RepositoryActionNormalization(StrictModel):
    raw_sha256: str
    raw_bytes: int = Field(ge=0)
    normalized_sha256: str | None = None
    normalized_bytes: int | None = Field(default=None, ge=0)
    decisions: list[
        Literal[
            "utf8_decoded",
            "leading_bom_removed",
            "line_endings_normalized",
            "outer_whitespace_stripped",
            "response_wide_json_fence_unwrapped",
            "response_wide_unlabeled_fence_unwrapped",
        ]
    ] = Field(default_factory=list)
    representation_only: Literal[True] = True


class RepositoryActionTurnRecord(StrictModel):
    """Replayable, bounded decision record for one completion turn."""

    schema_version: str = SCHEMA_VERSION
    turn_index: int = Field(ge=0)
    request_id: str
    transport: RepositoryActionTransport
    state_before: RepositoryActionState
    state_after: RepositoryActionState | None = None
    normalization: RepositoryActionNormalization | None = None
    accepted: bool
    permitted_normalization_used: bool = False
    validation_result: Literal["accepted", "rejected"]
    action_name: str | None = None
    action_envelope_hash: str | None = None
    arguments_hash: str | None = None
    tool_result_hash: str | None = None
    error_subcategory: RepositoryProtocolError | None = None
    termination_reason: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_result(self) -> RepositoryActionTurnRecord:
        if self.accepted:
            if (
                self.validation_result != "accepted"
                or self.action_name is None
                or self.action_envelope_hash is None
                or self.arguments_hash is None
            ):
                raise ValueError("accepted repository action lacks canonical identity")
            if self.error_subcategory is not None:
                raise ValueError("accepted repository action cannot contain a protocol error")
        elif self.validation_result != "rejected" or self.error_subcategory is None:
            raise ValueError("rejected repository action requires a protocol error subcategory")
        for value in (
            self.action_envelope_hash,
            self.arguments_hash,
            self.tool_result_hash,
        ):
            if value is not None and not _SHA256.fullmatch(value):
                raise ValueError("repository action record identity is not SHA-256")
        return self


__all__ = [
    "CanonicalRepositoryAction",
    "ProviderNativeToolCall",
    "RepositoryActionNormalization",
    "RepositoryActionProtocolDescriptor",
    "RepositoryActionProtocolSpec",
    "RepositoryActionState",
    "RepositoryActionStateMachine",
    "RepositoryActionTransport",
    "RepositoryActionTurnRecord",
    "RepositoryProtocolError",
]
