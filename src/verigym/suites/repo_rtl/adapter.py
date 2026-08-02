"""Adapter for strict Apache-2.0 synthetic repository repair tasks."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.loaders import load_model
from verigym.core.repository_candidate import (
    apply_repository_patch,
    freeze_repository_candidate,
    validate_repository_tree,
    verify_frozen_repository_candidate,
)
from verigym.core.workspace import copy_tree_safely, glob_matches
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import SuiteDescriptor, ToolchainProfile
from verigym.schemas.evolution import AgentVersionManifest
from verigym.schemas.repository import RepositoryCandidateRecord, RepositoryTaskManifest
from verigym.schemas.runtime import SessionReadOnlyMount
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.schemas.task import (
    Candidate,
    ConformanceCase,
    ResolvedTaskAssets,
    TaskRef,
    ValidationIssue,
    ValidationReport,
    VeriTask,
)
from verigym.suites.base import SuiteAdapter

_MAX_BUNDLE_FILES = 2048
_MAX_BUNDLE_FILE_BYTES = 8 * 1024 * 1024
_MAX_BUNDLE_BYTES = 32 * 1024 * 1024
_HELDOUT_GRANT_ENV = "VERIGYM_M10B_HELDOUT_AGENT_VERSION_MANIFEST"


class RepositoryRtlSuite(SuiteAdapter):
    """Package-backed generic repository repair fixtures."""

    _PACKAGED_ASSETS_ROOT = Path(__file__).parent / "assets"
    _EXPECTED_PACKAGED_TASK_IDS = frozenset(
        {
            "repo-rtl/arbiter-reset-recovery",
            "repo-rtl/counter-wrap",
            "repo-rtl/pipeline-stall-backpressure",
        }
    )
    _SOURCE_VARIANT = "repo-rtl-v1"
    _SOURCE_ROOT_LABEL = "<external-repo-rtl-source>"
    _NATIVE_LAYOUT = "repo_rtl_task_bundles_v1"
    _HELDOUT_ASSETS_ROOT: Path | None = Path(__file__).parent / "heldout_assets"

    descriptor = SuiteDescriptor(
        schema_version=SCHEMA_VERSION,
        name="repo-rtl",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[
            "repository_repair",
            "multi_file_patch",
            "trusted_public_tests",
            "hidden_regression",
            "conformance",
        ],
        title="VeriGym repository-level RTL repair",
        description="Strict multi-file RTL repository repair tasks with isolated public tests.",
        suite_version="0.1.0",
        license="Apache-2.0",
    )

    def __init__(self, source_config: SuiteSourceConfig | None = None) -> None:
        self._source_config = source_config
        self._snapshot_cache: SuiteSourceSnapshot | None = None
        self._heldout_agent_version: AgentVersionManifest | None = None
        assets = (
            self._PACKAGED_ASSETS_ROOT
            if source_config is None
            else self._external_tasks_root(source_config.source_root)
        )
        self._task_roots = {
            task_id: root
            for task_id, root in self._discover_roots(assets).items()
            if task_id.startswith(f"{self.descriptor.name}/")
        }
        if not self._task_roots:
            raise ConfigurationError(
                f"{self.descriptor.name} source contains no matching task bundles"
            )
        if source_config is None and self._HELDOUT_ASSETS_ROOT is not None:
            self._load_heldout_after_version_freeze()
        self._visible_temporaries: list[tempfile.TemporaryDirectory[str]] = []

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        if source_root is not None:
            return self.with_source(SuiteSourceConfig(source_root=source_root)).discover()
        return [
            TaskRef(
                id=task_id,
                suite=self.descriptor.name,
                native_id=task_id.split("/", 1)[1],
                source_root=(
                    str(self._source_config.source_root)
                    if self._source_config is not None
                    else None
                ),
            )
            for task_id in sorted(self._task_roots)
        ]

    def load_task(self, ref: TaskRef) -> VeriTask:
        root = self._root_for(ref.id)
        manifest = load_model(root / "task.yaml", RepositoryTaskManifest)
        self._validate_task_root(root, manifest)
        task = manifest.task.model_copy(deep=True)
        if task.id != ref.id:
            raise ConfigurationError("repository task ID differs from its discovered identity")
        task.source.content_hash = manifest.source.repository_hash
        task.metadata["repository_repair"] = {
            "manifest_hash": content_hash(manifest),
            "task_bundle_hash": manifest.source.task_bundle_hash,
            "source_identity_hash": content_hash(manifest.source),
            "license_file_hash": manifest.source.license_file_hash,
            "base_repository_hash": manifest.source.repository_hash,
            "issue_hash": manifest.issue_hash,
            "public_assets_hash": manifest.public_tests.public_assets_hash,
            "public_mount_hash": hash_directory(root / "public"),
            "public_test_ids": sorted(test.id for test in manifest.public_tests.tests),
            "hidden_verifier_hash": manifest.verification.hidden_verifier_hash,
            "reference_candidate_hash": manifest.verification.reference_candidate_hash,
            "reference_patch_hash": manifest.verification.reference_patch_hash,
            "workspace_contract": manifest.workspace.model_dump(mode="json"),
        }
        if self._heldout_agent_version is not None and "m10b_split" in task.metadata:
            task.metadata["repository_repair"]["heldout_access_agent_version_hash"] = (
                self._heldout_agent_version.version_hash
            )
        return task

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        root = self._root_for(task.id)
        manifest = load_model(root / "task.yaml", RepositoryTaskManifest)
        self._validate_task_root(root, manifest)
        temporary = tempfile.TemporaryDirectory(prefix="verigym-repo-rtl-visible-")
        visible = Path(temporary.name).resolve()
        (visible / "repository").mkdir()
        copy_tree_safely(root / "repository", visible / "repository")
        (visible / "TASK.md").write_bytes((root / manifest.issue_file).read_bytes())
        public_lines = [
            "# Public test interface",
            "",
            "List tests with `verigym-public-test list`.",
            "Run one test with `verigym-public-test run <test-id>`.",
            "",
            "Available IDs:",
            "",
            *(f"- `{test.id}`: {test.title}" for test in manifest.public_tests.tests),
            "",
            "The launcher and public assets are trusted and read-only.",
        ]
        (visible / "PUBLIC_TESTS.md").write_text(
            "\n".join(public_lines) + "\n",
            encoding="utf-8",
        )
        self._visible_temporaries.append(temporary)
        return ResolvedTaskAssets(
            visible_root=str(visible),
            hidden_roots=[str((root / "hidden").resolve(strict=True))],
            read_only_mounts=[
                SessionReadOnlyMount(
                    source_dir=str((root / "public").resolve(strict=True)),
                    destination="/verigym-public",
                    content_hash=hash_directory(root / "public"),
                    label="public_tests",
                )
            ],
        )

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        if source_root is not None:
            return self.with_source(SuiteSourceConfig(source_root=source_root)).validate_source()
        issues: list[ValidationIssue] = []
        expected = set(self._EXPECTED_PACKAGED_TASK_IDS)
        if self._heldout_agent_version is not None:
            expected.update(
                {
                    "repo-rtl/arbiter-rotating-priority-heldout",
                    "repo-rtl/counter-load-wrap-heldout",
                    "repo-rtl/pipeline-flush-heldout",
                }
            )
        if self._source_config is None and set(self._task_roots) != expected:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="task_set",
                    message=(
                        "repo-rtl task set differs from the frozen training set plus any "
                        "version-gated held-out set"
                    ),
                )
            )
        for task_id, root in sorted(self._task_roots.items()):
            try:
                manifest = load_model(root / "task.yaml", RepositoryTaskManifest)
                self._validate_task_root(root, manifest)
                if manifest.task.id != task_id:
                    raise ConfigurationError("manifest task ID differs from its fixture directory")
            except Exception as exc:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="task_invalid",
                        message=str(exc),
                        relative_path=f"{root.name}/task.yaml",
                    )
                )
        return ValidationReport(
            valid=not issues,
            errors=[issue.message for issue in issues],
            issues=issues,
        )

    def with_source(self, config: SuiteSourceConfig) -> RepositoryRtlSuite:
        if config.variant not in {None, self._SOURCE_VARIANT}:
            raise ConfigurationError(
                f"{self.descriptor.name} supports only the {self._SOURCE_VARIANT} source layout"
            )
        return self.__class__(config)

    def source_snapshot(self) -> SuiteSourceSnapshot | None:
        if self._source_config is None:
            return None
        if self._snapshot_cache is None:
            root = self._source_config.source_root.resolve(strict=True)
            tasks_root = self._external_tasks_root(root)
            self._snapshot_cache = SuiteSourceSnapshot(
                source_root=self._SOURCE_ROOT_LABEL,
                dataset_root="tasks",
                variant=self._SOURCE_VARIANT,
                native_layout=self._NATIVE_LAYOUT,
                strict_compatibility=self._source_config.strict_compatibility,
                configuration_fingerprint=content_hash(
                    {
                        "source_content_hash": hash_directory(root),
                        "variant": self._source_config.variant or self._SOURCE_VARIANT,
                        "strict_compatibility": self._source_config.strict_compatibility,
                    }
                ),
                dataset_content_hash=hash_directory(tasks_root),
                license_id=None,
                license_file_hash=None,
                git_commit=None,
                git_remote=None,
                git_metadata_available=False,
                synthetic_fixture=False,
            )
        return self._snapshot_cache

    def reference_solution(self, task: VeriTask) -> Candidate | None:
        root = self._root_for(task.id)
        base = root / "repository"
        reference = root / "reference" / "repository"
        files: dict[str, str] = {}
        for path in sorted(reference.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(reference)
            base_path = base / relative
            if not base_path.is_file() or base_path.read_bytes() != path.read_bytes():
                files[f"repository/{relative.as_posix()}"] = path.read_text(encoding="utf-8")
        return Candidate(files=files, label="reference-conformance-only")

    def conformance_cases(self) -> Iterable[ConformanceCase]:
        for task_id in sorted(self._task_roots):
            task = self.load_task(
                TaskRef(id=task_id, suite=self.descriptor.name, native_id=task_id)
            )
            reference = self.reference_solution(task)
            assert reference is not None
            yield ConformanceCase(
                name=f"{task_id.split('/', 1)[1]}-reference",
                candidate=reference,
                expected_resolved=True,
            )

    def repository_manifest(self, task: VeriTask) -> RepositoryTaskManifest:
        root = self._root_for(task.id)
        manifest = load_model(root / "task.yaml", RepositoryTaskManifest)
        self._validate_task_root(root, manifest)
        return manifest

    def base_repository(self, task: VeriTask) -> Path:
        return (self._root_for(task.id) / "repository").resolve(strict=True)

    def toolchain_profile(self, runtime: object, tools: object) -> ToolchainProfile | None:
        del runtime, tools
        return None

    def freeze_repository_candidate(
        self,
        *,
        task: VeriTask,
        candidate_dir: Path,
        run_root: Path,
        artifact_root: Path,
    ) -> RepositoryCandidateRecord | None:
        manifest = self.repository_manifest(task)
        repository = candidate_dir / manifest.workspace.repository_root
        if not repository.is_dir():
            raise ConfigurationError("repository candidate is missing repository/")
        return freeze_repository_candidate(
            task_id=task.id,
            base_repository=self.base_repository(task),
            candidate_repository=repository,
            contract=manifest.workspace,
            public_test_ids=[test.id for test in manifest.public_tests.tests],
            run_root=run_root,
            artifact_root=artifact_root,
        )

    def replay_repository_candidate(
        self,
        *,
        task: VeriTask,
        candidate_dir: Path,
        run_root: Path,
        record: RepositoryCandidateRecord,
    ) -> None:
        manifest = self.repository_manifest(task)
        verify_frozen_repository_candidate(
            base_repository=self.base_repository(task),
            candidate_repository=candidate_dir / manifest.workspace.repository_root,
            patch_file=run_root / "repository.patch",
            record=record,
            contract=manifest.workspace,
        )

    def _root_for(self, task_id: str) -> Path:
        try:
            return self._task_roots[task_id]
        except KeyError as exc:
            raise KeyError(f"unknown {self.descriptor.name} task: {task_id}") from exc

    def _load_heldout_after_version_freeze(self) -> None:
        """Expose packaged held-out assets only after a frozen v1 grant is validated."""

        raw = os.environ.get(_HELDOUT_GRANT_ENV)
        if raw is None:
            return
        grant_path = Path(raw)
        if not grant_path.is_absolute():
            raise ConfigurationError(f"{_HELDOUT_GRANT_ENV} must be an absolute path")
        self._reject_symlink_components(grant_path)
        resolved = grant_path.resolve(strict=True)
        mode = resolved.stat().st_mode
        if not stat.S_ISREG(mode) or resolved.stat().st_size > 256 * 1024:
            raise ConfigurationError("M10B held-out grant must be a bounded regular file")
        version = load_model(resolved, AgentVersionManifest)
        from verigym.evolution.memory import validate_agent_version

        validate_agent_version(version)
        if (
            version.update_type != "context_memory"
            or not version.executable_in_m10b
            or version.memory_pack_hash is None
            or version.parent_version_hash is None
        ):
            raise ConfigurationError(
                "M10B held-out access requires a frozen executable context-memory version"
            )
        heldout = self._HELDOUT_ASSETS_ROOT
        assert heldout is not None
        roots = self._discover_roots(heldout)
        overlap = set(roots).intersection(self._task_roots)
        if overlap:
            raise ConfigurationError(f"M10B held-out task identities overlap: {sorted(overlap)}")
        self._task_roots.update(roots)
        self._heldout_agent_version = version

    def _validate_task_root(
        self,
        root: Path,
        manifest: RepositoryTaskManifest,
    ) -> None:
        self._validate_bundle_files(root)
        required = [
            root / "task.yaml",
            root / "LICENSE",
            root / manifest.issue_file,
            root / "repository",
            root / "public" / manifest.public_tests.contract_file,
            root / "public" / "assets",
            root / "hidden",
            root / "reference" / "repository",
            root / "reference" / "reference.patch",
        ]
        missing = [path.relative_to(root).as_posix() for path in required if not path.exists()]
        if missing:
            raise ConfigurationError(f"repository task assets are missing: {missing}")
        issue = (root / manifest.issue_file).read_bytes()
        if hash_bytes(issue) != manifest.issue_hash:
            raise ConfigurationError("repository task issue identity changed")
        if hash_directory(root / "repository") != manifest.source.repository_hash:
            raise ConfigurationError("repository task base snapshot identity changed")
        if hash_directory(root, excluded_names={"task.yaml"}) != manifest.source.task_bundle_hash:
            raise ConfigurationError("repository task-bundle identity changed")
        expected_source_kind = "package_resource" if self._source_config is None else "user_path"
        if manifest.source.source_kind != expected_source_kind:
            raise ConfigurationError(
                f"repository task source_kind must be {expected_source_kind!r}"
            )
        license_path = root / "repository" / manifest.source.license_file
        if not license_path.is_file():
            raise ConfigurationError("repository task source license file is missing")
        if hash_bytes(license_path.read_bytes()) != manifest.source.license_file_hash:
            raise ConfigurationError("repository task source license identity changed")
        if (root / "LICENSE").read_bytes() != license_path.read_bytes():
            raise ConfigurationError("task-bundle and visible repository licenses differ")
        validate_repository_tree(root / "repository", manifest.workspace)
        self._validate_visible_path_classes(root / "repository", manifest)
        public_contract = json.loads(
            (root / "public" / manifest.public_tests.contract_file).read_text(encoding="utf-8")
        )
        if public_contract != manifest.public_tests.model_dump(mode="json"):
            raise ConfigurationError("public-test launcher contract differs from task manifest")
        public_hash = hash_directory(
            root / "public",
            excluded_names={manifest.public_tests.contract_file},
        )
        if public_hash != manifest.public_tests.public_assets_hash:
            raise ConfigurationError("repository task public-test asset identity changed")
        for relative, expected in manifest.public_tests.asset_files.items():
            path = root / "public" / relative
            if not path.is_file() or hash_bytes(path.read_bytes()) != expected:
                raise ConfigurationError(f"public-test file identity changed: {relative}")
        if hash_directory(root / "hidden") != manifest.verification.hidden_verifier_hash:
            raise ConfigurationError("repository hidden-verifier identity changed")
        reference = root / "reference" / "repository"
        validate_repository_tree(reference, manifest.workspace)
        if hash_directory(reference) != manifest.verification.reference_candidate_hash:
            raise ConfigurationError("repository reference candidate identity changed")
        reference_patch = root / "reference" / "reference.patch"
        if hash_bytes(reference_patch.read_bytes()) != manifest.verification.reference_patch_hash:
            raise ConfigurationError("repository reference patch identity changed")
        with tempfile.TemporaryDirectory(prefix="verigym-repo-reference-conformance-") as temporary:
            staged = Path(temporary) / "repository"
            copy_tree_safely(root / "repository", staged)
            apply_repository_patch(staged, reference_patch.read_text(encoding="utf-8"))
            if hash_directory(staged) != manifest.verification.reference_candidate_hash:
                raise ConfigurationError(
                    "repository reference patch does not reproduce the reference candidate"
                )

    @staticmethod
    def _external_tasks_root(source_root: Path) -> Path:
        raw_root = source_root.expanduser()
        RepositoryRtlSuite._reject_symlink_components(raw_root)
        root = raw_root.resolve(strict=True)
        tasks = root / "tasks"
        selected = tasks if tasks.is_dir() else root
        RepositoryRtlSuite._reject_symlink_components(selected)
        if not selected.is_dir():
            raise ConfigurationError("repo-rtl external source must contain a tasks directory")
        return selected

    @staticmethod
    def _discover_roots(tasks_root: Path) -> dict[str, Path]:
        roots: dict[str, Path] = {}
        for path in sorted(tasks_root.iterdir()):
            if path.is_symlink():
                raise ConfigurationError("repo-rtl task roots may not be symlinks")
            if not path.is_dir() or path.name.startswith("."):
                continue
            manifest_path = path / "task.yaml"
            if not manifest_path.is_file():
                continue
            try:
                payload = load_model(manifest_path, RepositoryTaskManifest)
            except Exception as exc:
                raise ConfigurationError(
                    f"invalid repo-rtl task manifest {path.name!r}: {exc}"
                ) from exc
            if payload.task.id in roots:
                raise ConfigurationError(f"duplicate repo-rtl task identity: {payload.task.id}")
            roots[payload.task.id] = path
        if not roots:
            raise ConfigurationError("repo-rtl source contains no task bundles")
        return roots

    @staticmethod
    def _reject_symlink_components(path: Path) -> None:
        cursor = Path(path.anchor) if path.is_absolute() else Path.cwd()
        for part in path.parts:
            if part in {path.anchor, "", "."}:
                continue
            cursor = cursor / part
            if cursor.is_symlink():
                raise ConfigurationError("repo-rtl source paths may not contain symlinks")

    @staticmethod
    def _validate_bundle_files(root: Path) -> None:
        casefolded: dict[str, str] = {}
        inodes: set[tuple[int, int]] = set()
        file_count = 0
        total_bytes = 0
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if ".git" in Path(relative).parts:
                raise ConfigurationError("repository task bundles may not contain .git")
            if unicodedata.normalize("NFC", relative) != relative or any(
                ord(character) < 32 for character in relative
            ):
                raise ConfigurationError("repository task bundle paths must be canonical text")
            previous = casefolded.get(relative.casefold())
            if previous is not None and previous != relative:
                raise ConfigurationError("repository task bundle has case-colliding paths")
            casefolded[relative.casefold()] = relative
            metadata = os.lstat(path)
            if stat.S_ISLNK(metadata.st_mode):
                raise ConfigurationError("repository task bundles may not contain symlinks")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ConfigurationError("repository task bundles may contain only regular files")
            file_count += 1
            total_bytes += metadata.st_size
            if (
                file_count > _MAX_BUNDLE_FILES
                or metadata.st_size > _MAX_BUNDLE_FILE_BYTES
                or total_bytes > _MAX_BUNDLE_BYTES
            ):
                raise ConfigurationError("repository task bundle exceeds its asset limits")
            inode = (metadata.st_dev, metadata.st_ino)
            if metadata.st_nlink != 1 or inode in inodes:
                raise ConfigurationError("repository task bundles may not contain hardlinks")
            inodes.add(inode)

    @staticmethod
    def _validate_visible_path_classes(
        repository: Path,
        manifest: RepositoryTaskManifest,
    ) -> None:
        paths = ["TASK.md", "PUBLIC_TESTS.md"]
        paths.extend(
            f"repository/{path.relative_to(repository).as_posix()}"
            for path in sorted(repository.rglob("*"))
            if path.is_file()
        )
        classes = {
            "editable": manifest.workspace.editable_globs,
            "read_only": manifest.workspace.read_only_globs,
            "runtime_generated": manifest.workspace.runtime_generated_globs,
            "forbidden": manifest.workspace.forbidden_globs,
        }
        for path in paths:
            matches = [
                name
                for name, patterns in classes.items()
                if any(glob_matches(path, pattern) for pattern in patterns)
            ]
            if len(matches) != 1:
                raise ConfigurationError(
                    f"visible repository path {path!r} has {len(matches)} path classes"
                )
        for entrypoint in manifest.task.workspace.entrypoints:
            entrypoint_path = repository.parent / entrypoint
            if not entrypoint_path.is_file():
                raise ConfigurationError(f"repository task entrypoint is missing: {entrypoint}")
            if not any(
                glob_matches(entrypoint, pattern) for pattern in manifest.workspace.editable_globs
            ):
                raise ConfigurationError(
                    f"repository task entrypoint is not editable: {entrypoint}"
                )


__all__ = ["RepositoryRtlSuite"]
