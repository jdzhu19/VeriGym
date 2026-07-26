"""Typed, non-executing policy evaluation for Codex CLI machine events."""

from __future__ import annotations

import shlex
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from .events import NormalizedEvent, ParsedEventStream

EventClassification = Literal[
    "harness_plan_only",
    "read_only_empty_workdir_inspection",
    "side_effecting_local_tool",
    "network_tool",
    "mcp_or_external_tool",
    "unknown_tool",
]
ToolPolicyId = Literal["text_only_zero_tools_v1", "typed_readonly_empty_workdir_v1"]

_LIFECYCLE_CATEGORIES = {
    "session_started",
    "turn_started",
    "turn_completed",
    "session_completed",
    "message_delta",
    "message_completed",
    "reasoning_summary",
    "usage",
    "error",
}
_NETWORK_COMMANDS = {
    "curl",
    "wget",
    "nc",
    "ncat",
    "ssh",
    "scp",
    "sftp",
    "git",
    "pip",
    "pip3",
    "npm",
    "npx",
    "yarn",
    "pnpm",
}
_SIDE_EFFECTING_COMMANDS = {
    "chmod",
    "chown",
    "cp",
    "dd",
    "install",
    "ln",
    "mkdir",
    "mv",
    "rm",
    "rmdir",
    "tee",
    "touch",
    "truncate",
}
_SHELL_WRAPPERS = {"bash", "sh"}
_FORBIDDEN_PATH_MARKERS = {
    ".codex",
    ".ssh",
    "auth.json",
    "config.toml",
    "credentials.json",
}


@dataclass(frozen=True)
class EventPolicyContext:
    """Declared identities used by the evaluator; no host state is executed or inferred."""

    working_directory: Path
    working_directory_identity: str
    sandbox_identity: str
    network_policy: Literal["disabled"]
    mcp_policy: Literal["disabled"]


@dataclass(frozen=True)
class ClassifiedEvent:
    sequence: int
    upstream_type: str
    normalized_category: str
    tool_name: str
    classification: EventClassification
    execution_occurred: bool | None
    side_effecting: bool
    filesystem_access: str
    outside_workdir_access: bool
    network_access: bool
    mcp_access: bool
    shell_event: bool
    plan_event: bool
    other_builtin_event: bool
    output_returned_to_model: bool | None
    allowed: bool
    reasons: tuple[str, ...]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "upstream_type": self.upstream_type,
            "normalized_category": self.normalized_category,
            "tool_name": self.tool_name,
            "classification": self.classification,
            "execution_occurred": self.execution_occurred,
            "side_effecting": self.side_effecting,
            "filesystem_access": self.filesystem_access,
            "outside_workdir_access": self.outside_workdir_access,
            "network_access": self.network_access,
            "mcp_access": self.mcp_access,
            "shell_event": self.shell_event,
            "plan_event": self.plan_event,
            "other_builtin_event": self.other_builtin_event,
            "output_returned_to_model": self.output_returned_to_model,
            "allowed": self.allowed,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class EventPolicyResult:
    policy_id: ToolPolicyId
    policy_passed: bool
    classified_events: tuple[ClassifiedEvent, ...]
    allowed_event_count: int
    forbidden_event_count: int
    tool_event_count: int
    side_effecting_tool_event_count: int
    read_only_tool_event_count: int
    external_network_tool_event_count: int
    mcp_tool_event_count: int
    workspace_write_count: int
    classification_counts: dict[str, int]
    side_effect_summary: dict[str, Any]
    filesystem_scope_summary: dict[str, Any]
    network_summary: dict[str, Any]
    reason_list: tuple[str, ...]
    working_directory_identity: str
    sandbox_identity: str

    def safe_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "policy_id": self.policy_id,
            "policy_passed": self.policy_passed,
            "classified_events": [event.safe_dict() for event in self.classified_events],
            "allowed_event_count": self.allowed_event_count,
            "forbidden_event_count": self.forbidden_event_count,
            "tool_event_count": self.tool_event_count,
            "side_effecting_tool_event_count": self.side_effecting_tool_event_count,
            "read_only_tool_event_count": self.read_only_tool_event_count,
            "external_network_tool_event_count": self.external_network_tool_event_count,
            "mcp_tool_event_count": self.mcp_tool_event_count,
            "workspace_write_count": self.workspace_write_count,
            "classification_counts": dict(sorted(self.classification_counts.items())),
            "side_effect_summary": self.side_effect_summary,
            "filesystem_scope_summary": self.filesystem_scope_summary,
            "network_summary": self.network_summary,
            "reason_list": list(self.reason_list),
            "working_directory_identity": self.working_directory_identity,
            "sandbox_identity": self.sandbox_identity,
        }


