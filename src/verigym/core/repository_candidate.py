"""Deterministic repository validation, patch freezing, and replay primitives."""

from __future__ import annotations

import difflib
import os
import re
import stat
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from verigym.core.errors import PathPolicyError
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.loaders import dump_json
from verigym.core.workspace import copy_tree_safely, glob_matches
from verigym.schemas.repository import (
    RepositoryCandidateRecord,
    RepositoryFileIdentity,
    RepositoryPatchSummary,
    RepositoryPlanIdentity,
    RepositorySnapshot,
    RepositoryWorkspaceContract,
)
from verigym.schemas.task import VeriTask

_HUNK = re.compile(r"^@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@$")
_FORBIDDEN_COMPONENTS = {
    ".git",
    ".hg",
    ".svn",
    ".verigym_internal",
    "__pycache__",
}


@dataclass(frozen=True)
class _TreeData:
    snapshot: RepositorySnapshot
    contents: dict[str, bytes]
    modes: dict[str, int]


def validate_repository_tree(
    root: Path,
    contract: RepositoryWorkspaceContract,
) -> RepositorySnapshot:
    """Reject unsafe trees and return a deterministic content snapshot."""

    return _read_tree(root, contract).snapshot


def repository_plan_identity(task: VeriTask) -> RepositoryPlanIdentity | None:
    """Normalize the strict repository identity embedded by a suite adapter."""

    raw = task.metadata.get("repository_repair")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("repository task metadata must be a strict object")
    workspace = raw.get("workspace_contract")
    if not isinstance(workspace, dict):
        raise ValueError("repository task metadata lacks its workspace contract")
    return RepositoryPlanIdentity(
        manifest_hash=str(raw.get("manifest_hash") or ""),
        task_bundle_hash=str(raw.get("task_bundle_hash") or ""),
        source_identity_hash=str(raw.get("source_identity_hash") or ""),
        license_file_hash=str(raw.get("license_file_hash") or ""),
        base_repository_hash=str(raw.get("base_repository_hash") or ""),
        issue_hash=str(raw.get("issue_hash") or ""),
        workspace_contract_hash=content_hash(workspace),
        public_assets_hash=str(raw.get("public_assets_hash") or ""),
        public_mount_hash=str(raw.get("public_mount_hash") or ""),
        hidden_verifier_hash=str(raw.get("hidden_verifier_hash") or ""),
        reference_candidate_hash=str(raw.get("reference_candidate_hash") or ""),
        reference_patch_hash=str(raw.get("reference_patch_hash") or ""),
    )


def repository_workspace_contract(task: VeriTask) -> RepositoryWorkspaceContract:
    """Read a frozen candidate contract without inventing repair-only reference identities."""
    repair = task.metadata.get("repository_repair")
    candidate = task.metadata.get("repository_candidate_workspace_contract")
    if repair is not None:
        if not isinstance(repair, dict) or not isinstance(repair.get("workspace_contract"), dict):
            raise ValueError("repository task snapshot lacks its workspace contract")
        raw = repair["workspace_contract"]
        if candidate is not None and candidate != raw:
            raise ValueError("repository task snapshot has conflicting workspace contracts")
    else:
        raw = candidate
    if not isinstance(raw, dict):
        raise ValueError("repository task snapshot lacks its workspace contract")
    return RepositoryWorkspaceContract.model_validate(raw)


