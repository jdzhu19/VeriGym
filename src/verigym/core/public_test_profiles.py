"""Resolve and execute task-bound commercial public-test profiles."""

from __future__ import annotations

import json
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.registry.base import PluginRegistry
from verigym.runtimes.base import RuntimeSession
from verigym.schemas.common import ErrorCategory
from verigym.schemas.task import VeriTask
from verigym.schemas.tool import CompletedCommand
from verigym.schemas.verifier_profile import ResolvedVerifierToolProfile, VerifierToolProfile
from verigym.tools.base import ToolContext, ToolPlugin, VerifierBackendPlugin

_TARGET_KEY = "required_public_test_profile_target"
_SOURCE_KEY = "public_test_profile_source_plugin"
_TEST_ID_KEY = "public_test_profile_test_id"
_SOURCES_KEY = "public_test_profile_sources"
_TOP_KEY = "public_test_profile_top"


def validate_required_public_test_profile(
    task: VeriTask,
    profile: VerifierToolProfile | None,
) -> None:
    """Require the declared public backend without weakening ordinary public tests."""

    target = task.metadata.get(_TARGET_KEY)
    if target is None:
        if profile is not None:
            raise ConfigurationError(
                f"task {task.id!r} does not declare a public-test profile interface"
            )
        return
    source = task.metadata.get(_SOURCE_KEY)
    test_id = task.metadata.get(_TEST_ID_KEY)
    sources = task.metadata.get(_SOURCES_KEY)
    top = task.metadata.get(_TOP_KEY)
    if (
        not isinstance(target, str)
        or not target
        or source != "repository.public_test"
        or test_id != "compile"
        or not isinstance(sources, list)
        or not sources
        or not all(isinstance(item, str) and item for item in sources)
        or not isinstance(top, str)
        or not top
    ):
        raise ConfigurationError("task public-test profile metadata is malformed")
    if profile is None:
        raise ConfigurationError(
            f"task {task.id!r} requires a public-test profile targeting {target!r}"
        )
    if profile.task_id != task.id:
        raise ConfigurationError(
            f"public-test profile {profile.id!r} is fixed to task {profile.task_id!r}"
        )
    if profile.source_plugin != source:
        raise ConfigurationError(
            f"public-test profile source {profile.source_plugin!r} does not satisfy "
            f"task-required source {source!r}"
        )
    if profile.target_plugin != target:
        raise ConfigurationError(
            f"public-test profile target {profile.target_plugin!r} does not satisfy "
            f"task-required target {target!r}"
        )


def resolve_public_test_profile(
    *,
    task: VeriTask,
    profile: VerifierToolProfile,
    tools: PluginRegistry[ToolPlugin],
    expected: ResolvedVerifierToolProfile | None = None,
) -> ResolvedVerifierToolProfile:
    """Resolve a model-invisible public-test transport before agent lookup."""

    validate_required_public_test_profile(task, profile)
    backend = tools.get(profile.target_plugin)
    if not isinstance(backend, VerifierBackendPlugin):
        raise ConfigurationError(
            f"public-test target {profile.target_plugin!r} does not support profile resolution"
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
        or resolved.declared_profile_hash != content_hash(profile)
    ):
        raise ConfigurationError("resolved public-test identity differs from its declared contract")
    return resolved


class PublicTestProfileController:
    """Project one fixed MCP compile result into the public-test protocol."""

    def __init__(
        self,
        *,
        task: VeriTask,
        profile: VerifierToolProfile,
        resolved_profile: ResolvedVerifierToolProfile,
        backend: VerifierBackendPlugin,
    ) -> None:
        validate_required_public_test_profile(task, profile)
        if resolved_profile.profile_id != profile.id:
            raise ConfigurationError("public-test resolved profile differs from its declaration")
        self._task = task
        self._profile = profile
        self._resolved_profile = resolved_profile
        self._backend = backend

    @property
    def resolved_profile_hash(self) -> str:
        return self._resolved_profile.resolved_profile_hash

    def execute(self, test_id: str, session: RuntimeSession) -> CompletedCommand:
        expected_test_id = self._task.metadata[_TEST_ID_KEY]
        if test_id != expected_test_id:
            return _completed_public_result(
                profile=self._profile,
                resolved=self._resolved_profile,
                test_id=test_id,
                success=False,
                category=ErrorCategory.INVALID_REQUEST,
                message="unknown task-declared public test",
                diagnostics=[],
                candidate_failure=False,
                duration_s=0.0,
            )
        raw_sources = self._task.metadata[_SOURCES_KEY]
        assert isinstance(raw_sources, list)
        result = self._backend.execute(
            {
                "test_id": test_id,
                "sources": list(raw_sources),
                "top": self._task.metadata[_TOP_KEY],
                "timeout_s": 30,
            },
            ToolContext(
                session=session,
                max_output_bytes=self._task.budget.max_output_bytes_per_tool,
                verifier_profile=self._profile,
                resolved_verifier_profile=self._resolved_profile,
            ),
        )
        candidate_failure = result.metadata.get("candidate_failure") is True
        if (
            result.tool != self._profile.target_plugin
            or result.stdout
            or result.stderr
            or result.artifacts
            or set(result.metadata) != {"candidate_failure"}
            or not isinstance(result.metadata["candidate_failure"], bool)
        ):
            return _completed_public_result(
                profile=self._profile,
                resolved=self._resolved_profile,
                test_id=test_id,
                success=False,
                category=ErrorCategory.INVALID_REQUEST,
                message="public VCS/MCP response violated the sanitized contract",
                diagnostics=[],
                candidate_failure=False,
                duration_s=result.duration_s,
            )
        return _completed_public_result(
            profile=self._profile,
            resolved=self._resolved_profile,
            test_id=test_id,
            success=result.success,
            category=result.category,
            message=result.message,
            diagnostics=result.diagnostics,
            candidate_failure=candidate_failure,
            duration_s=result.duration_s,
        )


def _completed_public_result(
    *,
    profile: VerifierToolProfile,
    resolved: ResolvedVerifierToolProfile,
    test_id: str,
    success: bool,
    category: ErrorCategory,
    message: str,
    diagnostics: list[str],
    candidate_failure: bool,
    duration_s: float,
) -> CompletedCommand:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "protocol": "verigym_public_test_v1",
        "test_id": test_id,
        "passed": success,
        "backend": profile.target_plugin,
        "category": category.value,
        "message": message,
        "diagnostics": diagnostics,
        "resolved_profile_hash": resolved.resolved_profile_hash,
    }
    infrastructure = not success and not candidate_failure
    return CompletedCommand(
        argv=["verigym-public-test-profile", test_id],
        cwd=".",
        exit_code=0 if success else 1,
        stdout=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        duration_s=duration_s,
        failure_reason=None if success else category.value,
        failure_origin=(
            None if success else "control_plane" if infrastructure else "candidate_process"
        ),
        runtime_role="public_test_control_plane",
        metadata={
            "public_test_backend": profile.target_plugin,
            "public_test_profile_id": profile.id,
            "resolved_public_test_profile_hash": resolved.resolved_profile_hash,
            "network_policy": "agent_workspace_none_verifier_control_plane",
            "public_assets_read_only": True,
        },
    )


__all__ = [
    "PublicTestProfileController",
    "resolve_public_test_profile",
    "validate_required_public_test_profile",
]