def evaluate_event_policy(
    parsed: ParsedEventStream,
    context: EventPolicyContext,
    *,
    policy_id: ToolPolicyId,
) -> EventPolicyResult:
    """Classify a parsed stream without executing or reading any referenced resource."""

    classified: list[ClassifiedEvent] = []
    for event in parsed.events:
        item = _classify_event(event, context)
        if item is None:
            continue
        allowed = item.classification in {
            "harness_plan_only",
            "read_only_empty_workdir_inspection",
        }
        if policy_id == "text_only_zero_tools_v1":
            allowed = False
        classified.append(
            replace(
                item,
                allowed=allowed,
                reasons=(item.reasons if allowed else (*item.reasons, f"forbidden_by_{policy_id}")),
            )
        )
    counts = Counter(event.classification for event in classified)
    forbidden = [event for event in classified if not event.allowed]
    reasons = tuple(sorted({reason for event in forbidden for reason in event.reasons}))
    side_effecting = counts["side_effecting_local_tool"]
    read_only = counts["read_only_empty_workdir_inspection"]
    network = sum(event.network_access for event in classified)
    mcp = sum(event.mcp_access for event in classified)
    outside = sum(event.outside_workdir_access for event in classified)
    writes = sum(
        event.normalized_category in {"file_write", "patch_applied"} for event in classified
    )
    return EventPolicyResult(
        policy_id=policy_id,
        policy_passed=not forbidden,
        classified_events=tuple(classified),
        allowed_event_count=len(classified) - len(forbidden),
        forbidden_event_count=len(forbidden),
        tool_event_count=len(classified),
        side_effecting_tool_event_count=side_effecting,
        read_only_tool_event_count=read_only,
        external_network_tool_event_count=network,
        mcp_tool_event_count=mcp,
        workspace_write_count=writes,
        classification_counts={str(key): value for key, value in counts.items()},
        side_effect_summary={
            "side_effecting_events": side_effecting,
            "workspace_write_events": writes,
            "writes_permitted": False,
        },
        filesystem_scope_summary={
            "outside_workdir_event_count": outside,
            "working_directory_identity": context.working_directory_identity,
            "fresh_empty_read_only_required": True,
        },
        network_summary={
            "network_event_count": network,
            "mcp_event_count": mcp,
            "network_policy": context.network_policy,
            "mcp_policy": context.mcp_policy,
        },
        reason_list=reasons,
        working_directory_identity=context.working_directory_identity,
        sandbox_identity=context.sandbox_identity,
    )


