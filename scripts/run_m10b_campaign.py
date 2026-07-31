#!/usr/bin/env python3
"""Execute the commit-bound Milestone 10B Evolve-Context campaign once."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from verigym_codex_cli.capabilities import discover_capabilities, runtime_capabilities
from verigym_codex_cli.config import readonly_agent_settings, settings_for_execution_backend
from verigym_codex_cli.memory_builder import (
    execute_memory_synthesis,
    memory_builder_identity_hashes,
    memory_runtime_binding_hashes,
)
from verigym_codex_cli.process import auth_identity_configuration
from verigym_codex_cli.runtime_execution import resolve_runtime_process_invocation_spec
from verigym_codex_cli.util import atomic_json

from verigym.core.external_agent import RuntimeExternalAgentBridge
from verigym.core.external_process_identity import (
    bind_external_process_payload,
    preview_external_process_identity,
)
from verigym.core.hashing import canonical_json, content_hash
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.core.sampling import classify_sample_outcome
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.core.trace import TraceWriter
from verigym.core.workspace import WorkspacePolicy
from verigym.evolution.comparison import (
    build_evolving_evaluation,
    validate_evolving_evaluation,
)
from verigym.evolution.exporter import (
    TrajectoryExporter,
    replay_trajectory_dataset,
)
from verigym.evolution.ledger import (
    authorize_process,
    finish_process,
    seal_process_ledger,
)
from verigym.evolution.memory import (
    build_agent_version,
    prepare_training_summary,
    validate_memory_pack,
)
from verigym.evolution.memory_builder import (
    MEMORY_BUILDER_PROMPT_CONTRACT_ID,
    MEMORY_BUILDER_PROMPT_TEMPLATE_HASH,
    build_memory_builder_input,
    build_memory_synthesis_plan,
    reconstruct_memory_synthesis_launch,
    render_memory_builder_prompt,
)
from verigym.evolution.reporting import EvolutionReportService
from verigym.evolution.rewards import classify_outcome
from verigym.evolution.splits import (
    build_task_split,
    scan_contamination,
    validate_contamination_scan,
)
from verigym.evolution.versions import (
    build_agent_lineage,
    build_agent_version_set,
    build_run_version_assignments,
    freeze_context_update,
    replay_context_update,
    validate_plan_agent_version_binding,
)
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig, ExperimentPlan, PlanItem
from verigym.experiments.state import (
    atomic_dump_json,
    atomic_write_text,
    load_jsonl_models,
)
from verigym.prompts.policy import prompt_contract_identity_hash
from verigym.reporting.loader import load_report_inputs
from verigym.runtimes.docker.external_process import (
    external_process_configuration_fingerprint,
)
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.evolution import (
    AgentVersionManifest,
    EpisodeTrajectory,
    MemoryBuilderInput,
    MemoryPack,
    MemorySynthesisPlan,
    RewardVector,
    RunAgentVersionAssignment,
    SanitizedTrainingSummary,
    TaskSplitEntry,
    TaskSplitManifest,
)
from verigym.schemas.external_agent import ExternalProcessResult
from verigym.schemas.repository import RepositoryTaskManifest
from verigym.schemas.run import RunConfig, RunResult
from verigym.schemas.runtime import (
    DockerExternalAgentRuntimeConfig,
    DockerRuntimeConfig,
    SessionSpec,
)

AUTHORIZATION_ID = "m10b-prompt-binding-owner-contract-v1"
START_COMMIT = "de9dc9ddf723173cf085c7870dfa6857ed109064"
START_BRANCH = "milestone10b-evolving-agent-evaluation"
MODEL_ID = "gpt-5.4"
REASONING_EFFORT = "xhigh"
CODEX_VERSION = "codex-cli 0.144.6"
CODEX_WRAPPER_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"
CODEX_NATIVE_SHA256 = "a31ae9450a26216eb1e7c53102fd42123dd675974310b0e2ca3aa4cb622a2c15"
AUTH_SEMANTIC_ID = "codex.auth.inherited_chatgpt_session.v1"
VERIFIER_IMAGE_ID = "sha256:8446a2d0c980ad27f93f03cfd52d207fa3b153605ac0db8c6c3489bc63bd35f0"
REPOSITORY_AGENT_IMAGE_ID = (
    "sha256:28b10111ae143d1580700f3a5bfb18a667758bfddb3d2a6cda8d96542d772777"
)
MEMORY_AGENT_IMAGE_ID = "sha256:b22da25b8db35190a2d1f4d80d02c60a952e7fb0006dc0a3cc7ab975e95c598f"
PUBLIC_LAUNCHER_SHA256 = "e3276ee142e7de78fd60bf4078138152d1974c93f72f27fd2eb95a3f6493b407"
M10A_BUNDLE = Path("/data/jzhu484/Agent/VeriGym_milestone10a_53b0755/evidence-bundle-final")
FAILED_M10B_BUNDLE = Path("/data/jzhu484/Agent/VeriGym_milestone10b_de9dc9d/evidence-bundle-final")
FAILED_M10B_CHECKSUM_HASH = "fd549b7e064aabdad1c2e07630de62f8e424a9a4c368d7df71813c048def8188"
REFERENCE_EXPERIMENT = Path("/data/jzhu484/Agent/VeriGym_reference_qualified_52318e1")
REFERENCE_CHECKPOINT_MANIFEST = REFERENCE_EXPERIMENT / "checkpoint-bundle-114/BUNDLE-MANIFEST.json"
REFERENCE_CHECKPOINT_HASH = "2d5cdb67bf60c1a26f3b20bfab4c50bbe3efc331db3bf7508ece2f1cbf3d1ce9"
TRAINING_TASKS = (
    "repo-rtl/arbiter-reset-recovery",
    "repo-rtl/counter-wrap",
    "repo-rtl/pipeline-stall-backpressure",
)
HELDOUT_TASKS = (
    "repo-rtl/arbiter-rotating-priority-heldout",
    "repo-rtl/counter-load-wrap-heldout",
    "repo-rtl/pipeline-flush-heldout",
)
PROXY_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "ALL_PROXY",
    "all_proxy",
)
API_KEY_NAMES = ("OPENAI_API_KEY", "CODEX_API_KEY")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def _assert_source_identity(expected_commit: str, expected_tree: str) -> None:
    if _git("rev-parse", "HEAD") != expected_commit:
        raise RuntimeError("source commit differs from the campaign authorization")
    if _git("rev-parse", "HEAD^{tree}") != expected_tree:
        raise RuntimeError("source tree differs from the campaign authorization")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("source worktree is not clean")
    if _git("merge-base", "--is-ancestor", START_COMMIT, expected_commit) != "":
        raise RuntimeError("final commit does not descend from the required M10A baseline")


def _assert_checksum_manifest(root: Path) -> int:
    manifest = root / "SHA256SUMS"
    if not manifest.is_file() or manifest.is_symlink():
        raise RuntimeError(f"protected bundle lacks a safe checksum manifest: {root}")
    count = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        path = root / relative
        if (
            not separator
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not path.is_file()
            or path.is_symlink()
            or _sha256(path) != digest
        ):
            raise RuntimeError(f"protected bundle checksum failed: {relative}")
        count += 1
    return count


def _preservation_identity() -> dict[str, Any]:
    failed_m10b_count = _assert_checksum_manifest(FAILED_M10B_BUNDLE)
    if _sha256(FAILED_M10B_BUNDLE / "SHA256SUMS") != FAILED_M10B_CHECKSUM_HASH:
        raise RuntimeError("failed M10B bundle checksum-manifest identity changed")
    m10a_count = _assert_checksum_manifest(M10A_BUNDLE)
    if _sha256(REFERENCE_CHECKPOINT_MANIFEST) != REFERENCE_CHECKPOINT_HASH:
        raise RuntimeError("reference-qualified experiment checkpoint identity changed")
    return {
        "schema_version": "1.0",
        "failed_m10b_bundle_checksum_manifest_sha256": _sha256(FAILED_M10B_BUNDLE / "SHA256SUMS"),
        "failed_m10b_bundle_verified_file_count": failed_m10b_count,
        "m10a_bundle_checksum_manifest_sha256": _sha256(M10A_BUNDLE / "SHA256SUMS"),
        "m10a_bundle_verified_file_count": m10a_count,
        "reference_experiment_checkpoint_manifest_sha256": _sha256(REFERENCE_CHECKPOINT_MANIFEST),
        "protected_assets_modified": False,
    }


def _image_hash(value: str) -> str:
    prefix, separator, digest = value.partition(":")
    if prefix != "sha256" or not separator or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"invalid immutable image identity: {value}")
    return digest


def _repository_agent_config() -> DockerExternalAgentRuntimeConfig:
    return DockerExternalAgentRuntimeConfig(
        image="verigym/codex-repository-agent:m10a-ci-repro",
        expected_image_id=REPOSITORY_AGENT_IMAGE_ID,
        expected_executable_name="codex",
        expected_executable_path="/usr/local/bin/codex",
        expected_executable_version=CODEX_VERSION,
        expected_executable_sha256=CODEX_NATIVE_SHA256,
        process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
        protocol="codex_app_server_remote_environment_v1",
        required_image_labels={
            "org.verigym.runtime.role": "repository-agent",
            "org.verigym.codex.version": "0.144.6",
            "org.verigym.codex.binary.sha256": CODEX_NATIVE_SHA256,
            "org.verigym.public_test_launcher.sha256": PUBLIC_LAUNCHER_SHA256,
            "org.verigym.iverilog.version": "12.0",
            "org.verigym.provider_credentials": "absent",
            "org.verigym.credential_material": "absent",
        },
        pull_policy="never",
        run_as_user=f"{os.getuid()}:{os.getgid()}",
        memory_bytes=1024 * 1024 * 1024,
        cpus=1.0,
        pids_limit=128,
        tmpfs_bytes=256 * 1024 * 1024,
        max_process_time_s=300,
        max_output_bytes=8 * 1024 * 1024,
    )


def _memory_agent_config() -> DockerExternalAgentRuntimeConfig:
    return DockerExternalAgentRuntimeConfig(
        image="verigym/codex-exec-server:0.144.6",
        expected_image_id=MEMORY_AGENT_IMAGE_ID,
        expected_executable_name="codex",
        expected_executable_path="/usr/local/bin/codex",
        expected_executable_version=CODEX_VERSION,
        expected_executable_sha256=CODEX_NATIVE_SHA256,
        process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
        protocol="codex_app_server_remote_environment_v1",
        required_image_labels={
            "org.verigym.codex.version": "0.144.6",
            "org.verigym.codex.binary.sha256": CODEX_NATIVE_SHA256,
            "org.verigym.external_agent.protocol": ("codex_app_server_remote_environment_v1"),
            "org.verigym.provider_credentials": "absent",
            "org.verigym.credential_material": "absent",
        },
        pull_policy="never",
        run_as_user=f"{os.getuid()}:{os.getgid()}",
        memory_bytes=1024 * 1024 * 1024,
        cpus=1.0,
        pids_limit=128,
        tmpfs_bytes=256 * 1024 * 1024,
        max_process_time_s=300,
        max_output_bytes=131_072,
    )


def _docker_config(
    external_agent: DockerExternalAgentRuntimeConfig | None = None,
) -> DockerRuntimeConfig:
    return DockerRuntimeConfig(
        image="verigym/rtl-iverilog:m10a-ci-repro",
        expected_image_id=VERIFIER_IMAGE_ID,
        pull_policy="never",
        network_mode="none",
        run_as_user=f"{os.getuid()}:{os.getgid()}",
        memory_bytes=512 * 1024 * 1024,
        cpus=1.0,
        pids_limit=128,
        tmpfs_bytes=64 * 1024 * 1024,
        stop_timeout_s=3,
        max_command_time_s=300,
        max_artifact_file_bytes=16 * 1024 * 1024,
        max_artifact_bytes=64 * 1024 * 1024,
        environment_allowlist=[],
        external_agent=external_agent or _repository_agent_config(),
    )


def _common_agent_options(capability: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model_id": MODEL_ID,
        "sandbox": "workspace-write",
        "approval_policy": "non-interactive",
        "reasoning_effort": REASONING_EFFORT,
        "allow_proxy_environment": True,
        "max_process_time_s": 300,
        "max_output_bytes": 8 * 1024 * 1024,
        "expected_cli_version": CODEX_VERSION,
        "expected_cli_executable_sha256": CODEX_WRAPPER_SHA256,
        "expected_capability_fingerprint": capability["capability_fingerprint"],
        "expected_requested_auth_mode": "chatgpt_cli_session",
        "expected_resolved_auth_mode": "inherited_codex_login",
        "expected_auth_semantic_id": AUTH_SEMANTIC_ID,
        "expected_execution_backend": "docker_outer_runtime_delegated",
        "prompt_contract_id": "codex_cli_workspace_verilog_task_context_v1",
    }


def _versioned_options(
    capability: Mapping[str, Any],
    version: AgentVersionManifest,
    memory: MemoryPack | None = None,
) -> dict[str, Any]:
    options = _common_agent_options(capability)
    options.update(
        {
            "agent_version_id": version.agent_version_id,
            "agent_version_hash": version.version_hash,
            "agent_version_manifest_json": canonical_json(version),
        }
    )
    if memory is not None:
        options["memory_pack"] = memory.model_dump(mode="json")
    return options


def _experiment_config(
    *,
    name: str,
    output: Path,
    tasks: Sequence[str],
    systems: Sequence[tuple[str, dict[str, Any]]],
    samples: int,
    process_count: int,
    campaign_kind: str,
    source_commit: str,
    source_tree: str,
    package_hashes: Mapping[str, str],
    capability_fingerprint: str,
    counterbalanced: bool = False,
) -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {
            "schema_version": "1.0",
            "name": name,
            "description": "Commit-bound Milestone 10B repository-agent experiment.",
            "suite": {
                "id": "repo-rtl",
                "tasks": {"include": list(tasks), "exclude": []},
            },
            "runs": {
                "mode": "agent",
                "seeds": [0],
                "samples_per_task": samples,
                "pass_k": list(range(1, samples + 1)),
            },
            "systems": [
                {
                    "id": system_id,
                    "agent": {"id": "codex-cli-agent", "options": options},
                }
                for system_id, options in systems
            ],
            "runtime": {
                "id": "docker",
                "docker": _docker_config().model_dump(mode="json"),
            },
            "execution": {
                "max_workers": 1,
                "continue_on_infrastructure_error": True,
                "max_plan_items": process_count,
                "max_model_processes": process_count,
                "resume_model_process_policy": "never_rerun_after_authorization",
                "max_consecutive_identical_shared_infrastructure_failures": 1,
                "max_total_infrastructure_failures": 1,
                "summary_checkpoint_interval": 1,
                "seal_plan_before_execution": True,
                "plan_order_policy": (
                    "counterbalanced_systems_v1" if counterbalanced else "canonical"
                ),
                "frozen_campaign_identity": {
                    "campaign_kind": campaign_kind,
                    "owner_contract_id": AUTHORIZATION_ID,
                    "campaign_process_ceiling": 24,
                    "source_commit": source_commit,
                    "source_tree": source_tree,
                    "core_wheel_sha256": package_hashes["verigym"],
                    "plugin_wheel_sha256": package_hashes["verigym-codex-cli"],
                    "verifier_image_id": VERIFIER_IMAGE_ID,
                    "agent_image_id": REPOSITORY_AGENT_IMAGE_ID,
                    "codex_capability_fingerprint": capability_fingerprint,
                    "requested_model_id": MODEL_ID,
                    "reasoning_effort": REASONING_EFFORT,
                    "expected_auth_semantic_id": AUTH_SEMANTIC_ID,
                    "execution_backend": "docker_outer_runtime_delegated",
                    "verifier_toolchain": "Icarus Verilog 12",
                    "retry": False,
                    "resume": False,
                    "fallback": False,
                    "candidate_repair": False,
                    "best_of_n": False,
                },
            },
            "output": {"root": output},
        }
    )


class _CampaignChildExecutor:
    def __init__(
        self,
        ledger: Path,
        process_kind: str,
        authorization_id: str = AUTHORIZATION_ID,
    ) -> None:
        self.ledger = ledger
        self.process_kind = process_kind
        self.authorization_id = authorization_id

    def __call__(self, item: PlanItem, config: RunConfig) -> RunResult:
        version_hash = item.system.agent_options.get("agent_version_hash")
        authorization = authorize_process(
            self.ledger,
            process_kind=self.process_kind,
            authorization_id=self.authorization_id,
            run_or_build_id=config.run_id or item.plan_item_id,
            requested_model_id=MODEL_ID,
            reasoning_effort=REASONING_EFFORT,
            task_identity_hash=item.task_hash,
            agent_version_hash=version_hash if isinstance(version_hash, str) else None,
        )
        try:
            result = VeriGym().run(config)
        except BaseException as exc:
            finish_process(
                self.ledger,
                authorization_record=authorization,
                terminal_outcome=f"exception:{type(exc).__name__}",
            )
            raise
        outcome = classify_outcome(result.scorecard)
        finish_process(
            self.ledger,
            authorization_record=authorization,
            terminal_outcome=outcome,
        )
        return result


def _validate_plan_versions(plan: ExperimentPlan) -> None:
    campaign = plan.config.execution.frozen_campaign_identity
    source_commit = campaign.get("source_commit")
    core_hash = campaign.get("core_wheel_sha256")
    plugin_hash = campaign.get("plugin_wheel_sha256")
    if not all(isinstance(value, str) for value in (source_commit, core_hash, plugin_hash)):
        raise RuntimeError("plan omitted its source or package identity")
    package_hashes = {
        "verigym": str(core_hash),
        "verigym-codex-cli": str(plugin_hash),
    }
    for item in plan.items:
        raw = item.system.agent_options.get("agent_version_manifest_json")
        if not isinstance(raw, str):
            raise RuntimeError("model-bearing M10B plan item lacks an agent version manifest")
        version = AgentVersionManifest.model_validate_json(raw)
        validate_plan_agent_version_binding(
            version=version,
            item=item,
            source_commit=str(source_commit),
            package_hashes=package_hashes,
        )
        prompt = item.prompt_policy
        if (
            prompt is None
            or prompt.resolver_id != "agent_execution_prompt_policy_v1"
            or item.prompt_policy_hash != prompt.configuration_fingerprint
            or prompt.agent_version_id != version.agent_version_id
            or prompt.agent_version_hash != version.version_hash
            or prompt.memory_pack_hash != version.memory_pack_hash
            or prompt_contract_identity_hash(prompt) != version.prompt_contract_hash
        ):
            raise RuntimeError(
                "plan prompt policy differs from its frozen agent-version execution identity"
            )


def _run_experiment(
    config: ExperimentConfig,
    *,
    ledger: Path,
    process_kind: str,
    authorization_id: str = AUTHORIZATION_ID,
) -> tuple[ExperimentPlan, Path]:
    planner = ExperimentPlanner()
    plan = planner.build(config)
    expected_commit = config.execution.frozen_campaign_identity.get("source_commit")
    if plan.verigym_commit != expected_commit:
        raise RuntimeError("installed core package provenance differs from the frozen commit")
    _validate_plan_versions(plan)
    if len(plan.items) != config.execution.max_model_processes:
        raise RuntimeError("frozen plan process count differs from its budget")
    runner = BatchRunner(
        planner=planner,
        child_executor=_CampaignChildExecutor(
            ledger,
            process_kind,
            authorization_id=authorization_id,
        ),
    )
    result = runner.run(plan)
    if result.exit_code != 0:
        raise RuntimeError(
            f"{process_kind} experiment failed its execution gate: exit={result.exit_code}"
        )
    inputs = load_report_inputs(result.experiment_dir)
    if len(inputs.valid_runs) != len(plan.items) or any(
        not classify_sample_outcome(run.scorecard)[1] for run in inputs.valid_runs
    ):
        raise RuntimeError(f"{process_kind} did not produce only terminal evaluable runs")
    return plan, result.experiment_dir


def _task_entry(root: Path) -> TaskSplitEntry:
    manifest = load_model(root / "task.yaml", RepositoryTaskManifest)
    return TaskSplitEntry(
        task_id=manifest.task.id,
        source_hash=manifest.source.repository_hash,
        task_hash=content_hash(manifest.task),
        license=manifest.source.license,
        attribution=manifest.source.attribution,
    )


def _training_roots(repository_root: Path) -> dict[str, Path]:
    roots = {
        _task_entry(root).task_id: root
        for root in sorted((repository_root / "src/verigym/suites/repo_rtl/assets").iterdir())
        if (root / "task.yaml").is_file()
    }
    if set(roots) != set(TRAINING_TASKS):
        raise RuntimeError("training task census differs from the frozen three-task family")
    return roots


def _heldout_roots(repository_root: Path) -> dict[str, Path]:
    roots = {
        _task_entry(root).task_id: root
        for root in sorted(
            (repository_root / "src/verigym/suites/repo_rtl/heldout_assets").iterdir()
        )
        if (root / "task.yaml").is_file()
    }
    if set(roots) != set(HELDOUT_TASKS):
        raise RuntimeError("held-out task census differs from the frozen three-task family")
    return roots


def _run_assignments(experiment: Path, version_by_system: Mapping[str, str]) -> dict[str, str]:
    inputs = load_report_inputs(experiment)
    assignments: dict[str, str] = {}
    for run in inputs.valid_runs:
        if run.plan_item is None:
            raise RuntimeError("trajectory source lacks a frozen plan item")
        assignments[run.manifest.run_id] = version_by_system[run.plan_item.system.system_id]
    return assignments


@contextmanager
def _replay_environment() -> Iterator[None]:
    names = (
        "VERIGYM_CODEX_BINARY",
        "VERIGYM_CODEX_CAPABILITY_FILE",
        "CODEX_HOME",
        *API_KEY_NAMES,
        *PROXY_NAMES,
    )
    before = {name: os.environ.get(name) for name in names}
    try:
        os.environ["VERIGYM_CODEX_BINARY"] = "/nonexistent/verigym-replay-codex"
        for name in names:
            if name != "VERIGYM_CODEX_BINARY":
                os.environ.pop(name, None)
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _replay_experiment(experiment: Path) -> list[dict[str, Any]]:
    inputs = load_report_inputs(experiment)
    results: list[dict[str, Any]] = []
    with _replay_environment():
        for run in sorted(inputs.valid_runs, key=lambda value: value.plan_index):
            replay = replay_run(experiment / run.relative_path, verify=True)
            results.append(
                {
                    "run_id": run.manifest.run_id,
                    "task_id": run.manifest.task_id,
                    "reverified_resolved": replay.reverified_resolved,
                    "codex_calls": 0,
                    "broker_calls": 0,
                    "credential_accesses": 0,
                    "proxy_uses": 0,
                    "public_launcher_calls": 0,
                    "verifier_only_reexecution": True,
                }
            )
    return results


def _run_outcomes(experiment: Path) -> list[dict[str, Any]]:
    inputs = load_report_inputs(experiment)
    outcomes: list[dict[str, Any]] = []
    for run in sorted(inputs.valid_runs, key=lambda value: value.plan_index):
        if run.plan_item is None:
            raise RuntimeError("run lacks a frozen plan item")
        prompt = run.manifest.prompt_policy
        frozen_prompt = run.plan_item.prompt_policy
        runtime_process_path = (
            experiment / run.relative_path / "artifacts/codex_cli/runtime_process.json"
        )
        runtime_process = load_model(runtime_process_path, ExternalProcessResult)
        runtime_prompt_hash = runtime_process.runtime_identity.prompt_policy_hash
        prompt_binding_verified = (
            prompt is not None
            and frozen_prompt is not None
            and prompt == frozen_prompt
            and run.manifest.prompt_policy_hash == run.plan_item.prompt_policy_hash
            and run.manifest.prompt_policy_hash == runtime_prompt_hash
            and run.manifest.agent_configuration_hash
            == run.plan_item.system.agent_configuration_hash
        )
        if not prompt_binding_verified:
            raise RuntimeError(
                f"run {run.manifest.run_id} lacks exact plan/child/harness prompt binding"
            )
        assert prompt is not None
        score = run.scorecard
        outcomes.append(
            {
                "plan_index": run.plan_index,
                "run_id": run.manifest.run_id,
                "task_id": run.manifest.task_id,
                "system_id": run.plan_item.system.system_id,
                "agent_version_id": run.plan_item.system.agent_options.get("agent_version_id"),
                "plan_prompt_policy_hash": run.plan_item.prompt_policy_hash,
                "child_prompt_policy_hash": run.manifest.prompt_policy_hash,
                "harness_runtime_prompt_policy_hash": runtime_prompt_hash,
                "task_context_hash": prompt.task_context_hash,
                "agent_version_hash": prompt.agent_version_hash,
                "memory_pack_hash": prompt.memory_pack_hash,
                "plan_agent_configuration_hash": (run.plan_item.system.agent_configuration_hash),
                "child_agent_configuration_hash": run.manifest.agent_configuration_hash,
                "prompt_binding_verified": prompt_binding_verified,
                "sample_index": run.manifest.sample_index,
                "outcome_kind": classify_outcome(score),
                "resolved": score.resolved,
                "evaluable": classify_sample_outcome(score)[1],
                "public_test_reached": bool(run.manifest.repository_public_tests),
                "hidden_verifier_reached": any(
                    "hidden" in result.node_id and result.status.value != "skipped"
                    for result in score.verifier_results
                ),
                "candidate_compile_passed": any(
                    "compile" in result.node_id and result.status.value == "passed"
                    for result in score.verifier_results
                ),
                "patch_reproducible": (
                    run.manifest.repository_candidate is not None
                    and run.manifest.repository_candidate.patch.reapply_exact
                ),
                "changed_files": len(score.patch.changed_files),
                "patch_lines": score.patch.added_lines + score.patch.deleted_lines,
                "public_tool_calls": run.manifest.repository_public_tool_invocation_count,
                "wall_time_s": score.efficiency.wall_time_s,
                "input_tokens": score.efficiency.external_input_tokens,
                "output_tokens": score.efficiency.external_output_tokens,
                "total_tokens": score.efficiency.external_total_tokens,
            }
        )
    return outcomes


def _execute_memory_builder(
    *,
    output: Path,
    summary: Any,
    ledger: Path,
    capability: Mapping[str, Any],
    training_dataset_hash: str,
    training_run_ids: Sequence[str],
    training_source_identities: Mapping[str, str],
    reward_profile_hash: str,
    authorization_id: str = AUTHORIZATION_ID,
    process_kind: str = "memory_synthesis",
    build_id: str = "m10b-memory-synthesis",
    require_success: bool = True,
) -> Any:
    frozen_summary_path = output / "frozen-training-summary.json"
    atomic_dump_json(frozen_summary_path, summary)
    frozen_summary = load_model(
        frozen_summary_path,
        SanitizedTrainingSummary,
    )
    empty_source = output / "empty-memory-workspace"
    empty_source.mkdir()
    runtime_config = _docker_config(_memory_agent_config())
    runtime = DockerRuntime(runtime_config)
    runtime.prepare("m10b-memory-synthesis")
    session = runtime.create_session(
        SessionSpec(
            source_dir=str(empty_source),
            label="agent",
            max_output_bytes=131_072,
        )
    )
    trace = TraceWriter(output / "memory-builder-trace.jsonl", "m10b-memory-synthesis")
    bridge = RuntimeExternalAgentBridge(
        session=session,
        artifact_root=output / "bridge-artifacts",
        isolation_level="docker_standard",
        policy=WorkspacePolicy(editable_globs=(), readonly_globs=()),
        trace=trace,
    )
    try:
        executable, observed_capabilities = runtime_capabilities()
        if observed_capabilities.capability_fingerprint != capability["capability_fingerprint"]:
            raise RuntimeError("memory builder observed a different Codex capability identity")
        settings = readonly_agent_settings(
            {
                "model_id": MODEL_ID,
                "sandbox": "read-only",
                "approval_policy": "non-interactive",
                "reasoning_effort": REASONING_EFFORT,
                "allow_proxy_environment": True,
                "max_process_time_s": 300,
                "max_output_bytes": 131_072,
                "expected_cli_version": CODEX_VERSION,
                "expected_cli_executable_sha256": CODEX_WRAPPER_SHA256,
                "expected_capability_fingerprint": capability["capability_fingerprint"],
                "expected_requested_auth_mode": "chatgpt_cli_session",
                "expected_resolved_auth_mode": "inherited_codex_login",
                "expected_auth_semantic_id": AUTH_SEMANTIC_ID,
                "expected_execution_backend": "docker_outer_runtime_delegated",
                "prompt_contract_id": "codex_cli_readonly_verilog_task_context_v1",
            },
            observed_capabilities,
            task_wall_time_s=300,
        )
        settings = settings_for_execution_backend(settings, bridge.execution_backend)
        identity = runtime.environment_summary()["docker_role_images"]
        if not isinstance(identity, dict):
            raise RuntimeError("memory runtime omitted its role-image identity map")
        verifier = identity["verifier"]
        agent = identity["external_agent"]
        if not isinstance(verifier, dict) or not isinstance(agent, dict):
            raise RuntimeError("memory runtime omitted its immutable role-image identities")
        output_schema_hash = content_hash(MemoryPack.model_json_schema(mode="serialization"))
        invocation_spec = resolve_runtime_process_invocation_spec(
            bridge=bridge,
            executable=executable,
            capabilities=observed_capabilities,
            settings=settings,
            workspace_mode="fresh_empty",
            prompt_contract_id=MEMORY_BUILDER_PROMPT_CONTRACT_ID,
            expected_output_schema_hash=output_schema_hash,
        )
        identity_preview = preview_external_process_identity(invocation_spec)
        agent_runtime_config = runtime_config.external_agent
        if agent_runtime_config is None:
            raise RuntimeError("memory runtime omitted its external-agent configuration")
        configuration_fingerprint = external_process_configuration_fingerprint(
            agent_config=agent_runtime_config,
            agent_image_id=str(agent["resolved_image_id"]),
            verifier_image_id=str(verifier["resolved_image_id"]),
            request=invocation_spec,
            synthesized_environment_names=["NO_PROXY", "no_proxy"],
            mandatory_loopback_bypass_present=True,
        )
        runtime_hash, image_hash = memory_runtime_binding_hashes(
            verifier_image_id=str(verifier["resolved_image_id"]),
            agent_image_id=str(agent["resolved_image_id"]),
            configuration_fingerprint=configuration_fingerprint,
        )
        model_hash, codex_hash = memory_builder_identity_hashes(
            observed_capabilities,
            model_id=MODEL_ID,
            reasoning_effort=REASONING_EFFORT,
        )
        request = build_memory_builder_input(
            training_summary=frozen_summary,
            model_identity_hash=model_hash,
            codex_identity_hash=codex_hash,
            auth_semantic_id=AUTH_SEMANTIC_ID,
            runtime_identity_hash=runtime_hash,
            image_identity_hash=image_hash,
            requested_model_id=MODEL_ID,
            reasoning_effort=REASONING_EFFORT,
            output_schema_hash=output_schema_hash,
            build_id=build_id,
            timeout_s=300,
            max_output_bytes=131_072,
        )
        rendered_prompt = render_memory_builder_prompt(request)
        payload_binding = bind_external_process_payload(
            invocation_spec,
            rendered_prompt,
            template_hash=MEMORY_BUILDER_PROMPT_TEMPLATE_HASH,
            input_dataset_hash=training_dataset_hash,
        )
        synthesis_plan = build_memory_synthesis_plan(
            request=request,
            invocation_spec=invocation_spec,
            identity_preview=identity_preview,
            payload_binding=payload_binding,
            training_dataset_hash=training_dataset_hash,
            training_run_ids=list(training_run_ids),
            training_source_identities=training_source_identities,
            reward_profile_hash=reward_profile_hash,
            reward_vector_schema_hash=content_hash(
                RewardVector.model_json_schema(mode="serialization")
            ),
        )
        atomic_dump_json(output / "memory-builder-input.json", request)
        atomic_dump_json(output / "external-process-invocation-spec.json", invocation_spec)
        atomic_dump_json(output / "external-process-identity-preview.json", identity_preview)
        atomic_dump_json(output / "external-process-payload-binding.json", payload_binding)
        atomic_dump_json(output / "memory-synthesis-plan.json", synthesis_plan)
        reloaded_summary = load_model(frozen_summary_path, SanitizedTrainingSummary)
        reloaded_request = load_model(
            output / "memory-builder-input.json",
            MemoryBuilderInput,
        )
        reloaded_plan = load_model(
            output / "memory-synthesis-plan.json",
            MemorySynthesisPlan,
        )
        reconstruct_memory_synthesis_launch(
            plan=reloaded_plan,
            request=reloaded_request,
            frozen_summary=reloaded_summary,
            executable_path=executable.path,
        )
        authorization = authorize_process(
            ledger,
            process_kind=process_kind,
            authorization_id=authorization_id,
            run_or_build_id=request.build_id,
            requested_model_id=MODEL_ID,
            reasoning_effort=REASONING_EFFORT,
            task_identity_hash=frozen_summary.summary_hash,
            invocation_spec_hash=invocation_spec.invocation_spec_hash,
            payload_binding_hash=payload_binding.payload_binding_hash,
            memory_synthesis_plan_hash=synthesis_plan.plan_hash,
        )
        try:
            outcome = execute_memory_synthesis(
                bridge=bridge,
                request=request,
                agent_options={
                    "model_id": MODEL_ID,
                    "sandbox": "read-only",
                    "approval_policy": "non-interactive",
                    "reasoning_effort": REASONING_EFFORT,
                    "allow_proxy_environment": True,
                    "max_process_time_s": 300,
                    "max_output_bytes": 131_072,
                    "expected_cli_version": CODEX_VERSION,
                    "expected_cli_executable_sha256": CODEX_WRAPPER_SHA256,
                    "expected_capability_fingerprint": capability["capability_fingerprint"],
                    "expected_requested_auth_mode": "chatgpt_cli_session",
                    "expected_resolved_auth_mode": "inherited_codex_login",
                    "expected_auth_semantic_id": AUTH_SEMANTIC_ID,
                    "expected_execution_backend": "docker_outer_runtime_delegated",
                    "prompt_contract_id": ("codex_cli_readonly_verilog_task_context_v1"),
                },
                process_ledger_record_hash=authorization.record_hash,
                artifact_root=output / "process-evidence",
                synthesis_plan=synthesis_plan,
            )
        except BaseException as exc:
            finish_process(
                ledger,
                authorization_record=authorization,
                terminal_outcome=f"exception:{type(exc).__name__}",
            )
            raise
        terminal = finish_process(
            ledger,
            authorization_record=authorization,
            terminal_outcome=f"memory_builder:{outcome.result.status}",
        )
        if require_success and (
            outcome.result.status != "success" or outcome.result.memory_pack is None
        ):
            raise RuntimeError(
                f"memory synthesis did not produce an accepted pack: {outcome.result.status}"
            )
        if outcome.result.memory_pack is not None:
            validate_memory_pack(outcome.result.memory_pack)
        return request, outcome.result, terminal, synthesis_plan
    finally:
        session.close()
        runtime.close()


def _scan_exported_content(
    roots: Sequence[Path],
    *,
    proxy_values: Sequence[str],
    forbidden_host_root: str,
) -> dict[str, Any]:
    report = require_security_scan_pass(
        scan_artifact_roots(
            roots,
            report_id="m10b-exported-content-security-scan",
            proxy_values=proxy_values,
            forbidden_host_roots=(forbidden_host_root,),
        )
    )
    return {
        **report.model_dump(mode="json"),
        "credentials_or_tokens_found": False,
        "proxy_values_found": False,
        "raw_source_host_paths_found": False,
    }


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"evidence destination already exists: {destination}")
    shutil.copytree(source, destination, symlinks=False)


def _write_bundle_checksums(root: Path) -> int:
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("evidence bundle contains a symlink")
        if path.is_file() and path.name != "SHA256SUMS":
            lines.append(f"{_sha256(path)}  {path.relative_to(root).as_posix()}")
    atomic_write_text(root / "SHA256SUMS", "\n".join(lines) + "\n")
    return len(lines)


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        os.chmod(path, mode & ~0o222)
    mode = stat.S_IMODE(os.lstat(root).st_mode)
    os.chmod(root, mode & ~0o222)


def _seal_bundle(
    *,
    campaign_root: Path,
    source_identity: Mapping[str, Any],
    package_and_images: Mapping[str, Any],
    preservation: Mapping[str, Any],
    training_experiment: Path,
    training_dataset: Path,
    training_reports: Path,
    training_summary: Any,
    memory_root: Path,
    heldout_experiment: Path,
    heldout_dataset: Path,
    heldout_reports: Path,
    forensic_evidence: Path,
    historical_binding_evidence: Path,
    resolver_test_evidence: Path,
    probe_experiment: Path,
    probe_dataset: Path,
    probe_replay: Sequence[Mapping[str, Any]],
    training_replay: Sequence[Mapping[str, Any]],
    heldout_replay: Sequence[Mapping[str, Any]],
    split: TaskSplitManifest,
    contamination: Any,
    v0: AgentVersionManifest,
    v1: AgentVersionManifest,
    update: Any,
    lineage: Any,
    lineage_reports: Path,
    version_set: Any,
    assignment_manifest: Any,
    process_manifest: Any,
    probe_outcomes: Sequence[Mapping[str, Any]],
    training_outcomes: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    evaluation: Any,
    repository_root: Path,
    proxy_values: Sequence[str],
) -> Path:
    bundle = campaign_root / "evidence-bundle-final"
    bundle.mkdir()
    for relative in (
        "root-cause",
        "implementation",
        "probes",
        "source-identities",
        "package-and-image-identities",
        "task-splits",
        "training",
        "evolution",
        "heldout-evaluation",
        "replay",
        "security-and-integrity",
        "reports",
    ):
        (bundle / relative).mkdir()
    atomic_dump_json(bundle / "source-identities/source-identity.json", dict(source_identity))
    atomic_dump_json(
        bundle / "source-identities/preservation.json",
        dict(preservation),
    )
    atomic_dump_json(
        bundle / "package-and-image-identities/identities.json",
        dict(package_and_images),
    )
    shutil.copy2(
        campaign_root / "preflight/quality-and-ci.json",
        bundle / "implementation/CI-and-package-identities.json",
    )
    shutil.copy2(forensic_evidence, bundle / "root-cause/prompt-binding-forensic.json")
    shutil.copy2(
        historical_binding_evidence,
        bundle / "root-cause/historical-probe2-binding-check.json",
    )
    shutil.copy2(
        resolver_test_evidence,
        bundle / "implementation/resolver-test-matrix.json",
    )
    shutil.copy2(
        campaign_root / "preflight/codex-capabilities.json",
        bundle / "package-and-image-identities/codex-capabilities.json",
    )
    _copy_tree(repository_root / "docs/schemas", bundle / "schemas")
    shutil.copy2(
        repository_root / "docs/schemas/prompt-policy-descriptor.schema.json",
        bundle / "implementation/prompt-policy-schema.json",
    )
    atomic_dump_json(bundle / "task-splits/task-split-manifest.json", split)
    atomic_dump_json(bundle / "task-splits/contamination-scan.json", contamination)
    _copy_tree(training_experiment, bundle / "training/experiment")
    _copy_tree(training_dataset, bundle / "training/trajectory-dataset")
    _copy_tree(training_reports, bundle / "training/reward-analysis")
    atomic_dump_json(
        bundle / "evolution/sanitized-training-summary.json",
        training_summary,
    )
    _copy_tree(probe_experiment, bundle / "probes/probe-1/experiment")
    _copy_tree(
        probe_dataset,
        bundle / "probes/probe-1/trajectory-dataset",
    )
    atomic_dump_json(
        bundle / "probes/probe-1/per-run-outcomes.json",
        {"schema_version": "1.0", "runs": list(probe_outcomes)},
    )
    _copy_tree(memory_root, bundle / "evolution/memory-builder")
    atomic_dump_json(bundle / "evolution/agent-version-v0.json", v0)
    atomic_dump_json(bundle / "evolution/agent-version-v1.json", v1)
    atomic_dump_json(bundle / "evolution/update-manifest.json", update)
    atomic_dump_json(bundle / "evolution/agent-lineage.json", lineage)
    atomic_dump_json(bundle / "evolution/agent-version-set.json", version_set)
    _copy_tree(heldout_experiment, bundle / "heldout-evaluation/experiment")
    _copy_tree(heldout_dataset, bundle / "heldout-evaluation/trajectory-dataset")
    _copy_tree(heldout_reports, bundle / "heldout-evaluation/reports")
    atomic_dump_json(
        bundle / "heldout-evaluation/run-version-assignments.json",
        assignment_manifest,
    )
    atomic_dump_json(
        bundle / "heldout-evaluation/per-run-outcomes.json",
        {"schema_version": "1.0", "runs": list(outcomes)},
    )
    atomic_dump_json(
        bundle / "training/per-run-outcomes.json",
        {"schema_version": "1.0", "runs": list(training_outcomes)},
    )
    atomic_dump_json(
        bundle / "replay/replay-summary.json",
        {
            "schema_version": "1.0",
            "probe": list(probe_replay),
            "training": list(training_replay),
            "heldout": list(heldout_replay),
            "trajectory_replays": 3,
            "update_replays": 1,
            "model_calls": 0,
            "broker_calls": 0,
            "credential_accesses": 0,
            "proxy_uses": 0,
            "public_launcher_calls": 0,
        },
    )
    atomic_dump_json(
        bundle / "security-and-integrity/process-ledger-manifest.json",
        process_manifest,
    )
    atomic_dump_json(
        bundle / "security-and-integrity/global-process-accounting.json",
        {
            "schema_version": "1.0",
            "authorization_id": AUTHORIZATION_ID,
            "historical_failed_campaign_processes": 2,
            "historical_processes_counted_against_new_authorization": False,
            "new_campaign_started_processes": process_manifest.started_processes,
            "maximum_new_authorized_processes": 24,
            "new_campaign_ledger_manifest_hash": process_manifest.manifest_hash,
            "retry_or_resume": False,
        },
    )
    shutil.copy2(
        campaign_root / "model-process-ledger.jsonl",
        bundle / "security-and-integrity/model-process-ledger.jsonl",
    )
    atomic_dump_json(bundle / "reports/evolving-evaluation.json", evaluation)
    shutil.copy2(
        heldout_reports / "evolving-evaluation.md",
        bundle / "reports/evolving-evaluation.md",
    )
    atomic_dump_json(bundle / "reports/agent-lineage.json", lineage)
    _copy_tree(lineage_reports, bundle / "reports/lineage")
    atomic_dump_json(bundle / "reports/split-integrity.json", contamination)
    atomic_dump_json(
        bundle / "reports/final-gate.json",
        {
            "schema_version": "1.0",
            "gate": "PASS",
            "label": "MILESTONE 10B PROMPT-BINDING REPAIR AND COMPLETION: PASS",
            "no_weight_update": True,
            "general_performance_improvement_established": False,
            "required_interpretation": (
                "The before/after result is a bounded first-party Evolve-Context pilot "
                "and does not establish general performance improvement."
            ),
        },
    )
    security_scan = _scan_exported_content(
        [bundle],
        proxy_values=proxy_values,
        forbidden_host_root=str(repository_root),
    )
    atomic_dump_json(
        bundle / "security-and-integrity/security-scan.json",
        security_scan,
    )
    preseal = {
        path.relative_to(bundle).as_posix(): _sha256(path)
        for path in sorted(bundle.rglob("*"))
        if path.is_file()
    }
    audit = {
        "schema_version": "1.0",
        "milestone": "10B",
        "gate": "PASS",
        "source_commit": source_identity["source_commit"],
        "source_tree": source_identity["source_tree"],
        "trajectory_schema": "observable_repo_trajectory_v1",
        "reward_schema": "repo_rtl_reward_vector_v1",
        "memory_policy": "task_independent_code_free_memory_v1",
        "training_processes": 3,
        "memory_synthesis_processes": 1,
        "heldout_processes": 18,
        "probe_processes": 1,
        "optional_probe_processes": 0,
        "successful_probe_processes": 1,
        "new_campaign_processes": process_manifest.started_processes,
        "historical_processes": 2,
        "maximum_new_authorized_processes": 24,
        "model_weights_modified": False,
        "historical_evidence_combined": False,
        "preseal_file_set_hash": content_hash(preseal),
    }
    atomic_dump_json(bundle / "audit_manifest.json", audit)
    checksum_count = _write_bundle_checksums(bundle)
    _assert_checksum_manifest(bundle)
    atomic_dump_json(
        campaign_root / "bundle-seal.json",
        {
            "schema_version": "1.0",
            "bundle_name": bundle.name,
            "sha256sums_sha256": _sha256(bundle / "SHA256SUMS"),
            "audit_manifest_sha256": _sha256(bundle / "audit_manifest.json"),
            "checksum_entry_count": checksum_count,
        },
    )
    _make_read_only(bundle)
    _assert_checksum_manifest(bundle)
    return bundle


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--core-wheel", type=Path, required=True)
    parser.add_argument("--plugin-wheel", type=Path, required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--quality-evidence", type=Path, required=True)
    parser.add_argument("--forensic-evidence", type=Path, required=True)
    parser.add_argument("--historical-binding-evidence", type=Path, required=True)
    parser.add_argument("--resolver-test-evidence", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_arguments()
    repository_root = Path.cwd().resolve(strict=True)
    output = args.output_root.resolve()
    if output.exists():
        raise RuntimeError("campaign output root must not already exist")
    if any(name in os.environ for name in API_KEY_NAMES):
        raise RuntimeError("API-key environment is forbidden for the M10B campaign")
    if _sha256(args.codex_binary.resolve(strict=True)) != CODEX_WRAPPER_SHA256:
        raise RuntimeError("Codex host wrapper differs from exact 0.144.6")
    if not args.quality_evidence.resolve(strict=True).is_file():
        raise RuntimeError("fully green quality/CI evidence is required before the probe")
    _assert_source_identity(args.source_commit, args.source_tree)
    preservation_before = _preservation_identity()
    forensic_evidence = args.forensic_evidence.resolve(strict=True)
    historical_binding_evidence = args.historical_binding_evidence.resolve(strict=True)
    resolver_test_evidence = args.resolver_test_evidence.resolve(strict=True)
    if (
        not forensic_evidence.is_file()
        or not historical_binding_evidence.is_file()
        or not resolver_test_evidence.is_file()
    ):
        raise RuntimeError("zero-model forensic evidence is required before the probe")
    output.mkdir(parents=True)
    (output / "preflight").mkdir()
    shutil.copy2(args.quality_evidence, output / "preflight/quality-and-ci.json")
    package_hashes = {
        "verigym": _sha256(args.core_wheel.resolve(strict=True)),
        "verigym-codex-cli": _sha256(args.plugin_wheel.resolve(strict=True)),
    }
    os.environ["VERIGYM_CODEX_BINARY"] = str(args.codex_binary.resolve(strict=True))
    os.environ["VERIGYM_CODEX_AUTH_MODE"] = "chatgpt_cli_session"
    identity, capabilities = discover_capabilities(force=True)
    capability = capabilities.safe_dict()
    if (
        capabilities.version_output != CODEX_VERSION
        or capabilities.executable_sha256 != CODEX_WRAPPER_SHA256
    ):
        raise RuntimeError("Codex CLI identity differs from the frozen requirement")
    auth, credential_env = auth_identity_configuration()
    if (
        auth.requested_auth_mode != "chatgpt_cli_session"
        or auth.resolved_auth_mode != "inherited_codex_login"
        or auth.auth_semantic_id != AUTH_SEMANTIC_ID
        or credential_env is not None
    ):
        raise RuntimeError("authentication identity differs from inherited ChatGPT CLI login")
    atomic_json(output / "preflight/codex-capabilities.json", capability)
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(output / "preflight/codex-capabilities.json")
    source_identity = {
        "schema_version": "1.0",
        "starting_commit": START_COMMIT,
        "starting_branch": START_BRANCH,
        "campaign_branch": "milestone10b-evolving-agent-evaluation",
        "source_commit": args.source_commit,
        "source_tree": args.source_tree,
        "worktree_clean_before_model_processes": True,
    }
    package_and_images = {
        "schema_version": "1.0",
        "package_hashes": package_hashes,
        "verifier_image_id": VERIFIER_IMAGE_ID,
        "repository_agent_image_id": REPOSITORY_AGENT_IMAGE_ID,
        "memory_agent_image_id": MEMORY_AGENT_IMAGE_ID,
        "codex_host_identity": identity.safe_dict(),
        "codex_capability_fingerprint": capabilities.capability_fingerprint,
        "requested_auth_mode": auth.requested_auth_mode,
        "resolved_auth_mode": auth.resolved_auth_mode,
        "auth_semantic_id": auth.auth_semantic_id,
        "credential_contents_accessed": False,
        "proxy_values_persisted_or_hashed": False,
    }
    atomic_dump_json(output / "preflight/source-identity.json", source_identity)
    atomic_dump_json(output / "preflight/package-and-image-identities.json", package_and_images)
    atomic_dump_json(output / "preflight/preservation-before.json", preservation_before)
    ledger = output / "model-process-ledger.jsonl"
    ledger.touch(mode=0o600)

    training_roots = _training_roots(repository_root)
    training_split = build_task_split(
        split_id="m10b-training-v0",
        training=[_task_entry(training_roots[task]) for task in TRAINING_TASKS],
        heldout=[],
    )
    preview_config = _experiment_config(
        name="m10b v0 identity preview",
        output=output / "unused-identity-preview",
        tasks=[TRAINING_TASKS[0]],
        systems=[("v0-preview", _common_agent_options(capability))],
        samples=1,
        process_count=1,
        campaign_kind="m10b_zero_call_identity_preview",
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        package_hashes=package_hashes,
        capability_fingerprint=capabilities.capability_fingerprint,
    )
    preview_plan = ExperimentPlanner().build(preview_config)
    if preview_plan.verigym_commit != args.source_commit:
        raise RuntimeError("installed core package provenance differs from the source commit")
    preview = preview_plan.items[0]
    if preview.prompt_policy_hash is None or preview.prompt_policy is None:
        raise RuntimeError("repository-agent plan omitted its prompt-policy hash")
    v0 = build_agent_version(
        agent_version_id="codex-cli-agent-v0",
        status="frozen",
        parent_version_hash=None,
        update_type="none",
        executable_in_m10b=True,
        base_agent_id="codex-cli-agent",
        agent_descriptor_hash=content_hash(preview.system.agent_descriptor),
        model_id=MODEL_ID,
        reasoning_effort=REASONING_EFFORT,
        auth_semantic_id=AUTH_SEMANTIC_ID,
        runtime_identity_hash=preview.runtime_identity_hash,
        tool_policy_hash=preview.tool_policy_hash,
        prompt_contract_hash=prompt_contract_identity_hash(preview.prompt_policy),
        source_commit=args.source_commit,
        package_hashes=package_hashes,
        image_hashes={
            "agent": _image_hash(REPOSITORY_AGENT_IMAGE_ID),
            "verifier": _image_hash(VERIFIER_IMAGE_ID),
        },
        model_weights_modified=False,
    )
    validate_plan_agent_version_binding(
        version=v0,
        item=preview,
        source_commit=args.source_commit,
        package_hashes=package_hashes,
    )
    atomic_dump_json(output / "preflight/agent-version-v0.json", v0)

    probe_config = _experiment_config(
        name="m10b prompt binding conformance probe one",
        output=output / "real-probe-1",
        tasks=[TRAINING_TASKS[1]],
        systems=[("v0", _versioned_options(capability, v0))],
        samples=1,
        process_count=1,
        campaign_kind="m10b_implementation_probe",
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        package_hashes=package_hashes,
        capability_fingerprint=capabilities.capability_fingerprint,
    )
    _probe_plan, probe_experiment = _run_experiment(
        probe_config,
        ledger=ledger,
        process_kind="implementation_probe",
    )
    probe_dataset = output / "probe-1-trajectory-dataset"
    probe_manifest = TrajectoryExporter().export(
        probe_experiment,
        probe_dataset,
        split_manifest=build_task_split(
            split_id="m10b-prompt-binding-probe-1-v0",
            training=[_task_entry(training_roots[TRAINING_TASKS[1]])],
            heldout=[],
        ),
        agent_versions={v0.agent_version_id: v0},
        run_agent_versions=_run_assignments(probe_experiment, {"v0": v0.agent_version_id}),
        source_commit=args.source_commit,
        package_identities=package_hashes,
        dataset_id="m10b-prompt-binding-probe-1",
    )
    replay_trajectory_dataset(probe_dataset, probe_experiment)
    probe_replay = _replay_experiment(probe_experiment)
    probe_outcomes = _run_outcomes(probe_experiment)
    if probe_manifest.eligible_record_count != 1:
        raise RuntimeError("implementation probe did not produce one eligible trajectory")

    training_config = _experiment_config(
        name="m10b final v0 training episodes",
        output=output / "training-experiment",
        tasks=TRAINING_TASKS,
        systems=[("v0", _versioned_options(capability, v0))],
        samples=1,
        process_count=3,
        campaign_kind="m10b_final_training",
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        package_hashes=package_hashes,
        capability_fingerprint=capabilities.capability_fingerprint,
    )
    _training_plan, training_experiment = _run_experiment(
        training_config,
        ledger=ledger,
        process_kind="training_episode",
    )
    training_dataset = output / "training-trajectory-dataset"
    training_manifest = TrajectoryExporter().export(
        training_experiment,
        training_dataset,
        split_manifest=training_split,
        agent_versions={v0.agent_version_id: v0},
        run_agent_versions=_run_assignments(training_experiment, {"v0": v0.agent_version_id}),
        source_commit=args.source_commit,
        package_identities=package_hashes,
        dataset_id="m10b-v0-training-trajectories",
    )
    replay_trajectory_dataset(training_dataset, training_experiment)
    trajectories = load_jsonl_models(
        training_dataset / "trajectories.jsonl",
        EpisodeTrajectory,
    )
    summary = prepare_training_summary(
        trajectories,
        split_manifest_hash=training_split.manifest_hash,
        trajectory_dataset_hash=training_manifest.dataset_hash,
    )
    training_reports = output / "training-reports"
    EvolutionReportService().generate_dataset(training_dataset, training_reports)
    atomic_dump_json(output / "sanitized-training-summary.json", summary)
    training_replay = _replay_experiment(training_experiment)
    training_outcomes = _run_outcomes(training_experiment)

    memory_root = output / "memory-synthesis"
    memory_root.mkdir()
    if training_manifest.reward_profile_hash is None:
        raise RuntimeError("training trajectory dataset omitted its reward profile identity")
    request, memory_result, memory_terminal, synthesis_plan = _execute_memory_builder(
        output=memory_root,
        summary=summary,
        ledger=ledger,
        capability=capability,
        training_dataset_hash=training_manifest.dataset_hash,
        training_run_ids=[trajectory.run_id for trajectory in trajectories],
        training_source_identities={
            trajectory.run_id: content_hash(
                {
                    "run_manifest_hash": trajectory.run_manifest_hash,
                    "artifact_manifest_hash": trajectory.artifact_manifest_hash,
                    "source_hash": trajectory.source_hash,
                }
            )
            for trajectory in trajectories
        },
        reward_profile_hash=training_manifest.reward_profile_hash,
    )
    memory = memory_result.memory_pack
    assert memory is not None
    v1, update = freeze_context_update(
        parent=v0,
        dataset=training_manifest,
        training_summary=summary,
        memory_pack=memory,
        memory_builder_identity_hash=memory_result.process_identity_hash,
        memory_builder_input_hash=request.input_hash,
        memory_builder_output_hash=memory_result.output_hash,
        process_ledger_hash=memory_terminal.record_hash,
        memory_synthesis_plan_hash=synthesis_plan.plan_hash,
        invocation_spec_hash=synthesis_plan.invocation_spec.invocation_spec_hash,
        payload_binding_hash=synthesis_plan.payload_binding.payload_binding_hash,
    )
    if memory_result.memory_synthesis_plan_hash != synthesis_plan.plan_hash:
        raise RuntimeError("memory-builder result omitted its frozen synthesis-plan identity")
    replay_context_update(
        parent=v0,
        result=v1,
        update=update,
        dataset=training_manifest,
        training_summary=summary,
        memory_pack=memory,
    )
    atomic_dump_json(output / "agent-version-v1.json", v1)
    os.environ["VERIGYM_M10B_HELDOUT_AGENT_VERSION_MANIFEST"] = str(
        output / "agent-version-v1.json"
    )

    heldout_roots = _heldout_roots(repository_root)
    full_split = build_task_split(
        split_id="m10b-first-party-train-heldout-v1",
        training=[_task_entry(training_roots[task]) for task in TRAINING_TASKS],
        heldout=[_task_entry(heldout_roots[task]) for task in HELDOUT_TASKS],
        heldout_assets_loaded_after_version_hash=v1.version_hash,
    )
    contamination = scan_contamination(
        split_manifest=full_split,
        training_roots=training_roots,
        heldout_roots=heldout_roots,
        memory_pack=memory,
    )
    validate_contamination_scan(contamination)
    if not contamination.passed:
        raise RuntimeError("train/held-out contamination scan failed")
    lineage = build_agent_lineage(parent=v0, result=v1, update=update)
    version_set = build_agent_version_set([v0, v1])
    lineage_reports = output / "lineage-reports"
    EvolutionReportService().generate_lineage(
        lineage=lineage,
        memory=memory,
        output=lineage_reports,
    )

    heldout_config = _experiment_config(
        name="m10b final heldout v0 v1 evaluation",
        output=output / "heldout-experiment",
        tasks=HELDOUT_TASKS,
        systems=[
            ("v0", _versioned_options(capability, v0)),
            ("v1", _versioned_options(capability, v1, memory)),
        ],
        samples=3,
        process_count=18,
        campaign_kind="m10b_final_heldout_counterbalanced",
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        package_hashes=package_hashes,
        capability_fingerprint=capabilities.capability_fingerprint,
        counterbalanced=True,
    )
    heldout_plan = ExperimentPlanner().build(heldout_config)
    _validate_plan_versions(heldout_plan)
    for task in HELDOUT_TASKS:
        by_system = {
            item.system.system_id: item for item in heldout_plan.items if item.task_id == task
        }
        v0_item = by_system["v0"]
        v1_item = by_system["v1"]
        v0_prompt = v0_item.prompt_policy
        v1_prompt = v1_item.prompt_policy
        if (
            v0_prompt is None
            or v1_prompt is None
            or v0_prompt.memory_pack_hash is not None
            or v1_prompt.memory_pack_hash != memory.content_hash
            or v0_prompt.configuration_fingerprint == v1_prompt.configuration_fingerprint
            or v0_item.runtime_identity_hash != v1_item.runtime_identity_hash
            or v0_item.tool_policy_hash != v1_item.tool_policy_hash
            or v0_item.verifier_hash != v1_item.verifier_hash
            or v0_item.system.agent_descriptor != v1_item.system.agent_descriptor
            or v0_item.system.agent_options.get("model_id")
            != v1_item.system.agent_options.get("model_id")
        ):
            raise RuntimeError("held-out v0/v1 prompt partition or shared identity is invalid")
    expected_order = [
        ("v0", 0),
        ("v1", 0),
        ("v1", 1),
        ("v0", 1),
        ("v0", 2),
        ("v1", 2),
    ]
    for task in HELDOUT_TASKS:
        observed = [
            (item.system.system_id, item.sample_index)
            for item in heldout_plan.items
            if item.task_id == task
        ]
        if observed != expected_order:
            raise RuntimeError("held-out plan is not counterbalanced as pre-registered")
    heldout_runner = BatchRunner(
        planner=ExperimentPlanner(),
        child_executor=_CampaignChildExecutor(ledger, "heldout"),
    )
    heldout_result = heldout_runner.run(heldout_plan)
    if heldout_result.exit_code != 0:
        raise RuntimeError("held-out experiment failed its execution gate")
    heldout_experiment = heldout_result.experiment_dir
    heldout_inputs = load_report_inputs(heldout_experiment)
    if len(heldout_inputs.valid_runs) != 18 or any(
        not classify_sample_outcome(run.scorecard)[1] for run in heldout_inputs.valid_runs
    ):
        raise RuntimeError("held-out campaign did not produce 18 terminal evaluable runs")
    assignments = _run_assignments(
        heldout_experiment,
        {"v0": v0.agent_version_id, "v1": v1.agent_version_id},
    )
    assignment_manifest = build_run_version_assignments(
        [
            RunAgentVersionAssignment(
                run_id=run_id,
                agent_version_id=version_id,
                agent_version_hash=(
                    v0.version_hash if version_id == v0.agent_version_id else v1.version_hash
                ),
            )
            for run_id, version_id in assignments.items()
        ]
    )
    atomic_dump_json(output / "heldout-run-version-assignments.json", assignment_manifest)
    heldout_dataset = output / "heldout-trajectory-dataset"
    TrajectoryExporter().export(
        heldout_experiment,
        heldout_dataset,
        split_manifest=full_split,
        agent_versions={v0.agent_version_id: v0, v1.agent_version_id: v1},
        run_agent_versions=assignments,
        source_commit=args.source_commit,
        package_identities=package_hashes,
        dataset_id="m10b-heldout-v0-v1-trajectories",
    )
    replay_trajectory_dataset(heldout_dataset, heldout_experiment)
    evaluation = build_evolving_evaluation(
        heldout_experiment,
        split_manifest=full_split,
        baseline_version_id=v0.agent_version_id,
        evolved_version_id=v1.agent_version_id,
    )
    validate_evolving_evaluation(evaluation)
    heldout_reports = output / "heldout-reports"
    EvolutionReportService().generate_evaluation(evaluation, heldout_reports)
    heldout_replay = _replay_experiment(heldout_experiment)
    outcomes = _run_outcomes(heldout_experiment)

    process_manifest = seal_process_ledger(
        ledger,
        authorization_id=AUTHORIZATION_ID,
        complete=True,
    )
    if (
        process_manifest.authorized_processes != 23
        or process_manifest.started_processes != 23
        or process_manifest.process_kind_counts
        != {
            "heldout": 18,
            "implementation_probe": 1,
            "memory_synthesis": 1,
            "training_episode": 3,
        }
    ):
        raise RuntimeError("campaign-wide process accounting differs from 1+3+1+18")
    preservation_after = _preservation_identity()
    if preservation_after != preservation_before:
        raise RuntimeError("protected historical evidence changed during M10B")
    _assert_source_identity(args.source_commit, args.source_tree)
    proxy_values = [
        value for name in PROXY_NAMES for value in [os.environ.get(name)] if value is not None
    ]
    bundle = _seal_bundle(
        campaign_root=output,
        source_identity=source_identity,
        package_and_images=package_and_images,
        preservation=preservation_after,
        training_experiment=training_experiment,
        training_dataset=training_dataset,
        training_reports=training_reports,
        training_summary=summary,
        memory_root=memory_root,
        heldout_experiment=heldout_experiment,
        heldout_dataset=heldout_dataset,
        heldout_reports=heldout_reports,
        forensic_evidence=forensic_evidence,
        historical_binding_evidence=historical_binding_evidence,
        resolver_test_evidence=resolver_test_evidence,
        probe_experiment=probe_experiment,
        probe_dataset=probe_dataset,
        probe_replay=probe_replay,
        training_replay=training_replay,
        heldout_replay=heldout_replay,
        split=full_split,
        contamination=contamination,
        v0=v0,
        v1=v1,
        update=update,
        lineage=lineage,
        lineage_reports=lineage_reports,
        version_set=version_set,
        assignment_manifest=assignment_manifest,
        process_manifest=process_manifest,
        probe_outcomes=probe_outcomes,
        training_outcomes=training_outcomes,
        outcomes=outcomes,
        evaluation=evaluation,
        repository_root=repository_root,
        proxy_values=proxy_values,
    )
    print(
        canonical_json(
            {
                "gate": "MILESTONE 10B PROMPT-BINDING REPAIR AND COMPLETION: PASS",
                "bundle": bundle.name,
                "bundle_sha256sums_sha256": _sha256(bundle / "SHA256SUMS"),
                "new_campaign_processes": process_manifest.started_processes,
                "historical_processes": 2,
                "v0_version_hash": v0.version_hash,
                "v1_version_hash": v1.version_hash,
                "evaluation_report_hash": evaluation.report_hash,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
