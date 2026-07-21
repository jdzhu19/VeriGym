"""Provider-independent model-client contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from verigym.schemas.common import ModelDescriptor
from verigym.schemas.model import ModelClientErrorInfo, ModelRequest, ModelResponse, ModelRunConfig


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