def _classify_event(
    event: NormalizedEvent,
    context: EventPolicyContext,
) -> ClassifiedEvent | None:
    if event.category in _LIFECYCLE_CATEGORIES:
        return None
    if event.category == "plan_update":
        return _event(
            event,
            tool_name="update_plan",
            classification="harness_plan_only",
            execution_occurred=False,
            plan_event=True,
        )
    if event.category in {"command_started", "command_completed"}:
        command = event.payload.get("command")
        if not isinstance(command, str) or not command.strip():
            return _event(
                event,
                tool_name="shell",
                classification="unknown_tool",
                execution_occurred=None,
                shell_event=True,
                reasons=("missing_command_identity",),
            )
        command_classification, scope, outside, reasons = _classify_command(
            command,
            context.working_directory,
        )
        return _event(
            event,
            tool_name="shell",
            classification=command_classification,
            execution_occurred=True,
            filesystem_access=scope,
            outside_workdir_access=outside,
            shell_event=True,
            output_returned_to_model=_optional_bool(event.payload.get("output_returned_to_model")),
            reasons=reasons,
        )
    if event.category == "file_read":
        path = event.payload.get("path")
        scope, outside, reasons = _classify_path(path, context.working_directory)
        classification: EventClassification = (
            "read_only_empty_workdir_inspection" if not outside and not reasons else "unknown_tool"
        )
        return _event(
            event,
            tool_name="file_read",
            classification=classification,
            execution_occurred=True,
            filesystem_access=scope,
            outside_workdir_access=outside,
            reasons=reasons,
        )
    if event.category in {"file_write", "patch_applied"}:
        return _event(
            event,
            tool_name=event.category,
            classification="side_effecting_local_tool",
            execution_occurred=True,
            side_effecting=True,
            filesystem_access="write_or_patch",
            reasons=("workspace_write_or_patch",),
        )
    if event.category == "tool_call":
        tool = str(event.payload.get("tool") or "unknown")
        lowered = tool.lower()
        if "web_search" in lowered or lowered in {"web", "network"}:
            return _event(
                event,
                tool_name=tool,
                classification="network_tool",
                execution_occurred=True,
                network_access=True,
                other_builtin_event=True,
                reasons=("network_tool_forbidden",),
            )
        if "mcp" in lowered:
            return _event(
                event,
                tool_name=tool,
                classification="mcp_or_external_tool",
                execution_occurred=True,
                mcp_access=True,
                other_builtin_event=True,
                reasons=("mcp_tool_forbidden",),
            )
        return _event(
            event,
            tool_name=tool,
            classification="mcp_or_external_tool",
            execution_occurred=True,
            other_builtin_event=True,
            reasons=("external_tool_forbidden",),
        )
    return _event(
        event,
        tool_name=str(event.payload.get("item_type") or event.category),
        classification="unknown_tool",
        execution_occurred=None,
        other_builtin_event=True,
        reasons=("unknown_event_fails_closed",),
    )


def _event(
    event: NormalizedEvent,
    *,
    tool_name: str,
    classification: EventClassification,
    execution_occurred: bool | None,
    side_effecting: bool = False,
    filesystem_access: str = "none",
    outside_workdir_access: bool = False,
    network_access: bool = False,
    mcp_access: bool = False,
    shell_event: bool = False,
    plan_event: bool = False,
    other_builtin_event: bool = False,
    output_returned_to_model: bool | None = None,
    reasons: tuple[str, ...] = (),
) -> ClassifiedEvent:
    return ClassifiedEvent(
        sequence=event.sequence,
        upstream_type=event.upstream_type,
        normalized_category=event.category,
        tool_name=tool_name[:128],
        classification=classification,
        execution_occurred=execution_occurred,
        side_effecting=side_effecting,
        filesystem_access=filesystem_access,
        outside_workdir_access=outside_workdir_access,
        network_access=network_access,
        mcp_access=mcp_access,
        shell_event=shell_event,
        plan_event=plan_event,
        other_builtin_event=other_builtin_event,
        output_returned_to_model=output_returned_to_model,
        allowed=False,
        reasons=reasons,
    )


