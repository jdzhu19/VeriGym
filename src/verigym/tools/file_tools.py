"""Policy-enforced agent workspace tools."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from pydantic import BaseModel, Field, ValidationError, model_validator

from verigym.core.errors import PathPolicyError
from verigym.core.repository_observation import (
    audit_record,
    bounded_read_view,
    bounded_text_with_marker,
    compact_tool_result,
    list_workspace_entries,
)
from verigym.core.workspace import WorkspacePolicy, glob_matches
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION, StrictModel
from verigym.schemas.common import ErrorCategory, ToolDescriptor, ToolVisibility
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.tools.base import ToolContext, ToolPlugin


class FileListRequest(StrictModel):
    path: str = "."
    recursive: bool = True
    max_depth: int | None = Field(default=None, ge=0, le=64)
    max_entries: int | None = Field(default=None, ge=1, le=4096)


class FileReadRequest(StrictModel):
    path: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    concise: bool | None = None

    @model_validator(mode="after")
    def validate_line_range(self) -> FileReadRequest:
        if (
            self.start_line is not None
            and self.end_line is not None
            and self.start_line > self.end_line
        ):
            raise ValueError("read_file start_line must not be after end_line")
        return self


class FileSearchRequest(StrictModel):
    query: str
    path: str = "."
    glob: str = "**/*"
    regex: bool = False


class FileWriteRequest(StrictModel):
    path: str
    content: str


class FileApplyPatchRequest(StrictModel):
    patch: str


class FileDiffRequest(StrictModel):
    pass


def _direct_result(
    tool: str,
    *,
    stdout: str = "",
    message: str = "",
    metadata: dict[str, Any] | None = None,
    truncated: bool = False,
) -> ToolResult:
    return ToolResult(
        tool=tool,
        success=True,
        category=ErrorCategory.SUCCESS,
        stdout=stdout,
        message=message,
        metadata=metadata or {},
        output_truncated=truncated,
    )


def _error_result(tool: str, category: ErrorCategory, message: str) -> ToolResult:
    return ToolResult(tool=tool, success=False, category=category, message=message, stderr=message)


class DirectFileTool(ToolPlugin):
    request_model: ClassVar[type[BaseModel]]

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        return HealthCheckResult(healthy=True, message="built in")

    def validate_request(self, request: dict[str, Any]) -> BaseModel:
        return self.request_model.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        raise RuntimeError("direct file tools do not render subprocess commands")

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        raise RuntimeError("direct file tools do not parse subprocess commands")

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        result: ToolResult
        try:
            request = self.validate_request(raw_request)
            if context.session is None or not isinstance(context.workspace_policy, WorkspacePolicy):
                result = _error_result(
                    self.descriptor.name,
                    ErrorCategory.INTERNAL_ERROR,
                    "missing workspace context",
                )
            else:
                result = self.execute_direct(request, context)
        except ValidationError as exc:
            result = _error_result(self.descriptor.name, ErrorCategory.INVALID_REQUEST, str(exc))
        except PathPolicyError as exc:
            result = _error_result(self.descriptor.name, ErrorCategory.PERMISSION_DENIED, str(exc))
        except FileNotFoundError:
            result = _error_result(
                self.descriptor.name, ErrorCategory.INVALID_REQUEST, "path not found"
            )
        except UnicodeDecodeError:
            result = _error_result(
                self.descriptor.name, ErrorCategory.INVALID_REQUEST, "file is not UTF-8 text"
            )
        except ValueError as exc:
            result = _error_result(self.descriptor.name, ErrorCategory.INVALID_REQUEST, str(exc))
        except Exception as exc:
            result = _error_result(self.descriptor.name, ErrorCategory.INTERNAL_ERROR, str(exc))
        return self._publish(result, context, raw_request)

    def _publish(
        self,
        result: ToolResult,
        context: ToolContext,
        raw_request: dict[str, Any] | None = None,
    ) -> ToolResult:
        if context.audit_callback is not None:
            context.audit_callback(
                audit_record(
                    result,
                    request=_safe_audit_request(raw_request),
                    policy=context.observation_policy,
                )
            )
        compacted = _apply_policy_view(result, raw_request, context)
        compacted = compact_tool_result(compacted, policy=context.observation_policy)
        stdout, stdout_truncated = bounded_text_with_marker(
            compacted.stdout,
            context.max_output_bytes,
            description=f"{compacted.tool} stdout",
        )
        stderr, stderr_truncated = bounded_text_with_marker(
            compacted.stderr,
            min(context.max_output_bytes, 8 * 1024),
            description=f"{compacted.tool} stderr",
        )
        return compacted.model_copy(
            update={
                "stdout": stdout,
                "stderr": stderr,
                "output_truncated": bool(
                    compacted.output_truncated or stdout_truncated or stderr_truncated
                ),
            }
        )

    def execute_direct(self, request: BaseModel, context: ToolContext) -> ToolResult:
        raise NotImplementedError


def _descriptor(name: str, capability: str) -> ToolDescriptor:
    return ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name=name,
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[capability, "workspace_policy"],
        visibility=ToolVisibility.AGENT_VISIBLE,
    )


class FileListTool(DirectFileTool):
    descriptor = _descriptor("file.list", "list")
    request_model = FileListRequest

    def execute_direct(self, request: BaseModel, context: ToolContext) -> ToolResult:
        assert isinstance(request, FileListRequest)
        assert context.session is not None
        policy = context.workspace_policy
        assert isinstance(policy, WorkspacePolicy)
        relative = policy.check_read(request.path, allow_root=True)
        root = _safe_directory(context, relative)
        try:
            output, metadata = list_workspace_entries(
                root,
                relative_path=relative,
                recursive=request.recursive,
                policy=None,
                is_excluded=policy.is_excluded,
                workspace_root=context.session.root,
            )
        except ValueError as exc:
            raise PathPolicyError(str(exc)) from exc
        return _direct_result(self.descriptor.name, stdout=output, metadata=metadata)


class FileReadTool(DirectFileTool):
    descriptor = _descriptor("file.read", "read")
    request_model = FileReadRequest

    def execute_direct(self, request: BaseModel, context: ToolContext) -> ToolResult:
        assert isinstance(request, FileReadRequest)
        assert context.session is not None
        policy = context.workspace_policy
        assert isinstance(policy, WorkspacePolicy)
        relative = policy.check_read(request.path)
        text = context.session.read_file(relative).decode("utf-8")
        line_count = len(text.splitlines())
        if request.start_line is not None and request.start_line > line_count:
            raise ValueError("start_line is outside the file")
        if request.end_line is not None and request.end_line > line_count:
            raise ValueError("end_line is outside the file")
        return _direct_result(
            self.descriptor.name,
            stdout=text,
            metadata={"line_count": len(text.splitlines()), "view_mode": "raw"},
        )


class FileSearchTool(DirectFileTool):
    descriptor = _descriptor("file.search", "search")
    request_model = FileSearchRequest

    def execute_direct(self, request: BaseModel, context: ToolContext) -> ToolResult:
        assert isinstance(request, FileSearchRequest)
        assert context.session is not None
        policy = context.workspace_policy
        assert isinstance(policy, WorkspacePolicy)
        relative = policy.check_read(request.path, allow_root=True)
        root = _safe_directory(context, relative)
        matcher = re.compile(request.query) if request.regex else None
        matches: list[str] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise PathPolicyError("symlinks are not permitted inside the workspace")
            if not path.is_file():
                continue
            workspace_relative = path.relative_to(context.session.root).as_posix()
            if policy.is_excluded(workspace_relative) or not glob_matches(
                workspace_relative, request.glob
            ):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(lines, start=1):
                found = bool(matcher.search(line)) if matcher else request.query in line
                if found:
                    matches.append(f"{workspace_relative}:{number}:{line}")
        return _direct_result(self.descriptor.name, stdout="\n".join(matches))


class FileWriteTool(DirectFileTool):
    descriptor = _descriptor("file.write", "write")
    request_model = FileWriteRequest

    def execute_direct(self, request: BaseModel, context: ToolContext) -> ToolResult:
        assert isinstance(request, FileWriteRequest)
        assert context.session is not None
        policy = context.workspace_policy
        assert isinstance(policy, WorkspacePolicy)
        relative = policy.check_write(request.path)
        target = context.session.root / relative
        previous = target.read_bytes() if target.is_file() else None
        context.session.write_file(relative, request.content.encode("utf-8"))
        try:
            _check_workspace_limits(context, policy)
        except Exception:
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                context.session.write_file(relative, previous)
            raise
        return _direct_result(
            self.descriptor.name,
            message=f"wrote {relative}",
            metadata={"changed_files": [relative]},
        )


class FileApplyPatchTool(DirectFileTool):
    descriptor = _descriptor("file.apply_patch", "apply_patch")
    request_model = FileApplyPatchRequest

    def execute_direct(self, request: BaseModel, context: ToolContext) -> ToolResult:
        assert isinstance(request, FileApplyPatchRequest)
        assert context.session is not None
        policy = context.workspace_policy
        assert isinstance(policy, WorkspacePolicy)
        changes, previous = _parse_and_apply_patch(request.patch, context, policy)
        policy.check_patch_size(len(changes), len(request.patch.splitlines()))
        try:
            _check_workspace_limits(context, policy)
        except Exception:
            for relative, prior_content in previous.items():
                target = context.session.root / relative
                if prior_content is None:
                    target.unlink(missing_ok=True)
                else:
                    context.session.write_file(relative, prior_content)
            raise
        return _direct_result(
            self.descriptor.name,
            message=f"applied patch to {len(changes)} file(s)",
            metadata={"changed_files": changes},
        )


class FileDiffTool(DirectFileTool):
    descriptor = _descriptor("file.diff", "diff")
    request_model = FileDiffRequest

    def execute_direct(self, request: BaseModel, context: ToolContext) -> ToolResult:
        assert context.session is not None
        diff = context.session.snapshot_diff()
        result = _direct_result(self.descriptor.name, stdout=diff.patch)
        result.metadata = {
            "changed_files": diff.changed_files,
            "added_lines": diff.added_lines,
            "deleted_lines": diff.deleted_lines,
        }
        return result


def _apply_policy_view(
    result: ToolResult,
    raw_request: dict[str, Any] | None,
    context: ToolContext,
) -> ToolResult:
    policy = context.observation_policy
    if (
        not result.success
        or policy is None
        or not isinstance(raw_request, dict)
        or context.session is None
    ):
        return result
    workspace_policy = context.workspace_policy
    if not isinstance(workspace_policy, WorkspacePolicy):
        return result
    if result.tool == "file.list":
        relative = workspace_policy.check_read(str(raw_request.get("path", ".")), allow_root=True)
        output, metadata = list_workspace_entries(
            _safe_directory(context, relative),
            relative_path=relative,
            recursive=bool(raw_request.get("recursive", True)),
            requested_max_depth=raw_request.get("max_depth")
            if isinstance(raw_request.get("max_depth"), int)
            else None,
            requested_max_entries=raw_request.get("max_entries")
            if isinstance(raw_request.get("max_entries"), int)
            else None,
            policy=policy,
            is_excluded=workspace_policy.is_excluded,
            workspace_root=context.session.root,
        )
        return result.model_copy(
            update={"stdout": output, "metadata": {**result.metadata, **metadata}}
        )
    if result.tool == "file.read":
        relative = workspace_policy.check_read(str(raw_request.get("path", "")))
        rendered, metadata = bounded_read_view(
            result.stdout,
            relative,
            start_line=raw_request.get("start_line")
            if isinstance(raw_request.get("start_line"), int)
            else None,
            end_line=raw_request.get("end_line")
            if isinstance(raw_request.get("end_line"), int)
            else None,
            concise=raw_request.get("concise")
            if isinstance(raw_request.get("concise"), bool)
            else None,
            policy=policy,
        )
        return result.model_copy(
            update={"stdout": rendered, "metadata": {**result.metadata, **metadata}}
        )
    return result


def _safe_audit_request(request: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(request, dict):
        return {}
    allowed = {
        "path",
        "start_line",
        "end_line",
        "concise",
        "recursive",
        "max_depth",
        "max_entries",
        "query",
        "glob",
        "regex",
    }
    return {key: value for key, value in request.items() if key in allowed}


def _safe_directory(context: ToolContext, relative: str) -> Path:
    assert context.session is not None
    root = context.session.root if relative == "." else context.session.root / relative
    if root.is_symlink():
        raise PathPolicyError("symlinks are not permitted inside the workspace")
    try:
        resolved = root.resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError(relative) from None
    if not resolved.is_relative_to(context.session.root) or not resolved.is_dir():
        raise PathPolicyError("directory escapes the workspace")
    return resolved


def _check_workspace_limits(context: ToolContext, policy: WorkspacePolicy) -> None:
    assert context.session is not None
    diff = context.session.snapshot_diff()
    policy.check_patch_size(len(diff.changed_files), diff.added_lines + diff.deleted_lines)
    if policy.max_workspace_bytes is not None:
        size = 0
        for path in context.session.root.rglob("*"):
            if path.is_symlink():
                raise PathPolicyError("symlinks are not permitted inside the workspace")
            if path.is_file() and ".verigym_internal" not in path.parts:
                size += path.stat().st_size
        if size > policy.max_workspace_bytes:
            raise PathPolicyError(
                f"workspace uses {size} bytes; limit is {policy.max_workspace_bytes}"
            )


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _clean_patch_path(header: str) -> str | None:
    raw = header.split("\t", 1)[0].split(" ", 1)[0]
    if raw == "/dev/null":
        return None
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    return PurePosixPath(raw).as_posix()


def _parse_and_apply_patch(
    patch: str, context: ToolContext, policy: WorkspacePolicy
) -> tuple[list[str], dict[str, bytes | None]]:
    assert context.session is not None
    lines = patch.splitlines(keepends=True)
    if lines and lines[0].strip() == "*** Begin Patch":
        lines = lines[1:]
    if lines and lines[-1].strip() == "*** End Patch":
        lines = lines[:-1]
    index = 0
    planned: dict[str, bytes | None] = {}
    while index < len(lines):
        if not lines[index].startswith("--- "):
            if lines[index].strip():
                raise PathPolicyError("invalid unified patch: expected '---' header")
            index += 1
            continue
        old_path = _clean_patch_path(lines[index][4:].strip())
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise PathPolicyError("invalid unified patch: missing '+++' header")
        new_path = _clean_patch_path(lines[index][4:].strip())
        index += 1
        target = new_path or old_path
        if target is None:
            raise PathPolicyError("patch cannot have both paths set to /dev/null")
        target = policy.check_write(target)
        if old_path is not None and policy.check_write(old_path) != target:
            raise PathPolicyError("renames are not supported by file.apply_patch")
        if old_path is None:
            original: list[str] = []
        else:
            original = context.session.read_file(target).decode("utf-8").splitlines(keepends=True)
        output: list[str] = []
        source_index = 0
        saw_hunk = False
        while index < len(lines) and not lines[index].startswith("--- "):
            if not lines[index].startswith("@@ "):
                if lines[index].strip():
                    raise PathPolicyError("invalid unified patch: expected hunk header")
                index += 1
                continue
            match = _HUNK_RE.match(lines[index].rstrip("\n"))
            if not match:
                raise PathPolicyError("invalid unified patch hunk header")
            saw_hunk = True
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_count = int(match.group(4) or "1")
            target_source_index = 0 if old_start == 0 else old_start - 1
            if target_source_index < source_index or target_source_index > len(original):
                raise PathPolicyError("patch hunk is out of range or overlaps a prior hunk")
            output.extend(original[source_index:target_source_index])
            source_index = target_source_index
            index += 1
            consumed_old = 0
            produced_new = 0
            while index < len(lines) and not lines[index].startswith(("@@ ", "--- ")):
                line = lines[index]
                if line.startswith("\\ No newline at end of file"):
                    index += 1
                    continue
                if not line or line[0] not in {" ", "+", "-"}:
                    raise PathPolicyError("invalid unified patch hunk body")
                marker, content = line[0], line[1:]
                if marker in {" ", "-"}:
                    if source_index >= len(original) or original[source_index] != content:
                        raise PathPolicyError("patch context does not match the workspace")
                    source_index += 1
                    consumed_old += 1
                if marker in {" ", "+"}:
                    output.append(content)
                    produced_new += 1
                index += 1
            if consumed_old != old_count or produced_new != new_count:
                raise PathPolicyError("patch hunk line counts do not match its header")
        if not saw_hunk:
            raise PathPolicyError("patch file has no hunks")
        output.extend(original[source_index:])
        planned[target] = None if new_path is None else "".join(output).encode("utf-8")
    if not planned:
        raise PathPolicyError("patch is empty")
    policy.check_patch_size(len(planned), len(patch.splitlines()))
    previous: dict[str, bytes | None] = {}
    for target, data in planned.items():
        target_path = context.session.root / target
        previous[target] = target_path.read_bytes() if target_path.is_file() else None
        if data is None:
            target_path.unlink(missing_ok=True)
        else:
            context.session.write_file(target, data)
    return sorted(planned), previous


def builtin_file_tools() -> list[ToolPlugin]:
    return [
        FileListTool(),
        FileReadTool(),
        FileSearchTool(),
        FileApplyPatchTool(),
        FileWriteTool(),
        FileDiffTool(),
    ]
