"""HWE-Bench repository-repair suite adapter."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AssetRef,
    BudgetSpec,
    Candidate,
    ConfigurationError,
    ConformanceCase,
    InteractionMode,
    InteractionSpec,
    ObservationPolicy,
    RepositoryCandidateRecord,
    RepositoryWorkspaceContract,
    ResolvedTaskAssets,
    ScoringSpec,
    SourceSpec,
    SubmissionPolicy,
    SuiteAdapter,
    SuiteDescriptor,
    SuiteSourceConfig,
    SuiteSourceSnapshot,
    TaskRef,
    TaskType,
    ToolVisibility,
    ValidationIssue,
    ValidationReport,
    VerifierGraph,
    VerifierNode,
    VerifierResult,
    VeriTask,
    WorkspaceSpec,
    content_hash,
    copy_tree_safely,
    freeze_repository_candidate,
    hash_bytes,
    verify_frozen_repository_candidate,
)

from .dataset import VARIANT, Catalog, load_catalog
from .docker_verifier import DockerHweVerifier
from .models import HweInstance, ImageLockEntry, ImageLockEntryType, ImageLockEntryV2, ImageLockV2

ADAPTER_VERSION = "0.1.0"
SUITE_VERSION = "hwe-bench-official-repo-repair-v1"


def _contract() -> RepositoryWorkspaceContract:
    return RepositoryWorkspaceContract(
        editable_globs=["repository/**"],
        read_only_globs=["TASK.md", "PUBLIC_TESTS.md"],
        runtime_generated_globs=[".verigym_runtime/**"],
        forbidden_globs=[
            ".git",
            ".git/**",
            ".verigym_internal",
            ".verigym_internal/**",
            "repository/.git",
            "repository/.git/**",
        ],
        max_changed_files=256,
        max_patch_lines=100_000,
        max_candidate_bytes=256 * 1024 * 1024,
        max_file_bytes=64 * 1024 * 1024,
        allow_file_addition=True,
        allow_file_deletion=True,
    )


class HweBenchSuite(SuiteAdapter):
    """External-source adapter with an immutable per-instance Docker verifier."""

    descriptor = SuiteDescriptor(
        schema_version=SCHEMA_VERSION,
        name="hwe-bench",
        version=ADAPTER_VERSION,
        api_version=PLUGIN_API_VERSION,
        provider="verigym-hwe-bench",
        capabilities=[
            "external_source",
            "repository_repair",
            "systemverilog",
            "chisel_scala",
            "functional_repair",
            "suite_managed_verifier",
            "digest_locked_per_pr_image",
            "agent_eval",
            "trajectory_capture",
        ],
        title="HWE-Bench repository-level hardware repair",
        description="Selected official HWE-Bench PR tasks with exact container verification.",
        suite_version=SUITE_VERSION,
        license="Apache-2.0",
    )

    def __init__(self, config: SuiteSourceConfig | None = None) -> None:
        self._config = config
        self._catalog_cache: Catalog | None = None
        self._snapshot_cache: SuiteSourceSnapshot | None = None
        self._visible_temporaries: list[tempfile.TemporaryDirectory[str]] = []
        self._verifier = DockerHweVerifier()

    def with_source(self, config: SuiteSourceConfig) -> HweBenchSuite:
        if config.variant not in {None, VARIANT}:
            raise ConfigurationError(f"HWE-Bench supports only variant {VARIANT!r}")
        return HweBenchSuite(config.model_copy(update={"variant": VARIANT}, deep=True))

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        adapter = (
            self
            if source_root is None
            else self.with_source(SuiteSourceConfig(source_root=source_root))
        )
        catalog = adapter._catalog()
        return [
            TaskRef(
                id=f"hwe-bench/{VARIANT}/{instance.slug}",
                suite=self.descriptor.name,
                native_id=instance.slug,
                source_root=str(catalog.root),
            )
            for instance in sorted(catalog.instances.values(), key=lambda item: item.instance_id)
        ]

    def load_task(self, ref: TaskRef) -> VeriTask:
        instance, entry = self._catalog().instance_for_slug(ref.native_id)
        return self._task(instance, entry)

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        instance, entry = self._for_task(task)
        source = self._catalog().root / "workspaces" / entry.slug
        temporary = tempfile.TemporaryDirectory(prefix="verigym-hwe-visible-")
        visible = Path(temporary.name).resolve()
        copy_tree_safely(source, visible, preserve_safe_file_modes=True)
        self._visible_temporaries.append(temporary)
        if task.source.content_hash != entry.repository_hash:
            raise ConfigurationError("HWE-Bench task source identity changed")
        del instance
        return ResolvedTaskAssets(visible_root=str(visible))

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        try:
            adapter = (
                self
                if source_root is None
                else self.with_source(SuiteSourceConfig(source_root=source_root, variant=VARIANT))
            )
            catalog = adapter._catalog(refresh=True)
            if not catalog.instances:
                raise ConfigurationError("prepared HWE-Bench source contains no tasks")
        except (ConfigurationError, OSError, ValueError) as exc:
            issue = ValidationIssue(level="error", code="source_invalid", message=str(exc))
            return ValidationReport(valid=False, errors=[str(exc)], issues=[issue])
        return ValidationReport(valid=True)

    def source_snapshot(self) -> SuiteSourceSnapshot | None:
        if self._config is None:
            return None
        catalog = self._catalog()
        if self._snapshot_cache is None:
            configuration = {
                "variant": VARIANT,
                "strict_compatibility": self._config.strict_compatibility,
                "dataset_content_hash": catalog.content_hash,
                "image_locks": [
                    {
                        "instance_id": entry.instance_id,
                        "image_id": entry.image_id,
                        "manifest_digest": entry.manifest_digest,
                    }
                    for entry in catalog.lock.entries
                ],
            }
            if isinstance(catalog.lock, ImageLockV2):
                configuration["repository_profile_hashes"] = {
                    entry.instance_id: catalog.profile_for(entry.instance_id).profile_hash
                    for entry in catalog.lock.entries
                }
                configuration["official_dataset_revision"] = catalog.lock.official_dataset_revision
                configuration["verifier_dependency_hashes"] = {
                    entry.instance_id: content_hash(entry.verifier_dependencies)
                    for entry in catalog.lock.entries
                }
            license_expressions = sorted(
                {catalog.instances[key].license_id for key in catalog.instances}
            )
            license_hashes = {
                entry.instance_id: self._entry_license_hash(entry) for entry in catalog.lock.entries
            }
            self._snapshot_cache = SuiteSourceSnapshot(
                source_root=str(catalog.root),
                dataset_root="instances.jsonl",
                variant=VARIANT,
                native_layout=catalog.native_layout,
                strict_compatibility=self._config.strict_compatibility,
                configuration_fingerprint=content_hash(configuration),
                dataset_content_hash=catalog.content_hash,
                license_id=" AND ".join(f"({value})" for value in license_expressions),
                license_file_hash=content_hash(license_hashes),
                git_commit=catalog.lock.official_source_commit,
                git_remote="https://github.com/pku-liang/hwe-bench",
                git_metadata_available=catalog.lock.official_source_commit is not None,
                synthetic_fixture=False,
            )
        return self._snapshot_cache.model_copy(deep=True)

    def reference_solution(self, task: VeriTask) -> Candidate | None:
        instance, entry = self._for_task(task)
        base = self._base_repository(entry)
        with tempfile.TemporaryDirectory(prefix="verigym-hwe-reference-") as temporary:
            repository = Path(temporary) / "repository"
            copy_tree_safely(base, repository)
            try:
                applied = subprocess.run(
                    ["git", "apply", "--whitespace=nowarn", "-"],
                    cwd=repository,
                    input=instance.fix_patch.encode("utf-8"),
                    capture_output=True,
                    check=False,
                    timeout=60,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                raise ConfigurationError("could not apply the official reference patch") from exc
            if applied.returncode != 0:
                raise ConfigurationError("official HWE-Bench reference patch no longer applies")
            files = {
                f"repository/{relative}": (repository / relative).read_text(encoding="utf-8")
                for relative in instance.modified_files
                if (repository / relative).is_file()
            }
        candidate = Candidate(files=files, label="official-reference-conformance-only")
        if content_hash(candidate) != entry.reference_candidate_hash:
            raise ConfigurationError("official HWE-Bench reference candidate identity changed")
        return candidate

    def conformance_cases(self) -> Iterable[ConformanceCase]:
        for ref in self.discover():
            task = self.load_task(ref)
            candidate = self.reference_solution(task)
            assert candidate is not None
            yield ConformanceCase(
                name=f"{ref.native_id}-official-reference",
                candidate=candidate,
                expected_resolved=True,
            )

    def freeze_repository_candidate(
        self,
        *,
        task: VeriTask,
        candidate_dir: Path,
        run_root: Path,
        artifact_root: Path,
    ) -> RepositoryCandidateRecord | None:
        _instance, entry = self._for_task(task)
        repository = candidate_dir / "repository"
        if not repository.is_dir():
            raise ConfigurationError("HWE-Bench candidate is missing repository/")
        return freeze_repository_candidate(
            task_id=task.id,
            base_repository=self._base_repository(entry),
            candidate_repository=repository,
            contract=_contract(),
            public_test_ids=[],
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
        _instance, entry = self._for_task(task)
        verify_frozen_repository_candidate(
            base_repository=self._base_repository(entry),
            candidate_repository=candidate_dir / "repository",
            patch_file=run_root / "repository.patch",
            record=record,
            contract=_contract(),
        )

    def verify_candidate(
        self,
        *,
        task: VeriTask,
        candidate_dir: Path,
        artifact_root: Path,
    ) -> list[VerifierResult] | None:
        instance, entry = self._for_task(task)
        node = task.verifier.nodes[0]
        return [
            self._verifier.evaluate(
                instance=instance,
                entry=entry,
                node=node,
                base_repository=self._base_repository(entry),
                candidate_repository=candidate_dir / "repository",
                artifact_root=artifact_root,
                verifier_dependency_root=self._catalog().verifier_dependency_root(
                    instance.instance_id
                ),
            )
        ]

    def _catalog(self, *, refresh: bool = False) -> Catalog:
        if self._config is None:
            raise ConfigurationError("HWE-Bench suite requires an explicit prepared source")
        if refresh or self._catalog_cache is None:
            self._catalog_cache = load_catalog(self._config.source_root)
            self._snapshot_cache = None
        return self._catalog_cache

    def _for_task(self, task: VeriTask) -> tuple[HweInstance, ImageLockEntryType]:
        native = task.metadata.get("native_task_id")
        if not isinstance(native, str):
            raise ConfigurationError("HWE-Bench task lacks its native identity")
        instance, entry = self._catalog().instance_for_slug(native)
        if task.id != f"hwe-bench/{VARIANT}/{native}":
            raise ConfigurationError("HWE-Bench task identity changed")
        return instance, entry

    def _base_repository(self, entry: ImageLockEntryType) -> Path:
        return (self._catalog().root / "workspaces" / entry.slug / "repository").resolve(
            strict=True
        )

    @staticmethod
    def _entry_license_hash(entry: ImageLockEntryType) -> str:
        if isinstance(entry, ImageLockEntry):
            return entry.license_file_hash
        return content_hash([item.model_dump(mode="json") for item in entry.license_inventory])

    def _task(self, instance: HweInstance, entry: ImageLockEntryType) -> VeriTask:
        contract = _contract()
        profile = self._catalog().profile_for(instance.instance_id)
        issue_hash = hash_bytes(instance.problem_statement.encode("utf-8"))
        public_assets_hash = content_hash({"public_tests": []})
        public_mount_hash = content_hash({"public_mount": None})
        safe_manifest = {
            "instance_id": instance.instance_id,
            "base_commit": entry.base_commit,
            "repository_hash": entry.repository_hash,
            "image_id": entry.image_id,
            "manifest_digest": entry.manifest_digest,
            "verifier_payload_hash": entry.verifier_payload_hash,
        }
        request = {
            "protocol": "hwe_bench_candidate_v1",
            "instance_id": instance.instance_id,
            "base_commit": entry.base_commit,
            "image_id": entry.image_id,
            "manifest_digest": entry.manifest_digest,
            "verifier_payload_hash": entry.verifier_payload_hash,
        }
        if isinstance(entry, ImageLockEntryV2):
            verifier_dependency_hash = content_hash(entry.verifier_dependencies)
            safe_manifest["verifier_dependency_hash"] = verifier_dependency_hash
            request["verifier_dependency_hash"] = verifier_dependency_hash
        node = VerifierNode(
            id="run_hidden_regression",
            plugin="hwe_bench.simulate",
            gate=True,
            required=True,
            visibility=ToolVisibility.VERIFIER_ONLY,
            request=request,
            timeout_s=profile.verifier_limits.timeout_s,
            artifact_globs=["result.json"],
        )
        return VeriTask(
            id=f"hwe-bench/{VARIANT}/{instance.slug}",
            suite=self.descriptor.name,
            suite_version=SUITE_VERSION,
            task_type=TaskType.REPO_REPAIR,
            title=instance.title,
            description=instance.problem_statement,
            source=SourceSpec(
                kind="repository",
                uri=f"https://github.com/{instance.org}/{instance.repo}",
                revision=SUITE_VERSION,
                commit=entry.base_commit,
                license=instance.license_id,
                attribution=f"HWE-Bench task derived from {instance.instance_id}.",
                content_hash=entry.repository_hash,
            ),
            workspace=WorkspaceSpec(
                base=AssetRef(kind="directory", path="."),
                editable_globs=contract.editable_globs,
                readonly_globs=contract.read_only_globs,
                excluded_globs=contract.forbidden_globs,
                # Golden modified-file paths are intentionally not exposed as entrypoints.
                entrypoints=[],
                max_changed_files=contract.max_changed_files,
                max_patch_lines=contract.max_patch_lines,
            ),
            interaction=InteractionSpec(
                supported_modes=[InteractionMode.AGENT],
                default_mode=InteractionMode.AGENT,
                allowed_tools=[
                    "file.apply_patch",
                    "file.diff",
                    "file.list",
                    "file.read",
                    "file.write",
                ],
                denied_tools=["repository.public_test"],
                allow_general_shell=False,
                network_policy="none",
                initial_observation=ObservationPolicy(
                    include_tree=True,
                    include_readme=True,
                    include_entrypoints=False,
                ),
                final_submission=SubmissionPolicy(kind="patch"),
            ),
            budget=BudgetSpec(
                max_turns=128,
                max_tool_calls=512,
                max_model_calls=128,
                max_wall_time_s=3600,
                max_tool_time_s=300,
                max_output_bytes_per_tool=512 * 1024,
                max_workspace_bytes=contract.max_candidate_bytes,
            ),
            verifier=VerifierGraph(nodes=[node]),
            scoring=ScoringSpec(correctness_required_nodes=[node.id]),
            metadata={
                "category": "repository_hardware_functional_repair",
                "native_task_id": instance.slug,
                "official_instance_id": instance.instance_id,
                "language": instance.language,
                "benchmark": "HWE-Bench",
                "verification_semantics": "official_all_tests_pass_v1",
                "repository_repair": {
                    "manifest_hash": content_hash(safe_manifest),
                    "task_bundle_hash": entry.task_bundle_hash,
                    "source_identity_hash": content_hash(
                        {
                            "repository": f"{instance.org}/{instance.repo}",
                            "base_commit": entry.base_commit,
                            "repository_hash": entry.repository_hash,
                        }
                    ),
                    "repository_profile_hash": profile.profile_hash,
                    "source_lock_format": (
                        "verigym_hwe_bench_source_v2"
                        if isinstance(entry, ImageLockEntryV2)
                        else "verigym_hwe_bench_source_v1"
                    ),
                    "base_commit_marker": profile.base_commit_marker,
                    "license_expression": instance.license_id,
                    "profile_license_expression": profile.license_expression,
                    "license_provenance_status": (
                        "profile_bound"
                        if isinstance(entry, ImageLockEntryV2)
                        else "legacy_v1_unbound"
                    ),
                    "license_inventory_hash": self._entry_license_hash(entry),
                    # Core repository plan identity retains this singular compatibility key.
                    "license_file_hash": self._entry_license_hash(entry),
                    "base_repository_hash": entry.repository_hash,
                    "issue_hash": issue_hash,
                    "public_assets_hash": public_assets_hash,
                    "public_mount_hash": public_mount_hash,
                    "public_test_ids": [],
                    "hidden_verifier_hash": entry.verifier_payload_hash,
                    "reference_candidate_hash": entry.reference_candidate_hash,
                    "reference_patch_hash": entry.reference_patch_hash,
                    "workspace_contract": contract.model_dump(mode="json"),
                },
            },
        )


__all__ = ["ADAPTER_VERSION", "HweBenchSuite", "SUITE_VERSION"]