def freeze_repository_candidate(
    *,
    task_id: str,
    base_repository: Path,
    candidate_repository: Path,
    contract: RepositoryWorkspaceContract,
    public_test_ids: list[str],
    run_root: Path,
    artifact_root: Path,
) -> RepositoryCandidateRecord:
    """Freeze one candidate repository and prove its patch round trip exactly."""

    base = _read_tree(base_repository, contract)
    candidate = _read_tree(candidate_repository, contract)
    changed = sorted(
        path
        for path in set(base.contents) | set(candidate.contents)
        if base.contents.get(path) != candidate.contents.get(path)
        or base.modes.get(path) != candidate.modes.get(path)
    )
    added = sorted(set(candidate.contents) - set(base.contents))
    deleted = sorted(set(base.contents) - set(candidate.contents))
    mode_changed = sorted(
        path
        for path in set(base.modes) & set(candidate.modes)
        if base.modes[path] != candidate.modes[path]
    )
    binary = sorted(
        path
        for path in changed
        if not _is_utf8_text(base.contents.get(path, b""))
        or not _is_utf8_text(candidate.contents.get(path, b""))
    )
    _enforce_candidate_policy(
        changed=changed,
        added=added,
        deleted=deleted,
        mode_changed=mode_changed,
        binary=binary,
        candidate=candidate,
        contract=contract,
    )
    patch, added_lines, deleted_lines = _build_patch(base.contents, candidate.contents, changed)
    patch_bytes = patch.encode("utf-8")
    if added_lines + deleted_lines > contract.max_patch_lines:
        raise PathPolicyError(
            f"repository patch has {added_lines + deleted_lines} lines; "
            f"limit is {contract.max_patch_lines}"
        )
    with tempfile.TemporaryDirectory(prefix="verigym-repository-patch-reapply-") as temporary:
        staging = Path(temporary) / "repository"
        copy_tree_safely(base_repository, staging, preserve_safe_file_modes=True)
        apply_repository_patch(staging, patch)
        reapplied = _read_tree(staging, contract)
    if reapplied.snapshot.repository_hash != candidate.snapshot.repository_hash:
        raise PathPolicyError("repository patch does not reproduce the frozen candidate exactly")
    summary = RepositoryPatchSummary(
        patch_hash=hash_bytes(patch_bytes),
        base_repository_hash=base.snapshot.repository_hash,
        candidate_repository_hash=candidate.snapshot.repository_hash,
        reapplied_repository_hash=reapplied.snapshot.repository_hash,
        reapply_exact=True,
        changed_files=changed,
        added_files=added,
        deleted_files=deleted,
        renamed_files=[],
        mode_changed_files=mode_changed,
        binary_files=binary,
        created_file_count=len(added),
        deleted_file_count=len(deleted),
        added_lines=added_lines,
        deleted_lines=deleted_lines,
        policy_status="passed",
    )
    record = RepositoryCandidateRecord(
        task_id=task_id,
        base=base.snapshot,
        candidate=candidate.snapshot,
        patch=summary,
        public_test_ids=sorted(public_test_ids),
        hidden_assets_present=False,
        reference_patch_used=False,
    )
    (run_root / "repository.patch").write_bytes(patch_bytes)
    repository_artifacts = artifact_root / "repository_candidate"
    repository_artifacts.mkdir(parents=True, exist_ok=False)
    dump_json(repository_artifacts / "workspace_before.json", base.snapshot)
    dump_json(repository_artifacts / "workspace_after.json", candidate.snapshot)
    dump_json(repository_artifacts / "patch_summary.json", summary)
    dump_json(repository_artifacts / "repository_candidate.json", record)
    return record


def verify_frozen_repository_candidate(
    *,
    base_repository: Path,
    candidate_repository: Path,
    patch_file: Path,
    record: RepositoryCandidateRecord,
    contract: RepositoryWorkspaceContract,
) -> None:
    """Replay the candidate-freeze proof without an agent or verifier."""

    base = _read_tree(base_repository, contract)
    candidate = _read_tree(candidate_repository, contract)
    patch_bytes = patch_file.read_bytes()
    _validate_frozen_record(base, candidate, patch_bytes, record)
    with tempfile.TemporaryDirectory(prefix="verigym-repository-replay-") as temporary:
        staging = Path(temporary) / "repository"
        copy_tree_safely(base_repository, staging, preserve_safe_file_modes=True)
        apply_repository_patch(staging, patch_bytes.decode("utf-8"))
        replayed = _read_tree(staging, contract)
    if replayed.snapshot.repository_hash != record.candidate.repository_hash:
        raise ValueError("repository replay patch does not reproduce the candidate")


def verify_frozen_repository_candidate_offline(
    *,
    candidate_repository: Path,
    patch_file: Path,
    record: RepositoryCandidateRecord,
    contract: RepositoryWorkspaceContract,
) -> None:
    """Prove a frozen candidate without the original suite source or any tool."""

    candidate = _read_tree(candidate_repository, contract)
    patch_bytes = patch_file.read_bytes()
    try:
        patch = patch_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("repository replay patch is not UTF-8 text") from exc
    with tempfile.TemporaryDirectory(prefix="verigym-repository-offline-replay-") as temporary:
        base_staging = Path(temporary) / "base"
        copy_tree_safely(candidate_repository, base_staging, preserve_safe_file_modes=True)
        apply_repository_patch(base_staging, _reverse_repository_patch(patch))
        base = _read_tree(base_staging, contract)
        _validate_frozen_record(base, candidate, patch_bytes, record)
        reapplied_staging = Path(temporary) / "reapplied"
        copy_tree_safely(base_staging, reapplied_staging, preserve_safe_file_modes=True)
        apply_repository_patch(reapplied_staging, patch)
        reapplied = _read_tree(reapplied_staging, contract)
    if reapplied.snapshot != candidate.snapshot:
        raise ValueError("offline repository patch replay does not reproduce the candidate")


