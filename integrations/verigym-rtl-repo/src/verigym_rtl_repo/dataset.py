"""Strict, read-only access to an official RTL-Repo Hugging Face snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

VARIANT = "official-parquet-v1"
AGENT_EVAL_VARIANT = "official-parquet-v1-agent-eval-v1"
AGENT_EVAL_V2_VARIANT = "official-parquet-v1-agent-eval-v2"
AGENT_EVAL_V3_VARIANT = "official-parquet-v1-agent-eval-v3"
NATIVE_LAYOUT = "huggingface-parquet-rtl-repo-v1"
CONTEXT_CLASSIFICATION_RULE = "rtl_repo_path_components_source_generated_v1"
EXPECTED_SPLIT_COUNTS = {"train": 2_924, "test": 1_174}
MAX_PARQUET_BYTES = 512 * 1024 * 1024
MAX_TASK_BYTES = 16 * 1024 * 1024
MAX_TARGET_BYTES = 64 * 1024
MAX_CONTEXT_ITEMS = 128

_PARQUET_NAME = re.compile(r"(?P<split>train|test)-.+\.parquet")
_REQUIRED_COLUMNS = {
    "repo_name",
    "file_path",
    "next_line",
    "context",
    "created_at",
    "all_code",
    "cropped_code",
    "level",
    "__index_level_0__",
}


@dataclass(frozen=True)
class Layout:
    source_root: Path
    dataset_root: Path


@dataclass(frozen=True)
class Issue:
    level: Literal["error", "warning"]
    code: str
    message: str
    relative_path: str | None = None


@dataclass(frozen=True)
class RowRef:
    native_id: str
    split: Literal["train", "test"]
    parquet_file: Path
    row_number: int
    official_index: int | None
    repo_name: str
    file_path: str
    level: str | int | None


@dataclass(frozen=True)
class Problem:
    ref: RowRef
    prompt: str
    target: str
    context_count: int
    content_hash: str
    prompt_hash: str
    target_hash: str
    cropped_code: str
    context: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Catalog:
    layout: Layout
    rows: tuple[RowRef, ...]
    parquet_files: tuple[Path, ...]
    issues: tuple[Issue, ...]
    dataset_content_hash: str
    file_state: tuple[tuple[str, int, int], ...]
    split_counts: dict[str, int]
    synthetic_fixture: bool


def resolve_layout(raw_root: Path, variant: str | None) -> Layout:
    supported = (VARIANT, AGENT_EVAL_VARIANT, AGENT_EVAL_V2_VARIANT, AGENT_EVAL_V3_VARIANT)
    if variant is not None and variant not in supported:
        raise ValueError("suite supports variants " + ", ".join(repr(item) for item in supported))
    expanded = raw_root.expanduser()
    if expanded.is_symlink():
        raise ValueError("source root must not be a symlink")
    try:
        root = expanded.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError(f"source path is unavailable: {expanded}") from exc
    if not root.is_dir():
        raise ValueError("source path must be a directory")
    dataset_candidate = root if root.name == "data" else root / "data"
    if dataset_candidate.is_symlink():
        raise ValueError("data must not be a symlink")
    try:
        dataset_root = dataset_candidate.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("source is missing the required data directory") from exc
    if not dataset_root.is_dir() or dataset_root.is_symlink():
        raise ValueError("data must be a real directory")
    if root.name != "data" and not dataset_root.is_relative_to(root):
        raise ValueError("data directory escapes the approved source root")
    return Layout(source_root=root, dataset_root=dataset_root)


def inspect_layout(layout: Layout, *, strict_compatibility: bool) -> Catalog:
    parquet = _parquet_module()
    issues: list[Issue] = []
    rows: list[RowRef] = []
    relevant: list[Path] = []
    split_offsets = {"train": 0, "test": 0}
    synthetic = (layout.source_root / "VERIGYM_SYNTHETIC_FIXTURE").is_file()
    try:
        entries = sorted(layout.dataset_root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        entries = []
        issues.append(Issue("error", "source_unreadable", f"cannot enumerate data: {exc}"))
    for path in entries:
        relative = path.name
        if path.is_symlink():
            issues.append(Issue("error", "symlink", "symlinks are not supported", relative))
            continue
        match = _PARQUET_NAME.fullmatch(path.name)
        if match is None:
            continue
        if not path.is_file():
            issues.append(Issue("error", "special_file", "expected a regular file", relative))
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            issues.append(Issue("error", "unreadable_file", str(exc), relative))
            continue
        if size > MAX_PARQUET_BYTES:
            issues.append(
                Issue(
                    "error",
                    "oversized_parquet",
                    f"Parquet file exceeds {MAX_PARQUET_BYTES} bytes",
                    relative,
                )
            )
            continue
        relevant.append(path)
        split: Literal["train", "test"] = "train" if match.group("split") == "train" else "test"
        try:
            parquet_file = parquet.ParquetFile(path)
            columns = set(parquet_file.schema_arrow.names)
            missing = sorted(_REQUIRED_COLUMNS - columns)
            if missing:
                issues.append(
                    Issue(
                        "error",
                        "missing_columns",
                        f"missing required columns: {', '.join(missing)}",
                        relative,
                    )
                )
                continue
            metadata = parquet_file.read(
                columns=[
                    "repo_name",
                    "file_path",
                    "level",
                    "__index_level_0__",
                ]
            ).to_pylist()
        except Exception as exc:
            issues.append(Issue("error", "invalid_parquet", str(exc), relative))
            continue
        for local_row, raw in enumerate(metadata):
            global_row = split_offsets[split] + local_row
            repo_name = _bounded_text(raw.get("repo_name"), "repo_name", 512)
            file_path = _bounded_path(raw.get("file_path"), "file_path")
            official_index = _optional_int(raw.get("__index_level_0__"))
            level = _level(raw.get("level"))
            if repo_name is None or file_path is None:
                issues.append(
                    Issue(
                        "error",
                        "invalid_row_metadata",
                        f"row {local_row} has an invalid repo_name or file_path",
                        relative,
                    )
                )
                continue
            rows.append(
                RowRef(
                    native_id=f"{split}-{global_row:06d}",
                    split=split,
                    parquet_file=path,
                    row_number=local_row,
                    official_index=official_index,
                    repo_name=repo_name,
                    file_path=file_path,
                    level=level,
                )
            )
        split_offsets[split] += len(metadata)
    if not relevant:
        issues.append(Issue("error", "no_parquet", "no train/test Parquet shards were found"))
    for split_name, expected in EXPECTED_SPLIT_COUNTS.items():
        actual = split_offsets[split_name]
        if actual == expected or synthetic:
            continue
        issue_level: Literal["error", "warning"] = "error" if strict_compatibility else "warning"
        issues.append(
            Issue(
                issue_level,
                "split_count_mismatch",
                f"{split_name} contains {actual} rows; the official release contains {expected}",
            )
        )
    return Catalog(
        layout=layout,
        rows=tuple(rows),
        parquet_files=tuple(relevant),
        issues=tuple(issues),
        dataset_content_hash=_paths_hash(layout.dataset_root, relevant),
        file_state=file_state(layout.dataset_root, relevant),
        split_counts=dict(split_offsets),
        synthetic_fixture=synthetic,
    )


def load_problem(ref: RowRef) -> Problem:
    parquet_file = _parquet_module().ParquetFile(ref.parquet_file)
    raw = _read_row(
        parquet_file,
        ref.row_number,
        [
            "repo_name",
            "file_path",
            "next_line",
            "context",
            "cropped_code",
            "level",
            "__index_level_0__",
        ],
    )
    repo_name = _required_text(raw.get("repo_name"), "repo_name", 512)
    file_path = _required_path(raw.get("file_path"), "file_path")
    if repo_name != ref.repo_name or file_path != ref.file_path:
        raise ValueError("row metadata differs from the discovered source")
    target = _required_text(raw.get("next_line"), "next_line", MAX_TARGET_BYTES, allow_empty=True)
    cropped_code = _required_text(
        raw.get("cropped_code"), "cropped_code", MAX_TASK_BYTES, allow_empty=True
    )
    raw_context = raw.get("context")
    if not isinstance(raw_context, list) or len(raw_context) > MAX_CONTEXT_ITEMS:
        raise ValueError("context must be a bounded list")
    context: list[dict[str, str]] = []
    for index, item in enumerate(raw_context):
        if not isinstance(item, dict):
            raise ValueError(f"context[{index}] must be a record")
        context.append(
            {
                "path": _required_path(item.get("path"), f"context[{index}].path"),
                "snippet": _required_text(
                    item.get("snippet"),
                    f"context[{index}].snippet",
                    MAX_TASK_BYTES,
                    allow_empty=True,
                ),
            }
        )
    prompt = build_official_prompt(
        repo_name=repo_name,
        file_path=file_path,
        cropped_code=cropped_code,
        context=context,
    )
    if len(prompt.encode("utf-8")) > MAX_TASK_BYTES:
        raise ValueError(f"official prompt exceeds {MAX_TASK_BYTES} bytes")
    identity = {
        "repo_name": repo_name,
        "file_path": file_path,
        "next_line": target,
        "context": context,
        "cropped_code": cropped_code,
        "level": _level(raw.get("level")),
        "official_index": _optional_int(raw.get("__index_level_0__")),
    }
    return Problem(
        ref=ref,
        prompt=prompt,
        target=target,
        context_count=len(context),
        content_hash=_content_hash(identity),
        prompt_hash=sha256_bytes(prompt.encode("utf-8")),
        target_hash=sha256_bytes(target.encode("utf-8")),
        cropped_code=cropped_code,
        context=tuple((item["path"], item["snippet"]) for item in context),
    )


def build_official_prompt(
    *,
    repo_name: str,
    file_path: str,
    cropped_code: str,
    context: list[dict[str, str]],
) -> str:
    """Reproduce RTL-Repo's tokenizer-independent prompt construction."""

    prompt = f"// Repo Name: {repo_name}\n"
    for item in context:
        prompt += f"// Path: {item['path']}\n{item['snippet']}\n\n"
    prompt += f"// Path: {file_path}\n{cropped_code}\n"
    return re.sub(r"\n{4,}", "\n\n", prompt)


