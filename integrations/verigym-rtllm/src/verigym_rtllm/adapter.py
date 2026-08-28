"""Pinned, external-source RTLLM counter-family task adapter."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable
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
    content_hash,
    materialize_agent_eval_workspace,
)

ADAPTER_VERSION = "0.3.0"
SUITE_VERSION = "rtllm-41b2689-counter12-v1"
UP_DOWN_SUITE_VERSION = "rtllm-41b2689-up-down-counter-v1"
UP_DOWN_ICARUS_TRAINING_SUITE_VERSION = "rtllm-41b2689-up-down-counter-icarus-training-v1"
AGENT_EVAL_SUITE_VERSION = "rtllm-41b2689-agent-eval-v1"
PINNED_COMMIT = "41b26896e33b536940116a975626455eed3de65e"
CANONICAL_REMOTE = "https://github.com/hkust-zhiyao/RTLLM.git"
TASK_ROOT = Path("Control/Counter/counter_12")
UP_DOWN_TASK_ROOT = Path("Control/Counter/up_down_counter")
PASS_MARKER = "===========Your Design Passed==========="
FAIL_MARKER = "===========Failed==========="
UP_DOWN_PASS_MARKER = "=========== Your Design Passed ==========="
UP_DOWN_FAIL_MARKER = "===========Failed==========="
_COMMON_HASHES = {
    "LICENSE": "a32206bcfbf5d6bb23be8a876de424d8a8d2a0e30a9adc9f8e1b3139fada9176",
}
_EXPECTED_HASHES = {
    **_COMMON_HASHES,
    "Control/Counter/counter_12/design_description.txt": (
        "7619e91759a69d54556766ecf5d370345a9445d279108aa38700258a9cbdfc0e"
    ),
    "Control/Counter/counter_12/makefile": (
        "a01e995ffe79476648fc6833b86e8a6bf337da3b07d4ed152afa4dce4768e0a8"
    ),
    "Control/Counter/counter_12/testbench.v": (
        "e47a642c0cece07786ec5d19f417221345fabb9dd22cdd51dbacedd5f731223a"
    ),
    "Control/Counter/counter_12/verified_counter_12.v": (
        "e3551f7d82fa522f9e9afe01a2c4ff35bd61143d395f490e17d340cb16a6ae04"
    ),
}
_UP_DOWN_EXPECTED_HASHES = {
    **_COMMON_HASHES,
    "Control/Counter/up_down_counter/design_description.txt": (
        "c14e7e7b9c465d9b65a4e69ea437ca57c76fae5ef9dbd7711aff5765745efcaa"
    ),
    "Control/Counter/up_down_counter/makefile": (
        "4ae77da544244cdc15e33b5380321b44e4729e3042c1d14df4ca82e526e7fb7e"
    ),
    "Control/Counter/up_down_counter/testbench.v": (
        "d7fde8db2019384d00c5933ebad11757a37f2e21e49c0e778986f57739723f95"
    ),
    "Control/Counter/up_down_counter/verified_up_down_counter.v": (
        "4af9a3fe6a61aefa2e6ba8df99bf10e2f1432a9c2cf460b8267d2ce14e739445"
    ),
}
_UP_DOWN_ICARUS_TRAINING_VARIANT = "up_down_counter_iverilog_training"
_AGENT_EVAL_VARIANTS = frozenset({"counter_12_agent_eval_v1", "up_down_counter_agent_eval_v1"})
_SUPPORTED_VARIANTS = frozenset(
    {"counter_12", "up_down_counter", _UP_DOWN_ICARUS_TRAINING_VARIANT, *_AGENT_EVAL_VARIANTS}
)
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
        ],
        title="RTLLM pinned counter-family pilot",
        description="Pinned external-source RTLLM tasks for commercial-flow validation.",
        suite_version=SUITE_VERSION,
        license="MIT",
    )

    def __init__(self, config: SuiteSourceConfig | None = None) -> None:
        self._config = config
        self._workspace_root = Path(__file__).parent / "assets" / "workspace"
        self._up_down_workspace_root = Path(__file__).parent / "assets" / "workspace_up_down"
        self._snapshot_cache: SuiteSourceSnapshot | None = None
        self._agent_workspaces: list[AgentEvalWorkspace] = []

    def with_source(self, config: SuiteSourceConfig) -> RTLLMSuite:
        if config.variant not in {None, *_SUPPORTED_VARIANTS}:
            supported = ", ".join(sorted(_SUPPORTED_VARIANTS))
            raise ConfigurationError(f"the RTLLM pilot supports variants: {supported}")
        return RTLLMSuite(config.model_copy(update={"variant": config.variant or "counter_12"}))

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        adapter = self._adapter_for_optional_root(source_root)
        report = adapter.validate_source()
        if not report.valid:
            raise ConfigurationError("invalid RTLLM source: " + "; ".join(report.errors[:3]))
        variant = adapter._variant()
        return [TaskRef(id=f"rtllm/{variant}", suite="rtllm", native_id=variant)]

    def load_task(self, ref: TaskRef) -> VeriTask:
        variant = self._variant()
        if ref.suite != "rtllm" or ref.native_id != variant:
            raise ConfigurationError(f"unknown RTLLM task: {ref.id}")
        base_variant = self._base_variant()
        up_down = base_variant == "up_down_counter"
        icarus_training = variant == _UP_DOWN_ICARUS_TRAINING_VARIANT
        agent_eval = variant in _AGENT_EVAL_VARIANTS
        task_root = UP_DOWN_TASK_ROOT if up_down else TASK_ROOT
        expected_hashes = _UP_DOWN_EXPECTED_HASHES if up_down else _EXPECTED_HASHES
        suite_version = (
            AGENT_EVAL_SUITE_VERSION
            if agent_eval
            else UP_DOWN_ICARUS_TRAINING_SUITE_VERSION
            if icarus_training
            else UP_DOWN_SUITE_VERSION
            if up_down
            else SUITE_VERSION
        )
        title = "RTLLM 16-bit up/down counter" if up_down else "RTLLM 12-state enabled counter"
        candidate_top = "up_down_counter" if up_down else "counter_12"
        testbench_top = "testbench" if up_down else "counter_12_tb"
        pass_marker = UP_DOWN_PASS_MARKER if up_down else PASS_MARKER
        fail_marker = UP_DOWN_FAIL_MARKER if up_down else FAIL_MARKER
        candidate_path = (
            f"repository/rtl/{base_variant}.v" if agent_eval else f"rtl/{base_variant}.v"
        )
        root = self._source_root()
        report = self.validate_source()
        if not report.valid:
            raise ConfigurationError("invalid RTLLM source: " + "; ".join(report.errors[:3]))
        prompt = _read_exact(root, (task_root / "design_description.txt").as_posix()).decode(
            "utf-8"
        )
        snapshot = self._snapshot()
        hidden = AssetRef(
            kind="inline",
            content_hash=expected_hashes[(task_root / "testbench.v").as_posix()],
            mount_path="verifier/testbench.v",
        )
        return VeriTask(
            id=f"rtllm/{variant}",
            suite="rtllm",
            suite_version=suite_version,
            task_type=TaskType.GENERATION,
            title=title,
            description=prompt,
            source=SourceSpec(
                kind="benchmark",
                uri=(
                    f"https://github.com/hkust-zhiyao/RTLLM/tree/{PINNED_COMMIT}/"
                    f"Control/Counter/{base_variant}"
                ),
                revision=suite_version,
                commit=PINNED_COMMIT,
                license="MIT",
                attribution="RTLLM, supplied as an external pinned checkout.",
                content_hash=snapshot.dataset_content_hash,
            ),
            workspace=WorkspaceSpec(
                base=AssetRef(
                    kind="directory",
                    path="workspace_up_down" if up_down else "workspace",
                ),
                editable_globs=[candidate_path],
                readonly_globs=(
                    ["TASK.md", "PUBLIC_TESTS.md", "repository/README.md"]
                    if agent_eval
                    else ["README.md"]
                ),
                excluded_globs=["verifier", "verifier/**", "hidden", "hidden/**"],
                entrypoints=[candidate_path],
                hidden_assets=[hidden],
                max_changed_files=1,
                max_patch_lines=2_000,
            ),
            interaction=InteractionSpec(
                supported_modes=(
                    [InteractionMode.AGENT]
                    if agent_eval
                    else [InteractionMode.CHAT, InteractionMode.AGENT]
                ),
                default_mode=(InteractionMode.AGENT if agent_eval else InteractionMode.CHAT),
                allowed_tools=[
                    "file.list",
                    "file.read",
                    "file.apply_patch",
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
                max_workspace_bytes=2_000_000,
            ),
            verifier=VerifierGraph(
                nodes=(
                    [
                        VerifierNode(
                            id="compile_hidden",
                            plugin="iverilog.compile",
                            gate=True,
                            required=True,
                            visibility=ToolVisibility.VERIFIER_ONLY,
                            timeout_s=30,
                            request={
                                "sources": [candidate_path, "verifier/testbench.v"],
                                "top": testbench_top,
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
                                "pass_marker": pass_marker,
                                "fail_marker": fail_marker,
                                "timeout_s": 30,
                            },
                        ),
                    ]
                    if icarus_training or agent_eval
                    else [
                        VerifierNode(
                            id="vcs_regression",
                            plugin="synopsys.vcs.simulate",
                            gate=True,
                            required=True,
                            visibility=ToolVisibility.VERIFIER_ONLY,
                            timeout_s=180,
                            request={
                                "sources": [candidate_path],
                                "testbench": "verifier/testbench.v",
                                "top": testbench_top,
                                "pass_marker": pass_marker,
                                "fail_marker": fail_marker,
                                "timeout_s": 180,
                            },
                        )
                    ]
                )
            ),
            scoring=ScoringSpec(
                correctness_required_nodes=(
                    ["compile_hidden", "run_hidden"]
                    if icarus_training or agent_eval
                    else ["vcs_regression"]
                ),
                ppa_enabled=not icarus_training,
            ),
            metadata={
                "native_task_id": f"Control/Counter/{base_variant}",
                "official_task_id": f"rtllm/{base_variant}",
                "candidate_top": candidate_top,
                "testbench_top": testbench_top,
                "language": "verilog-2005",
                "dataset_content_hash": snapshot.dataset_content_hash,
                "adapter_version": ADAPTER_VERSION,
                "pinned_commit": PINNED_COMMIT,
                "evaluation_profile": (
                    "icarus12-agent-eval-v1"
                    if agent_eval
                    else "icarus-training-long-context-v1"
                    if icarus_training
                    else "vcs-benchmark-v1"
                ),
                **(
                    {
                        "synthesis_source_projection": synthesis_source_projection_contract(
                            {candidate_path: f"rtl/{base_variant}.v"}
                        ),
                        "agent_eval": {
                            "benchmark_variant": variant,
                            "compile_test_id": "compile",
                            "ppa_supported": True,
                            "public_test_contract_hash": content_hash(
                                compile_feedback_contract(
                                    source_paths=[f"rtl/{base_variant}.v"],
                                    top_module=candidate_top,
                                    language="2005",
                                )
                            ),
                        },
                    }
                    if agent_eval
                    else {}
                ),
            },
        )

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        variant = self._variant()
        if task.id != f"rtllm/{variant}":
            raise ConfigurationError(f"unknown RTLLM task: {task.id}")
        up_down = self._base_variant() == "up_down_counter"
        task_root = UP_DOWN_TASK_ROOT if up_down else TASK_ROOT
        root = self._source_root()
        snapshot = self._snapshot()
        if task.source.content_hash != snapshot.dataset_content_hash:
            raise ConfigurationError("RTLLM task identity differs from the source snapshot")
        testbench = _read_exact(root, (task_root / "testbench.v").as_posix())
        if variant in _AGENT_EVAL_VARIANTS:
            base_workspace = self._up_down_workspace_root if up_down else self._workspace_root
            public_contract = compile_feedback_contract(
                source_paths=[f"rtl/{self._base_variant()}.v"],
                top_module="up_down_counter" if up_down else "counter_12",
                language="2005",
            )
            materialized = materialize_agent_eval_workspace(
                task_description=task.description,
                repository_files={
                    "README.md": (base_workspace / "README.md").read_text(encoding="utf-8"),
                    f"rtl/{self._base_variant()}.v": (
                        base_workspace / "rtl" / f"{self._base_variant()}.v"
                    ).read_text(encoding="utf-8"),
                },
                compile_contract=public_contract,
                ppa_available=True,
            )
            self._agent_workspaces.append(materialized)
            visible_root = str(materialized.visible_root)
            read_only_mounts = (
                [materialized.read_only_mount] if materialized.read_only_mount is not None else []
            )
        else:
            visible_root = str(
                (self._up_down_workspace_root if up_down else self._workspace_root).resolve(
                    strict=True
                )
            )
            read_only_mounts = []
        return ResolvedTaskAssets(
            visible_root=visible_root,
            hidden_assets=[
                AssetRef(
                    kind="inline",
                    content=testbench.decode("utf-8"),
                    content_hash=_hash_bytes(testbench),
                    mount_path="verifier/testbench.v",
                )
            ],
            read_only_mounts=read_only_mounts,
        )

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        try:
            adapter = self._adapter_for_optional_root(source_root)
            root = adapter._source_root()
        except ConfigurationError as exc:
            return _invalid("source_configuration", str(exc))
        expected_hashes = (
            _UP_DOWN_EXPECTED_HASHES
            if adapter._base_variant() == "up_down_counter"
            else _EXPECTED_HASHES
        )
        issues: list[ValidationIssue] = []
        for relative, expected in sorted(expected_hashes.items()):
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
                continue
            if actual != expected:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="source_hash",
                        message="file differs from the pinned RTLLM revision",
                        relative_path=relative,
                    )
                )
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
        variant = self._variant()
        if task.id != f"rtllm/{variant}":
            return None
        base_variant = self._base_variant()
        up_down = base_variant == "up_down_counter"
        task_root = UP_DOWN_TASK_ROOT if up_down else TASK_ROOT
        source = _read_exact(
            self._source_root(), (task_root / f"verified_{base_variant}.v").as_posix()
        ).decode("utf-8")
        needle = f"module verified_{base_variant}" if not up_down else "module up_down_counter"
        if source.count(needle) != 1:
            raise ConfigurationError("RTLLM reference module normalization is no longer exact")
        candidate_path = (
            f"repository/rtl/{base_variant}.v"
            if variant in _AGENT_EVAL_VARIANTS
            else f"rtl/{base_variant}.v"
        )
        return Candidate(
            files={candidate_path: source.replace(needle, f"module {base_variant}", 1)},
            label="pinned-upstream-reference",
        )

    def conformance_cases(self) -> Iterable[ConformanceCase]:
        if self._config is None:
            return []
        variant = self._variant()
        base_variant = self._base_variant()
        task = self.load_task(TaskRef(id=f"rtllm/{variant}", suite="rtllm", native_id=variant))
        reference = self.reference_solution(task)
        assert reference is not None
        candidate_path = f"rtl/{base_variant}.v"
        bad_source = (
            "module up_down_counter(input clk, reset, up_down, output [15:0] count); "
            "assign count = 16'b0; endmodule\n"
            if base_variant == "up_down_counter"
            else (
                "module counter_12(input rst_n, clk, valid_count, "
                "output [3:0] out); assign out = 4'b0; endmodule\n"
            )
        )
        return [
            ConformanceCase(
                name=f"{variant}-reference",
                candidate=reference,
                expected_resolved=True,
            ),
            ConformanceCase(
                name=f"{variant}-stuck-zero",
                candidate=Candidate(
                    files={candidate_path: bad_source},
                    label="known-bad",
                ),
                expected_resolved=False,
            ),
        ]

    def source_snapshot(self) -> SuiteSourceSnapshot | None:
        if self._config is None:
            return None
        return self._snapshot().model_copy(deep=True)

    def toolchain_profile(self, runtime: Runtime, tools: Any) -> ToolchainProfile | None:
        if self._variant() == _UP_DOWN_ICARUS_TRAINING_VARIANT or self._variant() in (
            _AGENT_EVAL_VARIANTS
        ):
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
            if self._variant() in _AGENT_EVAL_VARIANTS and not all(
                _is_icarus12_version(version) for version in (compiler_version, runner_version)
            ):
                raise ConfigurationError(
                    "RTLLM AgentEval requires qualified Icarus and vvp major version 12"
                )
            if self._variant() in _AGENT_EVAL_VARIANTS:
                compatibility = "reference_compatible"
            return ToolchainProfile(
                id=(
                    "rtllm-icarus12-agent-eval-v1"
                    if self._variant() in _AGENT_EVAL_VARIANTS
                    else "rtllm-icarus-training-v1"
                ),
                version="1.0.0",
                description=(
                    "Pinned Icarus functional verifier for an RTLLM AgentEval partition."
                    if self._variant() in _AGENT_EVAL_VARIANTS
                    else "Pinned Icarus training verifier for RTLLM sampling; scores are not "
                    "VCS benchmark results."
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
            description="Site-local VCS functional-verification profile for the RTLLM pilot.",
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
        if variant == _UP_DOWN_ICARUS_TRAINING_VARIANT:
            return "up_down_counter"
        if variant.endswith("_agent_eval_v1"):
            return variant.removesuffix("_agent_eval_v1")
        return variant

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
        base_variant = self._base_variant()
        up_down = base_variant == "up_down_counter"
        task_root = UP_DOWN_TASK_ROOT if up_down else TASK_ROOT
        expected_hashes = _UP_DOWN_EXPECTED_HASHES if up_down else _EXPECTED_HASHES
        dataset_hash = _canonical_hash(
            {key: value for key, value in expected_hashes.items() if key != "LICENSE"}
        )
        commit = _git_commit(root)
        self._snapshot_cache = SuiteSourceSnapshot(
            source_root=str(root),
            dataset_root=str((root / task_root).resolve(strict=True)),
            variant=variant,
            native_layout=f"RTLLM/Control/Counter/{base_variant}",
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
            license_file_hash=expected_hashes["LICENSE"],
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
    return ValidationReport(
        valid=False,
        errors=[f"[{code}] {message}"],
        issues=[issue],
    )


__all__ = ["ADAPTER_VERSION", "PINNED_COMMIT", "RTLLMSuite", "SUITE_VERSION"]
