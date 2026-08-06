"""Pinned, external-source RTLLM counter task adapter."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

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
)

ADAPTER_VERSION = "0.1.0"
SUITE_VERSION = "rtllm-41b2689-counter12-v1"
PINNED_COMMIT = "41b26896e33b536940116a975626455eed3de65e"
CANONICAL_REMOTE = "https://github.com/hkust-zhiyao/RTLLM.git"
TASK_ROOT = Path("Control/Counter/counter_12")
PASS_MARKER = "===========Your Design Passed==========="
FAIL_MARKER = "===========Failed==========="
_EXPECTED_HASHES = {
    "LICENSE": "a32206bcfbf5d6bb23be8a876de424d8a8d2a0e30a9adc9f8e1b3139fada9176",
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
            "synthesis_ready",
            "conformance",
        ],
        title="RTLLM pinned pilot",
        description="Pinned external-source RTLLM task for commercial-flow validation.",
        suite_version=SUITE_VERSION,
        license="MIT",
    )

    def __init__(self, config: SuiteSourceConfig | None = None) -> None:
        self._config = config
        self._workspace_root = Path(__file__).parent / "assets" / "workspace"
        self._snapshot_cache: SuiteSourceSnapshot | None = None

    def with_source(self, config: SuiteSourceConfig) -> RTLLMSuite:
        if config.variant not in {None, "counter_12"}:
            raise ConfigurationError("the RTLLM pilot supports only variant 'counter_12'")
        return RTLLMSuite(config.model_copy(update={"variant": "counter_12"}))

    def discover(self, source_root: Path | None = None) -> Iterable[TaskRef]:
        adapter = self._adapter_for_optional_root(source_root)
        report = adapter.validate_source()
        if not report.valid:
            raise ConfigurationError("invalid RTLLM source: " + "; ".join(report.errors[:3]))
        return [TaskRef(id="rtllm/counter_12", suite="rtllm", native_id="counter_12")]

    def load_task(self, ref: TaskRef) -> VeriTask:
        if ref.suite != "rtllm" or ref.native_id != "counter_12":
            raise ConfigurationError(f"unknown RTLLM task: {ref.id}")
        root = self._source_root()
        report = self.validate_source()
        if not report.valid:
            raise ConfigurationError("invalid RTLLM source: " + "; ".join(report.errors[:3]))
        prompt = _read_exact(root, (TASK_ROOT / "design_description.txt").as_posix()).decode(
            "utf-8"
        )
        snapshot = self._snapshot()
        hidden = AssetRef(
            kind="inline",
            content_hash=_EXPECTED_HASHES["Control/Counter/counter_12/testbench.v"],
            mount_path="verifier/testbench.v",
        )
        return VeriTask(
            id="rtllm/counter_12",
            suite="rtllm",
            suite_version=SUITE_VERSION,
            task_type=TaskType.GENERATION,
            title="RTLLM 12-state enabled counter",
            description=prompt,
            source=SourceSpec(
                kind="benchmark",
                uri=(
                    f"https://github.com/hkust-zhiyao/RTLLM/tree/{PINNED_COMMIT}/"
                    "Control/Counter/counter_12"
                ),
                revision=SUITE_VERSION,
                commit=PINNED_COMMIT,
                license="MIT",
                attribution="RTLLM, supplied as an external pinned checkout.",
                content_hash=snapshot.dataset_content_hash,
            ),
            workspace=WorkspaceSpec(
                base=AssetRef(kind="directory", path="workspace"),
                editable_globs=["rtl/counter_12.v"],
                readonly_globs=["README.md"],
                excluded_globs=["verifier", "verifier/**", "hidden", "hidden/**"],
                entrypoints=["rtl/counter_12.v"],
                hidden_assets=[hidden],
                max_changed_files=1,
                max_patch_lines=2_000,
            ),
            interaction=InteractionSpec(
                supported_modes=[InteractionMode.CHAT, InteractionMode.AGENT],
                default_mode=InteractionMode.CHAT,
                allowed_tools=[
                    "file.list",
                    "file.read",
                    "file.apply_patch",
                    "file.diff",
                ],
                allow_general_shell=False,
                network_policy="none",
                initial_observation=ObservationPolicy(
                    include_tree=True,
                    include_readme=True,
                    include_entrypoints=False,
                ),
                final_submission=SubmissionPolicy(kind="file", path="rtl/counter_12.v"),
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
                nodes=[
                    VerifierNode(
                        id="vcs_regression",
                        plugin="synopsys.vcs.simulate",
                        gate=True,
                        required=True,
                        visibility=ToolVisibility.VERIFIER_ONLY,
                        timeout_s=180,
                        request={
                            "sources": ["rtl/counter_12.v"],
                            "testbench": "verifier/testbench.v",
                            "top": "counter_12_tb",
                            "pass_marker": PASS_MARKER,
                            "fail_marker": FAIL_MARKER,
                            "timeout_s": 180,
                        },
                    )
                ]
            ),
            scoring=ScoringSpec(
                correctness_required_nodes=["vcs_regression"],
                ppa_enabled=True,
            ),
            metadata={
                "native_task_id": "Control/Counter/counter_12",
                "candidate_top": "counter_12",
                "testbench_top": "counter_12_tb",
                "language": "verilog-2005",
                "dataset_content_hash": snapshot.dataset_content_hash,
                "adapter_version": ADAPTER_VERSION,
                "pinned_commit": PINNED_COMMIT,
            },
        )

    def resolve_assets(self, task: VeriTask) -> ResolvedTaskAssets:
        if task.id != "rtllm/counter_12":
            raise ConfigurationError(f"unknown RTLLM task: {task.id}")
        root = self._source_root()
        snapshot = self._snapshot()
        if task.source.content_hash != snapshot.dataset_content_hash:
            raise ConfigurationError("RTLLM task identity differs from the source snapshot")
        testbench = _read_exact(root, (TASK_ROOT / "testbench.v").as_posix())
        return ResolvedTaskAssets(
            visible_root=str(self._workspace_root.resolve(strict=True)),
            hidden_assets=[
                AssetRef(
                    kind="inline",
                    content=testbench.decode("utf-8"),
                    content_hash=_hash_bytes(testbench),
                    mount_path="verifier/testbench.v",
                )
            ],
        )

    def validate_source(self, source_root: Path | None = None) -> ValidationReport:
        try:
            adapter = self._adapter_for_optional_root(source_root)
            root = adapter._source_root()
        except ConfigurationError as exc:
            return _invalid("source_configuration", str(exc))
        issues: list[ValidationIssue] = []
        for relative, expected in sorted(_EXPECTED_HASHES.items()):
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
        if task.id != "rtllm/counter_12":
            return None
        source = _read_exact(
            self._source_root(), (TASK_ROOT / "verified_counter_12.v").as_posix()
        ).decode("utf-8")
        needle = "module verified_counter_12"
        if source.count(needle) != 1:
            raise ConfigurationError("RTLLM reference module normalization is no longer exact")
        return Candidate(
            files={"rtl/counter_12.v": source.replace(needle, "module counter_12", 1)},
            label="pinned-upstream-reference",
        )

    def conformance_cases(self) -> Iterable[ConformanceCase]:
        if self._config is None:
            return []
        task = self.load_task(TaskRef(id="rtllm/counter_12", suite="rtllm", native_id="counter_12"))
        reference = self.reference_solution(task)
        assert reference is not None
        return [
            ConformanceCase(
                name="counter-12-reference",
                candidate=reference,
                expected_resolved=True,
            ),
            ConformanceCase(
                name="counter-12-stuck-zero",
                candidate=Candidate(
                    files={
                        "rtl/counter_12.v": (
                            "module counter_12(input rst_n, clk, valid_count, "
                            "output [3:0] out); assign out = 4'b0; endmodule\n"
                        )
                    },
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
                variant="counter_12",
                strict_compatibility=strict,
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
        dataset_hash = _canonical_hash(
            {key: value for key, value in _EXPECTED_HASHES.items() if key != "LICENSE"}
        )
        commit = _git_commit(root)
        self._snapshot_cache = SuiteSourceSnapshot(
            source_root=str(root),
            dataset_root=str((root / TASK_ROOT).resolve(strict=True)),
            variant="counter_12",
            native_layout="RTLLM/Control/Counter/counter_12",
            strict_compatibility=self._config.strict_compatibility if self._config else True,
            configuration_fingerprint=_canonical_hash(
                {
                    "source_root": str(root),
                    "variant": "counter_12",
                    "strict_compatibility": (
                        self._config.strict_compatibility if self._config else True
                    ),
                }
            ),
            dataset_content_hash=dataset_hash,
            license_id="MIT",
            license_file_hash=_EXPECTED_HASHES["LICENSE"],
            git_commit=commit,
            git_remote=CANONICAL_REMOTE if commit is not None else None,
            git_metadata_available=commit is not None,
            synthetic_fixture=False,
        )
        return self._snapshot_cache


def _invalid(code: str, message: str) -> ValidationReport:
    issue = ValidationIssue(level="error", code=code, message=message)
    return ValidationReport(
        valid=False,
        errors=[f"[{code}] {message}"],
        issues=[issue],
    )


__all__ = ["ADAPTER_VERSION", "PINNED_COMMIT", "RTLLMSuite", "SUITE_VERSION"]
