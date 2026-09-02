"""Explicit preparation of selected official HWE-Bench instances."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.plugin_api import (
    Candidate,
    ConfigurationError,
    content_hash,
    copy_tree_safely,
    hash_bytes,
    hash_directory,
)

from .models import (
    HweInstance,
    ImageLockEntryV2,
    ImageLockV2,
    LicenseFileLock,
    RepositoryProfile,
    VerifierDependencyFile,
    base_commit_marker,
    repository_profile,
)

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PATCH_SUMMARY_CREATE = re.compile(rb"^create mode ([0-7]{6}) ")
_MAX_PATCH_METADATA_BYTES = 8 * 1024 * 1024
_MAX_PATCH_PATH_BYTES = 4096


@dataclass(frozen=True)
class ReferencePatchCompatibility:
    """Content-free compatibility result for Candidate reference materialization."""

    classifier: str
    compatible: bool
    reason: str
    patch_file_count: int
    created_file_count: int
    deleted_file_count: int
    renamed_file_count: int
    copied_file_count: int
    mode_changed_file_count: int
    binary_file_count: int
    raw_output_persisted: bool
    network_accessed: bool
    docker_accessed: bool


def _has_symlink_component(root: Path, relative: str) -> bool:
    current = root
    for component in relative.split("/"):
        current /= component
        if current.is_symlink():
            return True
    return False


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _command(
    argv: list[str],
    *,
    timeout_s: int = 300,
    input_bytes: bytes | None = None,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            argv,
            input=input_bytes,
            capture_output=True,
            check=False,
            timeout=timeout_s,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError as exc:
        raise ConfigurationError(f"required executable is unavailable: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConfigurationError(f"command timed out: {argv[0]}") from exc


def _patch_compatibility_result(
    *,
    reason: str,
    patch_file_count: int = 0,
    created_file_count: int = 0,
    deleted_file_count: int = 0,
    renamed_file_count: int = 0,
    copied_file_count: int = 0,
    mode_changed_file_count: int = 0,
    binary_file_count: int = 0,
) -> ReferencePatchCompatibility:
    return ReferencePatchCompatibility(
        classifier="git-apply-metadata-v1",
        compatible=reason == "compatible",
        reason=reason,
        patch_file_count=patch_file_count,
        created_file_count=created_file_count,
        deleted_file_count=deleted_file_count,
        renamed_file_count=renamed_file_count,
        copied_file_count=copied_file_count,
        mode_changed_file_count=mode_changed_file_count,
        binary_file_count=binary_file_count,
        raw_output_persisted=False,
        network_accessed=False,
        docker_accessed=False,
    )


def _safe_patch_path(value: str) -> bool:
    encoded = value.encode("utf-8")
    return (
        bool(value)
        and len(encoded) <= _MAX_PATCH_PATH_BYTES
        and not value.startswith("/")
        and "\\" not in value
        and ".." not in value.split("/")
        and not any(character in value for character in ("\x00", "\n", "\r", "\t"))
    )


def reference_patch_compatibility(
    instance: HweInstance, *, temporary_root: Path | None = None
) -> ReferencePatchCompatibility:
    """Classify reference-patch shape without touching Docker, a repository, or the network."""

    if any(not _safe_patch_path(path) for path in instance.modified_files):
        return _patch_compatibility_result(reason="unsafe_modified_file_path")
    resolved_temporary_root: Path | None = None
    if temporary_root is not None:
        if temporary_root.is_symlink() or not temporary_root.is_dir():
            raise ConfigurationError("reference-patch temporary root is unsafe")
        resolved_temporary_root = temporary_root.resolve(strict=True)
    patch = instance.fix_patch.encode("utf-8")
    with tempfile.TemporaryDirectory(
        prefix="verigym-hwe-patch-metadata-", dir=resolved_temporary_root
    ) as temporary:
        metadata_root = Path(temporary).resolve(strict=True)
        git_environment = {
            **os.environ,
            "GIT_CEILING_DIRECTORIES": str(metadata_root.parent),
        }
        numstat = _command(
            ["git", "apply", "--numstat", "-z", "-"],
            timeout_s=60,
            input_bytes=patch,
            cwd=metadata_root,
            env=git_environment,
        )
        summary = _command(
            ["git", "apply", "--summary", "-"],
            timeout_s=60,
            input_bytes=patch,
            cwd=metadata_root,
            env=git_environment,
        )
    if (
        numstat.returncode != 0
        or summary.returncode != 0
        or len(numstat.stdout) > _MAX_PATCH_METADATA_BYTES
        or len(numstat.stderr) > _MAX_PATCH_METADATA_BYTES
        or len(summary.stdout) > _MAX_PATCH_METADATA_BYTES
        or len(summary.stderr) > _MAX_PATCH_METADATA_BYTES
    ):
        return _patch_compatibility_result(reason="malformed_patch_metadata")

    records = numstat.stdout.split(b"\0")
    if not records or records[-1] != b"":
        return _patch_compatibility_result(reason="malformed_patch_metadata")
    paths: list[str] = []
    binary_file_count = 0
    for record in records[:-1]:
        fields = record.split(b"\t", 2)
        if len(fields) != 3:
            return _patch_compatibility_result(reason="malformed_patch_metadata")
        added, deleted, raw_path = fields
        if added == b"-" or deleted == b"-":
            binary_file_count += 1
        elif not added.isdigit() or not deleted.isdigit():
            return _patch_compatibility_result(reason="malformed_patch_metadata")
        try:
            path = raw_path.decode("utf-8", errors="strict")
        except UnicodeError:
            return _patch_compatibility_result(reason="non_utf8_patch_path")
        if not _safe_patch_path(path):
            return _patch_compatibility_result(reason="unsafe_patch_path")
        paths.append(path)

    created_file_count = 0
    deleted_file_count = 0
    renamed_file_count = 0
    copied_file_count = 0
    mode_changed_file_count = 0
    non_regular_creation_count = 0
    for raw_line in summary.stdout.splitlines():
        line = raw_line.lstrip()
        create = _PATCH_SUMMARY_CREATE.match(line)
        if create is not None:
            created_file_count += 1
            if create.group(1) != b"100644":
                non_regular_creation_count += 1
        elif line.startswith(b"delete mode "):
            deleted_file_count += 1
        elif line.startswith(b"rename "):
            renamed_file_count += 1
        elif line.startswith(b"copy "):
            copied_file_count += 1
        elif line.startswith(b"mode change "):
            mode_changed_file_count += 1
        else:
            return _patch_compatibility_result(reason="unknown_patch_metadata")

    counts = {
        "patch_file_count": len(paths),
        "created_file_count": created_file_count,
        "deleted_file_count": deleted_file_count,
        "renamed_file_count": renamed_file_count,
        "copied_file_count": copied_file_count,
        "mode_changed_file_count": mode_changed_file_count,
        "binary_file_count": binary_file_count,
    }
    if len(paths) != len(set(paths)) or sorted(paths) != instance.modified_files:
        return _patch_compatibility_result(reason="modified_file_manifest_mismatch", **counts)
    if binary_file_count:
        return _patch_compatibility_result(reason="binary_patch", **counts)
    if deleted_file_count:
        return _patch_compatibility_result(reason="deleted_file", **counts)
    if renamed_file_count:
        return _patch_compatibility_result(reason="renamed_file", **counts)
    if copied_file_count:
        return _patch_compatibility_result(reason="copied_file", **counts)
    if mode_changed_file_count:
        return _patch_compatibility_result(reason="mode_change", **counts)
    if non_regular_creation_count:
        return _patch_compatibility_result(reason="non_regular_file_creation", **counts)
    return _patch_compatibility_result(reason="compatible", **counts)


def _reference_candidate_files(
    reference_repository: Path, modified_files: list[str]
) -> dict[str, str]:
    files: dict[str, str] = {}
    for relative in modified_files:
        path = reference_repository / relative
        if not path.is_file() or path.is_symlink():
            raise ConfigurationError(
                "HWE-Bench Candidate reference accepts only regular UTF-8 output files"
            )
        try:
            files[f"repository/{relative}"] = path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise ConfigurationError(
                "HWE-Bench Candidate reference accepts only regular UTF-8 output files"
            ) from exc
    return files


def _official_instances(dataset: Path, selected: set[str]) -> list[HweInstance]:
    if not dataset.is_file() or dataset.is_symlink() or dataset.stat().st_size > 512 * 1024 * 1024:
        raise ConfigurationError("official HWE-Bench JSONL path is not a bounded regular file")
    found: dict[str, HweInstance] = {}
    try:
        for line_number, line in enumerate(dataset.read_text(encoding="utf-8").splitlines(), 1):
            if not line or len(line.encode("utf-8")) > 16 * 1024 * 1024:
                raise ValueError(f"invalid official record at line {line_number}")
            row = json.loads(line, object_pairs_hook=_unique_object)
            if not isinstance(row, dict):
                raise ValueError(f"official record {line_number} is not an object")
            org = row.get("org")
            repo = row.get("repo")
            number = row.get("number")
            if not isinstance(org, str) or not isinstance(repo, str) or not isinstance(number, int):
                continue
            instance_id = f"{org}/{repo}:pr-{number}"
            if instance_id not in selected:
                continue
            base = row.get("base")
            f2p = row.get("f2p_tests")
            fix_result = row.get("fix_patch_result")
            test_result = row.get("test_patch_result")
            if not isinstance(base, dict) or not isinstance(base.get("sha"), str):
                raise ValueError(f"selected record lacks its base SHA: {instance_id}")
            if not isinstance(f2p, dict) or not f2p:
                raise ValueError(f"selected record is not an official F2P task: {instance_id}")
            if (
                not isinstance(fix_result, dict)
                or fix_result.get("failed_count") != 0
                or fix_result.get("skipped_count") != 0
                or fix_result.get("passed_count", 0) < 1
                or not isinstance(test_result, dict)
                or test_result.get("failed_count", 0) < 1
            ):
                raise ValueError(
                    f"selected record lacks official base-FAIL/fix-PASS evidence: {instance_id}"
                )
            profile = repository_profile(f"{org}/{repo}")
            found[instance_id] = HweInstance(
                org=org,
                repo=repo,
                number=number,
                title=str(row.get("title") or instance_id),
                problem_statement=str(row.get("problem_statement") or ""),
                base_commit=base["sha"],
                fix_patch=str(row.get("fix_patch") or ""),
                test_patch=str(row.get("test_patch") or ""),
                tb_script=str(row.get("tb_script") or ""),
                modified_files=list(row.get("modified_files") or []),
                expected_test_ids=sorted(str(value) for value in f2p),
                language=profile.language,
                license_id=profile.license_expression,
            )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ConfigurationError(f"could not select official HWE-Bench records: {exc}") from exc
    missing = sorted(selected - set(found))
    if missing:
        raise ConfigurationError(f"official HWE-Bench dataset lacks selected tasks: {missing}")
    return [found[instance_id] for instance_id in sorted(found)]


def load_selected_instances(dataset: Path, selected: set[str]) -> list[HweInstance]:
    """Load only explicit public instances for pre-image compatibility checks."""

    return _official_instances(dataset, selected)


def _inspect_image(reference: str, *, pull: bool) -> dict[str, Any]:
    if pull:
        pulled = _command(["docker", "pull", reference], timeout_s=3600)
        if pulled.returncode != 0:
            raise ConfigurationError(f"could not pull selected HWE-Bench image: {reference}")
    inspected = _command(["docker", "image", "inspect", reference], timeout_s=60)
    if inspected.returncode != 0:
        raise ConfigurationError(
            f"selected HWE-Bench image is not local; rerun with --pull: {reference}"
        )
    try:
        payload = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("Docker returned malformed image inspection output") from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ConfigurationError("Docker image inspection did not return one image")
    return payload[0]


def _resolve_image_identity(
    *,
    reference: str,
    image: Mapping[str, Any],
    imported_binding: Mapping[str, str] | None,
) -> tuple[str, str]:
    """Resolve a registry or independently verified daemonless-import identity."""

    image_id = image.get("Id")
    repo_digests = image.get("RepoDigests")
    if not isinstance(image_id, str) or not isinstance(repo_digests, list):
        raise ConfigurationError("selected image lacks immutable Docker identities")
    digest_values = {
        str(value).rsplit("@", 1)[1]
        for value in repo_digests
        if isinstance(value, str) and "@sha256:" in value
    }
    if imported_binding is None:
        if len(digest_values) != 1:
            raise ConfigurationError("selected image does not resolve to one manifest digest")
        return image_id, next(iter(digest_values))
    if set(imported_binding) != {"image_id", "manifest_digest"}:
        raise ConfigurationError("imported image binding is malformed")
    expected_id = imported_binding.get("image_id")
    expected_manifest = imported_binding.get("manifest_digest")
    if (
        not isinstance(expected_id, str)
        or not _SHA256_DIGEST.fullmatch(expected_id)
        or not isinstance(expected_manifest, str)
        or not _SHA256_DIGEST.fullmatch(expected_manifest)
        or image_id != expected_id
    ):
        raise ConfigurationError("imported image binding changed")
    if digest_values and digest_values != {expected_manifest}:
        raise ConfigurationError("imported image registry digest conflicts with its binding")
    return image_id, expected_manifest


def _extract_repository(
    *,
    image_id: str,
    repository_home: str,
    destination: Path,
    excluded_paths: list[str],
) -> None:
    created = _command(
        ["docker", "create", "--network", "none", "--entrypoint", "/bin/true", image_id],
        timeout_s=60,
    )
    if created.returncode != 0:
        raise ConfigurationError("could not create the selected HWE-Bench image")
    container = created.stdout.decode("utf-8", errors="replace").strip()
    try:
        copied = _command(
            ["docker", "cp", f"{container}:{repository_home}/.", str(destination)],
            timeout_s=300,
        )
        if copied.returncode != 0:
            raise ConfigurationError("could not extract the selected HWE-Bench base repository")
    finally:
        _command(["docker", "rm", "--force", container], timeout_s=60)
    metadata = destination / ".git"
    if metadata.exists():
        shutil.rmtree(metadata)
    _apply_workspace_exclusions(destination, excluded_paths)
    _materialize_internal_file_symlinks(destination)
    # VeriGym candidates are content patches, not mode patches. Normalize the extracted Docker
    # tree before hashing so safe workspace copies reproduce an empty candidate exactly.
    for path in sorted(destination.rglob("*")):
        mode = path.lstat().st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ConfigurationError(
                "selected HWE-Bench base repository contains a special filesystem entry"
            )
        os.chmod(path, 0o755 if path.is_dir() else 0o644)


def _apply_workspace_exclusions(repository: Path, excluded_paths: list[str]) -> None:
    root = repository.resolve(strict=True)
    for relative in excluded_paths:
        excluded = repository / relative
        resolved = excluded.resolve(strict=False)
        if excluded.is_symlink() or not resolved.is_relative_to(root):
            raise ConfigurationError(
                f"repository profile exclusion is missing or unsafe: {relative}"
            )
        # Profiles describe paths that must never reach the agent workspace. Older repository
        # snapshots may predate a generated build directory, in which case absence already
        # satisfies the exclusion. Existing non-directory nodes remain fail-closed.
        if not excluded.exists():
            continue
        if not excluded.is_dir():
            raise ConfigurationError(
                f"repository profile exclusion is missing or unsafe: {relative}"
            )
        shutil.rmtree(excluded)


def _materialize_internal_file_symlinks(repository: Path) -> None:
    """Replace bounded internal file links with ordinary files for safe agent workspaces."""

    root = repository.resolve(strict=True)
    for path in sorted(repository.rglob("*")):
        if not path.is_symlink():
            continue
        raw_target = os.readlink(path)
        unresolved = Path(raw_target)
        target = (unresolved if unresolved.is_absolute() else path.parent / unresolved).resolve(
            strict=False
        )
        if not target.is_relative_to(root):
            raise ConfigurationError(
                "selected HWE-Bench base repository contains an escaping symlink"
            )
        try:
            target = path.resolve(strict=True)
        except FileNotFoundError:
            # Some upstream repositories intentionally retain dangling source-tree links. Keep
            # their tracked Git blob as a plain file so the safe workspace remains deterministic.
            path.unlink()
            path.write_bytes(os.fsencode(raw_target))
            continue
        except (OSError, RuntimeError) as exc:
            raise ConfigurationError(
                "selected HWE-Bench base repository contains a broken symlink"
            ) from exc
        if not stat.S_ISREG(target.stat().st_mode):
            raise ConfigurationError(
                "selected HWE-Bench base repository contains a non-file symlink"
            )
        content = target.read_bytes()
        path.unlink()
        path.write_bytes(content)


def _image_baseline(
    *,
    image_id: str,
    repository_home: str,
    base_commit: str,
    marker: str | None = None,
    baseline_identity_policy: str = "official_base_or_bound_synthetic",
) -> str:
    """Read the runtime baseline and bind a synthetic baseline to the official PR base."""

    marker = marker or base_commit_marker(repository_home)
    checked = _command(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--entrypoint",
            "/bin/cat",
            image_id,
            marker,
        ],
        timeout_s=60,
    )
    observed = checked.stdout.decode("utf-8", errors="replace").strip()
    if checked.returncode != 0 or not _COMMIT.fullmatch(observed):
        raise ConfigurationError("selected HWE-Bench image lacks a valid runtime base commit")
    if observed == base_commit:
        return observed
    provenance_path = f"{repository_home}/.baseline_commit"
    provenance = _command(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--entrypoint",
            "/bin/cat",
            image_id,
            provenance_path,
        ],
        timeout_s=60,
    )
    prepared_from = provenance.stdout.decode("utf-8", errors="replace").strip()
    if provenance.returncode == 0 and prepared_from == base_commit:
        return observed
    if baseline_identity_policy == "digest_locked_runtime_marker":
        return observed
    if baseline_identity_policy == "official_base_or_bound_synthetic":
        raise ConfigurationError(
            "selected HWE-Bench synthetic runtime baseline is not bound to the official base"
        )
    raise ConfigurationError("selected HWE-Bench profile has an unsupported baseline policy")


def prepare_source(
    *,
    dataset: Path,
    output: Path,
    selected_tasks: list[str],
    pull: bool = False,
    official_dataset_revision: str | None = None,
    official_source_commit: str | None = None,
    verifier_cache: Path | None = None,
    imported_image_bindings: Mapping[str, Mapping[str, str]] | None = None,
) -> Path:
    """Prepare only explicitly selected tasks; never infer or pull a full repository set."""

    if not selected_tasks or len(selected_tasks) > 32:
        raise ConfigurationError("prepare-source requires between 1 and 32 explicit --task values")
    if len(selected_tasks) != len(set(selected_tasks)):
        raise ConfigurationError("prepare-source task selection contains duplicates")
    output = output.expanduser().resolve(strict=False)
    if output.exists() or output.is_symlink():
        raise ConfigurationError("prepare-source output already exists")
    dataset = dataset.expanduser().resolve(strict=True)
    instances = _official_instances(dataset, set(selected_tasks))
    for instance in instances:
        compatibility = reference_patch_compatibility(instance)
        if not compatibility.compatible:
            raise ConfigurationError(
                "HWE-Bench reference patch is incompatible with Candidate materialization: "
                f"{compatibility.reason}"
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    expected_image_references = {
        (f"ghcr.io/pku-liang/{instance.org.lower()}_m_{instance.repo.lower()}:pr-{instance.number}")
        for instance in instances
    }
    if imported_image_bindings is not None:
        if pull:
            raise ConfigurationError("imported image bindings cannot accompany Docker pulls")
        if set(imported_image_bindings) != expected_image_references:
            raise ConfigurationError("imported image bindings do not match selected tasks")
    resolved_verifier_cache: Path | None = None
    if verifier_cache is not None:
        if verifier_cache.is_symlink():
            raise ConfigurationError("verifier cache root may not be a symlink")
        resolved_verifier_cache = verifier_cache.expanduser().resolve(strict=True)
        if not resolved_verifier_cache.is_dir():
            raise ConfigurationError("verifier cache root must be a directory")
    entries: list[ImageLockEntryV2] = []
    with tempfile.TemporaryDirectory(prefix="verigym-hwe-prepare-", dir=output.parent) as temporary:
        prepared = Path(temporary) / "prepared"
        (prepared / "workspaces").mkdir(parents=True)
        for instance in instances:
            try:
                profile = repository_profile(instance.repository_id)
            except ValueError as exc:
                raise ConfigurationError(str(exc)) from exc
            repository_home = profile.repository_home
            reference = (
                f"ghcr.io/pku-liang/{instance.org.lower()}_m_{instance.repo.lower()}:"
                f"pr-{instance.number}"
            )
            image = _inspect_image(reference, pull=pull)
            image_id, manifest_digest = _resolve_image_identity(
                reference=reference,
                image=image,
                imported_binding=(
                    imported_image_bindings.get(reference)
                    if imported_image_bindings is not None
                    else None
                ),
            )
            runtime_base_commit = _image_baseline(
                image_id=image_id,
                repository_home=repository_home,
                base_commit=instance.base_commit,
                marker=profile.base_commit_marker,
                baseline_identity_policy=profile.baseline_identity_policy,
            )
            workspace = prepared / "workspaces" / instance.slug
            repository = workspace / "repository"
            repository.mkdir(parents=True)
            _extract_repository(
                image_id=image_id,
                repository_home=repository_home,
                destination=repository,
                excluded_paths=profile.workspace_excluded_paths,
            )
            repository_hash = hash_directory(repository)
            license_inventory = _license_inventory(repository, profile)
            verifier_dependencies = _prepare_verifier_dependencies(
                cache_root=resolved_verifier_cache,
                prepared_root=prepared,
                instance=instance,
                profile=profile,
            )
            (workspace / "TASK.md").write_text(
                f"# {instance.title}\n\n{instance.problem_statement.rstrip()}\n",
                encoding="utf-8",
            )
            (workspace / "PUBLIC_TESTS.md").write_text(
                "# Public tests\n\nThis HWE-Bench task has no public test interface. "
                "Final scoring uses a hidden, digest-locked verifier.\n",
                encoding="utf-8",
            )
            with tempfile.TemporaryDirectory(
                prefix="verigym-hwe-reference-build-", dir=output.parent
            ) as reference_temporary:
                reference_repository = Path(reference_temporary) / "repository"
                copy_tree_safely(repository, reference_repository)
                try:
                    applied = subprocess.run(
                        ["git", "apply", "--whitespace=nowarn", "-"],
                        cwd=reference_repository,
                        input=instance.fix_patch.encode("utf-8"),
                        capture_output=True,
                        check=False,
                        timeout=60,
                    )
                except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                    raise ConfigurationError(
                        "could not apply the official HWE-Bench reference patch"
                    ) from exc
                if applied.returncode != 0:
                    raise ConfigurationError("official HWE-Bench reference patch does not apply")
                reference_candidate = Candidate(
                    files=_reference_candidate_files(reference_repository, instance.modified_files),
                    label="official-reference-conformance-only",
                )
                reference_repository_hash = hash_directory(reference_repository)
            task_bundle_identity: dict[str, object] = {
                "instance": instance,
                "repository_hash": repository_hash,
                "image_id": image_id,
                "manifest_digest": manifest_digest,
                "repository_profile_hash": profile.profile_hash,
                "license_inventory": license_inventory,
                "verifier_dependencies": verifier_dependencies,
            }
            if runtime_base_commit != instance.base_commit:
                task_bundle_identity["runtime_base_commit"] = runtime_base_commit
            task_bundle_hash = content_hash(task_bundle_identity)
            entries.append(
                ImageLockEntryV2(
                    instance_id=instance.instance_id,
                    slug=instance.slug,
                    image_reference=reference,
                    manifest_digest=manifest_digest,
                    image_id=image_id,
                    repository_home=repository_home,
                    base_commit_marker=profile.base_commit_marker,
                    base_commit=runtime_base_commit,
                    repository_hash=repository_hash,
                    reference_repository_hash=reference_repository_hash,
                    reference_candidate_hash=content_hash(reference_candidate),
                    reference_patch_hash=hash_bytes(instance.fix_patch.encode("utf-8")),
                    verifier_payload_hash=content_hash(
                        {
                            "test_patch": instance.test_patch,
                            "tb_script": instance.tb_script,
                            "expected_test_ids": instance.expected_test_ids,
                            "semantics": "all_tests_pass",
                        }
                    ),
                    task_bundle_hash=task_bundle_hash,
                    repository_profile_hash=profile.profile_hash,
                    license_inventory=license_inventory,
                    verifier_dependencies=verifier_dependencies,
                )
            )
        records = "".join(
            json.dumps(instance.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) + "\n"
            for instance in instances
        )
        (prepared / "instances.jsonl").write_text(records, encoding="utf-8")
        lock = ImageLockV2(
            official_dataset_sha256=hash_bytes(dataset.read_bytes()),
            official_dataset_revision=official_dataset_revision,
            official_source_commit=official_source_commit,
            entries=entries,
        )
        (prepared / "image-lock.json").write_text(
            lock.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        os.replace(prepared, output)
    return output


def _license_inventory(repository: Path, profile: RepositoryProfile) -> list[LicenseFileLock]:
    inventory: list[LicenseFileLock] = []
    for relative in profile.license_files:
        license_path = repository / relative
        if license_path.is_symlink() or not license_path.is_file():
            raise ConfigurationError(
                f"selected base repository lacks declared license file: {relative}"
            )
        inventory.append(
            LicenseFileLock(path=relative, sha256=hash_bytes(license_path.read_bytes()))
        )
    return inventory


def _prepare_verifier_dependencies(
    *,
    cache_root: Path | None,
    prepared_root: Path,
    instance: HweInstance,
    profile: RepositoryProfile,
) -> list[VerifierDependencyFile]:
    dependencies = [item.model_copy(deep=True) for item in profile.verifier_dependencies]
    if not dependencies:
        return []
    if cache_root is None:
        raise ConfigurationError(
            f"repository profile requires an explicit verifier cache: {instance.repository_id}"
        )
    destination_root = prepared_root / "verifier-dependencies" / instance.slug
    for dependency in dependencies:
        source = cache_root / dependency.cache_path
        try:
            resolved = source.resolve(strict=True)
        except OSError as exc:
            raise ConfigurationError(
                f"verifier cache lacks a required file: {dependency.cache_path}"
            ) from exc
        if (
            _has_symlink_component(cache_root, dependency.cache_path)
            or not resolved.is_relative_to(cache_root)
            or not resolved.is_file()
            or resolved.stat().st_size != dependency.size_bytes
            or hash_bytes(resolved.read_bytes()) != dependency.sha256
        ):
            raise ConfigurationError(
                f"verifier cache dependency differs from its profile: {dependency.cache_path}"
            )
        destination = destination_root / dependency.cache_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(resolved, destination)
        os.chmod(destination, 0o644)
    return dependencies


__all__ = [
    "load_selected_instances",
    "prepare_source",
    "reference_patch_compatibility",
]
