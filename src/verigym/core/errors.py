"""Stable exception hierarchy used by the CLI and Python API."""

from __future__ import annotations


class VeriGymError(Exception):
    """Base class for expected VeriGym failures."""

    exit_code = 5


class ConfigurationError(VeriGymError):
    """User-provided configuration is invalid."""

    exit_code = 2


class PluginError(VeriGymError):
    """A plugin cannot be loaded or is incompatible."""

    exit_code = 2


class DuplicatePluginError(PluginError):
    """Two plugins claim the same stable identifier."""


class PluginNotFoundError(PluginError):
    """A requested plugin is not installed."""


class MissingDependencyError(VeriGymError):
    """An external executable or Python dependency is unavailable."""

    exit_code = 3


class RuntimeExecutionError(VeriGymError):
    """The runtime failed independently of candidate behavior."""

    exit_code = 4


class PolicyError(VeriGymError):
    """An action violates task workspace or tool policy."""

    exit_code = 2


class PathPolicyError(PolicyError):
    """A path escapes the workspace or violates its declared policy."""


class VerifierGraphError(ConfigurationError):
    """A verifier graph is malformed or cyclic."""


class ReplayError(ConfigurationError):
    """Stored run data cannot be validated or replayed."""


class ComparisonError(ConfigurationError):
    """Two ranked metrics do not share an identical comparison contract."""
