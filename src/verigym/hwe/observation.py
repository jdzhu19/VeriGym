"""Exact-token HWE observation compaction with explicit, auditable omissions."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any, Literal, Protocol

from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_ID,
    HWE_COLLECTION_PROFILE_V2_ID,
    HWE_TOKENIZER_ID,
    resolve_hwe_collection_profile,
)

HWE_TOKENIZER_HASH = hashlib.sha256(b"tiktoken==0.7.0\x00o200k_base").hexdigest()

ObservationKind = Literal["list", "search", "read", "shell", "diff"]

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_PROGRESS = re.compile(r"^(?:\s*\d{1,3}%|\s*\[[#=>. -]{4,}\]|\s*Downloading\b)", re.I)
_DIAGNOSTIC = re.compile(
    r"(?:\berror\b|\bfatal\b|\bassert(?:ion)?\b|\btraceback\b|\bexception\b|"
    r"\bhierarchy\b|\belaborat|\bseed\b|\bexpected\b|\bactual\b|\bfailed\b)",
    re.I,
)
_V23_READ_MAX_MODEL_LINES = 400
_V23_READ_MAX_BYTES = 128 * 1024
_V23_SHELL_HEAD_BYTES = 64 * 1024
_V23_SHELL_TAIL_BYTES = 64 * 1024
_V23_SHELL_CONTEXT_TOKENS = 65_536
_SCALA_STRUCTURE = re.compile(
    r"^\s*(?:(?:sealed\s+|abstract\s+|final\s+|case\s+)*(?:class|trait|object)\b|"
    r"(?:private\s+|protected\s+|override\s+|implicit\s+|lazy\s+)*(?:def|val|var|type)\b|"
    r"import\s+|package\s+|when\s*\(|elsewhen\s*\(|otherwise\b|switch\s*\(|is\s*\()"
)
_SV_STRUCTURE = re.compile(
    r"\b(?:module|endmodule|interface|endinterface|package|endpackage|parameter|localparam|"
    r"input|output|inout|typedef|enum|struct|union|always_ff|always_comb|always_latch|"
    r"always|assign|generate|endgenerate|assert|property|function|endfunction|task|endtask)\b"
)


class TokenCounter(Protocol):
    tokenizer_id: str
    tokenizer_hash: str

    def count(self, text: str) -> int: ...


class TiktokenO200kCounter:
    """The only production tokenizer accepted by HWE SFT collection."""

    tokenizer_id = HWE_TOKENIZER_ID

    def __init__(self) -> None:
        try:
            version = importlib.metadata.version("tiktoken")
            tiktoken = importlib.import_module("tiktoken")
        except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
            raise RuntimeError("HWE SFT collection requires tiktoken==0.7.0") from exc
        if version != "0.7.0":
            raise RuntimeError(f"HWE SFT collection requires tiktoken==0.7.0, found {version}")
        self._encoding = tiktoken.get_encoding("o200k_base")
        self.tokenizer_hash = HWE_TOKENIZER_HASH

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text, disallowed_special=()))


@dataclass(frozen=True)
class HweObservationResult:
    text: str
    kind: ObservationKind
    rule_id: str
    raw_bytes: int
    raw_sha256: str
    compact_bytes: int
    compact_tokens: int
    omitted: bool
    omitted_units: int
    metadata: dict[str, Any]


class HweObservationCompactor:
    """Create deterministic model-visible views while retaining content identities."""

    _LIMITS: dict[ObservationKind, tuple[int, int]] = {
        "list": (2_000, 2_000),
        "search": (3_000, 3_000),
        "read": (4_000, 8_000),
        "shell": (4_000, 8_000),
        "diff": (8_000, 16_000),
    }

    def __init__(
        self,
        counter: TokenCounter | None = None,
        *,
        profile_id: str = HWE_COLLECTION_PROFILE_ID,
        v23_bounded_projection: bool = False,
    ) -> None:
        self.counter = counter or TiktokenO200kCounter()
        if self.counter.tokenizer_id != HWE_TOKENIZER_ID:
            raise ValueError("HWE compaction requires the frozen o200k_base tokenizer")
        self.profile = resolve_hwe_collection_profile(profile_id)
        if v23_bounded_projection and profile_id != HWE_COLLECTION_PROFILE_V2_ID:
            raise ValueError("OpenHands v23 observation projection requires hwe_standard_v2")
        self.v23_bounded_projection = v23_bounded_projection

    def compact(
        self,
        kind: ObservationKind,
        text: str,
        *,
        path: str | None = None,
        stderr: str = "",
        command: str | None = None,
        cwd: str | None = None,
        exit_code: int | None = None,
        duration_ms: int | None = None,
    ) -> HweObservationResult:
        if kind not in self._LIMITS:
            raise ValueError(f"unknown HWE observation kind: {kind}")
        raw_text = (
            f"{text}\n[stderr]\n{stderr}"
            if stderr
            and (kind == "shell" or self.profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID)
            else text
        )
        raw = raw_text.encode("utf-8")
        raw_hash = hashlib.sha256(raw).hexdigest()
        preferred, hard = self._LIMITS[kind]
        result_header = (
            _result_header(
                command=command,
                cwd=cwd,
                exit_code=exit_code,
                duration_ms=duration_ms,
                stdout_bytes=len(text.encode("utf-8")),
                stderr_bytes=len(stderr.encode("utf-8")),
            )
            if self.profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
            else ""
        )
        cleaned = clean_terminal_noise(text)
        cleaned_stderr = clean_terminal_noise(stderr)
        v23_projection_metadata: dict[str, Any] = {}
        v23_projection_omitted = False
        if self.v23_bounded_projection and kind == "read":
            cleaned, v23_projection_metadata = _bounded_read_projection(
                cleaned,
                source_text=text,
                max_bytes=_V23_READ_MAX_BYTES - len(result_header.encode("utf-8")) - 1,
            )
            v23_projection_omitted = bool(
                v23_projection_metadata["omitted_lines"]
                or v23_projection_metadata["omitted_bytes"]
                or v23_projection_metadata["terminal_cleanup_changed"]
            )
        elif self.v23_bounded_projection and kind == "shell":
            cleaned, stdout_projection = _bounded_stream_projection(
                cleaned,
                label="stdout",
                head_bytes=_V23_SHELL_HEAD_BYTES,
                tail_bytes=_V23_SHELL_TAIL_BYTES,
                source_text=text,
            )
            cleaned_stderr, stderr_projection = _bounded_stream_projection(
                cleaned_stderr,
                label="stderr",
                head_bytes=_V23_SHELL_HEAD_BYTES,
                tail_bytes=_V23_SHELL_TAIL_BYTES,
                source_text=stderr,
            )
            v23_projection_metadata = {
                "stdout_projection": stdout_projection,
                "stderr_projection": stderr_projection,
            }
            v23_projection_omitted = any(
                projection["omitted_bytes"] or projection["terminal_cleanup_changed"]
                for projection in (stdout_projection, stderr_projection)
            )
        omitted_units = 0
        rule_suffix = (
            "v23"
            if self.v23_bounded_projection
            else "v2"
            if self.profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
            else "v1"
        )
        rule_id = f"{self.profile.observation_policy_id}/{kind}_{rule_suffix}"
        metadata: dict[str, Any] = {
            "preferred_tokens": preferred,
            "hard_tokens": hard,
            "tokenizer_id": self.counter.tokenizer_id,
            "tokenizer_hash": self.counter.tokenizer_hash,
            "raw_stdout_bytes": len(text.encode("utf-8")),
            "raw_stderr_bytes": len(stderr.encode("utf-8")),
            "raw_line_count": len(raw_text.splitlines()),
            **v23_projection_metadata,
        }
        if kind == "list":
            lines = cleaned.splitlines()
            selected = _bounded_tree_lines(lines, max_depth=2, max_entries=200)
            omitted_units = len(lines) - len(selected)
            candidate = "\n".join(selected)
            metadata.update({"max_depth": 2, "max_entries": 200})
        elif kind == "search":
            lines = cleaned.splitlines()
            selected = lines[:20]
            omitted_units = max(0, len(lines) - len(selected))
            candidate = "\n".join(selected)
            metadata["max_matches"] = 20
        elif kind == "read":
            lines = cleaned.splitlines()
            candidate = cleaned
            if self.counter.count(candidate) > preferred:
                structural = structural_view(lines, path or "")
                omitted_units = max(0, len(lines) - len(structural))
                candidate = _render_numbered(structural)
                metadata["view"] = "structural"
            else:
                metadata["view"] = "full"
        elif kind == "shell":
            combined = cleaned
            if stderr:
                combined = f"{cleaned}\n[stderr]\n{cleaned_stderr}".strip()
            candidate = combined
            if self.v23_bounded_projection:
                preferred = hard = _V23_SHELL_CONTEXT_TOKENS
                metadata["view"] = "stream_head_tail"
            elif self.counter.count(candidate) > preferred:
                candidate, omitted_units = _diagnostic_projection(combined.splitlines())
                metadata["view"] = "diagnostic"
            else:
                metadata["view"] = "full"
        else:
            candidate = cleaned
            metadata["view"] = "full"

        content_changed = candidate != cleaned
        if result_header:
            candidate = result_header + (f"\n{candidate}" if candidate else "")
        original_candidate = candidate
        if (
            self.v23_bounded_projection
            and kind == "shell"
            and self.counter.count(original_candidate) > hard
        ):
            raise RuntimeError(
                "OpenHands v23 exact head/tail stream projection exceeds its context bound"
            )
        candidate, bounded_omission = self._bound(
            candidate,
            hard,
            rule_id=rule_id,
            raw_bytes=len(raw),
            raw_sha256=raw_hash,
            description="hard token cap",
        )
        omitted = bool(
            omitted_units or bounded_omission or content_changed or v23_projection_omitted
        )
        if omitted and not bounded_omission:
            candidate = self._append_marker(
                candidate,
                hard,
                rule_id=rule_id,
                raw_bytes=len(raw),
                raw_sha256=raw_hash,
                description=f"{omitted_units} omitted units",
            )
        compact_tokens = self.counter.count(candidate)
        if compact_tokens > hard:
            raise RuntimeError("HWE compactor exceeded its hard token cap")
        metadata.update(
            {
                "pre_bound_tokens": self.counter.count(original_candidate),
                "omitted_units": omitted_units,
                "kept_line_count": len(
                    [
                        line
                        for line in candidate.splitlines()
                        if not line.startswith("[verigym-hwe ")
                    ]
                ),
                "omission_marker_present": "[verigym-hwe omission" in candidate,
            }
        )
        return HweObservationResult(
            text=candidate,
            kind=kind,
            rule_id=rule_id,
            raw_bytes=len(raw),
            raw_sha256=raw_hash,
            compact_bytes=len(candidate.encode("utf-8")),
            compact_tokens=compact_tokens,
            omitted=omitted,
            omitted_units=omitted_units,
            metadata=metadata,
        )

    def append_fixed_notice(
        self,
        result: HweObservationResult,
        notice: str,
        *,
        notice_id: str,
    ) -> HweObservationResult:
        """Append one fixed model-visible control notice under the existing hard cap."""

        if not self.v23_bounded_projection:
            raise ValueError("fixed progress notices are v23-only")
        if not notice or notice != notice.strip() or "\n" in notice:
            raise ValueError("fixed progress notice must be one canonical line")
        _preferred, hard = self._LIMITS[result.kind]
        existing = result.text
        line_compacted = False
        if result.kind == "read":
            lines = existing.splitlines()
            existing_limit = _V23_READ_MAX_MODEL_LINES - 1
            if len(lines) > existing_limit:
                head_count = (existing_limit - 1) // 2
                tail_count = existing_limit - 1 - head_count
                marker = (
                    "[verigym-hwe read checkpoint omission "
                    f"omitted_lines={len(lines) - head_count - tail_count} "
                    f"raw_sha256={result.raw_sha256}]"
                )
                existing = "\n".join([*lines[:head_count], marker, *lines[-tail_count:]])
                line_compacted = True
        combined = f"{existing}\n{notice}" if existing else notice
        bounded, omitted = self._bound(
            combined,
            hard,
            rule_id=result.rule_id,
            raw_bytes=result.raw_bytes,
            raw_sha256=result.raw_sha256,
            description="progress checkpoint append",
        )
        metadata = dict(result.metadata)
        metadata.update(
            {
                "fixed_notice_id": notice_id,
                "fixed_notice_sha256": hashlib.sha256(notice.encode()).hexdigest(),
                "fixed_notice_line_compaction": line_compacted,
            }
        )
        return replace(
            result,
            text=bounded,
            compact_bytes=len(bounded.encode("utf-8")),
            compact_tokens=self.counter.count(bounded),
            omitted=result.omitted or omitted,
            metadata=metadata,
        )

    def _bound(
        self,
        text: str,
        hard: int,
        *,
        rule_id: str,
        raw_bytes: int,
        raw_sha256: str,
        description: str,
    ) -> tuple[str, bool]:
        if self.counter.count(text) <= hard:
            return text, False
        marker = _marker(rule_id, raw_bytes, raw_sha256, 0, description)
        marker_tokens = self.counter.count(marker)
        content_budget = max(0, hard - marker_tokens - 2)
        lines = text.splitlines()
        head: list[str] = []
        tail: list[str] = []
        head_budget = content_budget // 2
        for line in lines:
            trial = "\n".join([*head, line])
            if self.counter.count(trial) > head_budget:
                break
            head.append(line)
        tail_budget = content_budget - self.counter.count("\n".join(head))
        for line in reversed(lines[len(head) :]):
            trial = "\n".join([line, *tail])
            if self.counter.count(trial) > tail_budget:
                break
            tail.insert(0, line)
        value = "\n".join([*head, marker, *tail])
        value = self._stabilize_marker(
            value,
            hard,
            rule_id=rule_id,
            raw_bytes=raw_bytes,
            raw_sha256=raw_sha256,
            description=description,
        )
        return value, True

    def _append_marker(
        self,
        text: str,
        hard: int,
        *,
        rule_id: str,
        raw_bytes: int,
        raw_sha256: str,
        description: str,
    ) -> str:
        marker = _marker(rule_id, raw_bytes, raw_sha256, 0, description)
        value = f"{text}\n{marker}" if text else marker
        if self.counter.count(value) > hard:
            value, _ = self._bound(
                value,
                hard,
                rule_id=rule_id,
                raw_bytes=raw_bytes,
                raw_sha256=raw_sha256,
                description=description,
            )
        return self._stabilize_marker(
            value,
            hard,
            rule_id=rule_id,
            raw_bytes=raw_bytes,
            raw_sha256=raw_sha256,
            description=description,
        )

    def _stabilize_marker(
        self,
        value: str,
        hard: int,
        *,
        rule_id: str,
        raw_bytes: int,
        raw_sha256: str,
        description: str,
    ) -> str:
        for _ in range(8):
            tokens = self.counter.count(value)
            replacement = _marker(rule_id, raw_bytes, raw_sha256, tokens, description)
            updated = re.sub(r"\[verigym-hwe omission[^\]]*\]", replacement, value, count=1)
            if updated == value:
                break
            value = updated
        while self.counter.count(value) > hard:
            lines = value.splitlines()
            marker_index = next(
                (index for index, line in enumerate(lines) if line.startswith("[verigym-hwe ")),
                len(lines) // 2,
            )
            removable = [index for index in range(len(lines)) if index != marker_index]
            if not removable:
                raise RuntimeError("HWE omission marker alone exceeds its hard cap")
            lines.pop(removable[len(removable) // 2])
            value = "\n".join(lines)
        return value


def clean_terminal_noise(text: str) -> str:
    """Mechanical SFT-safe cleanup: ANSI, CR progress updates, and progress-only lines."""

    normalized = _ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line for line in normalized.splitlines() if not _PROGRESS.match(line))


def collapse_repeated_lines(lines: Sequence[str]) -> tuple[list[str], int]:
    """Collapse only consecutive exact repeats and retain an explicit count."""

    if not lines:
        return [], 0
    result: list[str] = []
    collapsed = 0
    index = 0
    while index < len(lines):
        end = index + 1
        while end < len(lines) and lines[end] == lines[index]:
            end += 1
        count = end - index
        result.append(lines[index])
        if count > 1:
            result.append(f"[verigym-hwe repeated-line count={count - 1}]")
            collapsed += count - 1
        index = end
    return result, collapsed


def structural_view(lines: Sequence[str], path: str) -> list[tuple[int, str]]:
    suffix = PurePosixPath(path).suffix.casefold()
    matcher = _SCALA_STRUCTURE if suffix in {".scala", ".sc"} else _SV_STRUCTURE
    selected: set[int] = set()
    if suffix in {".scala", ".sc", ".sv", ".svh", ".v", ".vh"}:
        for index, line in enumerate(lines, start=1):
            if matcher.search(line):
                selected.update(range(max(1, index - 1), min(len(lines), index + 1) + 1))
    if not selected:
        selected.update(range(1, min(40, len(lines)) + 1))
        selected.update(range(max(1, len(lines) - 39), len(lines) + 1))
    return [(index, lines[index - 1]) for index in sorted(selected)]


def _bounded_tree_lines(lines: Sequence[str], *, max_depth: int, max_entries: int) -> list[str]:
    result: list[str] = []
    excluded = {"build", "generated", "vendor", "third_party"}
    for line in lines:
        clean = line.strip()
        if not clean:
            continue
        path = PurePosixPath(clean.rstrip("/"))
        if len(path.parts) > max_depth:
            continue
        if path.parts and path.parts[0].casefold() in excluded:
            continue
        result.append(line)
        if len(result) == max_entries:
            break
    return result


def _diagnostic_projection(lines: Sequence[str]) -> tuple[str, int]:
    keep: set[int] = set(range(min(30, len(lines))))
    keep.update(range(max(0, len(lines) - 60), len(lines)))
    for index, line in enumerate(lines):
        if _DIAGNOSTIC.search(line):
            keep.update(range(max(0, index - 2), min(len(lines), index + 3)))
    selected = [lines[index] for index in sorted(keep)]
    selected, collapsed = collapse_repeated_lines(selected)
    return "\n".join(selected), max(0, len(lines) - len(keep)) + collapsed


def _render_numbered(values: Iterable[tuple[int, str]]) -> str:
    result: list[str] = []
    previous: int | None = None
    for number, line in values:
        if previous is not None and number > previous + 1:
            result.append(f"[verigym-hwe structural gap lines={previous + 1}-{number - 1}]")
        result.append(f"{number}: {line}")
        previous = number
    return "\n".join(result)


def _marker(
    rule_id: str,
    raw_bytes: int,
    raw_sha256: str,
    compact_tokens: int,
    description: str,
) -> str:
    return (
        f"[verigym-hwe omission rule={rule_id} reason={description!r} raw_bytes={raw_bytes} "
        f"raw_sha256={raw_sha256} compact_tokens={compact_tokens}]"
    )


def _result_header(
    *,
    command: str | None,
    cwd: str | None,
    exit_code: int | None,
    duration_ms: int | None,
    stdout_bytes: int,
    stderr_bytes: int,
) -> str:
    rendered_command = command or ""
    if len(rendered_command) > 512:
        rendered_command = rendered_command[:512] + "…"
    command_hash = hashlib.sha256((command or "").encode()).hexdigest()
    fields = {
        "command": rendered_command,
        "command_sha256": command_hash,
        "cwd": cwd or ".",
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "stderr_bytes": stderr_bytes,
        "stdout_bytes": stdout_bytes,
    }
    return "[verigym-hwe result " + repr(fields) + "]"


def _bounded_read_projection(
    text: str,
    *,
    source_text: str,
    max_bytes: int,
) -> tuple[str, dict[str, Any]]:
    if not 1024 <= max_bytes <= _V23_READ_MAX_BYTES:
        raise ValueError("OpenHands v23 read projection byte budget is invalid")
    raw = text.encode("utf-8")
    source_raw = source_text.encode("utf-8")
    raw_hash = hashlib.sha256(raw).hexdigest()
    lines = text.splitlines()
    content_line_limit = _V23_READ_MAX_MODEL_LINES - 1
    omitted_lines = max(0, len(lines) - content_line_limit)
    if omitted_lines:
        head_count = (content_line_limit - 1) // 2
        tail_count = content_line_limit - 1 - head_count
        marker = (
            f"[verigym-hwe read omission omitted_lines={omitted_lines} "
            f"raw_bytes={len(raw)} raw_sha256={raw_hash}]"
        )
        lines = [*lines[:head_count], marker, *lines[-tail_count:]]
    projected = "\n".join(lines)
    projected_bytes = projected.encode("utf-8")
    byte_omitted = 0
    if len(projected_bytes) > max_bytes:
        projected, byte_omitted = _bounded_utf8_bytes(
            projected,
            label="read",
            head_bytes=(max_bytes - 512) // 2,
            tail_bytes=(max_bytes - 512) // 2,
        )
    if len(projected.encode("utf-8")) > max_bytes:
        raise RuntimeError("OpenHands v23 read projection exceeded 128 KiB")
    return projected, {
        "projection_policy": "read_head_tail_400_lines_128k_v23",
        "model_visible_line_count": len(projected.splitlines()) + 1,
        "model_visible_line_limit_including_result_header": _V23_READ_MAX_MODEL_LINES,
        "model_visible_bytes": len(projected.encode("utf-8")),
        "model_visible_bytes_including_result_header_limit": _V23_READ_MAX_BYTES,
        "omitted_lines": omitted_lines,
        "omitted_bytes": byte_omitted,
        "source_bytes": len(source_raw),
        "source_sha256": hashlib.sha256(source_raw).hexdigest(),
        "cleaned_sha256": raw_hash,
        "terminal_cleanup_changed": source_text != text,
    }


def _bounded_stream_projection(
    text: str,
    *,
    label: str,
    head_bytes: int,
    tail_bytes: int,
    source_text: str,
) -> tuple[str, dict[str, Any]]:
    projected, omitted_bytes = _bounded_utf8_bytes(
        text,
        label=label,
        head_bytes=head_bytes,
        tail_bytes=tail_bytes,
    )
    cleaned_raw = text.encode("utf-8")
    source_raw = source_text.encode("utf-8")
    return projected, {
        "projection_policy": "stream_head_64k_tail_64k_v23",
        "raw_bytes": len(source_raw),
        "raw_sha256": hashlib.sha256(source_raw).hexdigest(),
        "cleaned_bytes": len(cleaned_raw),
        "cleaned_sha256": hashlib.sha256(cleaned_raw).hexdigest(),
        "terminal_cleanup_changed": source_text != text,
        "model_visible_projection_bytes": len(projected.encode("utf-8")),
        "omitted_bytes": omitted_bytes,
    }


def _bounded_utf8_bytes(
    text: str,
    *,
    label: str,
    head_bytes: int,
    tail_bytes: int,
) -> tuple[str, int]:
    raw = text.encode("utf-8")
    if len(raw) <= head_bytes + tail_bytes:
        return text, 0
    head = _utf8_prefix(raw, head_bytes)
    tail = _utf8_suffix(raw, len(raw) - tail_bytes)
    if len(head) + len(tail) >= len(raw):
        return text, 0
    omitted = len(raw) - len(head) - len(tail)
    marker = (
        f"[verigym-hwe {label} omission omitted_bytes={omitted} "
        f"raw_bytes={len(raw)} raw_sha256={hashlib.sha256(raw).hexdigest()}]"
    )
    return "\n".join((head.decode("utf-8"), marker, tail.decode("utf-8"))), omitted


def _utf8_prefix(raw: bytes, limit: int) -> bytes:
    end = min(limit, len(raw))
    while end > 0:
        try:
            raw[:end].decode("utf-8")
        except UnicodeDecodeError:
            end -= 1
        else:
            return raw[:end]
    return b""


def _utf8_suffix(raw: bytes, start: int) -> bytes:
    offset = max(0, min(start, len(raw)))
    while offset < len(raw):
        try:
            raw[offset:].decode("utf-8")
        except UnicodeDecodeError:
            offset += 1
        else:
            return raw[offset:]
    return b""


__all__ = [
    "HWE_TOKENIZER_HASH",
    "HweObservationCompactor",
    "HweObservationResult",
    "ObservationKind",
    "TiktokenO200kCounter",
    "TokenCounter",
    "clean_terminal_noise",
    "collapse_repeated_lines",
    "structural_view",
]
