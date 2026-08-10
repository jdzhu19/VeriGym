"""Explicit preparation of selected official HWE-Bench instances."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
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

from .models import HweInstance, ImageLock, ImageLockEntry

_REPOSITORY_HOMES = {"lowRISC/ibex": "/home/ibex"}


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
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            argv,
            input=input_bytes,
            capture_output=True,
            check=False,
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise ConfigurationError(f"required executable is unavailable: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConfigurationError(f"command timed out: {argv[0]}") from exc


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
            )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ConfigurationError(f"could not select official HWE-Bench records: {exc}") from exc
    missing = sorted(selected - set(found))
    if missing:
        raise ConfigurationError(f"official HWE-Bench dataset lacks selected tasks: {missing}")
    return [found[instance_id] for instance_id in sorted(found)]


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


def _extract_repository(*, image_id: str, repository_home: str, destination: Path) -> None:
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
    # VeriGym candidates are content patches, not mode patches. Normalize the extracted Docker
    # tree before hashing so safe workspace copies reproduce an empty candidate exactly.
    for path in sorted(destination.rglob("*")):
        if path.is_symlink():
            raise ConfigurationError("selected HWE-Bench base repository contains a symlink")
        os.chmod(path, 0o755 if path.is_dir() else 0o644)


def _check_image_baseline(*, image_id: str, repository_home: str, base_commit: str) -> None:
    if repository_home != "/home/ibex":
        raise ConfigurationError("initial executable HWE-Bench profile currently supports Ibex")
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
            "/home/ibex_base_commit.txt",
        ],
        timeout_s=60,
    )
    observed = checked.stdout.decode("utf-8", errors="replace").strip()
    if checked.returncode != 0 or observed != base_commit:
        raise ConfigurationError("selected HWE-Bench image has an unexpected base commit")


def prepare_source(
    *,
    dataset: Path,
    output: Path,
    selected_tasks: list[str],
    pull: bool = False,
    official_source_commit: str | None = None,
) -> Path:
    """Prepare only explicitly selected tasks; never infer or pull a full repository set."""

    if not selected_tasks or len(selected_tasks) > 32:
        raise ConfigurationError("prepare-source requires between 1 and 32 explicit --task values")
    if len(selected_tasks) != len(set(selected_tasks)):
        raise ConfigurationError("prepare-source task selection contains duplicates")
    output = output.expanduser().resolve(strict=False)
    if output.exists() or output.is_symlink():
        raise ConfigurationError("prepare-source output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    dataset = dataset.expanduser().resolve(strict=True)
    instances = _official_instances(dataset, set(selected_tasks))
    entries: list[ImageLockEntry] = []
    with tempfile.TemporaryDirectory(prefix="verigym-hwe-prepare-", dir=output.parent) as temporary:
        prepared = Path(temporary) / "prepared"
        (prepared / "workspaces").mkdir(parents=True)
        for instance in instances:
            repository_key = f"{instance.org}/{instance.repo}"
            try:
                repository_home = _REPOSITORY_HOMES[repository_key]
            except KeyError as exc:
                raise ConfigurationError(
                    f"initial HWE-Bench adapter has no executable profile for {repository_key}"
                ) from exc
            reference = (
                f"ghcr.io/pku-liang/{instance.org.lower()}_m_{instance.repo.lower()}:"
                f"pr-{instance.number}"
            )
            image = _inspect_image(reference, pull=pull)
            image_id = image.get("Id")
            repo_digests = image.get("RepoDigests")
            if not isinstance(image_id, str) or not isinstance(repo_digests, list):
                raise ConfigurationError("selected image lacks immutable Docker identities")
            digest_values = [
                str(value).rsplit("@", 1)[1]
                for value in repo_digests
                if isinstance(value, str) and "@sha256:" in value
            ]
            if len(set(digest_values)) != 1:
                raise ConfigurationError("selected image does not resolve to one manifest digest")
            manifest_digest = digest_values[0]
            _check_image_baseline(
                image_id=image_id,
                repository_home=repository_home,
                base_commit=instance.base_commit,
            )
            workspace = prepared / "workspaces" / instance.slug
            repository = workspace / "repository"
            repository.mkdir(parents=True)
            _extract_repository(
                image_id=image_id,
                repository_home=repository_home,
                destination=repository,
            )
            repository_hash = hash_directory(repository)
            license_path = repository / "LICENSE"
            if not license_path.is_file():
                raise ConfigurationError("selected base repository lacks its declared LICENSE")
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
                for path in instance.modified_files:
                    if (
                        not (repository / path).is_file()
                        or not (reference_repository / path).is_file()
                    ):
                        raise ConfigurationError(
                            "initial HWE-Bench profile accepts only in-place text reference edits"
                        )
                reference_candidate = Candidate(
                    files={
                        f"repository/{path}": (reference_repository / path).read_text(
                            encoding="utf-8"
                        )
                        for path in instance.modified_files
                        if (reference_repository / path).is_file()
                    },
                    label="official-reference-conformance-only",
                )
                reference_repository_hash = hash_directory(reference_repository)
            task_bundle_hash = content_hash(
                {
                    "instance": instance,
                    "repository_hash": repository_hash,
                    "image_id": image_id,
                    "manifest_digest": manifest_digest,
                }
            )
            entries.append(
                ImageLockEntry(
                    instance_id=instance.instance_id,
                    slug=instance.slug,
                    image_reference=reference,
                    manifest_digest=manifest_digest,
                    image_id=image_id,
                    repository_home=repository_home,
                    base_commit=instance.base_commit,
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
                    license_file_hash=hash_bytes(license_path.read_bytes()),
                )
            )
        records = "".join(
            json.dumps(instance.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) + "\n"
            for instance in instances
        )
        (prepared / "instances.jsonl").write_text(records, encoding="utf-8")
        lock = ImageLock(
            official_dataset_sha256=hash_bytes(dataset.read_bytes()),
            official_source_commit=official_source_commit,
            entries=entries,
        )
        (prepared / "image-lock.json").write_text(
            lock.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        os.replace(prepared, output)
    return output


__all__ = ["prepare_source"]
