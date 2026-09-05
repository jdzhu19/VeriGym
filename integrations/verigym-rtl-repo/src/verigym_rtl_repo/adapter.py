"""VeriGym adapter for the externally supplied official RTL-Repo dataset."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentEvalWorkspace,
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
    materialize_agent_eval_workspace,
)

from .dataset import (
    AGENT_EVAL_V2_VARIANT,
    AGENT_EVAL_V3_VARIANT,
    AGENT_EVAL_VARIANT,
    CONTEXT_CLASSIFICATION_RULE,
    NATIVE_LAYOUT,
    VARIANT,
    Catalog,
    Problem,
    RowRef,
    classify_context_path,
    current_file_state,
    inspect_layout,
    load_problem,
    resolve_layout,
    sha256_bytes,
)
from .scoring import METRIC_PROFILE

ADAPTER_VERSION = "0.1.0"
SUITE_VERSION = "rtl-repo-official-full-context-compat-1"
AGENT_EVAL_SUITE_VERSION = "rtl-repo-official-context-projection-agent-eval-v1"
AGENT_EVAL_V2_SUITE_VERSION = "rtl-repo-official-context-projection-agent-eval-v2"
AGENT_EVAL_V3_SUITE_VERSION = "rtl-repo-official-context-projection-agent-eval-v3"
AGENT_EVAL_V3_COMPLETION_CONTRACT = "immediate_next_physical_line_v1"


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
            AGENT_EVAL_VARIANT,
            AGENT_EVAL_V2_VARIANT,
            AGENT_EVAL_V3_VARIANT,
            "repository_context_completion",
            "single_line_completion",
            "exact_match",
            "edit_similarity",
            "chat_eval",
            "agent_eval",
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
        self._agent_workspaces: list[AgentEvalWorkspace] = []

    def with_source(self, config: SuiteSourceConfig) -> RtlRepoSuite:
        if config.variant not in {
            None,
            VARIANT,
            AGENT_EVAL_VARIANT,
            AGENT_EVAL_V2_VARIANT,
            AGENT_EVAL_V3_VARIANT,
        }:
            raise ConfigurationError(
                "suite supports the official and AgentEval v1, v2, and v3 variants"
            )
        normalized = config.model_copy(update={"variant": config.variant or VARIANT}, deep=True)
        return RtlRepoSuite(normalized)

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        adapter = self._adapter_for_optional_root(source_root)
        catalog = adapter._valid_catalog()
        return [
            TaskRef(
                id=f"{self.descriptor.name}/{adapter._variant()}/{row.native_id}",
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
        if task.source.content_hash != self._source_content_hash(problem):
            raise ConfigurationError("RTL-Repo task differs from the frozen task snapshot")
        if self._is_agent_eval():
            context_index = self._context_index(problem)
            repository_files = {
                "README.md": (
                    "# RTL-Repo AgentEval\n\n"
                    "This is an official-context projection, not a complete repository.\n"
                ),
                "completion.txt": "",
                "target/cropped_target.sv": problem.cropped_code,
                "context/index.json": json.dumps(context_index, indent=2, sort_keys=True) + "\n",
                **{
                    f"context/{index:04d}.txt": snippet
                    for index, (_path, snippet) in enumerate(problem.context)
                },
            }
            materialized = materialize_agent_eval_workspace(
                task_description=task.description,
                repository_files=repository_files,
                compile_contract=None,
                ppa_available=False,
            )
            self._agent_workspaces.append(materialized)
            visible_root = str(materialized.visible_root)
        else:
            visible_root = str(self._workspace_root.resolve(strict=True))
        return ResolvedTaskAssets(
            visible_root=visible_root,
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
            files={
                "repository/completion.txt" if self._is_agent_eval() else "completion.txt": (
                    problem.target
                )
            },
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
                    files={
                        (
                            "repository/completion.txt"
                            if self._is_agent_eval()
                            else "completion.txt"
                        ): "__verigym_known_bad_completion__\n"
                    },
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
                variant=self._variant(),
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
                "variant": self._variant(),
                "strict_compatibility": self._config.strict_compatibility,
                "dataset_content_hash": catalog.dataset_content_hash,
                "prompt_context_policy": self._prompt_context_policy(),
                "context_classification_rule": (
                    CONTEXT_CLASSIFICATION_RULE if self._is_agent_eval_v2_or_later() else None
                ),
                **(
                    {"completion_contract": AGENT_EVAL_V3_COMPLETION_CONTRACT}
                    if self._is_agent_eval_v3()
                    else {}
                ),
            }
            self._snapshot_cache = SuiteSourceSnapshot(
                source_root=str(catalog.layout.source_root),
                dataset_root=str(catalog.layout.dataset_root),
                variant=self._variant(),
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
        variant = self._variant()
        agent_eval = self._is_agent_eval()
        suite_version = self._suite_version()
        source_content_hash = self._source_content_hash(problem)
        task_content_hash = self._task_content_hash(problem)
        task_id = f"{self.descriptor.name}/{variant}/{row.native_id}"
        candidate_path = "repository/completion.txt" if agent_eval else "completion.txt"
        return VeriTask(
            id=task_id,
            suite=self.descriptor.name,
            suite_version=suite_version,
            task_type=TaskType.COMPLETION,
            title=f"RTL-Repo {row.split} completion {row.native_id}",
            description=(self._agent_eval_description() if agent_eval else problem.prompt),
            source=SourceSpec(
                kind="synthetic" if snapshot.synthetic_fixture else "benchmark",
                uri=f"rtl-repo://{variant}/{row.native_id}",
                revision=suite_version,
                license=snapshot.license_id,
                attribution=(
                    "Synthetic layout-conformance fixture; not an official benchmark task."
                    if snapshot.synthetic_fixture
                    else "Externally supplied AUCOHL RTL-Repo dataset snapshot."
                ),
                content_hash=source_content_hash,
            ),
            workspace=WorkspaceSpec(
                base=AssetRef(kind="directory", path="workspace"),
                editable_globs=[candidate_path],
                readonly_globs=(
                    [
                        "TASK.md",
                        "PUBLIC_TESTS.md",
                        "repository/README.md",
                        "repository/context/**",
                        "repository/target/**",
                    ]
                    if agent_eval
                    else ["README.md"]
                ),
                excluded_globs=["verifier", "verifier/**", "hidden", "hidden/**"],
                entrypoints=[candidate_path],
                hidden_assets=[
                    AssetRef(
                        kind="inline",
                        content_hash=problem.target_hash,
                        mount_path="verifier/target.txt",
                    )
                ],
                max_changed_files=1,
                max_patch_lines=20 if agent_eval else 2,
            ),
            interaction=InteractionSpec(
                supported_modes=(
                    [InteractionMode.AGENT]
                    if agent_eval
                    else [InteractionMode.CHAT, InteractionMode.AGENT]
                ),
                default_mode=InteractionMode.AGENT if agent_eval else InteractionMode.CHAT,
                allowed_tools=(
                    ["file.list", "file.read", "file.apply_patch", "file.diff"]
                    if agent_eval
                    else []
                ),
                allow_general_shell=False,
                network_policy="none",
                initial_observation=ObservationPolicy(
                    include_tree=True,
                    include_readme=True,
                    include_entrypoints=False,
                ),
                final_submission=SubmissionPolicy(
                    kind="line",
                    path=candidate_path,
                ),
            ),
            budget=BudgetSpec(
                max_turns=20 if agent_eval else 1,
                max_tool_calls=40 if agent_eval else 0,
                max_model_calls=20 if agent_eval else 1,
                max_wall_time_s=300,
                max_tool_time_s=30,
                max_output_tokens=16_384 if agent_eval else 50,
                max_output_bytes_per_tool=64_000,
                max_workspace_bytes=64 * 1024 * 1024 if agent_eval else 512_000,
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
                            "candidate": candidate_path,
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
                "benchmark_variant": variant,
                "native_layout": NATIVE_LAYOUT,
                "native_task_id": row.native_id,
                "benchmark_split": row.split,
                "benchmark_level": row.level,
                "official_index": row.official_index,
                "repository_name": row.repo_name,
                "repository_file_path": row.file_path,
                "context_count": problem.context_count,
                "dataset_content_hash": snapshot.dataset_content_hash,
                "task_content_hash": task_content_hash,
                "prompt_hash": problem.prompt_hash,
                "target_hash": problem.target_hash,
                "prompt_context_policy": self._prompt_context_policy(),
                "metric_profile": METRIC_PROFILE,
                "adapter_version": ADAPTER_VERSION,
                "synthetic_fixture": snapshot.synthetic_fixture,
                **(
                    {
                        "agent_eval": {
                            "benchmark_variant": variant,
                            "compile_test_id": None,
                            "ppa_supported": False,
                            "public_test_contract_hash": None,
                        },
                        "projection_kind": "official-context projection",
                        "projection_version": self._agent_eval_projection_version(),
                        "complete_repository": False,
                        **(
                            {"context_classification_rule": CONTEXT_CLASSIFICATION_RULE}
                            if self._is_agent_eval_v2_or_later()
                            else {}
                        ),
                        **(
                            {
                                "completion_contract": AGENT_EVAL_V3_COMPLETION_CONTRACT,
                            }
                            if self._is_agent_eval_v3()
                            else {}
                        ),
                    }
                    if agent_eval
                    else {}
                ),
            },
        )

    def _variant(self) -> str:
        if self._config is not None and self._config.variant:
            return self._config.variant
        return VARIANT

    def _is_agent_eval(self) -> bool:
        return self._variant() in {
            AGENT_EVAL_VARIANT,
            AGENT_EVAL_V2_VARIANT,
            AGENT_EVAL_V3_VARIANT,
        }

    def _is_agent_eval_v2(self) -> bool:
        return self._variant() == AGENT_EVAL_V2_VARIANT

    def _is_agent_eval_v3(self) -> bool:
        return self._variant() == AGENT_EVAL_V3_VARIANT

    def _is_agent_eval_v2_or_later(self) -> bool:
        return self._variant() in {AGENT_EVAL_V2_VARIANT, AGENT_EVAL_V3_VARIANT}

    def _agent_eval_projection_version(self) -> str:
        if self._is_agent_eval_v3():
            return "v3"
        return "v2" if self._is_agent_eval_v2() else "v1"

    def _suite_version(self) -> str:
        if self._is_agent_eval_v3():
            return AGENT_EVAL_V3_SUITE_VERSION
        if self._is_agent_eval_v2():
            return AGENT_EVAL_V2_SUITE_VERSION
        return AGENT_EVAL_SUITE_VERSION if self._is_agent_eval() else SUITE_VERSION

    def _prompt_context_policy(self) -> str:
        if self._is_agent_eval_v3():
            return "official_context_projection_source_priority_immediate_physical_line_v3"
        if self._is_agent_eval_v2():
            return "official_context_projection_source_priority_v2"
        if self._is_agent_eval():
            return "official_context_projection_v1"
        return "official_full_context_without_tokenizer_truncation"

    def _agent_eval_description(self) -> str:
        if not self._is_agent_eval_v2_or_later():
            return (
                "Complete exactly the next line in repository/completion.txt. Browse the "
                "read-only cropped target and indexed context. This is an official-context "
                "projection, not a complete repository."
            )
        if self._is_agent_eval_v2():
            return (
                "Complete exactly the next line in repository/completion.txt. First read the "
                "tail of repository/target/cropped_target.sv, then use "
                "repository/context/index.json to read source-priority context before generated "
                "context. Write exactly one line only; punctuation and spacing affect the "
                "official exact match. This remains the complete official context in original "
                "order, not a complete repository."
            )
        return (
            "Predict only the immediate next physical source-code line after the end of "
            "repository/target/cropped_target.sv and write that one newline-terminated line to "
            "repository/completion.txt. Do not concatenate, flatten, or include any later "
            "source lines, even if the cropped target is rendered as one long physical line. "
            "First read the cropped target tail, then use repository/context/index.json to read "
            "source-priority context before generated context. Preserve exact leading whitespace "
            "and punctuation because they affect the official exact match. This remains the "
            "complete official context in original order, not a complete repository."
        )

    def _source_content_hash(self, problem: Problem) -> str:
        if self._is_agent_eval_v3():
            return _content_hash(
                {
                    "identity_kind": "rtl_repo_agent_eval_v3_source",
                    "official_problem_content_hash": problem.content_hash,
                    "suite_revision": AGENT_EVAL_V3_SUITE_VERSION,
                    "context_classification_rule": CONTEXT_CLASSIFICATION_RULE,
                    "completion_contract": AGENT_EVAL_V3_COMPLETION_CONTRACT,
                }
            )
        if not self._is_agent_eval_v2():
            return problem.content_hash
        return _content_hash(
            {
                "identity_kind": "rtl_repo_agent_eval_v2_source",
                "official_problem_content_hash": problem.content_hash,
                "suite_revision": AGENT_EVAL_V2_SUITE_VERSION,
                "context_classification_rule": CONTEXT_CLASSIFICATION_RULE,
            }
        )

    def _task_content_hash(self, problem: Problem) -> str:
        if not self._is_agent_eval_v2_or_later():
            return problem.content_hash
        payload = {
            "identity_kind": (
                "rtl_repo_agent_eval_v3_task"
                if self._is_agent_eval_v3()
                else "rtl_repo_agent_eval_v2_task"
            ),
            "source_content_hash": self._source_content_hash(problem),
            "prompt_context_policy": self._prompt_context_policy(),
            "description": self._agent_eval_description(),
        }
        if self._is_agent_eval_v3():
            payload["completion_contract"] = AGENT_EVAL_V3_COMPLETION_CONTRACT
        return _content_hash(payload)

    def _context_index(self, problem: Problem) -> dict[str, object]:
        if not self._is_agent_eval_v2_or_later():
            return {
                "projection": "official-context projection",
                "complete_repository": False,
                "target_path": problem.ref.file_path,
                "items": [
                    {"file": f"{index:04d}.txt", "path": path}
                    for index, (path, _snippet) in enumerate(problem.context)
                ],
            }
        items: list[dict[str, object]] = []
        byte_totals = {"source": 0, "generated": 0}
        for index, (path, snippet) in enumerate(problem.context):
            classification = classify_context_path(path)
            utf8_bytes = len(snippet.encode("utf-8"))
            byte_totals[classification] += utf8_bytes
            items.append(
                {
                    "file": f"{index:04d}.txt",
                    "path": path,
                    "utf8_bytes": utf8_bytes,
                    "classification": classification,
                    "read_priority": 0 if classification == "source" else 1,
                }
            )
        return {
            "projection": f"official-context projection {self._agent_eval_projection_version()}",
            "complete_repository": False,
            "target_path": problem.ref.file_path,
            "context_classification_rule": CONTEXT_CLASSIFICATION_RULE,
            "read_priority_order": ["source", "generated"],
            "source_utf8_bytes": byte_totals["source"],
            "generated_utf8_bytes": byte_totals["generated"],
            **(
                {"completion_contract": AGENT_EVAL_V3_COMPLETION_CONTRACT}
                if self._is_agent_eval_v3()
                else {}
            ),
            "items": items,
        }


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


__all__ = [
    "ADAPTER_VERSION",
    "AGENT_EVAL_SUITE_VERSION",
    "AGENT_EVAL_V2_SUITE_VERSION",
    "AGENT_EVAL_V3_COMPLETION_CONTRACT",
    "AGENT_EVAL_V3_SUITE_VERSION",
    "SUITE_VERSION",
    "RtlRepoSuite",
]
