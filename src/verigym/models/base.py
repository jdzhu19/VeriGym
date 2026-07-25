"""Provider-independent model-client contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from verigym.schemas.common import ModelDescriptor
from verigym.schemas.model import ModelClientErrorInfo, ModelRequest, ModelResponse, ModelRunConfig
from verigym.schemas.options import JsonValue


class ModelClientError(Exception):
    """A structured model-client failure safe to record in traces."""

    def __init__(self, info: ModelClientErrorInfo) -> None:
        super().__init__(info.message)
        self.info = info


class ModelClient(ABC):
    descriptor: ModelDescriptor

    @abstractmethod
    def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate one normalized response or raise ``ModelClientError``."""

    @abstractmethod
    def clone_for_run(self, configuration: ModelRunConfig | None = None) -> ModelClient:
        """Return independent per-run state without leaking response cursors."""

    def reset(self) -> None:
        """Reset deterministic client state when supported."""

        return None

    def drain_events(self) -> list[tuple[str, dict[str, JsonValue]]]:
        """Return safe plugin events accumulated by the most recent call."""

        return []

    def export_run_artifacts(self, destination: Path) -> None:
        """Persist bounded plugin artifacts after model interaction has ended."""

        del destination
