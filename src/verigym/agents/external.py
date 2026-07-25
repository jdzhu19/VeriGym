"""Narrow runtime-only bridge exposed to external coding-agent plugins."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.options import JsonValue


class ExternalAgentBridge(Protocol):
    @property
    def workspace_root(self) -> Path: ...

    @property
    def artifact_root(self) -> Path: ...

    @property
    def isolation_level(self) -> str: ...

    @property
    def editable_globs(self) -> tuple[str, ...]: ...

    @property
    def readonly_globs(self) -> tuple[str, ...]: ...

    def emit_event(self, event_type: str, payload: dict[str, JsonValue]) -> None: ...

    def record_accounting(self, accounting: ExternalAgentAccounting) -> None: ...


__all__ = ["ExternalAgentBridge"]
