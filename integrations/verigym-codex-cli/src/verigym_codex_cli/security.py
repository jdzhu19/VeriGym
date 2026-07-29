"""Workspace and event-policy checks for Codex CLI episodes."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .events import ParsedEventStream

_NETWORK_COMMANDS = {
    "curl",
    "wget",
    "nc",
    "ncat",
    "ssh",
    "scp",
    "git",
    "pip",
    "npm",
}
_VISIBLE_COMMANDS = {
    "bash",
    "cat",
    "find",
    "grep",
    "head",
    "iverilog",
    "ls",
    "printf",
    "pwd",
    "rg",
    "sed",
    "sh",
    "sort",
    "tail",
    "true",
    "vvp",
    "verigym-public-test",
    "wc",
    "zsh",
}
_SHELL_COMMANDS = {"bash", "sh", "zsh"}
_COMMAND_SEPARATORS = {"&&", "||", ";", "|", "&"}
_REDIRECTION_OPERATORS = {"<", ">", "<<", ">>", "<<<", "<>", ">&", "<&"}
_OPAQUE_LINE_BREAK = "\ue000"
_MAX_HEREDOC_BODY_BYTES = 2_000_000
_SANDBOX_BACKEND_MARKERS = (
    "bwrap: creating new namespace failed",
    "kernel does not allow non-root user namespaces",
    "permission profiles requiring direct runtime enforcement are incompatible with "
    "--use-legacy-landlock",
    "split sandbox policies requiring direct runtime enforcement are incompatible with "
    "--use-legacy-landlock",
    "error applying legacy linux sandbox restrictions",
    "sandbox(landlockrestrict)",
)


class CodexPolicyError(RuntimeError):
    """The external CLI crossed a declared workspace or command boundary."""


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Content-only visible-workspace identity without persisted file contents."""

    workspace_hash: str
    file_hashes: dict[str, str]
    directories: tuple[str, ...]
    file_count: int
    directory_count: int
    total_bytes: int

    def safe_dict(self) -> dict[str, Any]:
        return {
            "workspace_hash": self.workspace_hash,
            "file_hashes": dict(sorted(self.file_hashes.items())),
            "directories": list(self.directories),
            "file_count": self.file_count,
            "directory_count": self.directory_count,
            "total_bytes": self.total_bytes,
            "content_values_persisted": False,
        }


def assert_instruction_isolation(workspace: Path) -> None:
    resolved = workspace.resolve(strict=True)
    for ancestor in resolved.parents:
        for name in ("AGENTS.md", ".codex"):
            candidate = ancestor / name
            if candidate.exists() or candidate.is_symlink():
                raise CodexPolicyError(
                    f"ancestor instruction/config contamination detected: {name}"
                )


def assert_empty_directory(workspace: Path) -> None:
    if any(workspace.iterdir()):
        raise CodexPolicyError("Track A working directory is not empty")


def assert_safe_workspace_tree(workspace: Path) -> None:
    root = workspace.resolve(strict=True)
    for path in sorted(root.rglob("*")):
        metadata = os.lstat(path)
        relative = path.relative_to(root).as_posix()
        if relative == ".verigym_internal" and stat.S_ISDIR(metadata.st_mode):
            continue
        if ".verigym_internal" in path.relative_to(root).parts:
            raise CodexPolicyError("runtime-internal workspace content is forbidden")
        if stat.S_ISLNK(metadata.st_mode):
            raise CodexPolicyError(f"workspace symlink is forbidden: {relative}")
        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
            raise CodexPolicyError(f"workspace hardlink is forbidden: {relative}")
        if not stat.S_ISDIR(metadata.st_mode) and not stat.S_ISREG(metadata.st_mode):
            raise CodexPolicyError(f"workspace special file is forbidden: {relative}")


