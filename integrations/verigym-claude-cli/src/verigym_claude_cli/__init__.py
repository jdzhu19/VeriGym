"""Claude CLI integration plugin."""

from ._version import __version__
from .agent import ClaudeCliAgentAdapter

__all__ = ["ClaudeCliAgentAdapter", "__version__"]