def _classify_command(
    raw: str,
    root: Path,
) -> tuple[EventClassification, str, bool, tuple[str, ...]]:
    lowered = raw.lower()
    if any(marker in lowered for marker in ("http://", "https://", "ssh://")):
        return "network_tool", "unknown", False, ("network_command_forbidden",)
    if "\n" in raw or "\r" in raw or "\x00" in raw:
        return "unknown_tool", "unknown", False, ("unsafe_command_encoding",)
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError:
        return "unknown_tool", "unknown", False, ("command_tokenization_failed",)
    if not tokens:
        return "unknown_tool", "unknown", False, ("empty_command",)
    command_name = Path(tokens[0]).name
    if command_name in _SHELL_WRAPPERS:
        if len(tokens) != 3 or tokens[1] not in {"-c", "-lc"}:
            return "unknown_tool", "unknown", False, ("unbounded_shell_wrapper",)
        return _classify_command(tokens[2], root)
    if any(marker in raw for marker in (";", "&&", "||", "|", ">", "<", "$", "`")):
        return "unknown_tool", "unknown", False, ("shell_metacharacter_forbidden",)
    if command_name in _NETWORK_COMMANDS:
        return "network_tool", "none", False, ("network_command_forbidden",)
    if command_name in {"codex", "mcp"}:
        return "mcp_or_external_tool", "none", False, ("external_tool_forbidden",)
    if command_name in _SIDE_EFFECTING_COMMANDS:
        return (
            "side_effecting_local_tool",
            "write_or_patch",
            False,
            ("side_effecting_command_forbidden",),
        )
    paths: list[str] = []
    if command_name == "pwd" and len(tokens) == 1:
        return "read_only_empty_workdir_inspection", "inside_workdir_metadata", False, ()
    if command_name == "ls":
        paths = [token for token in tokens[1:] if not token.startswith("-")]
    elif command_name == "cat":
        paths = [token for token in tokens[1:] if not token.startswith("-")]
        if not paths:
            return "unknown_tool", "unknown", False, ("cat_requires_bounded_relative_path",)
    elif command_name in {"head", "tail", "wc"}:
        paths = [token for token in tokens[1:] if not token.startswith("-")]
        if not paths:
            return "unknown_tool", "unknown", False, ("read_requires_relative_path",)
    elif command_name == "sed":
        if len(tokens) != 4 or tokens[1] != "-n" or not _safe_sed_expression(tokens[2]):
            return "unknown_tool", "unknown", False, ("sed_shape_not_read_only",)
        paths = [tokens[3]]
    else:
        return "unknown_tool", "unknown", False, ("command_not_in_read_only_allowlist",)
    for path in paths or ["."]:
        scope, outside, reasons = _classify_path(path, root)
        if outside or reasons:
            return "unknown_tool", scope, outside, reasons
    return "read_only_empty_workdir_inspection", "inside_workdir_read", False, ()


def _classify_path(raw: Any, root: Path) -> tuple[str, bool, tuple[str, ...]]:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        return "unknown", False, ("missing_or_invalid_path",)
    normalized = PurePosixPath(raw.replace("\\", "/"))
    lowered_parts = {part.lower() for part in normalized.parts}
    if lowered_parts & _FORBIDDEN_PATH_MARKERS:
        return "forbidden_config_or_home_read", True, ("home_or_config_read_forbidden",)
    if raw.startswith("~") or "$" in raw or any(part == ".." for part in normalized.parts):
        return "outside_workdir_read", True, ("outside_workdir_read_forbidden",)
    candidate = Path(raw)
    resolved = (
        candidate.resolve(strict=False)
        if candidate.is_absolute()
        else (root / candidate).resolve(strict=False)
    )
    if not resolved.is_relative_to(root.resolve(strict=False)):
        return "outside_workdir_read", True, ("outside_workdir_read_forbidden",)
    return "inside_workdir_read", False, ()


def _safe_sed_expression(value: str) -> bool:
    prefix, separator, suffix = value.partition(",")
    if separator:
        return prefix.isdigit() and suffix.endswith("p") and suffix[:-1].isdigit()
    return value.endswith("p") and value[:-1].isdigit()


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


__all__ = [
    "ClassifiedEvent",
    "EventPolicyContext",
    "EventPolicyResult",
    "ToolPolicyId",
    "evaluate_event_policy",
]
