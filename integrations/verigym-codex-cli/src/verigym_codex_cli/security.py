"""Workspace and event-policy checks for Codex CLI episodes."""

from __future__ import annotations

import os
import shlex
import stat
from pathlib import Path, PurePosixPath

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


class CodexPolicyError(RuntimeError):
    """The external CLI crossed a declared workspace or command boundary."""


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
    expect_command = True
    expect_redirection_target = False
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            expect_command = True
            expect_redirection_target = False
            continue
        if token in _REDIRECTION_OPERATORS:
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
    unsupported = [name for name in commands if name not in _VISIBLE_COMMANDS]
    if unsupported:
        raise CodexPolicyError(
            f"external command is outside the visible command allowlist: {unsupported[0]}"
        )


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
    "assert_empty_directory",
    "assert_instruction_isolation",
    "assert_safe_workspace_tree",
    "validate_external_events",
]
