"""Persistent prompt and tool-policy identities stored in run manifests."""

from __future__ import annotations

from pydantic import Field

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.common import InteractionMode


class PromptPolicyDescriptor(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    version: str
    interaction_mode: InteractionMode
    configuration_fingerprint: str


class ToolPolicySnapshot(StrictModel):
    schema_version: str = SCHEMA_VERSION
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    allow_general_shell: bool = False
    network_policy: str = "none"
