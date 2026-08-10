"""Optional HWE-Bench integration for VeriGym."""

from .adapter import ADAPTER_VERSION, SUITE_VERSION, HweBenchSuite
from .agent import HweBenchProbeAgent

__version__ = ADAPTER_VERSION

__all__ = [
    "ADAPTER_VERSION",
    "HweBenchProbeAgent",
    "HweBenchSuite",
    "SUITE_VERSION",
    "__version__",
]
