"""Workspace and event-policy checks for Codex CLI episodes."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
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
    "tail",
    "true",
    "vvp",
    "wc",
    "zsh",
}
_SHELL_COMMANDS = {"bash", "sh", "zsh"}
_COMMAND_SEPARATORS = {"&&", "||", ";", "|", "&"}
_REDIRECTION_OPERATORS = {"<", ">", "<<", ">>", "<<<", "<>", ">&", "<&"}
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


def validate_external_events(parsed: ParsedEventStream, workspace: Path) -> None:
    root = workspace.resolve(strict=True)
    for event in parsed.events:
        if event.category in {"file_read", "file_write"}:
            path = event.payload.get("path")
            if isinstance(path, str) and path:
                _validate_event_path(path, root)
        if event.category == "patch_applied":
            paths = event.payload.get("paths")
            if isinstance(paths, list):
                for path in paths:
                    if isinstance(path, str) and path:
                        _validate_event_path(path, root)
        if event.category in {"command_started", "command_completed"}:
            command = event.payload.get("command")
            if isinstance(command, str) and command:
                _validate_command(command, root)
        if event.category == "tool_call":
            tool = str(event.payload.get("tool") or "unknown")
            raise CodexPolicyError(f"external network, MCP, or unknown tool is forbidden: {tool}")


def _validate_event_path(raw: str, root: Path) -> None:
    if "\x00" in raw:
        raise CodexPolicyError("CLI event contains a NUL path")
    path = Path(raw)
    if path.is_absolute():
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise CodexPolicyError("CLI event reports access outside the visible workspace")
        return
    normalized = PurePosixPath(raw.replace("\\", "/"))
    if any(part == ".." for part in normalized.parts):
        raise CodexPolicyError("CLI event reports parent-path traversal")


def _validate_command(command: str, root: Path) -> None:
    lowered = command.lower()
    if any(
        marker in lowered
        for marker in (
            "http://",
            "https://",
            "/etc/",
            "/proc/",
            "/sys/",
            "../",
            "$home",
            "${home",
            "$(",
            "`",
            "<(",
            ">(",
        )
    ):
        raise CodexPolicyError("external command crosses the visible task policy")
    if "\n" in command or "\r" in command:
        raise CodexPolicyError("external command contains a line break")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError as exc:
        raise CodexPolicyError("external command cannot be safely tokenized") from exc
    if tokens and Path(tokens[0]).name in _SHELL_COMMANDS:
        nested = False
        for index, token in enumerate(tokens[:-1]):
            if token in {"-c", "-lc"}:
                _validate_command(tokens[index + 1], root)
                nested = True
                break
        if not nested:
            raise CodexPolicyError("external shell commands require an inspectable -c payload")
        tokens = tokens[:1]
    commands: list[str] = []
    redirection_seen = False
    expect_command = True
    expect_redirection_target = False
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            expect_command = True
            expect_redirection_target = False
            continue
        if token in _REDIRECTION_OPERATORS:
            redirection_seen = True
            expect_redirection_target = True
            continue
        if expect_redirection_target:
            _validate_command_path(token, root)
            expect_redirection_target = False
            continue
        if expect_command and not token.startswith(("-", ">", "<")):
            commands.append(Path(token).name)
            expect_command = False
            continue
        _validate_command_path(token, root)
    if any(name in _NETWORK_COMMANDS for name in commands):
        raise CodexPolicyError("network-capable external command is forbidden")
    if redirection_seen and "printf" in commands:
        raise CodexPolicyError("printf is permitted only as a stdout-only command")
    unsupported = [name for name in commands if name not in _VISIBLE_COMMANDS]
    if unsupported:
        raise CodexPolicyError(
            f"external command is outside the visible command allowlist: {unsupported[0]}"
        )


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


def _validate_command_path(token: str, root: Path) -> None:
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
    candidate = Path(value)
    resolved = (
        candidate.resolve(strict=False)
        if candidate.is_absolute()
        else (root / candidate).resolve(strict=False)
    )
    if not resolved.is_relative_to(root):
        raise CodexPolicyError("external command names a path outside the visible workspace")


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
