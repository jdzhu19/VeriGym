"""Core-owned implementation of the narrow external-agent workspace bridge."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any, cast

from verigym.core.artifact_policy import bound_value
from verigym.core.errors import PathPolicyError
from verigym.core.redaction import redact_mapping
from verigym.core.repository_observation import (
    RawObservationCallback,
    RepositoryObservationPolicy,
    audit_record,
)
from verigym.core.trace import TraceWriter
from verigym.core.workspace import WorkspacePolicy
from verigym.runtimes.base import RuntimeSession
from verigym.schemas.external_agent import (
    ExternalAgentAccounting,
    ExternalAgentCallIdentity,
    ExternalProcessRequest,
    ExternalProcessResult,
    ExternalReadOnlyMountIdentity,
)
from verigym.schemas.options import JsonValue
from verigym.schemas.tool import CommandSpec, CompletedCommand, ToolResult
from verigym.tools.base import ToolContext
from verigym.tools.file_tools import builtin_file_tools
from verigym.tools.repository import RepositoryPublicTestRequest, RepositoryPublicTestTool

_EVENT_TYPE = re.compile(
    r"^(?:(?:codex|claude)_cli|openhands_sdk|deepseek_harness)_[a-z0-9_]{1,80}$"
)
_MAX_EVENT_BYTES = 256 * 1024
_MAX_TOOL_OUTPUT_BYTES = 256 * 1024
_WORKSPACE_TOOLS = {tool.descriptor.name: tool for tool in builtin_file_tools()}
_PUBLIC_TEST_TOOL = RepositoryPublicTestTool()
_FORBIDDEN_CANDIDATE_NAMES = {
    ".env",
    "auth.json",
    "credentials.json",
    "config.toml",
}


class RuntimeExternalAgentBridge:
    """Expose one materialized visible workspace without runtime internals."""

    def __init__(
        self,
        *,
        session: RuntimeSession,
        artifact_root: Path,
        isolation_level: str,
        policy: WorkspacePolicy,
        trace: TraceWriter,
        observation_policy: RepositoryObservationPolicy | None = None,
        audit_callback: RawObservationCallback | None = None,
    ) -> None:
        self._session = session
        self._artifact_root = artifact_root
        self._isolation_level = isolation_level
        self._policy = policy
        self._trace = trace
        self._observation_policy = observation_policy
        self._audit_callback = audit_callback
        self._accounting: ExternalAgentAccounting | None = None
        self._observations: list[ExternalAgentCallIdentity] = []
        artifact_root.mkdir(parents=True, exist_ok=False)

    @property
    def workspace_root(self) -> Path:
        return self._session.root

    @property
    def artifact_root(self) -> Path:
        return self._artifact_root

    @property
    def isolation_level(self) -> str:
        return self._isolation_level

    @property
    def observation_policy(self) -> RepositoryObservationPolicy | None:
        return self._observation_policy

    @property
    def editable_globs(self) -> tuple[str, ...]:
        return self._policy.editable_globs

    @property
    def readonly_globs(self) -> tuple[str, ...]:
        return self._policy.readonly_globs

    @property
    def execution_backend(self) -> str:
        return self._session.external_process_backend

    @property
    def logical_workspace_root(self) -> str:
        return self._session.logical_workspace_root

    @property
    def read_only_mounts(self) -> list[ExternalReadOnlyMountIdentity]:
        return [item.model_copy(deep=True) for item in self._session.external_read_only_mounts]

    def execute_process(self, request: ExternalProcessRequest) -> ExternalProcessResult:
        private_audit_root = (
            self._artifact_root.parent.parent
            if request.integration_track == "codex_cli_hwe_native_shell"
            else None
        )
        return self._session.execute_external_process(
            request,
            private_audit_root=private_audit_root,
        )

    def invoke_workspace_tool(self, tool_name: str, request: dict[str, JsonValue]) -> ToolResult:
        """Invoke one core-owned file tool against the visible workspace."""

        tool = _WORKSPACE_TOOLS.get(tool_name)
        if tool is None:
            raise ValueError("external agent requested an unavailable workspace tool")
        result = tool.execute(
            dict(request),
            ToolContext(
                session=self._session,
                workspace_policy=self._policy,
                max_output_bytes=_MAX_TOOL_OUTPUT_BYTES,
                artifact_dir=self._artifact_root,
                observation_policy=self._observation_policy,
                audit_callback=self._audit_callback,
            ),
        )
        return result.model_copy(deep=True)

    def execute_command(self, command: CommandSpec) -> CompletedCommand:
        """Run one shell-free command through the selected runtime session."""

        if command.requires_shell:
            raise PathPolicyError("external agents cannot request shell command strings")
        if command.env:
            raise PathPolicyError("external agents cannot inject command environment variables")
        if command.artifact_globs:
            raise PathPolicyError("external-agent commands cannot collect undeclared artifacts")
        if len(command.argv) > 128 or any(
            len(value.encode("utf-8")) > 16 * 1024 for value in command.argv
        ):
            raise PathPolicyError("external-agent command arguments exceed the safety bound")
        if command.stdin is not None and len(command.stdin.encode("utf-8")) > 1024 * 1024:
            raise PathPolicyError("external-agent command stdin exceeds the safety bound")
        if command.timeout_s > 1800:
            raise PathPolicyError("external-agent command timeout exceeds 1800 seconds")
        completed = self._session.execute(command)
        self.validate_workspace()
        return completed.model_copy(deep=True)

    def execute_external_agent_command(self, command: CommandSpec) -> CompletedCommand:
        """Run one HWE shell command in the credential-free external-agent image."""

        if (
            command.requires_shell
            or len(command.argv) != 3
            or command.argv[:2] != ["/bin/bash", "-lc"]
        ):
            raise PathPolicyError("HWE external-agent commands require exact /bin/bash -lc argv")
        if command.env:
            raise PathPolicyError("external-agent commands cannot inject environment variables")
        if command.stdin is not None or command.artifact_globs:
            raise PathPolicyError("external-agent commands cannot use stdin or collect artifacts")
        if len(command.argv[2].encode("utf-8")) > 64 * 1024:
            raise PathPolicyError("external-agent shell command exceeds 64 KiB")
        if command.timeout_s > 900:
            raise PathPolicyError("external-agent HWE command timeout exceeds 900 seconds")
        completed = self._session.execute_external_agent_command(command)
        self.validate_workspace()
        return completed.model_copy(deep=True)

    def execute_public_test(self, test_id: str) -> CompletedCommand:
        completed = self._session.execute_public_test(test_id)
        if self._audit_callback is not None:
            request = RepositoryPublicTestRequest(test_id=test_id)
            result = _PUBLIC_TEST_TOOL.parse_result(
                request,
                completed,
                ToolContext(
                    session=self._session,
                    max_output_bytes=_MAX_TOOL_OUTPUT_BYTES,
                    observation_policy=self._observation_policy,
                ),
            )
            self._audit_callback(
                audit_record(result, request={"test_id": test_id}, policy=self._observation_policy)
            )
        self.validate_workspace()
        return completed.model_copy(deep=True)

    @property
    def accounting(self) -> ExternalAgentAccounting | None:
        return self._accounting.model_copy(deep=True) if self._accounting is not None else None

    @property
    def observations(self) -> list[ExternalAgentCallIdentity]:
        return [item.model_copy(deep=True) for item in self._observations]

    @property
    def configuration_fingerprint(self) -> str | None:
        if not self._observations:
            return None
        return self._observations[-1].configuration_fingerprint

    def emit_event(self, event_type: str, payload: dict[str, JsonValue]) -> None:
        if not _EVENT_TYPE.fullmatch(event_type):
            raise ValueError("external-agent event types must use a registered *_cli_* namespace")
        clean = self._sanitize_payload(redact_mapping(payload))
        identity: ExternalAgentCallIdentity | None = None
        if event_type in {
            "codex_cli_identity_observed",
            "claude_cli_identity_observed",
            "deepseek_harness_identity_observed",
        }:
            identity = ExternalAgentCallIdentity.model_validate(dict(clean))
        bounded, truncated = bound_value(clean, _MAX_EVENT_BYTES)
        if not isinstance(bounded, dict):
            raise ValueError("external-agent event payload must remain an object")
        bounded["content_truncated"] = truncated
        if identity is not None:
            if self._observations:
                raise ValueError("an external-agent episode may record only one call identity")
            self._observations.append(identity)
        self._trace.emit(event_type, bounded)

    def record_accounting(self, accounting: ExternalAgentAccounting) -> None:
        if self._accounting is not None:
            raise ValueError("external-agent accounting was already recorded")
        self._accounting = accounting.model_copy(deep=True)
        surface = (
            self._observations[-1].execution_surface
            if self._observations and self._observations[-1].execution_surface is not None
            else "codex_cli"
        )
        self._trace.emit(f"{surface}_accounting_recorded", accounting.model_dump(mode="json"))

    def validate_workspace(self) -> None:
        """Reject direct external edits that bypass the declared workspace policy."""

        internal = self.workspace_root / ".verigym_internal"
        try:
            internal_metadata = os.lstat(internal)
        except OSError as exc:
            raise PathPolicyError("external agent removed the runtime-internal directory") from exc
        if (
            not stat.S_ISDIR(internal_metadata.st_mode)
            or stat.S_ISLNK(internal_metadata.st_mode)
            or any(internal.iterdir())
        ):
            raise PathPolicyError("external agent modified the runtime-internal directory")
        diff = self._session.snapshot_diff()
        for relative in diff.changed_files:
            self._policy.check_write(relative)
        self._policy.check_patch_size(
            len(diff.changed_files),
            diff.added_lines + diff.deleted_lines,
        )
        total_bytes = 0
        for path in sorted(self.workspace_root.rglob("*")):
            metadata = os.lstat(path)
            relative_path = path.relative_to(self.workspace_root)
            if stat.S_ISLNK(metadata.st_mode):
                raise PathPolicyError(
                    f"external agent created a symlink: {relative_path.as_posix()}"
                )
            if path.is_file():
                if metadata.st_nlink != 1:
                    raise PathPolicyError(
                        f"external agent workspace contains a hardlink: {relative_path.as_posix()}"
                    )
                if ".verigym_internal" not in relative_path.parts:
                    total_bytes += metadata.st_size
                    if path.name.lower() in _FORBIDDEN_CANDIDATE_NAMES:
                        raise PathPolicyError(
                            f"external agent created a credential/config file: "
                            f"{relative_path.as_posix()}"
                        )
        if (
            self._policy.max_workspace_bytes is not None
            and total_bytes > self._policy.max_workspace_bytes
        ):
            raise PathPolicyError(
                f"workspace uses {total_bytes} bytes; limit is {self._policy.max_workspace_bytes}"
            )

    def _sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        workspace = str(self.workspace_root)
        home = str(Path.home())

        def sanitize(value: Any) -> Any:
            if isinstance(value, dict):
                return {str(key): sanitize(item) for key, item in value.items()}
            if isinstance(value, list):
                return [sanitize(item) for item in value]
            if isinstance(value, str):
                return value.replace(workspace, "<task_workspace>").replace(home, "<home>")
            return value

        return cast(dict[str, Any], sanitize(payload))


__all__ = ["RuntimeExternalAgentBridge"]
