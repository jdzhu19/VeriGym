"""Pinned, metadata-driven external-source RTLLM task adapter."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.synthesis_projection import synthesis_source_projection_contract
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
    Runtime,
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
    compile_feedback_contract,
    compile_smoke_feedback_contract,
    content_hash,
    materialize_agent_eval_workspace,
)

from .known_bad import known_bad_source
from .manifest import (
    ALL_TASK_NAMES,
    FROZEN_DATASET_FILES_HASH,
    FROZEN_FILE_COUNT,
    FROZEN_TASK_COUNT,
    FROZEN_TASK_TREES,
    FROZEN_TASK_TREES_HASH,
    HARDER_TASK_NAMES,
    L2_BATCH1_TASK_NAMES,
    L2_BATCH2_TASK_NAMES,
    TASK_MANIFESTS,
    RTLLMTaskManifest,
)

ADAPTER_VERSION = "0.3.0"
SUITE_VERSION = "rtllm-41b2689-counter12-v1"
UP_DOWN_SUITE_VERSION = "rtllm-41b2689-up-down-counter-v1"
UP_DOWN_ICARUS_TRAINING_SUITE_VERSION = "rtllm-41b2689-up-down-counter-icarus-training-v1"
AGENT_EVAL_SUITE_VERSION = "rtllm-41b2689-agent-eval-v1"
FUNCTIONAL_AGENT_EVAL_SUITE_VERSION = "rtllm-41b2689-agent-eval-functional-v1"
FUNCTIONAL_AGENT_EVAL_ADAPTER_VERSION = "0.4.0"
FUNCTIONAL_AGENT_EVAL_V2_SUITE_VERSION = "rtllm-41b2689-agent-eval-functional-v2"
FUNCTIONAL_AGENT_EVAL_V2_ADAPTER_VERSION = "0.5.0"
HARDER_VARIANT = "v2-agent-eval-functional-harder-v1"
HARDER_SUITE_VERSION = "rtllm-41b2689-v2-agent-eval-functional-harder-v1"
HARDER_ADAPTER_VERSION = "0.6.0"
ALL_AGENT_EVAL_VARIANT = "v2-agent-eval-all-v1"
ALL_AGENT_EVAL_SUITE_VERSION = "rtllm-41b2689-v2-agent-eval-all-v1"
ALL_AGENT_EVAL_ADAPTER_VERSION = "0.7.0"
L2_BATCH1_VARIANT = "v2-agent-eval-functional-l2-batch1-v1"
L2_BATCH1_SUITE_VERSION = "rtllm-41b2689-v2-agent-eval-functional-l2-batch1-v1"
L2_BATCH1_ADAPTER_VERSION = "0.8.0"
L2_BATCH1_PUBLIC_SMOKE_SHA256 = {
    "adder_pipe_64bit": "88adcd3f90593f9666ae41ac0da44f375f102f07e9446c077a3039a135783c83",
    "LFSR": "9ce56236593435d22094b1389ccf8e96ffcaa1303b4671bad9ac3ecce5f513c6",
    "serial2parallel": "c2f61e7deb14b929a3aa21e22cb018c06805317ea8764cb700970da1ed850361",
}
L2_BATCH2_VARIANT = "v2-agent-eval-functional-l2-batch2-v1"
L2_BATCH2_SUITE_VERSION = "rtllm-41b2689-v2-agent-eval-functional-l2-batch2-v1"
L2_BATCH2_ADAPTER_VERSION = "0.9.0"
L2_BATCH2_PUBLIC_SMOKE_SHA256 = {
    "sequence_detector": "822d602bc674ee5b52bd3fb419b9682e398555ada400cdd064eedacfdac724ce",
    "synchronizer": "ce1663a66d4c9cb93f6328559bc5a6c6bc35565cfa04bcf1a4ab0b9c4dd7a296",
    "RAM": "57b07132eaee886a2957730036fd879ea9bddc2b242aada596afdc654acba464",
}


@dataclass(frozen=True)
class _FunctionalBatchSpec:
    task_names: tuple[str, ...]
    suite_version: str
    adapter_version: str
    workspace_asset: str
    public_smoke_asset: str
    public_smoke_sha256: dict[str, str]
    evaluation_profile: str
    public_feedback_semantics: str


_FUNCTIONAL_BATCH_SPECS = {
    L2_BATCH1_VARIANT: _FunctionalBatchSpec(
        task_names=L2_BATCH1_TASK_NAMES,
        suite_version=L2_BATCH1_SUITE_VERSION,
        adapter_version=L2_BATCH1_ADAPTER_VERSION,
        workspace_asset="workspace_l2_batch1",
        public_smoke_asset="public_smoke_l2_batch1",
        public_smoke_sha256=L2_BATCH1_PUBLIC_SMOKE_SHA256,
        evaluation_profile="icarus12-agent-eval-functional-l2-batch1-v1",
        public_feedback_semantics="compile_and_independent_functional_smoke_l2_batch1_v1",
    ),
    L2_BATCH2_VARIANT: _FunctionalBatchSpec(
        task_names=L2_BATCH2_TASK_NAMES,
        suite_version=L2_BATCH2_SUITE_VERSION,
        adapter_version=L2_BATCH2_ADAPTER_VERSION,
        workspace_asset="workspace_l2_batch2",
        public_smoke_asset="public_smoke_l2_batch2",
        public_smoke_sha256=L2_BATCH2_PUBLIC_SMOKE_SHA256,
        evaluation_profile="icarus12-agent-eval-functional-l2-batch2-v1",
        public_feedback_semantics="compile_and_independent_functional_smoke_l2_batch2_v1",
    ),
}
PINNED_COMMIT = "41b26896e33b536940116a975626455eed3de65e"
CANONICAL_REMOTE = "https://github.com/hkust-zhiyao/RTLLM.git"
LICENSE_SHA256 = "a32206bcfbf5d6bb23be8a876de424d8a8d2a0e30a9adc9f8e1b3139fada9176"

_UP_DOWN_ICARUS_TRAINING_VARIANT = "up_down_counter_iverilog_training"
_AGENT_EVAL_VARIANTS = frozenset({"counter_12_agent_eval_v1", "up_down_counter_agent_eval_v1"})
_FUNCTIONAL_AGENT_EVAL_VARIANTS = frozenset(
    {
        "counter_12_agent_eval_functional_v1",
        "up_down_counter_agent_eval_functional_v1",
        "counter_12_agent_eval_functional_v2",
        "up_down_counter_agent_eval_functional_v2",
    }
)
_SUPPORTED_VARIANTS = frozenset(
    {
        "counter_12",
        "up_down_counter",
        _UP_DOWN_ICARUS_TRAINING_VARIANT,
        ALL_AGENT_EVAL_VARIANT,
        HARDER_VARIANT,
        *_FUNCTIONAL_BATCH_SPECS,
        *_AGENT_EVAL_VARIANTS,
        *_FUNCTIONAL_AGENT_EVAL_VARIANTS,
    }
)
_MULTI_TASK_VARIANTS = {
    ALL_AGENT_EVAL_VARIANT: ALL_TASK_NAMES,
    HARDER_VARIANT: HARDER_TASK_NAMES,
    **{variant: spec.task_names for variant, spec in _FUNCTIONAL_BATCH_SPECS.items()},
}
_FUNCTIONAL_MULTI_TASK_VARIANTS = frozenset({HARDER_VARIANT, *_FUNCTIONAL_BATCH_SPECS})
_NO_PPA_AGENT_EVAL_VARIANTS = frozenset({ALL_AGENT_EVAL_VARIANT, *_FUNCTIONAL_BATCH_SPECS})
_BENCHMARK_ROOTS = ("Arithmetic", "Control", "Memory", "Miscellaneous")
_MAX_SOURCE_BYTES = 2 * 1024 * 1024


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_exact(root: Path, relative: str) -> bytes:
    path = root / relative
    if path.is_symlink():
        raise ValueError(f"RTLLM source cannot contain a symlink: {relative}")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError(f"RTLLM source path escapes its root: {relative}")
    if not resolved.is_file() or resolved.stat().st_size > _MAX_SOURCE_BYTES:
        raise ValueError(f"RTLLM source is missing or too large: {relative}")
    return resolved.read_bytes()


def _git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else None


class RTLLMSuite(SuiteAdapter):
    descriptor = SuiteDescriptor(
        schema_version=SCHEMA_VERSION,
        name="rtllm",
        version=ADAPTER_VERSION,
        api_version=PLUGIN_API_VERSION,
        provider="verigym-rtllm",
        capabilities=[
            "external_source",
            "generation",
            "chat",
            "agent",
            "commercial_verification",
            "open_source_training_verification",
            "synthesis_ready",
            "conformance",
            "metadata_driven_tasks",
        ],
        title="RTLLM pinned metadata-driven adapter",
        description="Pinned external-source RTLLM tasks with qualified functional projections.",
        suite_version=SUITE_VERSION,
        license="MIT",
    )

    def __init__(self, config: SuiteSourceConfig | None = None) -> None:
        self._config = config
        assets = Path(__file__).parent / "assets"
        self._workspace_root = assets / "workspace"
        self._up_down_workspace_root = assets / "workspace_up_down"
        self._harder_workspace_root = assets / "workspace_harder"
        self._all_workspace_root = assets / "workspace_all"
        self._functional_batch_workspace_roots = {
            variant: assets / spec.workspace_asset
            for variant, spec in _FUNCTIONAL_BATCH_SPECS.items()
        }
        self._snapshot_cache: SuiteSourceSnapshot | None = None
        self._agent_workspaces: list[AgentEvalWorkspace] = []

    def with_source(self, config: SuiteSourceConfig) -> RTLLMSuite:
        if config.variant not in {None, *_SUPPORTED_VARIANTS}:
            supported = ", ".join(sorted(_SUPPORTED_VARIANTS))
            raise ConfigurationError(f"the RTLLM adapter supports variants: {supported}")
        return RTLLMSuite(config.model_copy(update={"variant": config.variant or "counter_12"}))

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        adapter = self._adapter_for_optional_root(source_root)
        report = adapter.validate_source()
        if not report.valid:
            raise ConfigurationError("invalid RTLLM source: " + "; ".join(report.errors[:3]))
        variant = adapter._variant()
        if variant in _MULTI_TASK_VARIANTS:
            names = _MULTI_TASK_VARIANTS[variant]
            return [
                TaskRef(
                    id=f"rtllm/{variant}/{name}",
                    suite="rtllm",
                    native_id=name,
                )
                for name in names
            ]
        return [TaskRef(id=f"rtllm/{variant}", suite="rtllm", native_id=variant)]

    def load_task(self, ref: TaskRef) -> VeriTask:
        manifest = self._manifest_for_ref(ref)
        variant = self._variant()
        harder = variant == HARDER_VARIANT
        all_agent_eval = variant == ALL_AGENT_EVAL_VARIANT
        multi_task_variant = variant in _MULTI_TASK_VARIANTS
        icarus_training = variant == _UP_DOWN_ICARUS_TRAINING_VARIANT
        agent_eval = (
            multi_task_variant or variant in _AGENT_EVAL_VARIANTS | _FUNCTIONAL_AGENT_EVAL_VARIANTS
        )
        functional_agent_eval = (
            variant in _FUNCTIONAL_MULTI_TASK_VARIANTS or variant in _FUNCTIONAL_AGENT_EVAL_VARIANTS
        )
        functional_v2 = variant.endswith("_agent_eval_functional_v2")
        suite_version = self._suite_version(manifest)
        candidate_path = self._candidate_path(manifest)
        root = self._source_root()
        report = self.validate_source()
        if not report.valid:
            raise ConfigurationError("invalid RTLLM source: " + "; ".join(report.errors[:3]))
        upstream_prompt = _read_exact(root, f"{manifest.root}/{manifest.prompt_file}").decode(
            "utf-8"
        )
        derived_note = (
            self._derived_projection_note(manifest, compile_only=all_agent_eval)
            if multi_task_variant
            else ""
        )
        description = (
            upstream_prompt.rstrip() + "\n\n---\n\n" + derived_note.rstrip() + "\n"
            if multi_task_variant
            else upstream_prompt
        )
        snapshot = self._snapshot()
        hidden_assets = self._hidden_asset_declarations(manifest)
        public_smoke = self._public_smoke(manifest.name) if functional_agent_eval else None
        public_contract = (
            compile_smoke_feedback_contract(
                source_paths=[f"rtl/{manifest.name}.v"],
                top_module=manifest.candidate_top,
                language="2012" if multi_task_variant else "2005",
                public_testbench=public_smoke,
            )
            if public_smoke is not None
            else compile_feedback_contract(
                source_paths=[f"rtl/{manifest.name}.v"],
                top_module=manifest.candidate_top,
                language="2012" if multi_task_variant else "2005",
            )
            if agent_eval
            else None
        )
        task_id = self._task_id(manifest)
        return VeriTask(
            id=task_id,
            suite="rtllm",
            suite_version=suite_version,
            task_type=TaskType.GENERATION,
            title=manifest.title,
            description=description,
            source=SourceSpec(
                kind="benchmark",
                uri=f"https://github.com/hkust-zhiyao/RTLLM/tree/{PINNED_COMMIT}/{manifest.root}",
                revision=suite_version,
                commit=PINNED_COMMIT,
                license="MIT",
                attribution="RTLLM, supplied as an external pinned checkout.",
                content_hash=snapshot.dataset_content_hash,
            ),
            workspace=WorkspaceSpec(
                base=AssetRef(kind="directory", path=self._workspace_asset_name(manifest)),
                editable_globs=[candidate_path],
                readonly_globs=(
                    ["TASK.md", "PUBLIC_TESTS.md", "repository/README.md"]
                    if agent_eval
                    else ["README.md"]
                ),
                excluded_globs=[
                    "verifier",
                    "verifier/**",
                    "hidden",
                    "hidden/**",
                    *manifest.auxiliary_files,
                ],
                entrypoints=[candidate_path],
                hidden_assets=hidden_assets,
                max_changed_files=1,
                max_patch_lines=4_000 if multi_task_variant else 2_000,
            ),
            interaction=InteractionSpec(
                supported_modes=(
                    [InteractionMode.AGENT]
                    if agent_eval
                    else [InteractionMode.CHAT, InteractionMode.AGENT]
                ),
                default_mode=InteractionMode.AGENT if agent_eval else InteractionMode.CHAT,
                allowed_tools=[
                    "file.list",
                    "file.read",
                    "file.apply_patch",
                    *(["file.apply_codex_patch"] if multi_task_variant or functional_v2 else []),
                    "file.diff",
                    *(["repository.public_test"] if agent_eval else []),
                ],
                allow_general_shell=False,
                network_policy="none",
                initial_observation=ObservationPolicy(
                    include_tree=True,
                    include_readme=True,
                    include_entrypoints=False,
                ),
                final_submission=SubmissionPolicy(kind="file", path=candidate_path),
            ),
            budget=BudgetSpec(
                max_turns=20,
                max_tool_calls=40,
                max_model_calls=20,
                max_wall_time_s=900,
                max_tool_time_s=300,
                max_output_tokens=16_384,
                max_output_bytes_per_tool=1_000_000,
                max_workspace_bytes=4_000_000 if multi_task_variant else 2_000_000,
            ),
            verifier=self._verifier_graph(
                manifest,
                candidate_path=candidate_path,
                icarus=icarus_training or agent_eval,
                isolated_icarus=multi_task_variant,
            ),
            scoring=ScoringSpec(
                correctness_required_nodes=(
                    ["functional_hidden"]
                    if multi_task_variant
                    else ["compile_hidden", "run_hidden"]
                    if icarus_training or agent_eval
                    else ["vcs_regression"]
                ),
                ppa_enabled=(not icarus_training and variant not in _NO_PPA_AGENT_EVAL_VARIANTS),
            ),
            metadata=self._task_metadata(
                manifest,
                variant=variant,
                snapshot=snapshot,
                candidate_path=candidate_path,
                public_contract=public_contract,
                upstream_prompt=upstream_prompt,
                derived_note=derived_note,
                agent_eval=agent_eval,
                functional_agent_eval=functional_agent_eval,
                functional_v2=functional_v2,
                harder=harder,
                icarus_training=icarus_training,
            ),
        )

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        manifest = self._manifest_for_task(task)
        snapshot = self._snapshot()
        if task.source.content_hash != snapshot.dataset_content_hash:
            raise ConfigurationError("RTLLM task identity differs from the source snapshot")
        variant = self._variant()
        agent_eval = (
            variant in _MULTI_TASK_VARIANTS
            or variant in _AGENT_EVAL_VARIANTS | _FUNCTIONAL_AGENT_EVAL_VARIANTS
        )
        functional = (
            variant in _FUNCTIONAL_MULTI_TASK_VARIANTS or variant in _FUNCTIONAL_AGENT_EVAL_VARIANTS
        )
        if agent_eval:
            base_workspace = self._base_workspace(manifest)
            smoke = self._public_smoke(manifest.name) if functional else None
            contract = (
                compile_smoke_feedback_contract(
                    source_paths=[f"rtl/{manifest.name}.v"],
                    top_module=manifest.candidate_top,
                    language=("2012" if variant in _MULTI_TASK_VARIANTS else "2005"),
                    public_testbench=smoke,
                )
                if smoke is not None
                else compile_feedback_contract(
                    source_paths=[f"rtl/{manifest.name}.v"],
                    top_module=manifest.candidate_top,
                    language="2012" if variant in _MULTI_TASK_VARIANTS else "2005",
                )
            )
            materialized = materialize_agent_eval_workspace(
                task_description=task.description,
                repository_files={
                    "README.md": self._repository_readme(manifest),
                    f"rtl/{manifest.name}.v": (
                        self._candidate_stub(manifest)
                        if variant == ALL_AGENT_EVAL_VARIANT
                        else (base_workspace / "rtl" / f"{manifest.name}.v").read_text(
                            encoding="utf-8"
                        )
                    ),
                },
                compile_contract=contract,
                ppa_available=variant not in _NO_PPA_AGENT_EVAL_VARIANTS,
                public_asset_files=(
                    {"assets/public-smoke.sv": smoke} if smoke is not None else None
                ),
            )
            self._agent_workspaces.append(materialized)
            visible_root = str(materialized.visible_root)
            read_only_mounts = (
                [materialized.read_only_mount] if materialized.read_only_mount is not None else []
            )
        else:
            visible_root = str(self._base_workspace(manifest).resolve(strict=True))
            read_only_mounts = []
        hidden = [
            self._resolved_hidden_asset(manifest, manifest.testbench_file, "verifier/testbench.v"),
            *(
                self._resolved_hidden_asset(manifest, name, name)
                for name in manifest.auxiliary_files
            ),
        ]
        return ResolvedTaskAssets(
            visible_root=visible_root,
            hidden_assets=hidden,
            read_only_mounts=read_only_mounts,
        )

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        try:
            adapter = self._adapter_for_optional_root(source_root)
            root = adapter._source_root()
        except ConfigurationError as exc:
            return _invalid("source_configuration", str(exc))
        issues: list[ValidationIssue] = []
        adapter._validate_expected_file(root, "LICENSE", LICENSE_SHA256, issues)
        if adapter._variant() in _MULTI_TASK_VARIANTS:
            adapter._validate_frozen_inventory(root, issues)
        else:
            manifest = TASK_MANIFESTS[adapter._base_variant()]
            for relative, expected in sorted(manifest.expected_hashes.items()):
                adapter._validate_expected_file(root, relative, expected, issues)
        commit = _git_commit(root)
        if adapter._config is not None and adapter._config.strict_compatibility:
            if commit is None:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="git_identity",
                        message="strict compatibility requires checkout Git metadata",
                    )
                )
            elif commit != PINNED_COMMIT:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="git_commit",
                        message=f"checkout must be at pinned commit {PINNED_COMMIT}",
                    )
                )
        errors = [f"[{item.code}] {item.message}" for item in issues]
        return ValidationReport(valid=not errors, errors=errors, issues=issues)

    def reference_solution(self, task: VeriTask) -> Candidate | None:
        manifest = self._manifest_for_task(task)
        source = _read_exact(
            self._source_root(), f"{manifest.root}/{manifest.reference_file}"
        ).decode("utf-8")
        if manifest.reference_module != manifest.candidate_top:
            pattern = re.compile(
                rf"(?m)(\bmodule\s+){re.escape(manifest.reference_module)}(?=\s|#|\()"
            )
            source, replacements = pattern.subn(rf"\1{manifest.candidate_top}", source, count=1)
            if replacements != 1 or pattern.search(source) is not None:
                raise ConfigurationError("RTLLM reference module normalization is no longer exact")
        return Candidate(
            files={self._candidate_path(manifest): source},
            label="pinned-upstream-reference",
        )

    def conformance_cases(self) -> Iterable[ConformanceCase]:
        if self._config is None:
            return []
        cases: list[ConformanceCase] = []
        for ref in self.discover():
            task = self.load_task(ref)
            reference = self.reference_solution(task)
            assert reference is not None
            manifest = self._manifest_for_task(task)
            cases.append(
                ConformanceCase(
                    name=f"{manifest.name}-reference",
                    candidate=reference,
                    expected_resolved=True,
                )
            )
            categories = (
                ("stuck-zero", "reset-error", "protocol-latency-error", "functional-error")
                if self._variant() in _FUNCTIONAL_MULTI_TASK_VARIANTS
                else ()
                if self._variant() == ALL_AGENT_EVAL_VARIANT
                else ("stuck-zero",)
            )
            for category in categories:
                cases.append(
                    ConformanceCase(
                        name=f"{manifest.name}-{category}",
                        candidate=Candidate(
                            files={
                                self._candidate_path(manifest): known_bad_source(
                                    manifest.name, category
                                )
                            },
                            label=f"known-bad-{category}",
                        ),
                        expected_resolved=False,
                    )
                )
            if self._variant() == ALL_AGENT_EVAL_VARIANT:
                cases.append(
                    ConformanceCase(
                        name=f"{manifest.name}-missing-module",
                        candidate=Candidate(
                            files={self._candidate_path(manifest): self._candidate_stub(manifest)},
                            label="known-bad-missing-module",
                        ),
                        expected_resolved=False,
                    )
                )
        return cases

    def public_conformance_cases(self, task: VeriTask) -> Iterable[ConformanceCase]:
        """Return public-only qualification cases; never materialized for the model."""

        manifest = self._manifest_for_task(task)
        reference = self.reference_solution(task)
        assert reference is not None
        if self._variant() == ALL_AGENT_EVAL_VARIANT:
            return [
                ConformanceCase(
                    name=f"{manifest.name}-public-reference",
                    candidate=reference,
                    expected_resolved=True,
                ),
                ConformanceCase(
                    name=f"{manifest.name}-public-missing-module",
                    candidate=Candidate(
                        files={self._candidate_path(manifest): self._candidate_stub(manifest)},
                        label="known-bad-missing-module",
                    ),
                    expected_resolved=False,
                ),
            ]
        return [
            ConformanceCase(
                name=f"{manifest.name}-public-reference",
                candidate=reference,
                expected_resolved=True,
            ),
            *(
                ConformanceCase(
                    name=f"{manifest.name}-public-{category}",
                    candidate=Candidate(
                        files={
                            self._candidate_path(manifest): known_bad_source(
                                manifest.name, category
                            )
                        },
                        label=f"known-bad-{category}",
                    ),
                    expected_resolved=False,
                )
                for category in (
                    "stuck-zero",
                    "reset-error",
                    "protocol-latency-error",
                    "functional-error",
                )
            ),
        ]

    def source_snapshot(self) -> SuiteSourceSnapshot | None:
        if self._config is None:
            return None
        return self._snapshot().model_copy(deep=True)

    def toolchain_profile(self, runtime: Runtime, tools: Any) -> ToolchainProfile | None:
        agent_eval = (
            self._variant() in _MULTI_TASK_VARIANTS
            or self._variant() in _AGENT_EVAL_VARIANTS | _FUNCTIONAL_AGENT_EVAL_VARIANTS
        )
        if self._variant() == _UP_DOWN_ICARUS_TRAINING_VARIANT or agent_eval:
            image = runtime.descriptor.image
            if image is None:
                compiler = tools.get("iverilog.compile").health_check()
                runner = tools.get("iverilog.run").health_check()
                compiler_version = compiler.version
                runner_version = runner.version
                compatibility = (
                    "available" if compiler.healthy and runner.healthy else "unavailable"
                )
            else:
                compiler_version = image.iverilog_version
                runner_version = image.vvp_version
                compatibility = image.compatibility_status or "unverified_tool_version"
            if agent_eval and not all(
                _is_icarus12_version(version) for version in (compiler_version, runner_version)
            ):
                raise ConfigurationError(
                    "RTLLM AgentEval requires qualified Icarus and vvp major version 12"
                )
            if agent_eval:
                compatibility = "reference_compatible"
            return ToolchainProfile(
                id=(
                    "rtllm-icarus12-agent-eval-harder-v1"
                    if self._variant() == HARDER_VARIANT
                    else "rtllm-icarus12-agent-eval-l2-batch1-v1"
                    if self._variant() == L2_BATCH1_VARIANT
                    else "rtllm-icarus12-agent-eval-all-v1"
                    if self._variant() == ALL_AGENT_EVAL_VARIANT
                    else "rtllm-icarus12-agent-eval-v1"
                    if agent_eval
                    else "rtllm-icarus-training-v1"
                ),
                version="1.0.0",
                description=(
                    "Pinned Icarus functional verifier for an RTLLM AgentEval partition."
                    if agent_eval
                    else "Pinned Icarus training verifier; not a VCS benchmark result."
                ),
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
        health = tools.get("synopsys.vcs.simulate").health_check()
        return ToolchainProfile(
            id="rtllm-vcs-site",
            version="1.0.0",
            description="Site-local VCS functional-verification profile for RTLLM.",
            tools=[
                ToolRequirement(
                    name="vcs",
                    version=health.version,
                    executable=health.executable,
                    capabilities=["simulation", "systemverilog"],
                )
            ],
            runtime=RuntimeRequirement(runtime=runtime.descriptor.name),
            deterministic=True,
            reproducibility_scope="site_specific",
            compatibility_status="available" if health.healthy else "unavailable",
        )

    def _adapter_for_optional_root(self, source_root: Path | None) -> RTLLMSuite:
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

    def _variant(self) -> str:
        if self._config is None:
            return "counter_12"
        return self._config.variant or "counter_12"

    def _base_variant(self) -> str:
        variant = self._variant()
        if variant in _MULTI_TASK_VARIANTS:
            raise ConfigurationError("the RTLLM variant contains multiple native tasks")
        if variant == _UP_DOWN_ICARUS_TRAINING_VARIANT:
            return "up_down_counter"
        for suffix in (
            "_agent_eval_functional_v1",
            "_agent_eval_functional_v2",
            "_agent_eval_v1",
        ):
            if variant.endswith(suffix):
                return variant.removesuffix(suffix)
        return variant

    def _manifest_for_ref(self, ref: TaskRef) -> RTLLMTaskManifest:
        variant = self._variant()
        if ref.suite != "rtllm":
            raise ConfigurationError(f"unknown RTLLM task: {ref.id}")
        if variant in _MULTI_TASK_VARIANTS:
            names = _MULTI_TASK_VARIANTS[variant]
            prefix = f"rtllm/{variant}/"
            if not ref.id.startswith(prefix) or ref.native_id not in names:
                raise ConfigurationError(f"unknown RTLLM task: {ref.id}")
            if ref.id != prefix + ref.native_id:
                raise ConfigurationError(f"unknown RTLLM task: {ref.id}")
            return TASK_MANIFESTS[ref.native_id]
        if ref.id != f"rtllm/{variant}" or ref.native_id != variant:
            raise ConfigurationError(f"unknown RTLLM task: {ref.id}")
        return TASK_MANIFESTS[self._base_variant()]

    def _manifest_for_task(self, task: VeriTask) -> RTLLMTaskManifest:
        if task.suite != "rtllm":
            raise ConfigurationError(f"unknown RTLLM task: {task.id}")
        variant = self._variant()
        if variant in _MULTI_TASK_VARIANTS:
            names = _MULTI_TASK_VARIANTS[variant]
            prefix = f"rtllm/{variant}/"
            name = task.id.removeprefix(prefix) if task.id.startswith(prefix) else ""
            if name not in names or task.id != prefix + name:
                raise ConfigurationError(f"unknown RTLLM task: {task.id}")
            return TASK_MANIFESTS[name]
        if task.id != f"rtllm/{self._variant()}":
            raise ConfigurationError(f"unknown RTLLM task: {task.id}")
        return TASK_MANIFESTS[self._base_variant()]

    def _task_id(self, manifest: RTLLMTaskManifest) -> str:
        if self._variant() in _MULTI_TASK_VARIANTS:
            return f"rtllm/{self._variant()}/{manifest.name}"
        return f"rtllm/{self._variant()}"

    def _candidate_path(self, manifest: RTLLMTaskManifest) -> str:
        agent_eval = (
            self._variant() in _MULTI_TASK_VARIANTS
            or self._variant() in _AGENT_EVAL_VARIANTS | _FUNCTIONAL_AGENT_EVAL_VARIANTS
        )
        prefix = "repository/" if agent_eval else ""
        return f"{prefix}rtl/{manifest.name}.v"

    def _suite_version(self, manifest: RTLLMTaskManifest) -> str:
        variant = self._variant()
        if variant == ALL_AGENT_EVAL_VARIANT:
            return ALL_AGENT_EVAL_SUITE_VERSION
        if variant == HARDER_VARIANT:
            return HARDER_SUITE_VERSION
        if batch := _FUNCTIONAL_BATCH_SPECS.get(variant):
            return batch.suite_version
        if variant.endswith("_agent_eval_functional_v2"):
            return FUNCTIONAL_AGENT_EVAL_V2_SUITE_VERSION
        if variant in _FUNCTIONAL_AGENT_EVAL_VARIANTS:
            return FUNCTIONAL_AGENT_EVAL_SUITE_VERSION
        if variant in _AGENT_EVAL_VARIANTS:
            return AGENT_EVAL_SUITE_VERSION
        if variant == _UP_DOWN_ICARUS_TRAINING_VARIANT:
            return UP_DOWN_ICARUS_TRAINING_SUITE_VERSION
        return UP_DOWN_SUITE_VERSION if manifest.name == "up_down_counter" else SUITE_VERSION

    def _workspace_asset_name(self, manifest: RTLLMTaskManifest) -> str:
        if self._variant() == ALL_AGENT_EVAL_VARIANT:
            return "workspace_all"
        if self._variant() == HARDER_VARIANT:
            return "workspace_harder"
        if batch := _FUNCTIONAL_BATCH_SPECS.get(self._variant()):
            return batch.workspace_asset
        return "workspace_up_down" if manifest.name == "up_down_counter" else "workspace"

    def _base_workspace(self, manifest: RTLLMTaskManifest) -> Path:
        if self._variant() == ALL_AGENT_EVAL_VARIANT:
            return self._all_workspace_root
        if self._variant() == HARDER_VARIANT:
            return self._harder_workspace_root
        if self._variant() in self._functional_batch_workspace_roots:
            return self._functional_batch_workspace_roots[self._variant()]
        if manifest.name == "up_down_counter":
            return self._up_down_workspace_root
        return self._workspace_root

    def _repository_readme(self, manifest: RTLLMTaskManifest) -> str:
        if self._variant() not in _MULTI_TASK_VARIANTS:
            return (self._base_workspace(manifest) / "README.md").read_text(encoding="utf-8")
        extra = (
            " The same file may define both `dual_port_RAM` and `asyn_fifo`."
            if manifest.name == "asyn_fifo"
            else ""
        )
        return f"# {manifest.name}\n\nImplement the task in `rtl/{manifest.name}.v`.{extra}\n" + (
            "The public test is a candidate-only compile check; it does not test behavior.\n"
            if self._variant() == ALL_AGENT_EVAL_VARIANT
            else "Use the public test tool for candidate-only feedback before finishing.\n"
        )

    @staticmethod
    def _candidate_stub(manifest: RTLLMTaskManifest) -> str:
        return (
            f"// Implement `{manifest.candidate_top}` from TASK.md.\n"
            "// This intentionally incomplete scaffold contains no hidden implementation details.\n"
        )

    @staticmethod
    def _derived_projection_note(manifest: RTLLMTaskManifest, *, compile_only: bool = False) -> str:
        common = (
            "VeriGym derived projection: submit one repository-relative RTL entry at "
            f"`rtl/{manifest.name}.v`. "
        )
        if compile_only:
            return (
                common + "The repeatable public check validates candidate-only compilation, not "
                "functionality. The native functional verifier remains hidden and runs only "
                "after typed finish. This L1 projection does not provide or claim PPA feedback."
            )
        common += (
            "The public smoke is independently authored and candidate-only; the final verifier "
            "remains hidden."
        )
        task_note = {
            "radix2_div": (
                " This projection uses the scaffolded `res_ready` handshake and the upstream "
                "quotient/remainder result-field layout."
            ),
            "multi_pipe_8bit": " This projection fixes the upstream parameter `size` at 8.",
            "LIFObuffer": "",
            "asyn_fifo": (
                " This projection uses `WIDTH=8` and `DEPTH=16`; derive address and pointer "
                "widths from `DEPTH`. The candidate file may contain both the FIFO and its "
                "dual-port RAM submodule."
            ),
            "adder_pipe_64bit": (
                " This projection accepts an operation when `i_en` is sampled high and aligns "
                "`result` with `o_en` on the fourth rising edge including the capture edge."
            ),
            "LFSR": "",
            "serial2parallel": (
                " This projection treats a frame as eight consecutive `din_valid` samples, "
                "MSB first. Dropping `din_valid` discards a partial frame; the completed word "
                "and one-cycle `dout_valid` pulse appear on the following rising edge."
            ),
            "sequence_detector": (
                " This projection uses active-low `rst_n`, supports overlapping occurrences of "
                "`1001`, and asserts `sequence_detected` in the cycle that samples the final bit."
            ),
            "synchronizer": (
                " This projection samples `data_in` and `data_en` in the `clk_a` domain, passes "
                "the enable through two `clk_b` registers, and updates `dataout` from the stable "
                "source register when the delayed enable is observed."
            ),
            "RAM": (
                " This projection uses the stated six-bit data width and eight initialized "
                "locations at addresses 0 through 7. Reads are synchronous, and `read_data` "
                "clears when `read_en` is low."
            ),
        }.get(manifest.name)
        if task_note is None:
            raise ConfigurationError("RTLLM derived projection is not declared")
        return common + task_note

    def _public_smoke(self, name: str) -> str:
        batch = _FUNCTIONAL_BATCH_SPECS.get(self._variant())
        folder = (
            "public_smoke_harder"
            if self._variant() == HARDER_VARIANT
            else batch.public_smoke_asset
            if batch is not None
            else "public_smoke"
        )
        path = Path(__file__).parent / "assets" / folder / f"{name}.sv"
        if path.is_symlink() or not path.is_file():
            raise ConfigurationError("RTLLM public smoke asset is unavailable")
        smoke = path.read_text(encoding="utf-8")
        if batch is not None:
            expected = batch.public_smoke_sha256.get(name)
            if expected is None or _hash_bytes(smoke.encode("utf-8")) != expected:
                raise ConfigurationError("RTLLM L2 public smoke differs from its frozen hash")
        return smoke

    @staticmethod
    def _hidden_asset_declarations(manifest: RTLLMTaskManifest) -> list[AssetRef]:
        hashes = dict(manifest.file_hashes)
        testbench_hash = manifest.testbench_projection_sha256 or hashes[manifest.testbench_file]
        return [
            AssetRef(
                kind="inline",
                content_hash=testbench_hash,
                mount_path="verifier/testbench.v",
            ),
            *(
                AssetRef(kind="inline", content_hash=hashes[name], mount_path=name)
                for name in manifest.auxiliary_files
            ),
        ]

    def _resolved_hidden_asset(
        self, manifest: RTLLMTaskManifest, source_name: str, mount_path: str
    ) -> AssetRef:
        content = _read_exact(self._source_root(), f"{manifest.root}/{source_name}")
        if source_name == manifest.testbench_file:
            content = self._project_testbench(manifest, content)
        return AssetRef(
            kind="inline",
            content=content.decode("utf-8"),
            content_hash=_hash_bytes(content),
            mount_path=mount_path,
        )

    @staticmethod
    def _project_testbench(manifest: RTLLMTaskManifest, content: bytes) -> bytes:
        projection = manifest.testbench_projection
        if projection == "identity-v1":
            projected = content
        else:
            text = content.decode("utf-8")
            if projection == "edge-aligned-handshake-v1":
                initialization = "        res_ready = 1;\n        #20;"
                if text.count(initialization) != 1:
                    raise ConfigurationError("RTLLM divider testbench projection no longer matches")
                text = text.replace(
                    initialization,
                    "        res_ready = 0;\n        #20;",
                    1,
                )
                display_line = (
                    '                $display("Error: dividend=%d, divisor=%d, '
                    'expected=%h, got=%h", a_test[i], b_test[i], '
                    "expected_result[i], result);\n"
                )
                original = (
                    """        rst = 0;

        for (i = 0; i < 8; i = i + 1) begin
            // Apply test vectors
            dividend = a_test[i];
            divisor = b_test[i];
            sign = sign_test[i];
            opn_valid = 1;
            #10;
            opn_valid = 0;

            // Wait for result
            wait(res_valid);
            #10;

            // Check result
            if (result !== expected_result[i]) begin
                error = error + 1;
