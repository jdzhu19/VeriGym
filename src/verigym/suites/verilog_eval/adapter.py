"""External-path VerilogEval V2 spec-to-RTL suite adapter."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from verigym.core.agent_feedback_assets import (
    AgentEvalWorkspace,
    compile_feedback_contract,
    compile_smoke_feedback_contract,
    materialize_agent_eval_workspace,
)
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.registry.base import PluginRegistry
from verigym.runtimes.base import Runtime
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import (
    AssetRef,
    InteractionMode,
    RuntimeRequirement,
    SuiteDescriptor,
    TaskType,
    ToolchainProfile,
    ToolRequirement,
    ToolVisibility,
)
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.schemas.task import (
    BudgetSpec,
    Candidate,
    ConformanceCase,
    InteractionSpec,
    ObservationPolicy,
    ResolvedTaskAssets,
    ScoringSpec,
    SourceSpec,
    SubmissionPolicy,
    TaskRef,
    ValidationIssue,
    ValidationReport,
    VeriTask,
    WorkspaceSpec,
)
from verigym.schemas.verifier import VerifierGraph, VerifierNode
from verigym.suites.base import SuiteAdapter
from verigym.suites.verilog_eval.commercial import (
    VCS_MCP_EXCLUSIONS,
    combined_reference_testbench,
)
from verigym.suites.verilog_eval.layout import inspect_layout, validation_report
from verigym.suites.verilog_eval.normalization import transform_reference_candidate
from verigym.suites.verilog_eval.schemas import (
    IcarusCompatibility,
    VerilogEvalCatalog,
    VerilogEvalProblem,
    VerilogEvalVariant,
)
from verigym.suites.verilog_eval.source import build_source_snapshot, resolve_layout
from verigym.suites.verilog_eval.toolchain import detect_icarus

ADAPTER_VERSION = "0.1.0"
SUITE_VERSION = "v2-spec-to-rtl-compat-1"
AGENT_EVAL_SUITE_VERSION = "v2-spec-to-rtl-agent-eval-v1"
VERILATOR_AGENT_EVAL_SUITE_VERSION = "v2-spec-to-rtl-agent-eval-verilator-v1"
VERILATOR_AGENT_EVAL_ADAPTER_VERSION = "0.11.0"
VCS_MCP_AGENT_EVAL_SUITE_VERSION = "v2-spec-to-rtl-agent-eval-vcs-mcp-v1"
VCS_MCP_AGENT_EVAL_ADAPTER_VERSION = "0.9.0"
VCS_MCP_PUBLIC_AGENT_EVAL_SUITE_VERSION = "v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1"
VCS_MCP_PUBLIC_AGENT_EVAL_ADAPTER_VERSION = "0.10.0"
FUNCTIONAL_AGENT_EVAL_SUITE_VERSION = "v2-spec-to-rtl-agent-eval-functional-v1"
FUNCTIONAL_AGENT_EVAL_ADAPTER_VERSION = "0.2.0"
FUNCTIONAL_AGENT_EVAL_V2_SUITE_VERSION = "v2-spec-to-rtl-agent-eval-functional-v2"
FUNCTIONAL_AGENT_EVAL_V2_ADAPTER_VERSION = "0.3.0"
FUNCTIONAL_AGENT_EVAL_V3_SUITE_VERSION = "v2-spec-to-rtl-agent-eval-functional-v3"
FUNCTIONAL_AGENT_EVAL_V3_ADAPTER_VERSION = "0.4.0"
FUNCTIONAL_AGENT_EVAL_V4_SUITE_VERSION = "v2-spec-to-rtl-agent-eval-functional-v4"
FUNCTIONAL_AGENT_EVAL_V4_ADAPTER_VERSION = "0.5.0"
FUNCTIONAL_AGENT_EVAL_V5_SUITE_VERSION = "v2-spec-to-rtl-agent-eval-functional-v5"
FUNCTIONAL_AGENT_EVAL_V5_ADAPTER_VERSION = "0.6.0"
FUNCTIONAL_AGENT_EVAL_V6_SUITE_VERSION = "v2-spec-to-rtl-agent-eval-functional-v6"
FUNCTIONAL_AGENT_EVAL_V6_ADAPTER_VERSION = "0.7.0"
FUNCTIONAL_AGENT_EVAL_V7_SUITE_VERSION = "v2-spec-to-rtl-agent-eval-functional-v7"
FUNCTIONAL_AGENT_EVAL_V7_ADAPTER_VERSION = "0.8.0"
_FUNCTIONAL_SMOKE_TASKS = frozenset(
    {
        "Prob038_count15",
        "Prob067_countslow",
        "Prob096_review2015_fsmseq",
        "Prob100_fsm3comb",
        "Prob107_fsm1s",
        "Prob118_history_shift",
        "Prob124_rule110",
        "Prob128_fsm_ps2",
        "Prob137_fsm_serial",
        "Prob150_review2015_fsmonehot",
    }
)
_FUNCTIONAL_V4_ADDITIONAL_SMOKE_TASKS = frozenset(
    {
        "Prob140_fsm_hdlc",
        "Prob144_conwaylife",
        "Prob153_gshare",
        "Prob155_lemmings4",
    }
)


class VerilogEvalSuite(SuiteAdapter):
    descriptor = SuiteDescriptor(
        schema_version=SCHEMA_VERSION,
        name="verilog-eval",
        version=ADAPTER_VERSION,
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[
            "external_source",
            "v2-spec-to-rtl",
            "generation",
            "native_mismatch_regression",
            "conformance",
        ],
        title="VerilogEval V2",
        description=(
            "External-path compatibility adapter for VerilogEval V2 specification-to-RTL."
        ),
        suite_version=SUITE_VERSION,
        license=None,
    )

    def __init__(self, config: SuiteSourceConfig | None = None) -> None:
        self._config = config
        self._catalog_cache: VerilogEvalCatalog | None = None
        self._snapshot_cache: SuiteSourceSnapshot | None = None
        self._workspace_root = Path(__file__).parent / "assets" / "workspace"
        self._agent_workspaces: list[AgentEvalWorkspace] = []

    def with_source(self, config: SuiteSourceConfig) -> VerilogEvalSuite:
        return VerilogEvalSuite(config.model_copy(deep=True))

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        adapter = self._adapter_for_optional_root(source_root)
        catalog = adapter._valid_catalog()
        problems = (
            [
                problem
                for problem in catalog.problems
                if problem.native_id in adapter._functional_smoke_tasks()
            ]
            if adapter._is_functional_agent_eval()
            else [
                problem
                for problem in catalog.problems
                if problem.native_id not in VCS_MCP_EXCLUSIONS
            ]
            if adapter._is_vcs_mcp_agent_eval()
            else catalog.problems
        )
        return [
            TaskRef(
                id=f"verilog-eval/{catalog.layout.variant.value}/{problem.native_id}",
                suite="verilog-eval",
                native_id=problem.native_id,
            )
            for problem in problems
        ]

    def load_task(self, ref: TaskRef) -> VeriTask:
        catalog = self._valid_catalog()
        problem = next(
            (problem for problem in catalog.problems if problem.native_id == ref.native_id),
            None,
        )
        if problem is None:
            raise ConfigurationError(f"unknown VerilogEval task: {ref.native_id}")
        if self._is_vcs_mcp_agent_eval() and problem.native_id in VCS_MCP_EXCLUSIONS:
            raise ConfigurationError(
                f"VerilogEval VCS/MCP task is ineligible: {VCS_MCP_EXCLUSIONS[problem.native_id]}"
            )
        if (
            self._is_functional_agent_eval()
            and problem.native_id not in self._functional_smoke_tasks()
        ):
            raise ConfigurationError(
                f"VerilogEval functional AgentEval has no frozen public smoke for {ref.native_id}"
            )
        snapshot = self._snapshot(catalog)
        return self._normalize_task(problem, snapshot)

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        if self._config is None:
            raise ConfigurationError("VerilogEval requires an explicit external source path")
        catalog = inspect_layout(resolve_layout(self._config))
        report = validation_report(catalog)
        if not report.valid:
            preview = "; ".join(report.errors[:3])
            raise ConfigurationError(f"VerilogEval source changed or is invalid: {preview}")
        if task.metadata.get("dataset_content_hash") != catalog.dataset_content_hash:
            raise ConfigurationError(
                "VerilogEval dataset content differs from the frozen task snapshot"
            )
        native_id = task.metadata.get("native_task_id")
        if not isinstance(native_id, str):
            raise ConfigurationError("frozen VerilogEval task has no native task identifier")
        problem = next(
            (problem for problem in catalog.problems if problem.native_id == native_id),
            None,
        )
        if problem is None:
            raise ConfigurationError(f"VerilogEval source no longer contains {native_id!r}")
        if task.source.content_hash != problem.content_hash:
            raise ConfigurationError(
                "VerilogEval source task content differs from the frozen task snapshot"
            )
        if self._is_agent_eval():
            public_smoke = self._public_smoke(problem.native_id)
            contract = (
                compile_smoke_feedback_contract(
                    source_paths=["rtl/TopModule.sv"],
                    top_module="TopModule",
                    language="2012",
                    public_testbench=public_smoke,
                )
                if public_smoke is not None
                else compile_feedback_contract(
                    source_paths=["rtl/TopModule.sv"],
                    top_module="TopModule",
                    language="2012",
                    backend=("verilator" if self._is_verilator_agent_eval() else "iverilog"),
                )
            )
            materialized = materialize_agent_eval_workspace(
                task_description=task.description,
                repository_files={
                    "README.md": (self._workspace_root / "README.md").read_text(encoding="utf-8"),
                    "rtl/TopModule.sv": (self._workspace_root / "rtl/TopModule.sv").read_text(
                        encoding="utf-8"
                    ),
                },
                compile_contract=contract,
                ppa_available=False,
                public_asset_files=(
                    {"assets/public-smoke.sv": public_smoke} if public_smoke is not None else None
                ),
            )
            self._agent_workspaces.append(materialized)
            visible_root = str(materialized.visible_root)
            read_only_mounts = (
                [materialized.read_only_mount] if materialized.read_only_mount is not None else []
            )
        else:
            visible_root = str(self._workspace_root.resolve(strict=True))
            read_only_mounts = []
        if self._is_vcs_mcp_agent_eval():
            combined_testbench = combined_reference_testbench(
                problem.reference,
                problem.testbench,
            )
            hidden_assets = [
                AssetRef(
                    kind="inline",
                    content=combined_testbench,
                    content_hash=hash_bytes(combined_testbench.encode("utf-8")),
                    mount_path="verifier/testbench.sv",
                )
            ]
        else:
            hidden_assets = [
                AssetRef(
                    kind="inline",
                    content=problem.reference,
                    content_hash=hash_bytes(problem.reference.encode("utf-8")),
                    mount_path="verifier/golden.sv",
                ),
                AssetRef(
                    kind="inline",
                    content=problem.testbench,
                    content_hash=hash_bytes(problem.testbench.encode("utf-8")),
                    mount_path="verifier/testbench.sv",
                ),
            ]
        return ResolvedTaskAssets(
            visible_root=visible_root,
            hidden_assets=hidden_assets,
            read_only_mounts=read_only_mounts,
        )

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        try:
            adapter = self._adapter_for_optional_root(source_root)
            catalog = adapter._catalog()
        except ConfigurationError as exc:
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
        return validation_report(catalog)

    def reference_solution(self, task: VeriTask) -> Candidate | None:
        catalog = self._valid_catalog()
        native_id = task.metadata.get("native_task_id")
        problem = next(
            (problem for problem in catalog.problems if problem.native_id == native_id),
            None,
        )
        if problem is None:
            return None
        path = "repository/rtl/TopModule.sv" if self._is_agent_eval() else "rtl/TopModule.sv"
        return Candidate(
            files={path: transform_reference_candidate(problem.reference)},
            label="reference-derived",
        )

    def conformance_cases(self) -> Iterable[ConformanceCase]:
        catalog = self._valid_catalog()
        if not catalog.problems:
            return []
        task = self._normalize_task(catalog.problems[0], self._snapshot(catalog))
        reference = self.reference_solution(task)
        if reference is None:
            return []
        return [
            ConformanceCase(
                name=f"{catalog.problems[0].native_id}-reference",
                candidate=reference,
                expected_resolved=True,
            ),
            ConformanceCase(
                name=f"{catalog.problems[0].native_id}-wrong",
                candidate=Candidate(
                    files={
                        (
                            "repository/rtl/TopModule.sv"
                            if self._is_agent_eval()
                            else "rtl/TopModule.sv"
                        ): "module TopModule; endmodule\n"
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

    def toolchain_profile(
        self,
        runtime: Runtime,
        tools: PluginRegistry[Any],
    ) -> ToolchainProfile | None:
        if self._is_vcs_mcp_public_agent_eval():
            runtime_image = runtime.descriptor.image
            return ToolchainProfile(
                id="verilog-eval-v2-agent-eval-public-vcs-mcp-v1",
                version="1.0.0",
                description=(
                    "VerilogEval AgentEval public VCS/MCP compile profile; the independent "
                    "hidden VCS/MCP identity is bound separately."
                ),
                tools=[],
                runtime=RuntimeRequirement(runtime=runtime.descriptor.name),
                container_image=(
                    runtime_image.requested_reference if runtime_image is not None else None
                ),
                container_digest=(
                    runtime_image.resolved_image_id if runtime_image is not None else None
                ),
                deterministic=True,
                reproducibility_scope="site_specific",
                compatibility_status="public_vcs_mcp_profile_bound",
            )
        runtime_image = runtime.descriptor.image
        if runtime_image is not None:
            compiler_version = runtime_image.iverilog_version
            runner_version = runtime_image.vvp_version
            verilator_version = runtime_image.verilator_version
            try:
                compatibility = (
                    IcarusCompatibility(runtime_image.compatibility_status)
                    if runtime_image.compatibility_status is not None
                    else IcarusCompatibility.UNVERIFIED
                )
            except ValueError:
                compatibility = IcarusCompatibility.UNVERIFIED
        else:
            compiler = tools.get("verilog_eval.v2.compile").health_check()
            runner = tools.get("verilog_eval.v2.regression").health_check()
            compiler_version = compiler.version
            runner_version = runner.version
            verilator = (
                tools.get("verilator.compile").health_check()
                if self._is_verilator_agent_eval()
                else None
            )
            verilator_version = verilator.version if verilator is not None else None
            compiler_info = detect_icarus("iverilog")
            runner_info = detect_icarus("vvp")
            statuses = {compiler_info.compatibility, runner_info.compatibility}
            if IcarusCompatibility.INCOMPATIBLE in statuses:
                compatibility = IcarusCompatibility.INCOMPATIBLE
            elif statuses == {IcarusCompatibility.REFERENCE_COMPATIBLE}:
                compatibility = IcarusCompatibility.REFERENCE_COMPATIBLE
            else:
                compatibility = IcarusCompatibility.UNVERIFIED
        if self._is_verilator_agent_eval() and verilator_version is None:
            raise ConfigurationError(
                "VerilogEval Verilator public feedback requires an available Verilator"
            )
        return ToolchainProfile(
            id=(
                "verilog-eval-v2-agent-eval-public-icarus12-vcs-mcp-v1"
                if self._is_vcs_mcp_agent_eval()
                else "verilog-eval-v2-agent-eval-verilator-lint-icarus12-v1"
                if self._is_verilator_agent_eval()
                else "verilog-eval-v2-agent-eval-icarus12"
                if self._is_agent_eval()
                else "verilog-eval-v2-icarus"
            ),
            version="1.0.0",
            description=(
                "VerilogEval AgentEval public Icarus 12 compile profile; hidden VCS identity is "
                "bound separately by the required verifier profile."
                if self._is_vcs_mcp_agent_eval()
                else (
                    "VerilogEval repeatable public Verilator compile/lint feedback with the "
                    "independent hidden Icarus 12 functional verifier."
                )
                if self._is_verilator_agent_eval()
                else "VerilogEval V2 Icarus profile; upstream reference is Icarus v12."
            ),
            tools=[
                ToolRequirement(name="iverilog", version=compiler_version),
                ToolRequirement(name="vvp", version=runner_version),
                *(
                    [
                        ToolRequirement(
                            name="verilator",
                            version=verilator_version,
                            capabilities=["compile", "lint"],
                        )
                    ]
                    if self._is_verilator_agent_eval()
                    else []
                ),
            ],
            runtime=RuntimeRequirement(runtime=runtime.descriptor.name),
            container_image=(
                runtime_image.requested_reference if runtime_image is not None else None
            ),
            container_digest=(
                runtime_image.resolved_image_id if runtime_image is not None else None
            ),
            deterministic=True,
            reproducibility_scope="public",
            compatibility_status=(
                "reference_compatible_verilator_lint"
                if self._is_verilator_agent_eval()
                and compatibility == IcarusCompatibility.REFERENCE_COMPATIBLE
                else compatibility.value
            ),
        )

    def _adapter_for_optional_root(self, source_root: Path | None) -> VerilogEvalSuite:
        if source_root is None:
            return self
        variant = self._config.variant if self._config is not None else None
        strict = self._config.strict_compatibility if self._config is not None else True
        return self.with_source(
            SuiteSourceConfig(
                source_root=source_root,
                variant=variant,
                strict_compatibility=strict,
            )
        )

    def _catalog(self) -> VerilogEvalCatalog:
        if self._config is None:
            raise ConfigurationError(
                "VerilogEval requires an explicit external source path and variant"
            )
        if self._catalog_cache is None:
            self._catalog_cache = inspect_layout(resolve_layout(self._config))
        return self._catalog_cache

    def _valid_catalog(self) -> VerilogEvalCatalog:
        catalog = self._catalog()
        report = validation_report(catalog)
        if not report.valid:
            preview = "; ".join(report.errors[:3])
            raise ConfigurationError(f"invalid VerilogEval source: {preview}")
        return catalog

    def _snapshot(self, catalog: VerilogEvalCatalog) -> SuiteSourceSnapshot:
        assert self._config is not None
        if self._snapshot_cache is None:
            self._snapshot_cache = build_source_snapshot(self._config, catalog)
        return self._snapshot_cache

    def _normalize_task(
        self,
        problem: VerilogEvalProblem,
        snapshot: SuiteSourceSnapshot,
    ) -> VeriTask:
        variant = snapshot.variant
        agent_eval = variant in {
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_V1.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VERILATOR_V1.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_V1.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_PUBLIC_V1.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V1.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V2.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V3.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V4.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V5.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V6.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V7.value,
        }
        functional_agent_eval = variant in {
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V1.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V2.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V3.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V4.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V5.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V6.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V7.value,
        }
        codex_patch_compatible = variant in {
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VERILATOR_V1.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_V1.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_PUBLIC_V1.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V2.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V3.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V4.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V5.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V6.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V7.value,
        }
        functional_v7 = variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V7.value
        functional_v6 = variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V6.value
        functional_v5 = variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V5.value
        functional_v4 = variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V4.value
        functional_v3 = variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V3.value
        functional_v2 = variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V2.value
        vcs_mcp_public = (
            variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_PUBLIC_V1.value
        )
        vcs_mcp = variant in {
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_V1.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_PUBLIC_V1.value,
        }
        verilator_agent_eval = (
            variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VERILATOR_V1.value
        )
        task_id = f"verilog-eval/{variant}/{problem.native_id}"
        candidate_path = "repository/rtl/TopModule.sv" if agent_eval else "rtl/TopModule.sv"
        public_smoke = self._public_smoke(problem.native_id) if functional_agent_eval else None
        compile_contract = (
            compile_smoke_feedback_contract(
                source_paths=["rtl/TopModule.sv"],
                top_module="TopModule",
                language="2012",
                public_testbench=public_smoke,
            )
            if public_smoke is not None
            else compile_feedback_contract(
                source_paths=["rtl/TopModule.sv"],
                top_module="TopModule",
                language="2012",
                backend="verilator" if verilator_agent_eval else "iverilog",
            )
        )
        suite_version = (
            VCS_MCP_PUBLIC_AGENT_EVAL_SUITE_VERSION
            if vcs_mcp_public
            else VCS_MCP_AGENT_EVAL_SUITE_VERSION
            if vcs_mcp
            else FUNCTIONAL_AGENT_EVAL_V7_SUITE_VERSION
            if functional_v7
            else FUNCTIONAL_AGENT_EVAL_V6_SUITE_VERSION
            if functional_v6
            else FUNCTIONAL_AGENT_EVAL_V5_SUITE_VERSION
            if functional_v5
            else FUNCTIONAL_AGENT_EVAL_V4_SUITE_VERSION
            if functional_v4
            else FUNCTIONAL_AGENT_EVAL_V3_SUITE_VERSION
            if functional_v3
            else FUNCTIONAL_AGENT_EVAL_V2_SUITE_VERSION
            if functional_v2
            else FUNCTIONAL_AGENT_EVAL_SUITE_VERSION
            if functional_agent_eval
            else VERILATOR_AGENT_EVAL_SUITE_VERSION
            if verilator_agent_eval
            else AGENT_EVAL_SUITE_VERSION
            if agent_eval
            else SUITE_VERSION
        )
        if vcs_mcp:
            combined_testbench = combined_reference_testbench(
                problem.reference,
                problem.testbench,
            )
            hidden_assets = [
                AssetRef(
                    kind="inline",
                    content_hash=hash_bytes(combined_testbench.encode("utf-8")),
                    mount_path="verifier/testbench.sv",
                )
            ]
            verifier = VerifierGraph(
                nodes=[
                    VerifierNode(
                        id="vcs_regression",
                        plugin="synopsys.vcs.simulate",
                        gate=True,
                        required=True,
                        visibility=ToolVisibility.VERIFIER_ONLY,
                        timeout_s=180,
                        request={
                            "sources": [candidate_path],
                            "testbench": "verifier/testbench.sv",
                            "top": problem.testbench_top,
                            "pass_marker": "Mismatches: 0 in",
                            "fail_marker": "VERIGYM_VCS_EXPLICIT_FAIL",
                            "executable": "vcs",
                            "timeout_s": 180,
                        },
                    )
                ]
            )
            correctness_required_nodes = ["vcs_regression"]
        else:
            hidden_assets = [
                AssetRef(
                    kind="inline",
                    content_hash=hash_bytes(problem.reference.encode("utf-8")),
                    mount_path="verifier/golden.sv",
                ),
                AssetRef(
                    kind="inline",
                    content_hash=hash_bytes(problem.testbench.encode("utf-8")),
                    mount_path="verifier/testbench.sv",
                ),
            ]
            verifier = VerifierGraph(
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
                                candidate_path,
                            ],
                            "candidate": candidate_path,
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
            )
            correctness_required_nodes = ["compile_hidden", "run_hidden"]
        return VeriTask(
            id=task_id,
            suite="verilog-eval",
            suite_version=suite_version,
            task_type=TaskType.GENERATION,
            title=f"VerilogEval V2 {problem.native_id}",
            description=problem.prompt,
            source=SourceSpec(
                kind="synthetic" if snapshot.synthetic_fixture else "benchmark",
                uri=f"verilog-eval://{variant}/{problem.native_id}",
                revision=suite_version,
                commit=snapshot.git_commit,
                license=snapshot.license_id,
                attribution=(
                    "Synthetic layout-conformance fixture; not an official benchmark task."
                    if snapshot.synthetic_fixture
                    else "Externally supplied VerilogEval V2 checkout."
                ),
                content_hash=problem.content_hash,
            ),
            workspace=WorkspaceSpec(
                base=AssetRef(kind="directory", path="workspace"),
                editable_globs=[candidate_path],
                readonly_globs=(
                    ["TASK.md", "PUBLIC_TESTS.md", "repository/README.md"]
                    if agent_eval
                    else ["README.md"]
                ),
                excluded_globs=["verifier", "verifier/**", "hidden", "hidden/**"],
                entrypoints=[candidate_path],
                hidden_assets=hidden_assets,
                max_changed_files=1,
                max_patch_lines=2_000,
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
                    *(["file.apply_codex_patch"] if codex_patch_compatible else []),
                    "file.diff",
                    *(["repository.public_test"] if agent_eval else []),
                ],
                denied_tools=[],
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
                max_wall_time_s=300,
                max_tool_time_s=30,
                max_output_tokens=16_384,
                max_output_bytes_per_tool=1_000_000,
                max_workspace_bytes=2_000_000,
            ),
            verifier=verifier,
            scoring=ScoringSpec(
                correctness_required_nodes=correctness_required_nodes,
                ppa_enabled=False,
            ),
            metadata={
                "benchmark_variant": variant,
                "native_layout": snapshot.native_layout,
                "native_task_id": problem.native_id,
                "candidate_top": "TopModule",
                "golden_top": "RefModule",
                "testbench_top": problem.testbench_top,
                "language": "systemverilog",
                "dataset_content_hash": snapshot.dataset_content_hash,
                "task_content_hash": problem.content_hash,
                "adapter_version": (
                    VCS_MCP_PUBLIC_AGENT_EVAL_ADAPTER_VERSION
                    if vcs_mcp_public
                    else VCS_MCP_AGENT_EVAL_ADAPTER_VERSION
                    if vcs_mcp
                    else FUNCTIONAL_AGENT_EVAL_V7_ADAPTER_VERSION
                    if functional_v7
                    else FUNCTIONAL_AGENT_EVAL_V6_ADAPTER_VERSION
                    if functional_v6
                    else FUNCTIONAL_AGENT_EVAL_V5_ADAPTER_VERSION
                    if functional_v5
                    else FUNCTIONAL_AGENT_EVAL_V4_ADAPTER_VERSION
                    if functional_v4
                    else FUNCTIONAL_AGENT_EVAL_V3_ADAPTER_VERSION
                    if functional_v3
                    else FUNCTIONAL_AGENT_EVAL_V2_ADAPTER_VERSION
                    if functional_v2
                    else FUNCTIONAL_AGENT_EVAL_ADAPTER_VERSION
                    if functional_agent_eval
                    else VERILATOR_AGENT_EVAL_ADAPTER_VERSION
                    if verilator_agent_eval
                    else ADAPTER_VERSION
                ),
                "synthetic_fixture": snapshot.synthetic_fixture,
                "public_feedback_semantics": (
                    "compile_and_independent_functional_smoke_v7"
                    if functional_v7
                    else "compile_and_independent_functional_smoke_v6"
                    if functional_v6
                    else "compile_and_independent_functional_smoke_v5"
                    if functional_v5
                    else "compile_and_independent_functional_smoke_v4"
                    if functional_v4
                    else "compile_and_independent_functional_smoke_v3"
                    if functional_v3
                    else "compile_and_independent_functional_smoke_v2"
                    if functional_v2
                    else "compile_and_independent_functional_smoke_v1"
                    if functional_agent_eval
                    else "compile_only_vcs_mcp_v1"
                    if vcs_mcp_public
                    else "compile_only_verilator_lint_v1"
                    if verilator_agent_eval
                    else "compile_only_v1"
                    if agent_eval
                    else None
                ),
                **(
                    {
                        "public_feedback_partition": (
                            "verilog_eval_v2_public_verilator_compile_lint_v1"
                        ),
                        "public_feedback_backend": "verilator",
                        "diagnostic_only": True,
                        "benchmark_score_claimed": False,
                        "verification_requires_final_submission": True,
                    }
                    if verilator_agent_eval
                    else {}
                ),
                **(
                    {
                        "agent_eval": {
                            "benchmark_variant": variant,
                            "compile_test_id": "compile",
                            "ppa_supported": False,
                            "public_test_contract_hash": content_hash(compile_contract),
                        }
                    }
                    if agent_eval
                    else {}
                ),
                **(
                    {
                        "required_verifier_profile_target": "synopsys.vcs.mcp",
                        "verification_partition": (
                            "verilog_eval_v2_vcs_mcp_public_v1"
                            if vcs_mcp_public
                            else "verilog_eval_v2_vcs_mcp_v1"
                        ),
                        "verification_requires_final_submission": True,
                        "diagnostic_only": True,
                        "benchmark_score_claimed": False,
                        "upstream_tool_compatible": False,
                    }
                    if vcs_mcp
                    else {}
                ),
                **(
                    {
                        "required_public_test_profile_target": ("synopsys.vcs.public-compile.mcp"),
                        "public_test_profile_source_plugin": "repository.public_test",
                        "public_test_profile_test_id": "compile",
                        "public_test_profile_sources": [candidate_path],
                        "public_test_profile_top": "TopModule",
                        "public_feedback_partition": ("verilog_eval_v2_public_vcs_mcp_compile_v1"),
                    }
                    if vcs_mcp_public
                    else {}
                ),
            },
        )

    def _is_agent_eval(self) -> bool:
        return bool(
            self._config is not None
            and self._config.variant
            in {
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_V1.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VERILATOR_V1.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_V1.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_PUBLIC_V1.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V1.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V2.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V3.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V4.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V5.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V6.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V7.value,
            }
        )

    def _is_verilator_agent_eval(self) -> bool:
        return bool(
            self._config is not None
            and self._config.variant
            == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VERILATOR_V1.value
        )

    def _is_vcs_mcp_agent_eval(self) -> bool:
        return bool(
            self._config is not None
            and self._config.variant
            in {
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_V1.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_PUBLIC_V1.value,
            }
        )

    def _is_vcs_mcp_public_agent_eval(self) -> bool:
        return bool(
            self._config is not None
            and self._config.variant
            == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_VCS_MCP_PUBLIC_V1.value
        )

    def _is_functional_agent_eval(self) -> bool:
        return bool(
            self._config is not None
            and self._config.variant
            in {
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V1.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V2.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V3.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V4.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V5.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V6.value,
                VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V7.value,
            }
        )

    def _public_smoke(self, native_id: str) -> str | None:
        if not self._is_functional_agent_eval():
            return None
        if native_id not in self._functional_smoke_tasks():
            raise ConfigurationError(
                f"VerilogEval functional AgentEval has no frozen public smoke for {native_id}"
            )
        assert self._config is not None
        root = Path(__file__).parent / "assets"
        candidates = []
        if self._config.variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V7.value:
            candidates.extend(
                [
                    root / "public_smoke_v7" / f"{native_id}.sv",
                    root / "public_smoke_v6" / f"{native_id}.sv",
                    root / "public_smoke_v5" / f"{native_id}.sv",
                    root / "public_smoke_v4" / f"{native_id}.sv",
                    root / "public_smoke_v3" / f"{native_id}.sv",
                    root / "public_smoke_v2" / f"{native_id}.sv",
                ]
            )
        elif (
            self._config.variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V6.value
        ):
            candidates.extend(
                [
                    root / "public_smoke_v6" / f"{native_id}.sv",
                    root / "public_smoke_v5" / f"{native_id}.sv",
                    root / "public_smoke_v4" / f"{native_id}.sv",
                    root / "public_smoke_v3" / f"{native_id}.sv",
                    root / "public_smoke_v2" / f"{native_id}.sv",
                ]
            )
        elif (
            self._config.variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V5.value
        ):
            candidates.extend(
                [
                    root / "public_smoke_v5" / f"{native_id}.sv",
                    root / "public_smoke_v4" / f"{native_id}.sv",
                    root / "public_smoke_v3" / f"{native_id}.sv",
                    root / "public_smoke_v2" / f"{native_id}.sv",
                ]
            )
        elif (
            self._config.variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V4.value
        ):
            candidates.extend(
                [
                    root / "public_smoke_v4" / f"{native_id}.sv",
                    root / "public_smoke_v3" / f"{native_id}.sv",
                    root / "public_smoke_v2" / f"{native_id}.sv",
                ]
            )
        elif (
            self._config.variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V3.value
        ):
            candidates.extend(
                [
                    root / "public_smoke_v3" / f"{native_id}.sv",
                    root / "public_smoke_v2" / f"{native_id}.sv",
                ]
            )
        elif (
            self._config.variant == VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V2.value
        ):
            candidates.append(root / "public_smoke_v2" / f"{native_id}.sv")
        candidates.append(root / "public_smoke" / f"{native_id}.sv")
        path = next(
            (
                candidate
                for candidate in candidates
                if candidate.is_file() and not candidate.is_symlink()
            ),
            candidates[-1],
        )
        if path.is_symlink() or not path.is_file():
            raise ConfigurationError("VerilogEval public smoke asset is unavailable")
        return path.read_text(encoding="utf-8")

    def _functional_smoke_tasks(self) -> frozenset[str]:
        if self._config is not None and self._config.variant in {
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V4.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V5.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V6.value,
            VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V7.value,
        }:
            return _FUNCTIONAL_SMOKE_TASKS | _FUNCTIONAL_V4_ADDITIONAL_SMOKE_TASKS
        return _FUNCTIONAL_SMOKE_TASKS


__all__ = ["ADAPTER_VERSION", "SUITE_VERSION", "VerilogEvalSuite"]