def apply_repository_patch(repository: Path, patch: str) -> None:
    """Apply the narrow deterministic unified-diff format emitted above."""

    if "\x00" in patch or "\r" in patch:
        raise PathPolicyError("repository patch contains forbidden bytes")
    lines = patch.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            raise PathPolicyError("repository patch has an unexpected record")
        old_label = lines[index][4:].rstrip("\n")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise PathPolicyError("repository patch is missing its new-file header")
        new_label = lines[index][4:].rstrip("\n")
        index += 1
        old_path = _patch_path(old_label, prefix="a/")
        new_path = _patch_path(new_label, prefix="b/")
        if old_path is None and new_path is None:
            raise PathPolicyError("repository patch cannot delete and add /dev/null")
        if old_path is not None and new_path is not None and old_path != new_path:
            raise PathPolicyError("repository patch renames are not supported")
        relative = old_path or new_path
        assert relative is not None
        target = repository / relative
        original = [] if old_path is None else _read_patch_text(target)
        output: list[str] = []
        cursor = 0
        hunk_seen = False
        while index < len(lines) and lines[index].startswith("@@ "):
            hunk_seen = True
            match = _HUNK.fullmatch(lines[index].rstrip("\n"))
            if match is None:
                raise PathPolicyError("repository patch contains a malformed hunk header")
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_count = int(match.group(4) or "1")
            expected_cursor = max(old_start - 1, 0)
            if expected_cursor < cursor or expected_cursor > len(original):
                raise PathPolicyError("repository patch hunk position is invalid")
            output.extend(original[cursor:expected_cursor])
            cursor = expected_cursor
            index += 1
            consumed_old = 0
            produced_new = 0
            while consumed_old < old_count or produced_new < new_count:
                if index >= len(lines) or lines[index][:1] not in {" ", "+", "-"}:
                    raise PathPolicyError("repository patch hunk ended before its declared counts")
                marker = lines[index][0]
                value = lines[index][1:]
                if marker == " ":
                    if cursor >= len(original) or original[cursor] != value:
                        raise PathPolicyError("repository patch context does not match the base")
                    output.append(value)
                    cursor += 1
                    consumed_old += 1
                    produced_new += 1
                elif marker == "-":
                    if cursor >= len(original) or original[cursor] != value:
                        raise PathPolicyError("repository patch deletion does not match the base")
                    cursor += 1
                    consumed_old += 1
                else:
                    output.append(value)
                    produced_new += 1
                index += 1
            if consumed_old != old_count or produced_new != new_count:
                raise PathPolicyError("repository patch hunk counts do not match its body")
        if not hunk_seen:
            raise PathPolicyError("repository patch file record has no hunks")
        output.extend(original[cursor:])
        if new_path is None:
            if output:
                raise PathPolicyError("deleted repository patch file retained content")
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(output), encoding="utf-8", newline="")


def build_repository_patch(
    base_repository: Path,
    candidate_repository: Path,
) -> str:
    """Build the canonical text-only patch used by reference conformance."""

    before = {
        path.relative_to(base_repository).as_posix(): path.read_bytes()
        for path in sorted(base_repository.rglob("*"))
        if path.is_file()
    }
    after = {
        path.relative_to(candidate_repository).as_posix(): path.read_bytes()
        for path in sorted(candidate_repository.rglob("*"))
        if path.is_file()
    }
    changed = sorted(
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    )
    patch, _added, _deleted = _build_patch(before, after, changed)
    return patch


