"""Strict, read-only inspection of the official VerilogEval code-completion layout."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DATASET_DIRECTORY = "dataset_code-complete-iccad2023"
VARIANT = "v2-code-complete-iccad2023"
NATIVE_LAYOUT = "dataset-code-complete-iccad2023-quadruplets-v2"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TASKS = 2_048

_SUFFIXES = {
    "_prompt.txt": "prompt",
    "_ifc.txt": "interface",
    "_ref.sv": "reference",
    "_test.sv": "testbench",
}
_REQUIRED_ROLES = frozenset(_SUFFIXES.values())
_STEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_MODULE = re.compile(r"\bmodule\s+(?:(?:automatic|static)\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_$]*)\b")


@dataclass(frozen=True)
class Layout:
    source_root: Path
    repository_root: Path
    dataset_root: Path


@dataclass(frozen=True)
class Issue:
    level: Literal["error", "warning"]
    code: str
    message: str
    relative_path: str | None = None


@dataclass(frozen=True)
class Problem:
    native_id: str
    prompt: str
    interface: str
    reference: str
    testbench: str
    content_hash: str
    testbench_top: str


@dataclass(frozen=True)
class Catalog:
    layout: Layout
    problems: tuple[Problem, ...]
    issues: tuple[Issue, ...]
    dataset_content_hash: str


def resolve_layout(raw_root: Path, variant: str | None) -> Layout:
    if variant not in {None, VARIANT}:
        raise ValueError(f"suite supports only variant {VARIANT!r}")
    expanded = raw_root.expanduser()
    if expanded.is_symlink():
        raise ValueError("source root must not be a symlink")
    try:
        root = expanded.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError(f"source path is unavailable: {expanded}") from exc
    if not root.is_dir():
        raise ValueError("source path must be a directory")

    if root.name == DATASET_DIRECTORY:
        dataset_root = root
        repository_root = root.parent
    else:
        repository_root = root
        dataset_root = root / DATASET_DIRECTORY
    try:
        dataset_root = dataset_root.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError(f"source is missing required directory {DATASET_DIRECTORY}") from exc
    if not dataset_root.is_dir() or dataset_root.is_symlink():
        raise ValueError(f"{DATASET_DIRECTORY} must be a real directory")
    if root.name != DATASET_DIRECTORY and not dataset_root.is_relative_to(root):
        raise ValueError("dataset directory escapes the approved source root")
    return Layout(source_root=root, repository_root=repository_root, dataset_root=dataset_root)


def inspect_layout(layout: Layout) -> Catalog:
    issues: list[Issue] = []
    grouped: dict[str, dict[str, Path]] = {}
    relevant_paths: list[Path] = []

    try:
        entries = sorted(layout.dataset_root.rglob("*"), key=lambda path: path.as_posix())
    except OSError as exc:
        entries = []
        issues.append(Issue("error", "source_unreadable", f"cannot enumerate dataset: {exc}"))
    for path in entries:
        relative = _relative(path, layout.dataset_root, issues)
        if relative is None:
            continue
        if path.is_symlink():
            issues.append(Issue("error", "symlink", "symlinks are not supported", relative))
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            issues.append(Issue("error", "special_file", "special files are unsupported", relative))
            continue
        split = _split_role(path.name)
        if path.parent != layout.dataset_root:
            if split is not None:
                issues.append(
                    Issue(
                        "error",
                        "nested_task_file",
                        "task files must be directly inside the dataset directory",
                        relative,
                    )
                )
            continue
        if split is None:
            continue
        stem, role = split
        relevant_paths.append(path)
        if not _STEM.fullmatch(stem):
            issues.append(Issue("error", "invalid_stem", f"invalid task stem {stem!r}", relative))
            continue
        roles = grouped.setdefault(stem, {})
        if role in roles:
            issues.append(
                Issue("error", "duplicate_role", f"duplicate {role} for {stem!r}", relative)
            )
        roles[role] = path

    if len(grouped) > MAX_TASKS:
        issues.append(Issue("error", "too_many_tasks", f"dataset exceeds {MAX_TASKS} tasks"))

    problems: list[Problem] = []
    for stem in sorted(grouped, key=natural_sort_key):
        roles = grouped[stem]
        missing = sorted(_REQUIRED_ROLES - set(roles))
        if missing:
            issues.append(
                Issue("error", "incomplete_task", f"{stem!r} is missing: {', '.join(missing)}")
            )
            continue
        contents = _read_roles(layout.dataset_root, roles, issues)
        if set(contents) != _REQUIRED_ROLES:
            continue
        testbench_top = _validate_problem(stem, contents, issues)
        problems.append(
            Problem(
                native_id=stem,
                prompt=contents["prompt"],
                interface=contents["interface"],
                reference=contents["reference"],
                testbench=contents["testbench"],
                content_hash=_paths_hash(layout.dataset_root, list(roles.values())),
                testbench_top=testbench_top,
            )
        )

    if not grouped:
        issues.append(Issue("error", "no_tasks", "no code-completion tasks were discovered"))
    return Catalog(
        layout=layout,
        problems=tuple(problems),
        issues=tuple(issues),
        dataset_content_hash=_paths_hash(layout.dataset_root, relevant_paths),
    )


def declared_modules(source: str) -> list[str]:
    masked = _mask_comments_and_strings(source)
    return [match.group("name") for match in _MODULE.finditer(masked)]


def transform_reference(reference: str) -> str:
    masked = _mask_comments_and_strings(reference)
    matches = [match for match in _MODULE.finditer(masked) if match.group("name") == "RefModule"]
    if len(matches) != 1:
        raise ValueError("reference must declare exactly one RefModule")
    start, end = matches[0].span("name")
    transformed = reference[:start] + "TopModule" + reference[end:]
    if declared_modules(transformed).count("TopModule") != 1:
        raise ValueError("reference transformation produced an ambiguous TopModule")
    return transformed


def natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    pieces = re.split(r"(\d+)", value.casefold())
    return tuple((0, int(piece)) if piece.isdigit() else (1, piece) for piece in pieces if piece)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _split_role(filename: str) -> tuple[str, str] | None:
    lowered = filename.casefold()
    matches = [(suffix, role) for suffix, role in _SUFFIXES.items() if lowered.endswith(suffix)]
    if len(matches) != 1:
        return None
    suffix, role = matches[0]
    return filename[: len(filename) - len(suffix)], role


def _relative(path: Path, root: Path, issues: list[Issue]) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        issues.append(Issue("error", "path_escape", "dataset entry escapes source root"))
        return None


def _read_roles(root: Path, roles: dict[str, Path], issues: list[Issue]) -> dict[str, str]:
    contents: dict[str, str] = {}
    for role in sorted(_REQUIRED_ROLES):
        path = roles[role]
        relative = path.relative_to(root).as_posix()
        try:
            file_stat = path.stat()
            if not file_stat.st_mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH):
                raise PermissionError("file has no readable permission bits")
            if file_stat.st_size > MAX_FILE_BYTES:
                issues.append(
                    Issue(
                        "error",
                        "oversized_file",
                        f"task file exceeds {MAX_FILE_BYTES} bytes",
                        relative,
                    )
                )
                continue
            if not os.access(path, os.R_OK):
                raise PermissionError("file is not readable")
            contents[role] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append(Issue("error", "non_utf8", "task file is not UTF-8", relative))
        except OSError as exc:
            issues.append(
                Issue(
                    "error",
                    "unreadable_file",
                    f"cannot read task file: {exc}",
                    relative,
                )
            )
    return contents


def _validate_problem(stem: str, contents: dict[str, str], issues: list[Issue]) -> str:
    prompt = contents["prompt"]
    interface = contents["interface"]
    reference = contents["reference"]
    testbench = contents["testbench"]
    if not prompt.strip():
        issues.append(Issue("error", "empty_prompt", f"{stem!r} has an empty prompt"))
    if declared_modules(interface).count("TopModule") != 1:
        issues.append(
            Issue("error", "invalid_interface", f"{stem!r} must declare one interface TopModule")
        )
    if declared_modules(reference).count("RefModule") != 1:
        issues.append(Issue("error", "invalid_reference", f"{stem!r} must declare one RefModule"))
    modules = declared_modules(testbench)
    top = "tb" if "tb" in modules else (modules[0] if len(modules) == 1 else "tb")
    if "tb" not in modules:
        issues.append(Issue("error", "missing_testbench_top", f"{stem!r} has no tb module"))
    if not re.search(r"\bRefModule\b", testbench) or not re.search(r"\bTopModule\b", testbench):
        issues.append(
            Issue("error", "missing_testbench_instances", f"{stem!r} must compare both modules")
        )
    if "Mismatches:" not in testbench or "samples" not in testbench:
        issues.append(Issue("error", "missing_native_summary", f"{stem!r} has no mismatch summary"))
    return top


def _paths_hash(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _mask_comments_and_strings(source: str) -> str:
    output = list(source)
    index = 0
    state = "code"
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if current == "/" and following == "/":
                output[index] = output[index + 1] = " "
                index += 2
                state = "line_comment"
                continue
            if current == "/" and following == "*":
                output[index] = output[index + 1] = " "
                index += 2
                state = "block_comment"
                continue
            if current == '"':
                output[index] = " "
                index += 1
                state = "string"
                continue
        elif state == "line_comment":
            if current == "\n":
                state = "code"
            else:
                output[index] = " "
            index += 1
            continue
        elif state == "block_comment":
            if current == "*" and following == "/":
                output[index] = output[index + 1] = " "
                index += 2
                state = "code"
                continue
            if current != "\n":
                output[index] = " "
            index += 1
            continue
        elif state == "string":
            if current == "\\" and following:
                output[index] = " "
                if following != "\n":
                    output[index + 1] = " "
                index += 2
                continue
            if current == '"':
                output[index] = " "
                state = "code"
            elif current != "\n":
                output[index] = " "
            index += 1
            continue
        index += 1
    return "".join(output)
