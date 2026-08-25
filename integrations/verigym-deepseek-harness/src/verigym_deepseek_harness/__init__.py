"""DeepSeek Harness HWE integration package."""

from ._version import __version__
from .agent import DeepSeekHarnessHweAgentAdapter, DeepSeekHarnessHweAgentV3Adapter

__all__ = [
    "DeepSeekHarnessHweAgentAdapter",
    "DeepSeekHarnessHweAgentV3Adapter",
    "__version__",
]