def _read_tree(root: Path, contract: RepositoryWorkspaceContract) -> _TreeData:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise PathPolicyError("repository source must be a directory")
    contents: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    files: list[RepositoryFileIdentity] = []
    casefolded: dict[str, str] = {}
    inodes: set[tuple[int, int]] = set()
    total = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        parts = PurePosixPath(relative).parts
        if any(part in _FORBIDDEN_COMPONENTS for part in parts):
            raise PathPolicyError(f"forbidden repository metadata path: {relative}")
        if unicodedata.normalize("NFC", relative) != relative or any(
            ord(character) < 32 for character in relative
        ):
            raise PathPolicyError(f"repository path is not canonical Unicode text: {relative!r}")
        folded = relative.casefold()
        previous = casefolded.get(folded)
        if previous is not None and previous != relative:
            raise PathPolicyError(
                f"case-colliding repository paths are forbidden: {previous!r}, {relative!r}"
            )
        casefolded[folded] = relative
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            raise PathPolicyError(f"repository symlinks are forbidden: {relative}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise PathPolicyError(f"repository special files are forbidden: {relative}")
        inode = (metadata.st_dev, metadata.st_ino)
        if metadata.st_nlink != 1 or inode in inodes:
            raise PathPolicyError(f"repository hardlinks are forbidden: {relative}")
        inodes.add(inode)
        if metadata.st_size > contract.max_file_bytes:
            raise PathPolicyError(
                f"repository file {relative!r} exceeds {contract.max_file_bytes} bytes"
            )
        data = path.read_bytes()
        total += len(data)
        if total > contract.max_candidate_bytes:
            raise PathPolicyError(
                f"repository candidate exceeds {contract.max_candidate_bytes} bytes"
            )
        contents[relative] = data
        modes[relative] = stat.S_IMODE(metadata.st_mode)
        files.append(
            RepositoryFileIdentity(
                path=relative,
                sha256=hash_bytes(data),
                size_bytes=len(data),
            )
        )
    return _TreeData(
        snapshot=RepositorySnapshot(
            repository_hash=hash_directory(root),
            total_bytes=total,
            files=files,
        ),
        contents=contents,
        modes=modes,
    )


def _enforce_candidate_policy(
    *,
    changed: list[str],
    added: list[str],
    deleted: list[str],
    mode_changed: list[str],
    binary: list[str],
    candidate: _TreeData,
    contract: RepositoryWorkspaceContract,
) -> None:
    if len(changed) > contract.max_changed_files:
        raise PathPolicyError(
            f"repository candidate changes {len(changed)} files; "
            f"limit is {contract.max_changed_files}"
        )
    for relative in changed:
        workspace_path = f"repository/{relative}"
        if any(glob_matches(workspace_path, pattern) for pattern in contract.forbidden_globs):
            raise PathPolicyError(f"repository candidate changed a forbidden path: {relative}")
        if any(glob_matches(workspace_path, pattern) for pattern in contract.read_only_globs):
            raise PathPolicyError(f"repository candidate changed a read-only path: {relative}")
        if not any(glob_matches(workspace_path, pattern) for pattern in contract.editable_globs):
            raise PathPolicyError(f"repository candidate changed a non-editable path: {relative}")
    if added and not contract.allow_file_addition:
        raise PathPolicyError(f"repository file additions are forbidden: {added}")
    if deleted and not contract.allow_file_deletion:
        raise PathPolicyError(f"repository file deletions are forbidden: {deleted}")
    if mode_changed and not contract.allow_mode_change:
        raise PathPolicyError(f"repository mode changes are forbidden: {mode_changed}")
    if binary and not contract.allow_binary_files:
        raise PathPolicyError(f"repository binary changes are forbidden: {binary}")
    if candidate.snapshot.total_bytes > contract.max_candidate_bytes:
        raise PathPolicyError("repository candidate exceeds its total-byte limit")


def _build_patch(
    before: dict[str, bytes],
    after: dict[str, bytes],
    changed: list[str],
) -> tuple[str, int, int]:
    records: list[str] = []
    added_lines = 0
    deleted_lines = 0
    for path in changed:
        before_lines = _decode_patch_text(before.get(path, b""), path)
        after_lines = _decode_patch_text(after.get(path, b""), path)
        old_label = f"a/{path}" if path in before else "/dev/null"
        new_label = f"b/{path}" if path in after else "/dev/null"
        diff = list(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=old_label,
                tofile=new_label,
                n=3,
                lineterm="\n",
            )
        )
        if not diff:
            continue
        records.extend(diff)
        added_lines += sum(
            1 for line in diff if line.startswith("+") and not line.startswith("+++")
        )
        deleted_lines += sum(
            1 for line in diff if line.startswith("-") and not line.startswith("---")
        )
    return "".join(records), added_lines, deleted_lines


