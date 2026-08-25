"""Deterministic bounded observations for repository agents.

The repository action wire protocol deliberately stays small and provider-neutral.  This
module owns the model-visible projection behind that protocol so that the ordinary
environment, external-agent bridge, and training brokers use the same limits and omission
markers.  The policy is opt-in at the harness boundary; callers that do not select it keep
the historical file-tool behavior.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from verigym.schemas.tool import ToolResult

REPOSITORY_OBSERVATION_POLICY_ID = "repository_observation_v1"
REPOSITORY_OBSERVATION_POLICY_VERSION = "1.0.0"

LIST_MAX_DEPTH = 2
LIST_MAX_ENTRIES = 200
LIST_MAX_BYTES = 8 * 1024
READ_MAX_BYTES = 16 * 1024
READ_CONCISE_LINE_THRESHOLD = 200
SEARCH_MAX_BYTES = 8 * 1024
PUBLIC_TEST_MAX_BYTES = 16 * 1024
DIFF_MAX_BYTES = 32 * 1024
RAW_AUDIT_MAX_BYTES = 32 * 1024 * 1024

OMISSION_MARKER = "[verigym omission: {description}]"
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "build",
        "dist",
        "target",
        "__pycache__",
        ".cache",
    }
)

_RTL_SUFFIXES = frozenset({".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl"})
_RTL_STRUCTURE = re.compile(
    r"\b(?:module|endmodule|interface|endinterface|package|endpackage|program|endprogram|"
    r"parameter|localparam|input|output|inout|wire|logic|reg|bit|integer|genvar|typedef|"
    r"enum|struct|union|always(?:_ff|_comb|_latch)?|assign|generate|endgenerate|assert|"
    r"property|function|endfunction|task|endtask|import|export)\b"
)
_GENERIC_STRUCTURE = re.compile(
    r"^(?:\s*(?:class|def|async\s+def|function|module|interface|package|type|enum|struct|"
    r"export|import|from|#\s*(?:include|define)|[A-Za-z_][\w.]*\s*=))"
)


@dataclass(frozen=True)
class RepositoryObservationPolicy:
    """Frozen limits used by one repository-agent harness."""

    policy_id: str = REPOSITORY_OBSERVATION_POLICY_ID
    version: str = REPOSITORY_OBSERVATION_POLICY_VERSION
    list_max_depth: int = LIST_MAX_DEPTH
    list_max_entries: int = LIST_MAX_ENTRIES
    list_max_bytes: int = LIST_MAX_BYTES
    read_max_bytes: int = READ_MAX_BYTES
    read_concise_line_threshold: int = READ_CONCISE_LINE_THRESHOLD
    search_max_bytes: int = SEARCH_MAX_BYTES
    public_test_max_bytes: int = PUBLIC_TEST_MAX_BYTES
    diff_max_bytes: int = DIFF_MAX_BYTES

    def __post_init__(self) -> None:
        if self.policy_id != REPOSITORY_OBSERVATION_POLICY_ID:
            raise ValueError("unknown repository observation policy")
        if self.version != REPOSITORY_OBSERVATION_POLICY_VERSION:
            raise ValueError("repository observation policy version is not supported")
        positive = (
            ("list_max_depth", self.list_max_depth),
            ("list_max_entries", self.list_max_entries),
            ("list_max_bytes", self.list_max_bytes),
            ("read_max_bytes", self.read_max_bytes),
            ("read_concise_line_threshold", self.read_concise_line_threshold),
            ("search_max_bytes", self.search_max_bytes),
            ("public_test_max_bytes", self.public_test_max_bytes),
            ("diff_max_bytes", self.diff_max_bytes),
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for _name, value in positive
        ):
            raise ValueError("repository observation policy limits must be positive integers")
        for field_name, expected_value in (
            ("list_max_depth", LIST_MAX_DEPTH),
            ("list_max_entries", LIST_MAX_ENTRIES),
            ("list_max_bytes", LIST_MAX_BYTES),
            ("read_max_bytes", READ_MAX_BYTES),
            ("read_concise_line_threshold", READ_CONCISE_LINE_THRESHOLD),
            ("search_max_bytes", SEARCH_MAX_BYTES),
            ("public_test_max_bytes", PUBLIC_TEST_MAX_BYTES),
            ("diff_max_bytes", DIFF_MAX_BYTES),
        ):
            if getattr(self, field_name) != expected_value:
                raise ValueError("repository observation policy limits are fixed")

    def identity(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "list_max_depth": self.list_max_depth,
            "list_max_entries": self.list_max_entries,
            "list_max_bytes": self.list_max_bytes,
            "read_max_bytes": self.read_max_bytes,
            "read_concise_line_threshold": self.read_concise_line_threshold,
            "search_max_bytes": self.search_max_bytes,
            "public_test_max_bytes": self.public_test_max_bytes,
            "diff_max_bytes": self.diff_max_bytes,
            "ignored_directory_names": sorted(IGNORED_DIRECTORY_NAMES),
        }


BOUNDED_REPOSITORY_OBSERVATION_POLICY = RepositoryObservationPolicy()


def resolve_repository_observation_policy(
    value: object = None,
) -> RepositoryObservationPolicy | None:
    """Resolve an optional policy identifier without accepting ad-hoc limits."""

    if value is None:
        return None
    if isinstance(value, str) and value in {"legacy", "none"}:
        return None
    if value == REPOSITORY_OBSERVATION_POLICY_ID:
        return BOUNDED_REPOSITORY_OBSERVATION_POLICY
    raise ValueError(f"unsupported repository observation policy: {value!r}")


def policy_identity(value: RepositoryObservationPolicy | None) -> str | None:
    return value.policy_id if value is not None else None


def observation_limit(policy: RepositoryObservationPolicy | None, tool: str, fallback: int) -> int:
    fixed_limits = {
        "file.search": SEARCH_MAX_BYTES,
        "repository.public_test": PUBLIC_TEST_MAX_BYTES,
        "file.diff": DIFF_MAX_BYTES,
    }
    if tool in fixed_limits:
        return fixed_limits[tool]
    if policy is None:
        return fallback
    return {
        "file.list": policy.list_max_bytes,
        "file.read": policy.read_max_bytes,
        "file.search": policy.search_max_bytes,
        "repository.public_test": policy.public_test_max_bytes,
        "file.diff": policy.diff_max_bytes,
    }.get(tool, fallback)


def bounded_text_with_marker(
    text: str,
    max_bytes: int,
    *,
    description: str = "content",
) -> tuple[str, bool]:
    """Bound UTF-8 text while making every omission explicit.

    A head/tail projection is used for diagnostics and diffs.  The marker is itself included
    in the budget, and the result is always valid UTF-8 and no larger than ``max_bytes``.
    """

    if max_bytes <= 0:
        raise ValueError("text bound must be positive")
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    marker = OMISSION_MARKER.format(description=description)
    marker_bytes = len(marker.encode("utf-8"))
    if marker_bytes >= max_bytes:
        return marker.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore"), True
    remaining = max_bytes - marker_bytes
    head_budget = (remaining + 1) // 2
    tail_budget = remaining - head_budget
    head = encoded[:head_budget].decode("utf-8", errors="ignore")
    tail = encoded[-tail_budget:].decode("utf-8", errors="ignore") if tail_budget else ""
    result = head + marker + tail
    # Decoding at byte boundaries can leave a few bytes unused; never exceed the requested cap.
    while len(result.encode("utf-8")) > max_bytes:
        if len(tail) >= len(head) and tail:
            tail = tail[:-1]
        elif head:
            head = head[:-1]
        else:  # pragma: no cover - marker branch above handles the minimum case
            break
        result = head + marker + tail
    return result, True


def list_workspace_entries(
    root: Any,
    *,
    relative_path: str,
    recursive: bool,
    requested_max_depth: int | None = None,
    requested_max_entries: int | None = None,
    policy: RepositoryObservationPolicy | None,
    is_excluded: Callable[[str], bool],
    workspace_root: Any,
) -> tuple[str, dict[str, Any]]:
    """List deterministic entries with policy-owned depth and count caps."""

    if policy is None:
        iterator = root.rglob("*") if recursive else root.glob("*")
        legacy_entries: list[str] = []
        for path in sorted(iterator):
            workspace_relative = path.relative_to(workspace_root).as_posix()
            if is_excluded(workspace_relative):
                continue
            if path.is_symlink():
                raise ValueError("symlinks are not permitted inside the workspace")
            legacy_entries.append(workspace_relative + ("/" if path.is_dir() else ""))
        return "\n".join(legacy_entries), {
            "entry_count": len(legacy_entries),
            "omitted_entries": 0,
        }

    max_depth = policy.list_max_depth
    if requested_max_depth is not None:
        max_depth = min(max_depth, requested_max_depth)
    if not recursive:
        max_depth = min(max_depth, 1)
    max_entries = policy.list_max_entries
    if requested_max_entries is not None:
        max_entries = min(max_entries, requested_max_entries)

    entries: list[str] = []
    # Walk the bounded depth explicitly so ignored directory names are never traversed.
    pending: list[tuple[Any, int]] = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        children = sorted(directory.iterdir(), key=lambda item: item.name)
        for path in children:
            workspace_relative = path.relative_to(workspace_root).as_posix()
            if is_excluded(workspace_relative):
                continue
            if path.is_symlink():
                raise ValueError("symlinks are not permitted inside the workspace")
            if path.is_dir() and path.name in IGNORED_DIRECTORY_NAMES:
                continue
            child_depth = depth + 1
            if child_depth > max_depth:
                continue
            rendered = workspace_relative + ("/" if path.is_dir() else "")
            entries.append(rendered)
            if path.is_dir() and child_depth < max_depth:
                pending.append((path, child_depth))
    entries.sort()
    omitted_entries = max(0, len(entries) - max_entries)
    selected = entries[:max_entries]
    if omitted_entries:
        selected.append(
            OMISSION_MARKER.format(
                description=f"{omitted_entries} entries beyond max_entries={max_entries}"
            )
        )
    output, byte_truncated = bounded_text_with_marker(
        "\n".join(selected), policy.list_max_bytes, description="list output"
    )
    return output, {
        "entry_count": len(entries),
        "included_entries": min(len(entries), max_entries),
        "omitted_entries": omitted_entries,
        "max_depth": max_depth,
        "max_entries": max_entries,
        "ignored_directory_names": sorted(IGNORED_DIRECTORY_NAMES),
        "byte_truncated": byte_truncated,
    }


def bounded_read_view(
    text: str,
    path: str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
    concise: bool | None = None,
    policy: RepositoryObservationPolicy | None,
) -> tuple[str, dict[str, Any]]:
    """Render a numbered full, ranged, or structural file view."""

    if policy is None:
        return text, {"view_mode": "legacy", "line_count": len(text.splitlines())}
    lines = text.splitlines()
    line_count = len(lines)
    if start_line is not None and start_line > line_count:
        raise ValueError("start_line is outside the file")
    if end_line is not None and end_line > line_count:
        raise ValueError("end_line is outside the file")
    selected_start = start_line or 1
    selected_end = end_line or line_count
    if selected_start > selected_end:
        raise ValueError("start_line must not be after end_line")
    ranged = start_line is not None or end_line is not None
    selected_lines = lines[selected_start - 1 : selected_end]
    selected_pairs = [
        (selected_start + offset, value) for offset, value in enumerate(selected_lines)
    ]
    byte_size = len(text.encode("utf-8"))
    use_concise = bool(concise) or (
        not ranged
        and (line_count > policy.read_concise_line_threshold or byte_size > policy.read_max_bytes)
    )
    omitted_ranges: list[tuple[int, int]] = []
    if use_concise:
        source_path = PurePosixPath(path)
        structural = _structural_line_numbers(lines, source_path)
        if ranged:
            structural = {
                number for number in structural if selected_start <= number <= selected_end
            }
        selected_pairs = [(number, lines[number - 1]) for number in sorted(structural)]
        if not selected_pairs:
            selected_pairs = _head_tail_pairs(selected_start, selected_lines)
        mode = "ranged_concise" if ranged else "concise"
    else:
        mode = "ranged" if ranged else "full"

    rendered = _render_numbered_pairs(selected_pairs, omitted_ranges)
    if len(rendered.encode("utf-8")) > policy.read_max_bytes:
        rendered, line_omissions = _bound_numbered_pairs(
            selected_pairs,
            policy.read_max_bytes,
            description="read output",
        )
        omitted_ranges.extend(line_omissions)
    return rendered, {
        "view_mode": mode,
        "line_count": line_count,
        "line_range": [selected_start, selected_end],
        "concise": use_concise,
        "structural_line_count": len(selected_pairs) if use_concise else None,
        "omitted_line_ranges": [list(item) for item in omitted_ranges],
    }


def _structural_line_numbers(lines: list[str], path: PurePosixPath) -> set[int]:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return _python_structure(lines)
    if suffix in _RTL_SUFFIXES:
        selected = {
            index for index, line in enumerate(lines, start=1) if _RTL_STRUCTURE.search(line)
        }
        # Keep a small amount of surrounding context around declarations and blocks.
        return _with_neighbors(selected, len(lines), radius=1)
    selected = {
        index for index, line in enumerate(lines, start=1) if _GENERIC_STRUCTURE.search(line)
    }
    return _with_neighbors(selected, len(lines), radius=0)


def _python_structure(lines: list[str]) -> set[int]:
    text = "\n".join(lines)
    selected: set[int] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {
            index for index, line in enumerate(lines, start=1) if _GENERIC_STRUCTURE.search(line)
        }
    for node in ast.walk(tree):
        if isinstance(
            node,
            (
                ast.ClassDef,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.Import,
                ast.ImportFrom,
                ast.Assign,
                ast.AnnAssign,
                ast.AsyncFor,
                ast.For,
                ast.If,
            ),
        ):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", start)
            if isinstance(start, int) and isinstance(end, int):
                selected.update(range(start, min(end, start + 2) + 1))
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    for decorator in node.decorator_list:
                        if isinstance(decorator.lineno, int):
                            selected.add(decorator.lineno)
    return {line for line in selected if 1 <= line <= len(lines)}


def _with_neighbors(values: set[int], length: int, *, radius: int) -> set[int]:
    result = set(values)
    for value in values:
        result.update(range(max(1, value - radius), min(length, value + radius) + 1))
    return result


def _head_tail_pairs(start: int, lines: list[str]) -> list[tuple[int, str]]:
    if len(lines) <= 40:
        return [(start + index, value) for index, value in enumerate(lines)]
    head = [(start + index, value) for index, value in enumerate(lines[:20])]
    tail_start = start + len(lines) - 20
    return [*head, *[(tail_start + index, value) for index, value in enumerate(lines[-20:])]]


def _render_numbered_pairs(
    pairs: Iterable[tuple[int, str]], omitted_ranges: list[tuple[int, int]] | None = None
) -> str:
    del omitted_ranges  # The caller computes omission metadata from the selected pairs.
    ordered = sorted(set(pairs), key=lambda item: item[0])
    rendered: list[str] = []
    previous: int | None = None
    for number, value in ordered:
        if previous is not None and number > previous + 1:
            rendered.append(
                OMISSION_MARKER.format(description=f"lines {previous + 1}-{number - 1}")
            )
        rendered.append(f"{number}: {value}")
        previous = number
    return "\n".join(rendered)


def _bound_numbered_pairs(
    pairs: list[tuple[int, str]], max_bytes: int, *, description: str
) -> tuple[str, list[tuple[int, int]]]:
    if not pairs:
        return "", []
    marker = OMISSION_MARKER.format(description=description)
    selected: list[tuple[int, str]] = []
    used = 0
    for pair in pairs:
        rendered = f"{pair[0]}: {pair[1]}"
        extra = len(rendered.encode("utf-8")) + (1 if selected else 0)
        if used + extra + len(marker.encode("utf-8")) + 1 > max_bytes:
            break
        selected.append(pair)
        used += extra
    omitted = pairs[len(selected) :]
    if not omitted:
        return _render_numbered_pairs(selected), []
    # Keep the tail when the selected structure is large enough to contain it.
    tail: list[tuple[int, str]] = []
    tail_used = 0
    for pair in reversed(omitted):
        rendered = f"{pair[0]}: {pair[1]}"
        extra = len(rendered.encode("utf-8")) + (1 if tail else 0)
        if used + tail_used + extra + len(marker.encode("utf-8")) + 1 > max_bytes:
            break
        tail.append(pair)
        tail_used += extra
    tail.reverse()
    combined = [*selected, *tail]
    omission_range = (omitted[0][0], omitted[-1][0])
    rendered = _render_numbered_pairs(combined)
    # Insert an explicit marker at the gap, even if the generic renderer would do so.
    lines = rendered.splitlines()
    insertion = (
        next(
            (index for index, line in enumerate(lines) if line.startswith(f"{tail[0][0]}: ")),
            len(lines),
        )
        if tail
        else len(lines)
    )
    lines.insert(insertion, marker)
    rendered = "\n".join(lines)
    rendered, _ = bounded_text_with_marker(rendered, max_bytes, description=description)
    return rendered, [omission_range]


def compact_tool_result(
    result: ToolResult,
    *,
    policy: RepositoryObservationPolicy | None,
) -> ToolResult:
    """Apply the shared per-tool output bound to a raw result."""

    if policy is None and result.tool not in {
        "file.search",
        "repository.public_test",
        "file.diff",
    }:
        return result
    limit = observation_limit(policy, result.tool, 64 * 1024)
    stdout, stdout_truncated = bounded_text_with_marker(
        result.stdout, limit, description=f"{result.tool} stdout"
    )
    stderr, stderr_truncated = bounded_text_with_marker(
        result.stderr,
        min(limit, 2 * 1024),
        description=f"{result.tool} stderr",
    )
    metadata = dict(result.metadata)
    metadata.update(
        {
            "observation_omission_marker": OMISSION_MARKER.split("{", 1)[0].rstrip(),
            "observation_stdout_bytes": len(stdout.encode("utf-8")),
            "observation_stderr_bytes": len(stderr.encode("utf-8")),
        }
    )
    if policy is not None:
        metadata.update(
            {
                "observation_policy_id": policy.policy_id,
                "observation_policy_version": policy.version,
            }
        )
    return result.model_copy(
        update={
            "stdout": stdout,
            "stderr": stderr,
            "output_truncated": bool(
                result.output_truncated or stdout_truncated or stderr_truncated
            ),
            "metadata": metadata,
        }
    )


def compact_observation_value(
    value: object,
    *,
    policy: RepositoryObservationPolicy | None,
    max_bytes: int,
) -> tuple[object, bool]:
    """Bound initial/rolling observation JSON without silently dropping content."""

    if policy is None:
        return value, False
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    bounded, truncated = bounded_text_with_marker(
        serialized, max_bytes, description="observation JSON"
    )
    if not truncated:
        return value, False
    return {
        "observation_policy_id": policy.policy_id,
        "observation_omitted": True,
        "observation_json": bounded,
    }, True


RawObservationCallback = Callable[[dict[str, Any]], None]

_SECRET_SCAN = re.compile(
    r"(?:"
    r"\b(?:authorization|api[_ -]?key|access[_ -]?token|password)\s*[:=]\s*['\"]?"
    r"[A-Za-z0-9._~+/=-]{8,}"
    r"|\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"
    r"|\b(?:sk|ds)-[A-Za-z0-9_-]{12,}"
    r")",
    re.IGNORECASE,
)


class RawObservationAuditWriter:
    """Append restricted raw public observations with a bounded, hashed artifact."""

    def __init__(self, path: Path, *, max_bytes: int = RAW_AUDIT_MAX_BYTES) -> None:
        if max_bytes <= 0:
            raise ValueError("raw observation audit bound must be positive")
        if path.exists():
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("raw observation audit path is not a private regular file")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise ValueError("raw observation audit directory cannot be a symlink")
        os.chmod(path.parent, 0o700)
        self.path = path
        self.max_bytes = max_bytes
        self._bytes = path.stat().st_size if path.exists() else 0
        if self._bytes > max_bytes:
            raise ValueError("existing raw observation audit exceeds its byte bound")
        self._count = 0
        self._digest = hashlib.sha256()
        if path.exists():
            self._digest.update(path.read_bytes())

    @property
    def count(self) -> int:
        return self._count

    @property
    def bytes_written(self) -> int:
        return self._bytes

    def __call__(self, record: dict[str, Any]) -> None:
        encoded_record = json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        if _SECRET_SCAN.search(encoded_record.decode("utf-8", errors="ignore")):
            raise ValueError("raw repository observation failed the secret scan")
        encoded = encoded_record + b"\n"
        if self._bytes + len(encoded) > self.max_bytes:
            raise ValueError("raw repository observation audit exceeded its byte bound")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags | nofollow, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("raw observation audit path is not a private regular file")
            written = 0
            while written < len(encoded):
                written += os.write(descriptor, encoded[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(self.path, 0o600)
        self._bytes += len(encoded)
        self._count += 1
        self._digest.update(encoded)

    def finalize(self) -> dict[str, Any]:
        digest = self._digest.hexdigest()
        manifest = {
            "schema_version": "1.0",
            "format_id": "verigym_raw_repository_observation_manifest_v1",
            "path": self.path.name,
            "record_count": self._count,
            "bytes": self._bytes,
            "sha256": digest,
            "max_bytes": self.max_bytes,
            "secret_scan": "passed",
            "policy": REPOSITORY_OBSERVATION_POLICY_ID,
        }
        target = self.path.with_name(f"{self.path.stem}-manifest.json")
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_text(
            json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        return manifest


def audit_record(
    result: ToolResult,
    *,
    request: Mapping[str, Any] | None = None,
    policy: RepositoryObservationPolicy | None,
) -> dict[str, Any]:
    """Build a raw audit payload before compacting the public result."""

    return {
        "schema_version": "1.0",
        "format_id": "verigym_raw_repository_observation_v1",
        "observation_policy_id": policy.policy_id if policy is not None else None,
        "tool": result.tool,
        "request": dict(request or {}),
        "result": result.model_dump(mode="json"),
    }


__all__ = [
    "BOUNDED_REPOSITORY_OBSERVATION_POLICY",
    "DIFF_MAX_BYTES",
    "IGNORED_DIRECTORY_NAMES",
    "LIST_MAX_BYTES",
    "LIST_MAX_DEPTH",
    "LIST_MAX_ENTRIES",
    "OMISSION_MARKER",
    "PUBLIC_TEST_MAX_BYTES",
    "REPOSITORY_OBSERVATION_POLICY_ID",
    "REPOSITORY_OBSERVATION_POLICY_VERSION",
    "RAW_AUDIT_MAX_BYTES",
    "READ_CONCISE_LINE_THRESHOLD",
    "READ_MAX_BYTES",
    "SEARCH_MAX_BYTES",
    "RawObservationCallback",
    "RawObservationAuditWriter",
    "RepositoryObservationPolicy",
    "audit_record",
    "bounded_read_view",
    "bounded_text_with_marker",
    "compact_observation_value",
    "compact_tool_result",
    "list_workspace_entries",
    "observation_limit",
    "policy_identity",
    "resolve_repository_observation_policy",
]