"""
                    + display_line
                    + """            end

            res_ready = 1;
            #10;
        end
"""
                )
                replacement = (
                    """        rst = 0;
        @(negedge clk);

        for (i = 0; i < 8; i = i + 1) begin
            // Apply test vectors away from the active clock edge.
            dividend = a_test[i];
            divisor = b_test[i];
            sign = sign_test[i];
            opn_valid = 1;
            @(negedge clk);
            opn_valid = 0;

            // Wait for result and sample away from the active clock edge.
            wait(res_valid);
            @(negedge clk);

            // Check result
            if (result !== expected_result[i]) begin
                error = error + 1;
"""
                    + display_line
                    + """            end

            res_ready = 1;
            @(negedge clk);
            res_ready = 0;
            @(negedge clk);
        end
"""
                )
            elif projection == "icarus12-loop-control-v1":
                original = """  initial begin
  repeat (17) begin
    #20;
    if (wfull) begin
      // $display("FIFO is full (wfull=1) at depth %d", $time);
      break;
    end
    winc = 1; // Enable write
    wdata = wdata + 1; // Write data
    #10;
    winc = 0; // Disable write
  end
  end
"""
                replacement = """  initial begin
  begin : write_until_full
  repeat (17) begin
    #20;
    if (wfull) begin
      // $display("FIFO is full (wfull=1) at depth %d", $time);
      disable write_until_full;
    end
    winc = 1; // Enable write
    wdata = wdata + 1; // Write data
    #10;
    winc = 0; // Disable write
  end
  end
  end
