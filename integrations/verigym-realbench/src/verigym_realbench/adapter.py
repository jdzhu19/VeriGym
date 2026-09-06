"""Draft module projection. Execution fails closed until both fixed backends are supplied."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from verigym_cadence.protocol import bounded_read

from verigym.core.agent_feedback_assets import (
    AgentEvalWorkspace,
    compile_feedback_contract,
    materialize_agent_eval_workspace,
)
from verigym.plugin_api import ConfigurationError, SuiteAdapter, content_hash
from verigym.schemas.common import (
    AssetRef,
    InteractionMode,
    SuiteDescriptor,
    TaskType,
    ToolVisibility,
)
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.schemas.task import (
    BudgetSpec,
    InteractionSpec,
    ResolvedTaskAssets,
    ScoringSpec,
    SourceSpec,
    SubmissionPolicy,
    TaskRef,
    ValidationReport,
    VeriTask,
    WorkspaceSpec,
)
from verigym.schemas.verifier import VerifierGraph, VerifierNode

from .source import UPSTREAM, VARIANT, ModuleTask, SourceLock, load_source


class RealBenchSuite(SuiteAdapter):
    descriptor = SuiteDescriptor(
        name="realbench",
        version="0.1.0",
        provider="verigym-realbench",
        title="RealBench bounded module projection (draft)",
        description="Operator-audited source projection; not suite-qualified or a native score.",
        suite_version=VARIANT,
        capabilities=["external_source", "module_slice", "draft"],
    )

    def __init__(self, config: SuiteSourceConfig | None = None) -> None:
        self.config = config
        self._workspaces: list[AgentEvalWorkspace] = []

    def with_source(self, config: SuiteSourceConfig) -> RealBenchSuite:
        if config.variant not in {None, VARIANT}:
            raise ConfigurationError("RealBench only exposes the draft bounded module slice")
        return RealBenchSuite(config)

    def _source(self, root: Path | None = None) -> tuple[Path, SourceLock]:
        selected = root if root is not None else self.config.source_root if self.config else None
        if selected is None:
            raise ConfigurationError(
                "provide an audited external RealBench checkout and source lock"
            )
        try:
            return selected, load_source(selected)
        except Exception as exc:
            raise ConfigurationError("RealBench source lock/layout/hash validation failed") from exc

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        root, lock = self._source(source_root)
        for task in lock.tasks:
            yield TaskRef(
                id=self._id(task, lock),
                suite="realbench",
                native_id=task.native_id,
                source_root=str(root),
            )

    @staticmethod
    def _id(task: ModuleTask, lock: SourceLock) -> str:
        return f"realbench/{VARIANT}/{lock.identity[:16]}/{task.native_id}"

    def _manifest(
        self, task_id: str, root: Path | None = None
    ) -> tuple[Path, SourceLock, ModuleTask]:
        selected, lock = self._source(root)
        for task in lock.tasks:
            if self._id(task, lock) == task_id:
                return selected, lock, task
        raise ConfigurationError("RealBench task differs from the current source identity")

    @staticmethod
    def _sources(manifest: ModuleTask) -> list[str]:
        return [a.destination for a in manifest.assets if a.role == "stub" and a.destination]

    @staticmethod
    def _contract(manifest: ModuleTask) -> dict[str, object]:
        return compile_feedback_contract(
            source_paths=[
                path.removeprefix("repository/") for path in RealBenchSuite._sources(manifest)
            ],
            top_module=manifest.top,
            language="2012",
            backend="verilator",
        )

    def load_task(self, ref: TaskRef) -> VeriTask:
        root, lock, manifest = self._manifest(
            ref.id, Path(ref.source_root) if ref.source_root else None
        )
        if ref.suite != "realbench" or ref.native_id != manifest.native_id:
            raise ConfigurationError("RealBench task reference mismatch")
        spec = "\n\n".join(
            bounded_read(root / a.path).decode("utf-8") for a in manifest.assets if a.role == "spec"
        )
        sources = self._sources(manifest)
        readonly = [a.destination for a in manifest.assets if a.destination and a.role != "stub"]
        return VeriTask(
            id=ref.id,
            suite="realbench",
            suite_version=VARIANT,
            task_type=TaskType.GENERATION,
            title=manifest.native_id,
            description=spec,
            source=SourceSpec(
                kind="synthetic" if lock.synthetic_fixture else "benchmark",
                uri=UPSTREAM,
                commit=lock.commit,
                content_hash=lock.identity,
                license="MIT",
                attribution="RealBench, IPRC-DIP; external assets only",
            ),
            workspace=WorkspaceSpec(
                base=AssetRef(kind="directory", path="visible"),
                editable_globs=sources,
                readonly_globs=["TASK.md", "PUBLIC_TESTS.md", *readonly],
                excluded_globs=["verifier/**", "hidden/**"],
                entrypoints=sources,
                max_changed_files=len(sources),
                max_patch_lines=8000,
            ),
            interaction=InteractionSpec(
                supported_modes=[InteractionMode.AGENT],
                default_mode=InteractionMode.AGENT,
                allowed_tools=[
                    "file.list",
                    "file.read",
                    "file.apply_patch",
                    "file.apply_codex_patch",
                    "file.diff",
                    "repository.public_test",
                ],
                allow_general_shell=False,
                network_policy="none",
                final_submission=SubmissionPolicy(kind="workspace"),
            ),
            budget=BudgetSpec(
                max_turns=20,
                max_tool_calls=40,
                max_wall_time_s=1800,
                max_workspace_bytes=32 * 1024 * 1024,
            ),
            verifier=VerifierGraph(
                nodes=[
                    VerifierNode(
                        id="formal_hidden",
                        plugin="realbench.sec",
                        visibility=ToolVisibility.VERIFIER_ONLY,
                        request={"sources": sources, "top": manifest.top, "timeout_s": 300},
                    )
                ]
            ),
            scoring=ScoringSpec(correctness_required_nodes=["formal_hidden"]),
            metadata={
                "diagnostic_only": True,
                "benchmark_score_claimed": False,
                "qualification_status": "draft",
                "partition": "module",
                "module_kind": manifest.kind,
                "source_lock_hash": lock.identity,
                "agent_eval": {
                    "benchmark_variant": VARIANT,
                    "compile_test_id": "compile",
                    "ppa_supported": False,
                    "public_test_contract_hash": content_hash(self._contract(manifest)),
                },
                "required_verifier_profile_target": "cadence.jaspergold.sec.mcp",
                # Mandatory backend prevents falling back to lint-only and calling it functional.
                "required_public_test_profile_target": "realbench.verilator.public.mcp",
                "public_test_profile_source_plugin": "repository.public_test",
                "public_test_profile_test_id": "compile",
                "public_test_profile_sources": sources,
                "public_test_profile_top": manifest.top,
                "native_metrics": ["syntax@k", "func@k", "formal@k"],
            },
        )

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        root, lock, manifest = self._manifest(task.id)
        if task.source.content_hash != lock.identity:
            raise ConfigurationError("RealBench task source drift")
        files = {
            a.destination.removeprefix("repository/"): bounded_read(root / a.path).decode()
            for a in manifest.assets
            if a.destination and a.role != "image"
        }
        workspace = materialize_agent_eval_workspace(
            task_description=task.description,
            repository_files=files,
            compile_contract=self._contract(manifest),
            ppa_available=False,
        )
        for asset in manifest.assets:
            if asset.role == "image" and asset.destination is not None:
                destination = workspace.visible_root / asset.destination
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(bounded_read(root / asset.path))
        self._workspaces.append(workspace)
        return ResolvedTaskAssets(
            visible_root=str(workspace.visible_root),
            read_only_mounts=[workspace.read_only_mount] if workspace.read_only_mount else [],
        )

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        try:
            self._source(source_root)
            return ValidationReport(valid=True, warnings=["Draft projection; not suite-qualified"])
        except ConfigurationError:
            return ValidationReport(
                valid=False, errors=["External source/lock is unavailable or invalid"]
            )

    def source_snapshot(self) -> SuiteSourceSnapshot:
        root, lock = self._source()
        return SuiteSourceSnapshot(
            source_root=str(root),
            dataset_root=str(root),
            variant=VARIANT,
            native_layout="operator-audited-module-projection-v1",
            strict_compatibility=True,
            configuration_fingerprint=lock.identity,
            dataset_content_hash=lock.identity,
            license_id="MIT",
            license_file_hash=lock.license_sha256,
            git_commit=lock.commit,
            git_remote=UPSTREAM,
            git_metadata_available=not lock.synthetic_fixture,
            synthetic_fixture=lock.synthetic_fixture,
        )
