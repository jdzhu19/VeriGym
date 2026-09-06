"""Resolve and apply explicit verifier backend profiles."""

from __future__ import annotations

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.registry.base import PluginRegistry
from verigym.schemas.task import VeriTask
from verigym.schemas.verifier_profile import ResolvedVerifierToolProfile, VerifierToolProfile
from verigym.tools.base import ToolPlugin, VerifierBackendPlugin


def uses_controller_verifier_transport(
    *,
    runtime: str,
    profile: VerifierToolProfile,
    backend: ToolPlugin,
) -> bool:
    """Return whether Docker staging may call a fixed local verifier-control transport."""

    return bool(
        isinstance(backend, VerifierBackendPlugin)
        and "remote_mcp" in backend.descriptor.capabilities
        and runtime == "docker"
        and profile.runtime == "local"
    )


def validate_required_verifier_profile(
    task: VeriTask,
    profile: VerifierToolProfile | None,
) -> None:
    """Fail closed when a task is restricted to one verifier-profile backend."""

    required_target = task.metadata.get("required_verifier_profile_target")
    if required_target is None:
        return
    if not isinstance(required_target, str) or not required_target:
        raise ConfigurationError(
            "task required_verifier_profile_target metadata must be a nonempty string"
        )
    if profile is None:
        raise ConfigurationError(
            f"task {task.id!r} requires a verifier profile targeting {required_target!r}"
        )
    if profile.target_plugin != required_target:
        raise ConfigurationError(
            f"verifier profile target {profile.target_plugin!r} does not satisfy task-required "
            f"target {required_target!r}"
        )


def resolve_verifier_profile(
    *,
    task: VeriTask,
    profile: VerifierToolProfile,
    tools: PluginRegistry[ToolPlugin],
    expected: ResolvedVerifierToolProfile | None = None,
) -> ResolvedVerifierToolProfile:
    validate_required_verifier_profile(task, profile)
    if task.id != profile.task_id:
        raise ConfigurationError(
            f"verifier profile {profile.id!r} is fixed to task {profile.task_id!r}"
        )
    matches = [node for node in task.verifier.nodes if node.plugin == profile.source_plugin]
    if len(matches) != 1:
        raise ConfigurationError("verifier profile must replace exactly one matching verifier node")
    backend = tools.get(profile.target_plugin)
    if not isinstance(backend, VerifierBackendPlugin):
        raise ConfigurationError(
            f"verifier target {profile.target_plugin!r} does not support profile resolution"
        )
    resolved = backend.resolve_verifier_profile(profile, expected=expected)
    if (
        resolved.profile_id != profile.id
        or resolved.profile_version != profile.version
        or resolved.task_id != profile.task_id
        or resolved.source_plugin != profile.source_plugin
        or resolved.target_plugin != profile.target_plugin
        or resolved.runtime != profile.runtime
        or resolved.transport_sha256 != profile.transport_sha256
        or resolved.service_protocol != profile.service_protocol
        or resolved.server_version != profile.server_version
        or resolved.server_profile_id != profile.server_profile_id
        or resolved.server_declared_profile_hash != profile.server_declared_profile_hash
        or resolved.server_contract_hash != profile.server_contract_hash
        or resolved.tool_version != profile.accepted_tool_version
    ):
        raise ConfigurationError("resolved verifier identity differs from its declared contract")
    if resolved.declared_profile_hash != content_hash(profile):
        raise ConfigurationError("resolved verifier profile changed its declared identity")
    return resolved


def task_with_verifier_profile(
    task: VeriTask,
    profile: VerifierToolProfile,
) -> VeriTask:
    validate_required_verifier_profile(task, profile)
    replacements = 0
    nodes = []
    for node in task.verifier.nodes:
        if node.plugin == profile.source_plugin:
            replacements += 1
            nodes.append(node.model_copy(update={"plugin": profile.target_plugin}))
        else:
            nodes.append(node.model_copy(deep=True))
    if replacements != 1:
        raise ConfigurationError("verifier profile replacement count changed after resolution")
    return task.model_copy(
        update={"verifier": task.verifier.model_copy(update={"nodes": nodes})},
        deep=True,
    )


__all__ = [
    "resolve_verifier_profile",
    "task_with_verifier_profile",
    "uses_controller_verifier_transport",
    "validate_required_verifier_profile",
]
