"""OpenHands SDK integration plugin."""

from ._version import __version__
from .agent import OpenHandsRepositoryAgentAdapter

__all__ = ["OpenHandsRepositoryAgentAdapter", "__version__"]
