"""Deterministic V2 triplet discovery and structural validation."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from verigym.core.hashing import hash_bytes
from verigym.schemas.task import ValidationIssue, ValidationReport
from verigym.suites.verilog_eval.normalization import declared_modules
from verigym.suites.verilog_eval.schemas import (
    VerilogEvalCatalog,
    VerilogEvalLayout,
    VerilogEvalProblem,
)

MAX_TRIPLET_FILE_BYTES = 8 * 1024 * 1024
_SUFFIXES = {
    "_prompt.txt": "prompt",
    "_ref.sv": "reference",
    "_test.sv": "testbench",
}
_REQUIRED_ROLES = frozenset(_SUFFIXES.values())


def inspect_layout(layout: VerilogEvalLayout) -> VerilogEvalCatalog:
    issues: list[ValidationIssue] = []
    grouped: dict[str, dict[str, Path]] = {}
    case_stems: dict[str, set[str]] = {}
    relevant_paths: list[Path] = []

    try:
        entries = sorted(layout.dataset_root.rglob("*"), key=lambda path: path.as_posix())
    except OSError as exc:
        issues.append(_issue("source_unreadable", f"cannot enumerate dataset: {exc}"))
        entries = []
    for path in entries:
        try:
            relative = path.relative_to(layout.dataset_root).as_posix()
        except ValueError:
            issues.append(_issue("path_escape", "dataset entry escapes source root"))
            continue
        if path.is_symlink():
            target = path.resolve(strict=False)
            code = "symlink_escape" if not target.is_relative_to(layout.dataset_root) else "symlink"
            issues.append(
                _issue(code, "symlinks are not supported in VerilogEval sources", relative)
            )
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            issues.append(_issue("special_file", "special files are unsupported", relative))
            continue
        if path.parent != layout.dataset_root:
            if _split_role(path.name) is not None:
                issues.append(
                    _issue(
                        "nested_triplet",
                        "V2 triplet files must be directly inside the dataset directory",
                        relative,
                    )
                )
            continue
        split = _split_role(path.name)
        if split is None:
            continue
        stem, role = split
        relevant_paths.append(path)
        case_stems.setdefault(stem.casefold(), set()).add(stem)
        roles = grouped.setdefault(stem, {})
        if role in roles:
            issues.append(
                _issue(
                    "duplicate_triplet_role",
                    f"duplicate {role} file for native stem {stem!r}",
                    relative,
                )
            )
        else:
            roles[role] = path

    for folded, stems in sorted(case_stems.items()):
        if len(stems) > 1:
            issues.append(
                _issue(
                    "case_collision",
                    f"case-colliding native stems: {sorted(stems)}",
                )
            )
        if not folded:
            issues.append(_issue("empty_stem", "triplet stem cannot be empty"))

    problems: list[VerilogEvalProblem] = []
    for stem in sorted(grouped, key=natural_sort_key):
        roles = grouped[stem]
        missing = sorted(_REQUIRED_ROLES - set(roles))
        if missing:
            issues.append(
                _issue(
                    "incomplete_triplet",
                    f"native stem {stem!r} is missing: {', '.join(missing)}",
                )
            )
            continue
        contents: dict[str, str] = {}
        unreadable = False
        for role in sorted(_REQUIRED_ROLES):
            path = roles[role]
            relative = path.relative_to(layout.dataset_root).as_posix()
            try:
                mode = path.stat().st_mode
                if not mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH):
                    raise PermissionError("file has no readable permission bits")
                size = path.stat().st_size
                if size > MAX_TRIPLET_FILE_BYTES:
                    issues.append(
                        _issue(
                            "oversized_file",
                            f"triplet file exceeds {MAX_TRIPLET_FILE_BYTES} bytes",
                            relative,
                        )
                    )
                    unreadable = True
                    continue
                if not os.access(path, os.R_OK):
                    raise PermissionError("file is not readable")
                contents[role] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                code = "non_utf8_prompt" if role == "prompt" else "non_utf8_source"
                issues.append(_issue(code, "triplet file is not valid UTF-8", relative))
                unreadable = True
            except OSError as exc:
                issues.append(
                    _issue("unreadable_file", f"cannot read triplet file: {exc}", relative)
                )
                unreadable = True
        if unreadable or set(contents) != _REQUIRED_ROLES:
            continue
        prompt = contents["prompt"]
        reference = contents["reference"]
        testbench = contents["testbench"]
        testbench_top = _validate_conventions(stem, prompt, reference, testbench, issues)
        problems.append(
            VerilogEvalProblem(
                native_id=stem,
                prompt_path=roles["prompt"],
                reference_path=roles["reference"],
                testbench_path=roles["testbench"],
                prompt=prompt,
                reference=reference,
                testbench=testbench,
                content_hash=_task_hash(layout.dataset_root, roles),
                testbench_top=testbench_top,
            )
        )

    if not grouped:
        issues.append(_issue("no_problems", "no VerilogEval V2 triplets were discovered"))
    elif not problems and not any(issue.code == "no_problems" for issue in issues):
        issues.append(_issue("no_valid_problems", "no complete readable V2 problems are available"))
    return VerilogEvalCatalog(
        layout=layout,
        problems=problems,
        issues=issues,
        dataset_content_hash=_dataset_hash(layout.dataset_root, relevant_paths),
    )


def validation_report(catalog: VerilogEvalCatalog) -> ValidationReport:
    errors = [
        f"[{issue.code}] {issue.message}" for issue in catalog.issues if issue.level == "error"
    ]
    warnings = [
        f"[{issue.code}] {issue.message}" for issue in catalog.issues if issue.level == "warning"
    ]
    return ValidationReport(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        issues=catalog.issues,
    )


def natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    pieces = re.split(r"(\d+)", value.casefold())
    return tuple((0, int(piece)) if piece.isdigit() else (1, piece) for piece in pieces if piece)


def _split_role(filename: str) -> tuple[str, str] | None:
    lowered = filename.casefold()
    matches = [
        (suffix, role) for suffix, role in _SUFFIXES.items() if lowered.endswith(suffix.casefold())
    ]
    if len(matches) != 1:
        return None
    suffix, role = matches[0]
    return filename[: len(filename) - len(suffix)], role


def _validate_conventions(
    stem: str,
    prompt: str,
    reference: str,
    testbench: str,
    issues: list[ValidationIssue],
) -> str:
    if not prompt.strip():
        issues.append(_issue("empty_prompt", f"native stem {stem!r} has an empty prompt"))
    if "TopModule" not in prompt:
        issues.append(
            _issue(
                "prompt_topmodule_missing",
                f"native stem {stem!r} prompt does not name TopModule",
                level="warning",
            )
        )
    reference_modules = declared_modules(reference)
    if reference_modules.count("RefModule") != 1:
        issues.append(
            _issue(
                "invalid_reference_module",
                f"native stem {stem!r} must declare exactly one RefModule",
            )
        )
    test_modules = declared_modules(testbench)
    if "tb" in test_modules:
        testbench_top = "tb"
    elif len(test_modules) == 1:
        testbench_top = test_modules[0]
        issues.append(
            _issue(
                "nonstandard_testbench_top",
                f"native stem {stem!r} uses deterministically recognized top "
                f"{testbench_top!r} instead of tb",
                level="warning",
            )
        )
    else:
        testbench_top = "tb"
        issues.append(
            _issue(
                "missing_testbench_top",
                f"native stem {stem!r} has no unambiguous testbench top module",
            )
        )
    if not re.search(r"\bRefModule\b", testbench) or not re.search(r"\bTopModule\b", testbench):
        issues.append(
            _issue(
                "missing_testbench_instances",
                f"native stem {stem!r} testbench must reference RefModule and TopModule",
            )
        )
    if "Mismatches:" not in testbench or "samples" not in testbench:
        issues.append(
            _issue(
                "missing_native_summary",
                f"native stem {stem!r} testbench has no native mismatch summary",
            )
        )
    if "TIMEOUT" not in testbench:
        issues.append(
            _issue(
                "missing_native_timeout_marker",
                f"native stem {stem!r} testbench has no TIMEOUT marker",
                level="warning",
            )
        )
    return testbench_top


def _dataset_hash(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        try:
            data = path.read_bytes()
        except OSError:
            data = b""
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _task_hash(root: Path, roles: dict[str, Path]) -> str:
    values = []
    for role in sorted(roles):
        path = roles[role]
        values.append(
            {
                "role": role,
                "name": path.relative_to(root).as_posix(),
                "sha256": hash_bytes(path.read_bytes()),
            }
        )
    from verigym.core.hashing import content_hash

    return content_hash(values)


def _issue(
    code: str,
    message: str,
    relative_path: str | None = None,
    *,
    level: str = "error",
) -> ValidationIssue:
    return ValidationIssue(
        level="warning" if level == "warning" else "error",
        code=code,
        message=message,
        relative_path=relative_path,
    )


__all__ = [
    "MAX_TRIPLET_FILE_BYTES",
    "inspect_layout",
    "natural_sort_key",
    "validation_report",
]
