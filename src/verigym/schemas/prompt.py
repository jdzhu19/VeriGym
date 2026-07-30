"""Persistent prompt and tool-policy identities stored in run manifests."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.common import InteractionMode

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AgentPromptPolicySpec(StrictModel):
    """Static safe declaration used by the generic prompt-policy resolver."""

    schema_version: str = SCHEMA_VERSION
    prompt_bearing: Literal[True] = True
    prompt_contract_id: str = Field(min_length=1, max_length=128)
    prompt_contract_version: str = Field(min_length=1, max_length=64)
    task_context_policy: str = Field(min_length=1, max_length=128)
    base_instruction_policy: str = Field(min_length=1, max_length=128)
    content_visibility_policy: str = Field(min_length=1, max_length=128)
    max_prompt_bytes: int = Field(ge=1024, le=2 * 1024 * 1024)
    max_task_context_bytes: int = Field(ge=1024, le=2 * 1024 * 1024)
    versioned_context_allowed: bool = False


class PromptPolicyDescriptor(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    version: str
    interaction_mode: InteractionMode
    configuration_fingerprint: str
    resolver_id: Literal["agent_execution_prompt_policy_v1"] | None = None
    task_context_policy: str | None = None
    task_context_hash: str | None = None
    base_instruction_policy: str | None = None
    content_visibility_policy: str | None = None
    max_prompt_bytes: int | None = Field(default=None, ge=1024, le=2 * 1024 * 1024)
    max_task_context_bytes: int | None = Field(
        default=None,
        ge=1024,
        le=2 * 1024 * 1024,
    )
    agent_descriptor_hash: str | None = None
    agent_version_id: str | None = None
    agent_version_hash: str | None = None
    memory_pack_hash: str | None = None

    @model_validator(mode="after")
    def validate_resolved_agent_policy(self) -> PromptPolicyDescriptor:
        if self.resolver_id is None:
            return self
        required = (
            self.task_context_policy,
            self.task_context_hash,
            self.base_instruction_policy,
            self.content_visibility_policy,
            self.max_prompt_bytes,
            self.max_task_context_bytes,
            self.agent_descriptor_hash,
        )
        if any(value is None for value in required):
            raise ValueError("resolved agent prompt policy is incomplete")
        hashes = (
            self.configuration_fingerprint,
            self.task_context_hash,
            self.agent_descriptor_hash,
        )
        if any(not isinstance(value, str) or not _SHA256.fullmatch(value) for value in hashes):
            raise ValueError("resolved agent prompt policy contains an invalid identity hash")
        if (self.agent_version_id is None) != (self.agent_version_hash is None):
            raise ValueError("agent-version prompt identity must contain both ID and hash")
        if self.agent_version_hash is not None and not _SHA256.fullmatch(self.agent_version_hash):
            raise ValueError("agent-version prompt hash must be lowercase SHA-256")
        if self.memory_pack_hash is not None:
            if not _SHA256.fullmatch(self.memory_pack_hash):
                raise ValueError("memory-pack prompt hash must be lowercase SHA-256")
            if self.agent_version_hash is None:
                raise ValueError("memory-bearing prompt policy requires an agent version")
        return self


class ToolPolicySnapshot(StrictModel):
    schema_version: str = SCHEMA_VERSION
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    allow_general_shell: bool = False
    network_policy: str = "none"