"""
            elif projection == "iverilog12-unpacked-array-race-v1":
                pattern = re.compile(
                    r"(?m)^(?P<indent>\s*)"
                    r"(?P<declaration>(?:reg|logic)\s+\[[^\n;]+?\]\s+"
                    r"(?P<name>[A-Za-z_][A-Za-z0-9_$]*)\s+"
                    r"\[(?P<left>\d+)\s*:\s*(?P<right>\d+)\])"
                    r"\s*=\s*\{(?P<values>[^{}]+)\};\s*$"
                )
                match = pattern.search(text)
                if match is None or pattern.search(text, match.end()) is not None:
                    raise ConfigurationError(
                        "RTLLM unpacked-array testbench projection no longer matches exactly"
                    )
                left = int(match.group("left"))
                right = int(match.group("right"))
                step = 1 if right >= left else -1
                indices = list(range(left, right + step, step))
                values = [item.strip() for item in match.group("values").split(",")]
                if len(indices) != len(values) or any(not item for item in values):
                    raise ConfigurationError(
                        "RTLLM unpacked-array initializer shape is unsupported"
                    )
                indent = match.group("indent")
                name = match.group("name")
                assignments = "\n".join(
                    f"{indent}  {name}[{index}] = {value};"
                    for index, value in zip(indices, values, strict=True)
                )
                replacement = (
                    f"{indent}{match.group('declaration')};\n"
                    f"{indent}initial begin : verigym_init_{name}\n"
                    f"{assignments}\n"
                    f"{indent}end"
                )
                projected_text = text[: match.start()] + replacement + text[match.end() :]
                counter_pattern = re.compile(
                    r"(?m)^(?P<indent>\s*)(?P<counter>[A-Za-z_][A-Za-z0-9_$]*)"
                    r"\s*=\s*(?P=counter)\s*\+\s*1\s*;\s*$"
                )
                counter_match = counter_pattern.search(projected_text)
                if (
                    counter_match is None
                    or counter_pattern.search(projected_text, counter_match.end()) is not None
                ):
                    raise ConfigurationError(
                        "RTLLM counter-race testbench projection no longer matches exactly"
                    )
                counter_replacement = (
                    f"{counter_match.group('indent')}{counter_match.group('counter')} <= "
                    f"{counter_match.group('counter')} + 1;"
                )
                projected_text = (
                    projected_text[: counter_match.start()]
                    + counter_replacement
                    + projected_text[counter_match.end() :]
                )
                projected = projected_text.encode("utf-8")
            elif projection == "candidate-module-normalization-v1":
                pattern = re.compile(rf"\b{re.escape(manifest.reference_module)}\b")
                matches = list(pattern.finditer(text))
                if len(matches) != 1:
                    raise ConfigurationError(
                        "RTLLM candidate-module testbench projection no longer matches exactly"
                    )
                projected = pattern.sub(manifest.candidate_top, text, count=1).encode("utf-8")
            elif projection == "pre-edge-clock-sampling-v1":
                lines = text.splitlines(keepends=True)
                sample_pattern = re.compile(
                    r"^(?P<indent>\s*)#(?P<delay>\d+)\s*;(?P<tail>[^\n]*)(?P<newline>\n?)$"
                )
                samples = [
                    (index, match)
                    for index, line in enumerate(lines)
                    if (match := sample_pattern.match(line)) is not None
                ]
                if len(samples) != 1:
                    raise ConfigurationError("RTLLM pre-edge testbench sample point is ambiguous")
                sample_index, sample_match = samples[0]
                delay = int(sample_match.group("delay"))
                if delay <= 1:
                    raise ConfigurationError("RTLLM pre-edge sample delay is too small")
                indent = sample_match.group("indent")
                repeat_pattern = re.compile(
                    r"^(?P<indent>\s*)repeat\s*\([^\n]+\)\s*begin"
                    r"(?:\s*//[^\n]*)?\s*$"
                )
                starts = [
                    (index, match)
                    for index, line in enumerate(lines[:sample_index])
                    if (match := repeat_pattern.match(line.rstrip("\n"))) is not None
                    and len(match.group("indent")) < len(indent)
                ]
                if not starts:
                    raise ConfigurationError("RTLLM pre-edge repeat block is ambiguous")
                _, repeat_match = starts[-1]
                repeat_indent = repeat_match.group("indent")
                closes = [
                    index
                    for index, line in enumerate(lines[sample_index + 1 :], sample_index + 1)
                    if line.rstrip("\n") == f"{repeat_indent}end"
                ]
                if not closes:
                    raise ConfigurationError("RTLLM pre-edge repeat block is unterminated")
                close_index = closes[0]
                lines[sample_index] = (
                    f"{indent}#{delay - 1};{sample_match.group('tail')}"
                    f"{sample_match.group('newline')}"
                )
                newline = "\n" if lines[close_index].endswith("\n") else ""
                lines.insert(close_index, f"{indent}#1;{newline}")
                projected = "".join(lines).encode("utf-8")
            else:
                raise ConfigurationError(f"unknown RTLLM testbench projection: {projection}")
            if projection not in {
                "candidate-module-normalization-v1",
                "iverilog12-unpacked-array-race-v1",
                "pre-edge-clock-sampling-v1",
            }:
                if text.count(original) != 1:
                    raise ConfigurationError("RTLLM testbench projection no longer matches exactly")
                projected = text.replace(original, replacement, 1).encode("utf-8")
        expected = (
            manifest.testbench_projection_sha256
            or dict(manifest.file_hashes)[manifest.testbench_file]
        )
        if _hash_bytes(projected) != expected:
            raise ConfigurationError("RTLLM projected testbench differs from its frozen identity")
        return projected

    @staticmethod
    def _verifier_graph(
        manifest: RTLLMTaskManifest,
        *,
        candidate_path: str,
        icarus: bool,
        isolated_icarus: bool,
    ) -> VerifierGraph:
        if isolated_icarus:
            return VerifierGraph(
                nodes=[
                    VerifierNode(
                        id="functional_hidden",
                        plugin="iverilog.simulate",
                        gate=True,
                        required=True,
                        visibility=ToolVisibility.VERIFIER_ONLY,
                        timeout_s=60,
                        request={
                            "sources": [candidate_path],
                            "testbench": "verifier/testbench.v",
                            "auxiliary_files": list(manifest.auxiliary_files),
                            "top": manifest.testbench_top,
                            "pass_marker": manifest.pass_marker,
                            "fail_marker": manifest.fail_marker,
                            "timeout_s": 60,
                        },
                    )
                ]
            )
        if icarus:
            return VerifierGraph(
                nodes=[
                    VerifierNode(
                        id="compile_hidden",
                        plugin="iverilog.compile",
                        gate=True,
                        required=True,
                        visibility=ToolVisibility.VERIFIER_ONLY,
                        timeout_s=30,
                        request={
                            "sources": [candidate_path, "verifier/testbench.v"],
                            "top": manifest.testbench_top,
                            "output": ".verigym_internal/compile_hidden/simv",
                            "language": "2012",
                            "timeout_s": 30,
                        },
                    ),
                    VerifierNode(
                        id="run_hidden",
                        plugin="iverilog.run",
                        depends_on=["compile_hidden"],
                        gate=True,
                        required=True,
                        visibility=ToolVisibility.VERIFIER_ONLY,
                        timeout_s=30,
                        request={
                            "executable_from": "compile_hidden",
                            "pass_marker": manifest.pass_marker,
                            "fail_marker": manifest.fail_marker,
                            "timeout_s": 30,
                        },
                    ),
                ]
            )
        vcs_request: dict[str, Any] = {
            "sources": [candidate_path],
            "testbench": "verifier/testbench.v",
            "top": manifest.testbench_top,
            "pass_marker": manifest.pass_marker,
            "fail_marker": manifest.fail_marker,
            "timeout_s": 180,
        }
        if manifest.auxiliary_files:
            vcs_request["auxiliary_files"] = list(manifest.auxiliary_files)
        return VerifierGraph(
            nodes=[
                VerifierNode(
                    id="vcs_regression",
                    plugin="synopsys.vcs.simulate",
                    gate=True,
                    required=True,
                    visibility=ToolVisibility.VERIFIER_ONLY,
                    timeout_s=180,
                    request=vcs_request,
                )
            ]
        )

    def _task_metadata(
        self,
        manifest: RTLLMTaskManifest,
        *,
        variant: str,
        snapshot: SuiteSourceSnapshot,
        candidate_path: str,
        public_contract: Any,
        upstream_prompt: str,
        derived_note: str,
        agent_eval: bool,
        functional_agent_eval: bool,
        functional_v2: bool,
        harder: bool,
        icarus_training: bool,
    ) -> dict[str, Any]:
        all_agent_eval = variant == ALL_AGENT_EVAL_VARIANT
        batch = _FUNCTIONAL_BATCH_SPECS.get(variant)
        adapter_version = (
            ALL_AGENT_EVAL_ADAPTER_VERSION
            if all_agent_eval
            else batch.adapter_version
            if batch is not None
            else HARDER_ADAPTER_VERSION
            if harder
            else FUNCTIONAL_AGENT_EVAL_V2_ADAPTER_VERSION
            if functional_v2
            else FUNCTIONAL_AGENT_EVAL_ADAPTER_VERSION
            if functional_agent_eval
            else ADAPTER_VERSION
        )
        evaluation_profile = (
            "icarus12-agent-eval-all-v1"
            if all_agent_eval
            else batch.evaluation_profile
            if batch is not None
            else "icarus12-agent-eval-functional-harder-v1"
            if harder
            else "icarus12-agent-eval-functional-v2"
            if functional_v2
            else "icarus12-agent-eval-functional-v1"
            if functional_agent_eval
            else "icarus12-agent-eval-v1"
            if agent_eval
            else "icarus-training-long-context-v1"
            if icarus_training
            else "vcs-benchmark-v1"
        )
        metadata: dict[str, Any] = {
            "native_task_id": manifest.root,
            "official_task_id": f"rtllm/{manifest.name}",
            "candidate_top": manifest.candidate_top,
            "testbench_top": manifest.testbench_top,
            "language": (
                "systemverilog-2012" if variant in _MULTI_TASK_VARIANTS else "verilog-2005"
            ),
            "dataset_content_hash": snapshot.dataset_content_hash,
            "adapter_version": adapter_version,
            "pinned_commit": PINNED_COMMIT,
            "evaluation_profile": evaluation_profile,
        }
        if agent_eval:
            assert public_contract is not None
            metadata.update(
                {
                    "synthesis_source_projection": synthesis_source_projection_contract(
                        {candidate_path: f"rtl/{manifest.name}.v"}
                    ),
                    "agent_eval": {
                        "benchmark_variant": variant,
                        "compile_test_id": "compile",
                        "ppa_supported": variant not in _NO_PPA_AGENT_EVAL_VARIANTS,
                        "public_test_contract_hash": content_hash(public_contract),
                    },
                    "public_feedback_semantics": (
                        "candidate_only_compile_l1_v1"
                        if all_agent_eval
                        else batch.public_feedback_semantics
                        if batch is not None
                        else "compile_and_independent_functional_smoke_harder_v1"
                        if harder
                        else "compile_and_independent_functional_smoke_v2"
                        if functional_v2
                        else "compile_and_independent_functional_smoke_v1"
                        if functional_agent_eval
                        else "compile_only_v1"
                    ),
                }
            )
            if all_agent_eval:
                metadata["gym_qualification_level"] = "L1_compile_only"
            elif batch is not None:
                metadata["gym_qualification_level"] = "L2_functional_smoke"
        if variant in _MULTI_TASK_VARIANTS:
            manifest_payload = {
                "name": manifest.name,
                "root": manifest.root,
                "prompt_file": manifest.prompt_file,
                "reference_file": manifest.reference_file,
                "testbench_file": manifest.testbench_file,
                "auxiliary_files": list(manifest.auxiliary_files),
                "candidate_top": manifest.candidate_top,
                "reference_module": manifest.reference_module,
                "testbench_top": manifest.testbench_top,
                "testbench_projection": manifest.testbench_projection,
                "testbench_projection_sha256": (
                    manifest.testbench_projection_sha256
                    or dict(manifest.file_hashes)[manifest.testbench_file]
                ),
                "synthesis_top": manifest.synthesis_top,
                "clocks": [
                    {"name": clock.name, "period_ns": clock.period_ns} for clock in manifest.clocks
                ],
                "power_base_clock": manifest.power_base_clock,
                "file_hashes": dict(manifest.file_hashes),
            }
            metadata.update(
                {
                    "diagnostic_only": True,
                    "benchmark_score_claimed": False,
                    "verification_requires_final_submission": True,
                    "upstream_prompt_sha256": _hash_bytes(upstream_prompt.encode("utf-8")),
                    "derived_projection_sha256": _hash_bytes(derived_note.encode("utf-8")),
                    "task_manifest_hash": content_hash(manifest_payload),
                    "frozen_task_count": FROZEN_TASK_COUNT,
                    "frozen_file_count": FROZEN_FILE_COUNT,
                    "frozen_task_trees_hash": FROZEN_TASK_TREES_HASH,
                    "frozen_dataset_files_hash": FROZEN_DATASET_FILES_HASH,
                    "clock_constraints": manifest_payload["clocks"],
                    "power_base_clock": manifest.power_base_clock,
                }
            )
        return metadata

    @staticmethod
    def _validate_expected_file(
        root: Path,
        relative: str,
        expected: str,
        issues: list[ValidationIssue],
    ) -> None:
        try:
            actual = _hash_bytes(_read_exact(root, relative))
        except (FileNotFoundError, OSError, ValueError) as exc:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="source_file",
                    message=str(exc),
                    relative_path=relative,
                )
            )
            return
        if actual != expected:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="source_hash",
                    message="file differs from the pinned RTLLM revision",
                    relative_path=relative,
                )
            )

    @staticmethod
    def _validate_frozen_inventory(root: Path, issues: list[ValidationIssue]) -> None:
        files: dict[str, str] = {}
        task_files: dict[str, dict[str, str]] = {}
        try:
            for benchmark_root in _BENCHMARK_ROOTS:
                base = root / benchmark_root
                if base.is_symlink() or not base.is_dir():
                    raise ValueError(f"RTLLM benchmark root is unavailable: {benchmark_root}")
                for path in sorted(base.rglob("*")):
                    relative = path.relative_to(root).as_posix()
                    if path.is_symlink():
                        raise ValueError(f"RTLLM source cannot contain a symlink: {relative}")
                    if path.is_file():
                        digest = _hash_bytes(_read_exact(root, relative))
                        files[relative] = digest
                        task_root, name = relative.rsplit("/", 1)
                        task_files.setdefault(task_root, {})[name] = digest
        except (FileNotFoundError, OSError, ValueError) as exc:
            issues.append(ValidationIssue(level="error", code="source_inventory", message=str(exc)))
            return
        trees = {
            task_root: {
                "file_count": len(file_hashes),
                "files_hash": _canonical_hash(file_hashes),
            }
            for task_root, file_hashes in sorted(task_files.items())
        }
        expected_trees = {
            task_root: {
                "file_count": frozen.file_count,
                "files_hash": frozen.files_hash,
            }
            for task_root, frozen in sorted(FROZEN_TASK_TREES.items())
        }
        checks = (
            (len(trees), FROZEN_TASK_COUNT, "task count"),
            (len(files), FROZEN_FILE_COUNT, "file count"),
            (_canonical_hash(trees), FROZEN_TASK_TREES_HASH, "task-tree hash"),
            (_canonical_hash(files), FROZEN_DATASET_FILES_HASH, "dataset file hash"),
        )
        for actual, expected, label in checks:
            if actual != expected:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="source_inventory",
                        message=f"frozen RTLLM {label} differs: expected {expected}, got {actual}",
                    )
                )
        if trees != expected_trees and _canonical_hash(trees) == FROZEN_TASK_TREES_HASH:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="source_inventory",
                    message="frozen RTLLM task inventory differs despite aggregate identity",
                )
            )

    def _source_root(self) -> Path:
        if self._config is None:
            raise ConfigurationError("RTLLM requires an explicit external checkout path")
        root = self._config.source_root.expanduser()
        if root.is_symlink():
            raise ConfigurationError("RTLLM source root cannot be a symlink")
        try:
            resolved = root.resolve(strict=True)
        except OSError as exc:
            raise ConfigurationError("RTLLM source root does not exist") from exc
        if not resolved.is_dir():
            raise ConfigurationError("RTLLM source root is not a directory")
        return resolved

    def _snapshot(self) -> SuiteSourceSnapshot:
        if self._snapshot_cache is not None:
            return self._snapshot_cache
        root = self._source_root()
        report = self.validate_source()
        if not report.valid:
            raise ConfigurationError("invalid RTLLM source: " + "; ".join(report.errors[:3]))
        variant = self._variant()
        if variant in _MULTI_TASK_VARIANTS:
            dataset_root = root
            native_layout = "RTLLM/{Arithmetic,Control,Memory,Miscellaneous}"
            dataset_hash = FROZEN_DATASET_FILES_HASH
        else:
            manifest = TASK_MANIFESTS[self._base_variant()]
            dataset_root = (root / manifest.root).resolve(strict=True)
            native_layout = f"RTLLM/{manifest.root}"
            dataset_hash = _canonical_hash(manifest.expected_hashes)
        commit = _git_commit(root)
        self._snapshot_cache = SuiteSourceSnapshot(
            source_root=str(root),
            dataset_root=str(dataset_root),
            variant=variant,
            native_layout=native_layout,
            strict_compatibility=self._config.strict_compatibility if self._config else True,
            configuration_fingerprint=_canonical_hash(
                {
                    "source_root": str(root),
                    "variant": variant,
                    "strict_compatibility": (
                        self._config.strict_compatibility if self._config else True
                    ),
                }
            ),
            dataset_content_hash=dataset_hash,
            license_id="MIT",
            license_file_hash=LICENSE_SHA256,
            git_commit=commit,
            git_remote=CANONICAL_REMOTE if commit is not None else None,
            git_metadata_available=commit is not None,
            synthetic_fixture=False,
        )
        return self._snapshot_cache


def _is_icarus12_version(version: str | None) -> bool:
    if version is None:
        return False
    match = re.search(r"\bversion\s+(\d+)(?:\.|\b)", version, flags=re.IGNORECASE)
    if match is None:
        match = re.match(r"\s*(\d+)(?:\.|\b)", version)
    return match is not None and int(match.group(1)) == 12


def _invalid(code: str, message: str) -> ValidationReport:
    issue = ValidationIssue(level="error", code=code, message=message)
    return ValidationReport(valid=False, errors=[f"[{code}] {message}"], issues=[issue])


__all__ = [
    "ADAPTER_VERSION",
    "ALL_AGENT_EVAL_ADAPTER_VERSION",
    "ALL_AGENT_EVAL_SUITE_VERSION",
    "ALL_AGENT_EVAL_VARIANT",
    "HARDER_ADAPTER_VERSION",
    "HARDER_SUITE_VERSION",
    "HARDER_VARIANT",
    "PINNED_COMMIT",
    "RTLLMSuite",
    "SUITE_VERSION",
]