def snapshot_visible_workspace(workspace: Path) -> WorkspaceSnapshot:
    """Hash the safe visible tree while excluding the empty runtime-internal directory."""

    assert_safe_workspace_tree(workspace)
    root = workspace.resolve(strict=True)
    file_hashes: dict[str, str] = {}
    directories: list[str] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)
        if ".verigym_internal" in relative_path.parts:
            continue
        relative = relative_path.as_posix()
        metadata = os.lstat(path)
        if stat.S_ISDIR(metadata.st_mode):
            directories.append(relative)
            continue
        data = path.read_bytes()
        if len(data) != metadata.st_size:
            raise CodexPolicyError("workspace file changed while its identity was captured")
        file_hashes[relative] = hashlib.sha256(data).hexdigest()
        total_bytes += len(data)
    identity = {
        "files": sorted(file_hashes.items()),
        "directories": sorted(directories),
    }
    workspace_hash = hashlib.sha256(
        json.dumps(identity, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return WorkspaceSnapshot(
        workspace_hash=workspace_hash,
        file_hashes=file_hashes,
        directories=tuple(sorted(directories)),
        file_count=len(file_hashes),
        directory_count=len(directories),
        total_bytes=total_bytes,
    )


def compare_workspace_snapshots(
    before: WorkspaceSnapshot,
    after: WorkspaceSnapshot,
    *,
    editable_globs: tuple[str, ...],
    readonly_globs: tuple[str, ...],
) -> dict[str, Any]:
    """Describe file-level mutations and record policy violations for core enforcement."""

    changed_paths = sorted(
        path
        for path in set(before.file_hashes) | set(after.file_hashes)
        if before.file_hashes.get(path) != after.file_hashes.get(path)
    )
    violations: list[str] = []
    for path in changed_paths:
        if _matches_any_glob(path, readonly_globs):
            violations.append(f"external agent changed a read-only path: {path}")
        elif not _matches_any_glob(path, editable_globs):
            violations.append(f"external agent changed a path outside editable globs: {path}")
    return {
        "schema_version": "1.0",
        "policy_id": "visible_task_workspace_policy_v2",
        "before": before.safe_dict(),
        "after": after.safe_dict(),
        "changed_paths": changed_paths,
        "changed_file_count": len(changed_paths),
        "editable_globs": list(editable_globs),
        "readonly_globs": list(readonly_globs),
        "policy_passed": not violations,
        "violations": violations,
        "enforcement_owner": "verigym_core_external_agent_bridge",
        "content_values_persisted": False,
    }


def sandbox_backend_failure(stdout: str, stderr: str) -> str | None:
    """Return a stable category for a known local sandbox-backend prerequisite failure."""

    text = f"{stdout}\n{stderr}".lower()
    if any(marker in text for marker in _SANDBOX_BACKEND_MARKERS):
        return "sandbox_backend_unavailable"
    return None


def validate_external_events(
    parsed: ParsedEventStream,
    workspace: Path,
    *,
    logical_workspace: bool = False,
    editable_globs: tuple[str, ...] = (),
) -> None:
    """Validate events against either a host path or a runtime-logical path.

    Docker event paths are expressed in the container's ``/workspace`` namespace.
    Resolving that path on the host would both conflate namespaces and require an
    unrelated host directory to exist. Logical validation is therefore lexical and
    fail-closed; host-local validation retains symlink-aware filesystem resolution.
    """

    if logical_workspace:
        logical_root = PurePosixPath(workspace.as_posix())
        if not logical_root.is_absolute() or ".." in logical_root.parts:
            raise CodexPolicyError("runtime logical workspace root is invalid")
        root = workspace
    else:
        root = workspace.resolve(strict=True)
    for event in parsed.events:
        if event.category in {"file_read", "file_write"}:
            path = event.payload.get("path")
            if isinstance(path, str) and path:
                _validate_event_path(path, root, logical_workspace=logical_workspace)
        if event.category == "patch_applied":
            paths = event.payload.get("paths")
            if isinstance(paths, list):
                for path in paths:
                    if isinstance(path, str) and path:
                        _validate_event_path(path, root, logical_workspace=logical_workspace)
        if event.category in {"command_started", "command_completed"}:
            command = event.payload.get("command")
            if isinstance(command, str) and command:
                _validate_command(
                    command,
                    root,
                    logical_workspace=logical_workspace,
                    editable_globs=editable_globs,
                )
        if event.category == "tool_call":
            tool = str(event.payload.get("tool") or "unknown")
            raise CodexPolicyError(f"external network, MCP, or unknown tool is forbidden: {tool}")


def _validate_event_path(raw: str, root: Path, *, logical_workspace: bool) -> None:
    if "\x00" in raw:
        raise CodexPolicyError("CLI event contains a NUL path")
    if logical_workspace and "\\" in raw:
        raise CodexPolicyError("CLI event contains a non-POSIX runtime path")
    normalized = PurePosixPath(raw.replace("\\", "/"))
    if any(part == ".." for part in normalized.parts):
        raise CodexPolicyError("CLI event reports parent-path traversal")
    if logical_workspace:
        logical_root = PurePosixPath(root.as_posix())
        if normalized.is_absolute() and not normalized.is_relative_to(logical_root):
            raise CodexPolicyError("CLI event reports access outside the visible workspace")
        return
    path = Path(raw)
    if path.is_absolute():
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise CodexPolicyError("CLI event reports access outside the visible workspace")
        return


def _validate_command(
    command: str,
    root: Path,
    *,
    logical_workspace: bool,
    editable_globs: tuple[str, ...] = (),
) -> None:
    lowered = command.lower()
    if any(
        marker in lowered
        for marker in (
            "$home",
            "${home",
            "$(",
            "`",
            "<(",
            ">(",
        )
    ):
        raise CodexPolicyError("external command crosses the visible task policy")
    try:
        outer_tokens = shlex.split(command, posix=True)
    except ValueError as exc:
        raise CodexPolicyError("external command cannot be safely tokenized") from exc
    if outer_tokens and Path(outer_tokens[0]).name in _SHELL_COMMANDS:
        _validate_executable(outer_tokens[0])
        if len(outer_tokens) != 3 or outer_tokens[1] not in {"-c", "-lc"}:
            raise CodexPolicyError("external shell commands require an inspectable -c payload")
        payload = outer_tokens[2]
    else:
        payload = command
    if "\r" in payload:
        raise CodexPolicyError("external command contains an unsupported carriage return")
    if "\n" in payload and _validate_heredoc(
        payload,
        root,
        logical_workspace=logical_workspace,
        editable_globs=editable_globs,
    ):
        return
    _validate_simple_command(payload, root, logical_workspace=logical_workspace)


def _validate_heredoc(
    payload: str,
    root: Path,
    *,
    logical_workspace: bool,
    editable_globs: tuple[str, ...],
) -> bool:
    """Accept only one expansion-disabled heredoc write and no trailing command."""

    lines = payload.splitlines()
    if len(lines) < 2:
        return False
    header = re.fullmatch(
        r"[ \t]*cat[ \t]+>[ \t]+(?P<target>[A-Za-z0-9_./-]+)"
        r"[ \t]+<<'(?P<delimiter>[A-Za-z_][A-Za-z0-9_]{0,63})'[ \t]*",
        lines[0],
    )
    if header is None:
        return False
    delimiter = header.group("delimiter")
    delimiter_indexes = [
        index for index, line in enumerate(lines[1:], start=1) if line == delimiter
    ]
    if delimiter_indexes != [len(lines) - 1]:
        raise CodexPolicyError("external heredoc must end at its single static delimiter")
    body = "\n".join(lines[1:-1])
    if len(body.encode("utf-8")) > _MAX_HEREDOC_BODY_BYTES:
        raise CodexPolicyError("external heredoc body exceeds the bounded workspace policy")
    target = header.group("target")
    _validate_command_path(target, root, logical_workspace=logical_workspace)
    relative_target = _relative_workspace_path(
        target,
        root,
        logical_workspace=logical_workspace,
    )
    if not editable_globs or not _matches_any_glob(relative_target, editable_globs):
        raise CodexPolicyError("external heredoc output target is not declared editable")
    return True


def _validate_simple_command(
    command: str,
    root: Path,
    *,
    logical_workspace: bool,
) -> None:
    protected = _protect_quoted_line_breaks(command)
    try:
        lexer = shlex.shlex(protected, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError as exc:
        raise CodexPolicyError("external command cannot be safely tokenized") from exc
    if not tokens:
        raise CodexPolicyError("external command is empty")

    invocations: list[tuple[list[str], list[tuple[str, str]]]] = []
    arguments: list[str] = []
    redirections: list[tuple[str, str]] = []
    expect_redirection: str | None = None
    for token in tokens:
        if expect_redirection is not None:
            if token in _COMMAND_SEPARATORS or token in _REDIRECTION_OPERATORS:
                raise CodexPolicyError("external command has an incomplete redirection")
            if _OPAQUE_LINE_BREAK in token:
                raise CodexPolicyError("external redirection target contains a line break")
            redirections.append((expect_redirection, token))
            expect_redirection = None
            continue
        if token in _REDIRECTION_OPERATORS:
            if token in {"<<", "<<<"}:
                raise CodexPolicyError("external heredoc form is not statically permitted")
            expect_redirection = token
            continue
        if token in _COMMAND_SEPARATORS:
            if not arguments:
                raise CodexPolicyError("external command contains an empty command segment")
            invocations.append((arguments, redirections))
            arguments = []
            redirections = []
            continue
        arguments.append(token)
    if expect_redirection is not None:
        raise CodexPolicyError("external command has an incomplete redirection")
    if not arguments:
        raise CodexPolicyError("external command contains a trailing separator")
    invocations.append((arguments, redirections))

    commands: list[str] = []
    for arguments, redirections in invocations:
        executable = arguments[0]
        if _OPAQUE_LINE_BREAK in executable:
            raise CodexPolicyError("external executable contains a line break")
        name = _validate_executable(executable)
        commands.append(name)
        for _operator, target in redirections:
            _validate_command_path(target, root, logical_workspace=logical_workspace)
        if name == "printf" and redirections:
            raise CodexPolicyError("printf is permitted only as a stdout-only command")
        _validate_command_operands(
            name,
            arguments[1:],
            root,
            logical_workspace=logical_workspace,
        )
    if any(name in _NETWORK_COMMANDS for name in commands):
        raise CodexPolicyError("network-capable external command is forbidden")
    unsupported = [name for name in commands if name not in _VISIBLE_COMMANDS]
    if unsupported:
        raise CodexPolicyError(
            f"external command is outside the visible command allowlist: {unsupported[0]}"
        )
    if any(name in _SHELL_COMMANDS for name in commands):
        raise CodexPolicyError("nested external shell commands are forbidden")


def _protect_quoted_line_breaks(command: str) -> str:
    if _OPAQUE_LINE_BREAK in command:
        raise CodexPolicyError("external command contains a reserved parser character")
    output: list[str] = []
    quote: str | None = None
    escaped = False
    for character in command:
        if escaped:
            if character == "\n":
                raise CodexPolicyError("external command contains an unquoted line break")
            output.append(character)
            escaped = False
            continue
        if quote != "'" and character == "\\":
            output.append(character)
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            output.append(character)
            continue
        if character == "\n":
            if quote is None:
                raise CodexPolicyError("external command contains an unquoted line break")
            output.append(_OPAQUE_LINE_BREAK)
            continue
        output.append(character)
    if escaped or quote is not None:
        raise CodexPolicyError("external command cannot be safely tokenized")
    return "".join(output)


def _validate_executable(token: str) -> str:
    if _OPAQUE_LINE_BREAK in token or "\\" in token or "$" in token or token.startswith("~"):
        raise CodexPolicyError("external executable path is not statically bounded")
    normalized = PurePosixPath(token)
    if any(part == ".." for part in normalized.parts):
        raise CodexPolicyError("external executable contains parent-path traversal")
    name = normalized.name
    if "/" in token:
        allowed = {
            PurePosixPath("/bin") / name,
            PurePosixPath("/usr/bin") / name,
        }
        if name == "verigym-public-test":
            allowed.add(PurePosixPath("/usr/local/bin/verigym-public-test"))
        if normalized not in allowed:
            raise CodexPolicyError("external executable path is outside the system allowlist")
    return name


def _validate_command_operands(
    name: str,
    operands: list[str],
    root: Path,
    *,
    logical_workspace: bool,
) -> None:
    if name == "printf":
        return
    if name == "verigym-public-test":
        if operands == ["list"]:
            return
        if (
            len(operands) == 2
            and operands[0] == "run"
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", operands[1])
        ):
            return
        raise CodexPolicyError("public-test command must be exactly list or run <safe-test-id>")
    if any(_OPAQUE_LINE_BREAK in operand for operand in operands):
        raise CodexPolicyError("external command contains a non-printf multiline operand")
    if name == "sed":
        _validate_sed_operands(operands, root, logical_workspace=logical_workspace)
        return
    for operand in operands:
        _validate_command_path(operand, root, logical_workspace=logical_workspace)


def _validate_sed_operands(
    operands: list[str],
    root: Path,
    *,
    logical_workspace: bool,
) -> None:
    expression_seen = False
    expect_expression = False
    expect_script_path = False
    for operand in operands:
        if expect_expression:
            expect_expression = False
            expression_seen = True
            continue
        if expect_script_path:
            _validate_command_path(operand, root, logical_workspace=logical_workspace)
            expect_script_path = False
            expression_seen = True
            continue
        if operand == "-e":
            expect_expression = True
            continue
        if operand == "-f":
            expect_script_path = True
            continue
        if operand.startswith("-"):
            continue
        if not expression_seen:
            expression_seen = True
            continue
        _validate_command_path(operand, root, logical_workspace=logical_workspace)
    if expect_expression or expect_script_path:
        raise CodexPolicyError("external sed command has an incomplete operand")


def _matches_any_glob(path: str, patterns: tuple[str, ...]) -> bool:
    return any(
        fnmatch.fnmatchcase(path, variant)
        for pattern in patterns
        for variant in _glob_variants(pattern)
    )


def _glob_variants(pattern: str) -> set[str]:
    variants = {pattern}
    pending = [pattern]
    while pending:
        current = pending.pop()
        marker = "**/"
        start = current.find(marker)
        if start >= 0:
            collapsed = current[:start] + current[start + len(marker) :]
            if collapsed not in variants:
                variants.add(collapsed)
                pending.append(collapsed)
    return variants


def _validate_command_path(token: str, root: Path, *, logical_workspace: bool) -> None:
    value = token.split("=", 1)[-1] if "=" in token else token
    if not value or value.startswith("-"):
        return
    if "$" in value or value.startswith("~"):
        raise CodexPolicyError("external command contains an unbounded path expansion")
    normalized = PurePosixPath(value.replace("\\", "/"))
    if any(part == ".." for part in normalized.parts):
        raise CodexPolicyError("external command contains parent-path traversal")
    if not normalized.is_absolute() and "/" not in value:
        return
    if logical_workspace:
        if "\\" in value:
            raise CodexPolicyError("external command contains a non-POSIX runtime path")
        logical_root = PurePosixPath(root.as_posix())
        logical_candidate = normalized if normalized.is_absolute() else logical_root / normalized
        if not logical_candidate.is_relative_to(logical_root):
            raise CodexPolicyError("external command names a path outside the visible workspace")
        return
    candidate = Path(value)
    resolved = (
        candidate.resolve(strict=False)
        if candidate.is_absolute()
        else (root / candidate).resolve(strict=False)
    )
    if not resolved.is_relative_to(root):
        raise CodexPolicyError("external command names a path outside the visible workspace")


def _relative_workspace_path(
    token: str,
    root: Path,
    *,
    logical_workspace: bool,
) -> str:
    normalized = PurePosixPath(token)
    if logical_workspace:
        logical_root = PurePosixPath(root.as_posix())
        logical_candidate = normalized if normalized.is_absolute() else logical_root / normalized
        return logical_candidate.relative_to(logical_root).as_posix()
    resolved_root = root.resolve(strict=True)
    host_candidate = (
        Path(token).resolve(strict=False)
        if Path(token).is_absolute()
        else (resolved_root / token).resolve(strict=False)
    )
    return host_candidate.relative_to(resolved_root).as_posix()


__all__ = [
    "CodexPolicyError",
    "WorkspaceSnapshot",
    "assert_empty_directory",
    "assert_instruction_isolation",
    "assert_safe_workspace_tree",
    "compare_workspace_snapshots",
    "sandbox_backend_failure",
    "snapshot_visible_workspace",
    "validate_external_events",
]
