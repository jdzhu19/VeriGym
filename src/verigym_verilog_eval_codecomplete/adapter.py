"""VeriGym adapter for externally supplied VerilogEval V2 code-completion tasks."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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
    RuntimeRequirement,
    ScoringSpec,
    SourceSpec,
    SubmissionPolicy,
    SuiteAdapter,
    SuiteDescriptor,
    SuiteSourceConfig,
    SuiteSourceSnapshot,
    TaskRef,
    TaskType,
    ToolchainProfile,
    ToolRequirement,
    ToolVisibility,
    ValidationIssue,
    ValidationReport,
    VerifierGraph,
    VerifierNode,
    VeriTask,
    WorkspaceSpec,
)

from .layout import (
    NATIVE_LAYOUT,
    VARIANT,
    Catalog,
    Problem,
    inspect_layout,
    resolve_layout,
    sha256_bytes,
    transform_reference,
)

ADAPTER_VERSION = "0.1.0"
SUITE_VERSION = "v2-code-complete-iccad2023-compat-1"


class VerilogEvalCodeCompleteSuite(SuiteAdapter):
    """Read-only adapter registered from an independently installed distribution."""

    descriptor = SuiteDescriptor(
        schema_version=SCHEMA_VERSION,
        name="verilog-eval-code-complete",
        version=ADAPTER_VERSION,
        api_version=PLUGIN_API_VERSION,
        provider="verigym-verilog-eval-codecomplete",
        capabilities=[
            "external_source",
            VARIANT,
            "completion",
            "native_mismatch_regression",
            "conformance",
        ],
        title="VerilogEval V2 code completion",
        description=(
            "Out-of-tree adapter for the official VerilogEval V2 ICCAD 2023 code-completion layout."
        ),
        suite_version=SUITE_VERSION,
        license="MIT",
    )

    def __init__(self, config: SuiteSourceConfig | None = None) -> None:
        self._config = config
        self._catalog_cache: Catalog | None = None
        self._snapshot_cache: SuiteSourceSnapshot | None = None
        self._workspace_root = Path(__file__).parent / "assets" / "workspace"

    def with_source(self, config: SuiteSourceConfig) -> VerilogEvalCodeCompleteSuite:
        if config.variant not in {None, VARIANT}:
            raise ConfigurationError(f"suite supports only variant {VARIANT!r}")
        normalized = config.model_copy(update={"variant": VARIANT}, deep=True)
        return VerilogEvalCodeCompleteSuite(normalized)

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        adapter = self._adapter_for_optional_root(source_root)
        catalog = adapter._valid_catalog()
        return [
            TaskRef(
                id=f"{self.descriptor.name}/{VARIANT}/{problem.native_id}",
                suite=self.descriptor.name,
                native_id=problem.native_id,
                source_root=str(catalog.layout.source_root),
            )
            for problem in catalog.problems
        ]

    def load_task(self, ref: TaskRef) -> VeriTask:
        catalog = self._valid_catalog()
        problem = self._problem(catalog, ref.native_id)
        return self._normalize_task(problem, self._snapshot(catalog))

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        catalog = self._valid_catalog(refresh=True)
        if task.metadata.get("dataset_content_hash") != catalog.dataset_content_hash:
            raise ConfigurationError("VerilogEval dataset differs from the frozen task snapshot")
        native_id = task.metadata.get("native_task_id")
        if not isinstance(native_id, str):
            raise ConfigurationError("frozen task has no native task identifier")
        problem = self._problem(catalog, native_id)
        if task.source.content_hash != problem.content_hash:
            raise ConfigurationError("VerilogEval task differs from the frozen task snapshot")
        return ResolvedTaskAssets(
            visible_root=str(self._workspace_root.resolve(strict=True)),
            hidden_assets=[
                AssetRef(
                    kind="inline",
                    content=problem.reference,
                    content_hash=sha256_bytes(problem.reference.encode()),
                    mount_path="verifier/golden.sv",
                ),
                AssetRef(
                    kind="inline",
                    content=problem.testbench,
                    content_hash=sha256_bytes(problem.testbench.encode()),
                    mount_path="verifier/testbench.sv",
                ),
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
        problem = self._problem(self._valid_catalog(), native_id)
        return Candidate(
            files={"rtl/TopModule.sv": transform_reference(problem.reference)},
            label="reference-derived-conformance-only",
        )

    def conformance_cases(self) -> Iterable[ConformanceCase]:
        catalog = self._valid_catalog()
        if not catalog.problems:
            return []
        task = self._normalize_task(catalog.problems[0], self._snapshot(catalog))
        reference = self.reference_solution(task)
        assert reference is not None
        return [
            ConformanceCase(
                name=f"{catalog.problems[0].native_id}-reference",
                candidate=reference,
                expected_resolved=True,
            ),
            ConformanceCase(
                name=f"{catalog.problems[0].native_id}-wrong",
                candidate=Candidate(
                    files={"rtl/TopModule.sv": "module TopModule; endmodule\n"},
                    label="known-bad",
                ),
                expected_resolved=False,
            ),
        ]

    def source_snapshot(self) -> SuiteSourceSnapshot | None:
        if self._config is None:
            return None
        return self._snapshot(self._valid_catalog()).model_copy(deep=True)

    def toolchain_profile(self, runtime: Any, tools: Any) -> ToolchainProfile | None:
        image = runtime.descriptor.image
        if image is None:
            compiler_version = tools.get("verilog_eval.v2.compile").health_check().version
            runner_version = tools.get("verilog_eval.v2.regression").health_check().version
            compatibility = "unverified_tool_version"
        else:
            compiler_version = image.iverilog_version
            runner_version = image.vvp_version
            compatibility = image.compatibility_status or "unverified_tool_version"
        return ToolchainProfile(
            id="verilog-eval-v2-code-complete-icarus",
            version="1.0.0",
            description="VerilogEval V2 code-completion Icarus profile; reference version is 12.",
            tools=[
                ToolRequirement(name="iverilog", version=compiler_version),
                ToolRequirement(name="vvp", version=runner_version),
            ],
            runtime=RuntimeRequirement(runtime=runtime.descriptor.name),
            container_image=image.requested_reference if image is not None else None,
            container_digest=image.resolved_image_id if image is not None else None,
            deterministic=True,
            reproducibility_scope="public",
            compatibility_status=compatibility,
        )

    def _adapter_for_optional_root(self, source_root: Path | None) -> VerilogEvalCodeCompleteSuite:
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
                self._catalog_cache = inspect_layout(layout)
            except ValueError as exc:
                raise ConfigurationError(str(exc)) from exc
        return self._catalog_cache

    def _valid_catalog(self, *, refresh: bool = False) -> Catalog:
        catalog = self._catalog(refresh=refresh)
        errors = [issue for issue in catalog.issues if issue.level == "error"]
        if errors:
            preview = "; ".join(f"[{issue.code}] {issue.message}" for issue in errors[:3])
            raise ConfigurationError(f"invalid VerilogEval code-completion source: {preview}")
        return catalog

    def _snapshot(self, catalog: Catalog) -> SuiteSourceSnapshot:
        assert self._config is not None
        if self._snapshot_cache is None:
            license_id, license_hash = _license_metadata(catalog.layout.repository_root)
            git_commit, git_remote, git_available = _git_metadata(catalog.layout.repository_root)
            configuration = {
                "variant": VARIANT,
                "strict_compatibility": self._config.strict_compatibility,
                "dataset_content_hash": catalog.dataset_content_hash,
            }
            synthetic = (catalog.layout.repository_root / "VERIGYM_SYNTHETIC_FIXTURE").is_file()
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
                git_commit=git_commit,
                git_remote=git_remote,
                git_metadata_available=git_available,
                synthetic_fixture=synthetic,
            )
        return self._snapshot_cache

    @staticmethod
    def _problem(catalog: Catalog, native_id: str) -> Problem:
        problem = next((item for item in catalog.problems if item.native_id == native_id), None)
        if problem is None:
            raise ConfigurationError(f"unknown VerilogEval code-completion task: {native_id}")
        return problem

    def _normalize_task(
        self,
        problem: Problem,
        snapshot: SuiteSourceSnapshot,
    ) -> VeriTask:
        task_id = f"{self.descriptor.name}/{VARIANT}/{problem.native_id}"
        hidden_assets = [
            AssetRef(
                kind="inline",
                content_hash=sha256_bytes(problem.reference.encode()),
                mount_path="verifier/golden.sv",
            ),
            AssetRef(
                kind="inline",
                content_hash=sha256_bytes(problem.testbench.encode()),
                mount_path="verifier/testbench.sv",
            ),
        ]
        return VeriTask(
            id=task_id,
            suite=self.descriptor.name,
            suite_version=SUITE_VERSION,
            task_type=TaskType.COMPLETION,
            title=f"VerilogEval code completion {problem.native_id}",
            description=problem.prompt,
            source=SourceSpec(
                kind="synthetic" if snapshot.synthetic_fixture else "benchmark",
                uri=f"verilog-eval://{VARIANT}/{problem.native_id}",
                revision=SUITE_VERSION,
                commit=snapshot.git_commit,
                license=snapshot.license_id,
                attribution=(
                    "Synthetic layout-conformance fixture; not an official benchmark task."
                    if snapshot.synthetic_fixture
                    else "Externally supplied official NVlabs VerilogEval checkout."
                ),
                content_hash=problem.content_hash,
            ),
            workspace=WorkspaceSpec(
                base=AssetRef(kind="directory", path="workspace"),
                editable_globs=["rtl/TopModule.sv"],
                readonly_globs=["README.md"],
                excluded_globs=["verifier", "verifier/**", "hidden", "hidden/**"],
                entrypoints=["rtl/TopModule.sv"],
                hidden_assets=hidden_assets,
                max_changed_files=1,
                max_patch_lines=2_000,
            ),
            interaction=InteractionSpec(
                supported_modes=[InteractionMode.CHAT, InteractionMode.AGENT],
                default_mode=InteractionMode.CHAT,
                allowed_tools=["file.list", "file.read", "file.apply_patch", "file.diff"],
                allow_general_shell=False,
                network_policy="none",
                initial_observation=ObservationPolicy(
                    include_tree=True,
                    include_readme=True,
                    include_entrypoints=False,
                ),
                final_submission=SubmissionPolicy(kind="file", path="rtl/TopModule.sv"),
            ),
            budget=BudgetSpec(
                max_turns=20,
                max_tool_calls=40,
                max_model_calls=20,
                max_wall_time_s=300,
                max_tool_time_s=30,
                max_output_tokens=16_384,
                max_output_bytes_per_tool=1_000_000,
                max_workspace_bytes=2_000_000,
            ),
            verifier=VerifierGraph(
                nodes=[
                    VerifierNode(
                        id="compile_hidden",
                        plugin="verilog_eval.v2.compile",
                        gate=True,
                        required=True,
                        visibility=ToolVisibility.VERIFIER_ONLY,
                        timeout_s=30,
                        request={
                            "sources": [
                                "verifier/golden.sv",
                                "verifier/testbench.sv",
                                "rtl/TopModule.sv",
                            ],
                            "candidate": "rtl/TopModule.sv",
                            "top": problem.testbench_top,
                            "output": ".verigym_internal/verilog_eval/simv",
                            "language": "2012",
                        },
                    ),
                    VerifierNode(
                        id="run_hidden",
                        plugin="verilog_eval.v2.regression",
                        depends_on=["compile_hidden"],
                        gate=True,
                        required=True,
                        visibility=ToolVisibility.VERIFIER_ONLY,
                        timeout_s=30,
                        request={"executable_from": "compile_hidden"},
                    ),
                ]
            ),
            scoring=ScoringSpec(
                correctness_required_nodes=["compile_hidden", "run_hidden"],
                ppa_enabled=False,
            ),
            metadata={
                "benchmark_variant": VARIANT,
                "native_layout": NATIVE_LAYOUT,
                "native_task_id": problem.native_id,
                "candidate_top": "TopModule",
                "golden_top": "RefModule",
                "testbench_top": problem.testbench_top,
                "language": "systemverilog",
                "dataset_content_hash": snapshot.dataset_content_hash,
                "task_content_hash": problem.content_hash,
                "interface_hash": sha256_bytes(problem.interface.encode()),
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
    license_id = "MIT" if "mit license" in text and "permission is hereby granted" in text else None
    return license_id, sha256_bytes(data)


def _git_metadata(root: Path) -> tuple[str | None, str | None, bool]:
    if not (root / ".git").exists():
        return None, None, False
    commit = _git_read(root, ["rev-parse", "HEAD"])
    remote = _git_read(root, ["remote", "get-url", "origin"])
    return commit, _sanitize_remote(remote) if remote else None, commit is not None


def _git_read(root: Path, arguments: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _sanitize_remote(value: str) -> str | None:
    if re.match(r"^[^/@\s]+@[^/:\s]+:", value):
        _, host_path = value.split("@", 1)
        host, path = host_path.split(":", 1)
        return f"ssh://{host}/{path.lstrip('/')}"
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https", "ssh", "git"} or not parsed.hostname:
        return None
    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return None
    return urlunsplit((parsed.scheme, f"{parsed.hostname}{port}", parsed.path, "", ""))


__all__ = ["ADAPTER_VERSION", "SUITE_VERSION", "VerilogEvalCodeCompleteSuite"]
