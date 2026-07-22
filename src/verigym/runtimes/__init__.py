"""Built-in runtimes."""

from verigym.runtimes.docker import DockerRuntime
from verigym.runtimes.local import LocalRuntime

__all__ = ["DockerRuntime", "LocalRuntime"]
