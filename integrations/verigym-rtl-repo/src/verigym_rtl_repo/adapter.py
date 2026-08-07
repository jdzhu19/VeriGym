"""VeriGym adapter for the externally supplied official RTL-Repo dataset."""

from __future__ import annotations

import hashlib
import json
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
    VeriTask,
    WorkspaceSpec,
)

from .dataset import (
    NATIVE_LAYOUT,
    VARIANT,
    Catalog,
    Problem,
    RowRef,
    current_file_state,
    inspect_layout,
    load_problem,
    resolve_layout,
    sha256_bytes,
)
from .scoring import METRIC_PROFILE

ADAPTER_VERSION = "0.1.0"
SUITE_VERSION = "rtl-repo-official-full-context-compat-1"


class RtlRepoSuite(SuiteAdapter):
    """Read-only adapter registered from an independently installable distribution."""

    descriptor = SuiteDescriptor(
        schema_version=SCHEMA_VERSION,
        name="rtl-repo",
        version=ADAPTER_VERSION,
        api_version=PLUGIN_API_VERSION,
        provider="verigym-rtl-repo",
        capabilities=[
            "external_source",
            VARIANT,
            "repository_context_completion",
            "single_line_completion",
            "exact_match",
            "edit_similarity",
            "chat_eval",
            "conformance",
        ],
        title="RTL-Repo repository-context completion",
        description=("Installable adapter for the official RTL-Repo Hugging Face Parquet layout."),
        suite_version=SUITE_VERSION,
        license="Apache-2.0",
    )

    def __init__(self, config: SuiteSourceConfig | None = None) -> None:
        self._config = config
        self._catalog_cache: Catalog | None = None
        self._snapshot_cache: SuiteSourceSnapshot | None = None
        self._workspace_root = Path(__file__).parent / "assets" / "workspace"

    def with_source(self, config: SuiteSourceConfig) -> RtlRepoSuite:
        if config.variant not in {None, VARIANT}:
            raise ConfigurationError(f"suite supports only variant {VARIANT!r}")
        normalized = config.model_copy(update={"variant": VARIANT}, deep=True)
        return RtlRepoSuite(normalized)

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        adapter = self._adapter_for_optional_root(source_root)
        catalog = adapter._valid_catalog()
        return [
            TaskRef(
                id=f"{self.descriptor.name}/{VARIANT}/{row.native_id}",
                suite=self.descriptor.name,
                native_id=row.native_id,
                source_root=str(catalog.layout.source_root),
            )
            for row in catalog.rows
        ]

    def load_task(self, ref: TaskRef) -> VeriTask:
        catalog = self._valid_catalog()
        row = self._row(catalog, ref.native_id)
        problem = self._load_problem(row)
        return self._normalize_task(problem, self._snapshot(catalog))

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        catalog = self._valid_catalog()
        try:
            observed_state = current_file_state(catalog)
        except OSError as exc:
            raise ConfigurationError(f"RTL-Repo source became unavailable: {exc}") from exc
        if observed_state != catalog.file_state:
            raise ConfigurationError("RTL-Repo dataset differs from the frozen source snapshot")
        if task.metadata.get("dataset_content_hash") != catalog.dataset_content_hash:
            raise ConfigurationError("RTL-Repo dataset differs from the frozen task snapshot")
        native_id = task.metadata.get("native_task_id")
        if not isinstance(native_id, str):
            raise ConfigurationError("frozen task has no native task identifier")
        problem = self._load_problem(self._row(catalog, native_id))
        if task.source.content_hash != problem.content_hash:
            raise ConfigurationError("RTL-Repo task differs from the frozen task snapshot")
        return ResolvedTaskAssets(
            visible_root=str(self._workspace_root.resolve(strict=True)),
            hidden_assets=[
                AssetRef(
                    kind="inline",
                    content=problem.target,
                    content_hash=problem.target_hash,
                    mount_path="verifier/target.txt",
                )
            ],
        )

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        try:
            adapter = self._adapter_for_optional_root(source_root)
            catalog = adapter._catalog(refresh=True)
        except (ConfigurationError, ValueError) as exc:
            issue = ValidationIssue(
                level="error",
                code="source_configuration",
                message=str(exc),
            )
            return ValidationReport(
                valid=False,
                errors=[f"[source_configuration] {exc}"],
                issues=[issue],
            )
        issues = [
            ValidationIssue(
                level=issue.level,
                code=issue.code,
                message=issue.message,
                relative_path=issue.relative_path,
            )
            for issue in catalog.issues
        ]
        errors = [f"[{issue.code}] {issue.message}" for issue in issues if issue.level == "error"]
        warnings = [
            f"[{issue.code}] {issue.message}" for issue in issues if issue.level == "warning"
        ]
        return ValidationReport(valid=not errors, errors=errors, warnings=warnings, issues=issues)

    def reference_solution(self, task: VeriTask) -> Candidate | None:
        native_id = task.metadata.get("native_task_id")
        if not isinstance(native_id, str):
            return None
        problem = self._load_problem(self._row(self._valid_catalog(), native_id))
        return Candidate(
            files={"completion.txt": problem.target},
            label="hidden-reference-conformance-only",
        )

    def conformance_cases(self) -> Iterable[ConformanceCase]:
        catalog = self._valid_catalog()
        preferred = next((row for row in catalog.rows if row.split == "test"), None)
        if preferred is None:
            return []
        problem = self._load_problem(preferred)
        task = self._normalize_task(problem, self._snapshot(catalog))
        reference = self.reference_solution(task)
        assert reference is not None
        return [
            ConformanceCase(
                name=f"{preferred.native_id}-reference",
                candidate=reference,
                expected_resolved=True,
            ),
            ConformanceCase(
                name=f"{preferred.native_id}-wrong",
                candidate=Candidate(
                    files={"completion.txt": "__verigym_known_bad_completion__\n"},
                    label="known-bad",
                ),
                expected_resolved=False,
            ),
        ]

    def source_snapshot(self) -> SuiteSourceSnapshot | None:
        if self._config is None:
            return None
        return self._snapshot(self._valid_catalog()).model_copy(deep=True)

    def _adapter_for_optional_root(self, source_root: Path | None) -> RtlRepoSuite:
        if source_root is None:
            return self
        strict = self._config.strict_compatibility if self._config is not None else True
        return self.with_source(
            SuiteSourceConfig(
                source_root=source_root,
                variant=VARIANT,
                strict_compatibility=strict,
            )
        )

    def _catalog(self, *, refresh: bool = False) -> Catalog:
        if self._config is None:
            raise ConfigurationError("suite requires an explicit external source path")
        if refresh or self._catalog_cache is None:
            try:
                layout = resolve_layout(self._config.source_root, self._config.variant)
                self._catalog_cache = inspect_layout(
                    layout,
                    strict_compatibility=self._config.strict_compatibility,
                )
                self._snapshot_cache = None
            except ValueError as exc:
                raise ConfigurationError(str(exc)) from exc
        return self._catalog_cache

    def _valid_catalog(self) -> Catalog:
        catalog = self._catalog()
        errors = [issue for issue in catalog.issues if issue.level == "error"]
        if errors:
            preview = "; ".join(f"[{issue.code}] {issue.message}" for issue in errors[:3])
            raise ConfigurationError(f"invalid RTL-Repo source: {preview}")
        return catalog

    def _snapshot(self, catalog: Catalog) -> SuiteSourceSnapshot:
        assert self._config is not None
        if self._snapshot_cache is None:
            license_id, license_hash = _license_metadata(catalog.layout.source_root)
            configuration = {
                "variant": VARIANT,
                "strict_compatibility": self._config.strict_compatibility,
                "dataset_content_hash": catalog.dataset_content_hash,
                "prompt_context_policy": "official_full_context_without_tokenizer_truncation",
            }
            self._snapshot_cache = SuiteSourceSnapshot(
                source_root=str(catalog.layout.source_root),
                dataset_root=str(catalog.layout.dataset_root),
                variant=VARIANT,
                native_layout=NATIVE_LAYOUT,
                strict_compatibility=self._config.strict_compatibility,
                configuration_fingerprint=_content_hash(configuration),
                dataset_content_hash=catalog.dataset_content_hash,
                license_id=license_id,
                license_file_hash=license_hash,
                git_metadata_available=False,
                synthetic_fixture=catalog.synthetic_fixture,
            )
        return self._snapshot_cache

    @staticmethod
    def _row(catalog: Catalog, native_id: str) -> RowRef:
        row = next((item for item in catalog.rows if item.native_id == native_id), None)
        if row is None:
            raise ConfigurationError(f"unknown RTL-Repo task: {native_id}")
        return row

    @staticmethod
    def _load_problem(row: RowRef) -> Problem:
        try:
            return load_problem(row)
        except ValueError as exc:
            raise ConfigurationError(f"invalid RTL-Repo task {row.native_id}: {exc}") from exc

    def _normalize_task(
        self,
        problem: Problem,
        snapshot: SuiteSourceSnapshot,
    ) -> VeriTask:
        row = problem.ref
        task_id = f"{self.descriptor.name}/{VARIANT}/{row.native_id}"
        return VeriTask(
            id=task_id,
            suite=self.descriptor.name,
            suite_version=SUITE_VERSION,
            task_type=TaskType.COMPLETION,
            title=f"RTL-Repo {row.split} completion {row.native_id}",
            description=problem.prompt,
            source=SourceSpec(
                kind="synthetic" if snapshot.synthetic_fixture else "benchmark",
                uri=f"rtl-repo://{VARIANT}/{row.native_id}",
                revision=SUITE_VERSION,
                license=snapshot.license_id,
                attribution=(
                    "Synthetic layout-conformance fixture; not an official benchmark task."
                    if snapshot.synthetic_fixture
                    else "Externally supplied AUCOHL RTL-Repo dataset snapshot."
                ),
                content_hash=problem.content_hash,
            ),
            workspace=WorkspaceSpec(
                base=AssetRef(kind="directory", path="workspace"),
                editable_globs=["completion.txt"],
                readonly_globs=["README.md"],
                excluded_globs=["verifier", "verifier/**", "hidden", "hidden/**"],
                entrypoints=["completion.txt"],
                hidden_assets=[
                    AssetRef(
                        kind="inline",
                        content_hash=problem.target_hash,
                        mount_path="verifier/target.txt",
                    )
                ],
                max_changed_files=1,
                max_patch_lines=2,
            ),
            interaction=InteractionSpec(
                supported_modes=[InteractionMode.CHAT],
                default_mode=InteractionMode.CHAT,
                allowed_tools=[],
                allow_general_shell=False,
                network_policy="none",
                initial_observation=ObservationPolicy(
                    include_tree=True,
                    include_readme=True,
                    include_entrypoints=False,
                ),
                final_submission=SubmissionPolicy(
                    kind="line",
                    path="completion.txt",
                ),
            ),
            budget=BudgetSpec(
                max_turns=1,
                max_tool_calls=0,
                max_model_calls=1,
                max_wall_time_s=300,
                max_tool_time_s=30,
                max_output_tokens=50,
                max_output_bytes_per_tool=64_000,
                max_workspace_bytes=512_000,
            ),
            verifier=VerifierGraph(
                nodes=[
                    VerifierNode(
                        id="native_score",
                        plugin="rtl_repo.score",
                        gate=True,
                        required=True,
                        visibility=ToolVisibility.VERIFIER_ONLY,
                        timeout_s=30,
                        request={
                            "candidate": "completion.txt",
                            "target": "verifier/target.txt",
                            "metric_profile": METRIC_PROFILE,
                            "split": row.split,
                        },
                    )
                ]
            ),
            scoring=ScoringSpec(
                correctness_required_nodes=["native_score"],
                ppa_enabled=False,
            ),
            metadata={
                "benchmark_variant": VARIANT,
                "native_layout": NATIVE_LAYOUT,
                "native_task_id": row.native_id,
                "benchmark_split": row.split,
                "benchmark_level": row.level,
                "official_index": row.official_index,
                "repository_name": row.repo_name,
                "repository_file_path": row.file_path,
                "context_count": problem.context_count,
                "dataset_content_hash": snapshot.dataset_content_hash,
                "task_content_hash": problem.content_hash,
                "prompt_hash": problem.prompt_hash,
                "target_hash": problem.target_hash,
                "prompt_context_policy": "official_full_context_without_tokenizer_truncation",
                "metric_profile": METRIC_PROFILE,
                "adapter_version": ADAPTER_VERSION,
                "synthetic_fixture": snapshot.synthetic_fixture,
            },
        )


def _content_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _license_metadata(root: Path) -> tuple[str | None, str | None]:
    path = root / "LICENSE"
    if not path.is_file() or path.is_symlink():
        return None, None
    data = path.read_bytes()
    text = data[:64_000].decode(errors="ignore").casefold()
    license_id = "Apache-2.0" if "apache license" in text and "version 2.0" in text else None
    return license_id, sha256_bytes(data)


__all__ = ["ADAPTER_VERSION", "SUITE_VERSION", "RtlRepoSuite"]