def _validate_frozen_record(
    base: _TreeData,
    candidate: _TreeData,
    patch_bytes: bytes,
    record: RepositoryCandidateRecord,
) -> None:
    if base.snapshot != record.base:
        raise ValueError("repository replay base snapshot differs from the frozen record")
    if candidate.snapshot != record.candidate:
        raise ValueError("repository replay candidate snapshot differs from the frozen record")
    if hash_bytes(patch_bytes) != record.patch.patch_hash:
        raise ValueError("repository replay patch hash differs from the frozen record")
    if (
        record.patch.base_repository_hash != base.snapshot.repository_hash
        or record.patch.candidate_repository_hash != candidate.snapshot.repository_hash
        or record.patch.reapplied_repository_hash != candidate.snapshot.repository_hash
    ):
        raise ValueError("repository replay summary hashes are internally inconsistent")
    changed = sorted(
        path
        for path in set(base.contents) | set(candidate.contents)
        if base.contents.get(path) != candidate.contents.get(path)
        or base.modes.get(path) != candidate.modes.get(path)
    )
    added = sorted(set(candidate.contents) - set(base.contents))
    deleted = sorted(set(base.contents) - set(candidate.contents))
    canonical, added_lines, deleted_lines = _build_patch(
        base.contents,
        candidate.contents,
        changed,
    )
    if canonical.encode("utf-8") != patch_bytes:
        raise ValueError("repository replay patch is not the canonical frozen diff")
    if (
        record.patch.changed_files != changed
        or record.patch.added_files != added
        or record.patch.deleted_files != deleted
        or record.patch.created_file_count != len(added)
        or record.patch.deleted_file_count != len(deleted)
        or record.patch.added_lines != added_lines
        or record.patch.deleted_lines != deleted_lines
        or record.patch.renamed_files
        or record.patch.mode_changed_files
        or record.patch.binary_files
    ):
        raise ValueError("repository replay patch statistics differ from the frozen candidate")


def _reverse_repository_patch(patch: str) -> str:
    if not patch:
        return ""
    lines = patch.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            raise PathPolicyError("repository reverse patch has an unexpected record")
        old_label = lines[index][4:].rstrip("\n")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise PathPolicyError("repository reverse patch is missing its new-file header")
        new_label = lines[index][4:].rstrip("\n")
        index += 1
        old_path = _patch_path(old_label, prefix="a/")
        new_path = _patch_path(new_label, prefix="b/")
        output.append(f"--- {'/dev/null' if new_path is None else f'a/{new_path}'}\n")
        output.append(f"+++ {'/dev/null' if old_path is None else f'b/{old_path}'}\n")
        hunk_seen = False
        while index < len(lines) and lines[index].startswith("@@ "):
            hunk_seen = True
            match = _HUNK.fullmatch(lines[index].rstrip("\n"))
            if match is None:
                raise PathPolicyError("repository reverse patch contains a malformed hunk")
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_count = int(match.group(4) or "1")
            output.append(f"@@ -{new_start},{new_count} +{old_start},{old_count} @@\n")
            index += 1
            consumed_old = 0
            produced_new = 0
            while consumed_old < old_count or produced_new < new_count:
                if index >= len(lines) or lines[index][:1] not in {" ", "+", "-"}:
                    raise PathPolicyError(
                        "repository reverse patch hunk ended before its declared counts"
                    )
                marker = lines[index][0]
                value = lines[index][1:]
                output.append(("-" if marker == "+" else "+" if marker == "-" else " ") + value)
                if marker in {" ", "-"}:
                    consumed_old += 1
                if marker in {" ", "+"}:
                    produced_new += 1
                index += 1
        if not hunk_seen:
            raise PathPolicyError("repository reverse patch record has no hunks")
    return "".join(output)


def _decode_patch_text(data: bytes, path: str) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PathPolicyError(f"repository patch cannot encode binary file: {path}") from exc
    if text and not text.endswith("\n"):
        raise PathPolicyError(f"repository text files must end with a newline: {path}")
    return text.splitlines(keepends=True)


def _read_patch_text(path: Path) -> list[str]:
    if not path.is_file() or path.is_symlink():
        raise PathPolicyError("repository patch base file is missing or unsafe")
    return _decode_patch_text(path.read_bytes(), path.as_posix())


def _patch_path(label: str, *, prefix: str) -> str | None:
    if label == "/dev/null":
        return None
    if not label.startswith(prefix):
        raise PathPolicyError("repository patch paths must use canonical a/ and b/ prefixes")
    value = label[len(prefix) :]
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or ".." in PurePosixPath(value).parts
        or PurePosixPath(value).as_posix() != value
    ):
        raise PathPolicyError("repository patch path is unsafe")
    return value


def _is_utf8_text(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


__all__ = [
    "apply_repository_patch",
    "build_repository_patch",
    "freeze_repository_candidate",
    "repository_plan_identity",
    "validate_repository_tree",
    "verify_frozen_repository_candidate",
]
