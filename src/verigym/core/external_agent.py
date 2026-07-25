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
from verigym.core.trace import TraceWriter
from verigym.core.workspace import WorkspacePolicy
from verigym.runtimes.base import RuntimeSession
from verigym.schemas.external_agent import (
    ExternalAgentAccounting,
    ExternalAgentCallIdentity,
)
from verigym.schemas.options import JsonValue

_EVENT_TYPE = re.compile(r"^codex_cli_[a-z0-9_]{1,80}$")
_MAX_EVENT_BYTES = 256 * 1024
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
    ) -> None:
        self._session = session
        self._artifact_root = artifact_root
        self._isolation_level = isolation_level
        self._policy = policy
        self._trace = trace
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
    def editable_globs(self) -> tuple[str, ...]:
        return self._policy.editable_globs

    @property
    def readonly_globs(self) -> tuple[str, ...]:
        return self._policy.readonly_globs

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
            raise ValueError("external-agent event types must use the codex_cli_* namespace")
        clean = self._sanitize_payload(redact_mapping(payload))
        identity: ExternalAgentCallIdentity | None = None
        if event_type == "codex_cli_identity_observed":
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
        self._trace.emit(
            "codex_cli_accounting_recorded",
            accounting.model_dump(mode="json"),
        )

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