def classify_context_path(path: str) -> Literal["source", "generated"]:
    """Classify context using only a frozen, case-insensitive path-component rule."""

    pure = PurePosixPath(path)
    components = tuple(component.casefold() for component in pure.parts)
    generated_component = any(
        component.endswith(".sim") or component in {"impl", "synth", "xsim"}
        for component in components
    )
    generated_file = pure.stem.casefold() == "glbl"
    return "generated" if generated_component or generated_file else "source"


def file_state(root: Path, paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
    state: list[tuple[str, int, int]] = []
    for path in sorted(set(paths), key=lambda item: item.relative_to(root).as_posix()):
        stat_result = path.stat()
        state.append(
            (path.relative_to(root).as_posix(), stat_result.st_size, stat_result.st_mtime_ns)
        )
    return tuple(state)


def current_file_state(catalog: Catalog) -> tuple[tuple[str, int, int], ...]:
    return file_state(catalog.layout.dataset_root, list(catalog.parquet_files))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_row(parquet_file: Any, row_number: int, columns: list[str]) -> dict[str, Any]:
    offset = 0
    for row_group in range(parquet_file.num_row_groups):
        count = parquet_file.metadata.row_group(row_group).num_rows
        if row_number < offset + count:
            table = parquet_file.read_row_group(row_group, columns=columns)
            rows = table.slice(row_number - offset, 1).to_pylist()
            if len(rows) != 1 or not isinstance(rows[0], dict):
                raise ValueError("Parquet row could not be decoded")
            return rows[0]
        offset += count
    raise ValueError(f"Parquet row {row_number} is out of range")


def _parquet_module() -> Any:
    try:
        import pyarrow.parquet as parquet  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ValueError("RTL-Repo support requires the optional pyarrow dependency") from exc
    return parquet


def _paths_hash(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def _content_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return sha256_bytes(encoded)


def _bounded_text(value: object, label: str, maximum: int) -> str | None:
    try:
        return _required_text(value, label, maximum)
    except ValueError:
        return None


def _required_text(
    value: object,
    label: str,
    maximum: int,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError(f"{label} must be NUL-free text")
    if not allow_empty and not value:
        raise ValueError(f"{label} must not be empty")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{label} exceeds {maximum} bytes")
    return value


def _bounded_path(value: object, label: str) -> str | None:
    try:
        return _required_path(value, label)
    except ValueError:
        return None


def _required_path(value: object, label: str) -> str:
    text = _required_text(value, label, 4_096)
    pure = PurePosixPath(text)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"{label} must be a safe repository-relative path")
    return text


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _level(value: object) -> str | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        return value
    return None


__all__ = [
    "AGENT_EVAL_VARIANT",
    "AGENT_EVAL_V2_VARIANT",
    "AGENT_EVAL_V3_VARIANT",
    "CONTEXT_CLASSIFICATION_RULE",
    "NATIVE_LAYOUT",
    "VARIANT",
    "Catalog",
    "Issue",
    "Layout",
    "Problem",
    "RowRef",
    "build_official_prompt",
    "classify_context_path",
    "current_file_state",
    "inspect_layout",
    "load_problem",
    "resolve_layout",
    "sha256_bytes",
]
