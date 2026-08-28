#!/usr/bin/env python3
"""Qualify and execute the frozen four-process RTL AgentEval Codex smoke."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from prepare_nangate45_ppa_profile import main as prepare_nangate45_profile
from verigym_codex_cli.agenteval_agent import CodexCliAgentEvalAdapter
from verigym_codex_cli.agenteval_config import (
    AGENTEVAL_AGENT_VERSION_HASH,
    AGENTEVAL_AGENT_VERSION_ID,
    AGENTEVAL_PROMPT_HASH,
    AGENTEVAL_TOOL_POLICY_FINGERPRINT,
)
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.preflight import run_auth_preflight
from verigym_codex_cli.process import auth_identity_configuration
from verigym_rtllm import RTLLMSuite
from verigym_synopsys.export_mcp_profile import bind_mcp_client_profile_to_docker
from verigym_synopsys.worker_release import COMMERCIAL_WORKER_RELEASE_PROTOCOL

from verigym.core.agent_feedback import (
    AGENT_FEEDBACK_INFRASTRUCTURE_SUBCATEGORIES,
    resolve_agent_feedback_contract,
    task_with_agent_feedback_contract,
)
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.core.repository_observation import (
    BOUNDED_REPOSITORY_OBSERVATION_POLICY,
    bounded_read_view,
)
from verigym.core.synthesis import (
    execute_candidate_synthesis_feedback,
    execute_synthesis_quality,
)
from verigym.core.synthesis_projection import resolve_synthesis_source_projection
from verigym.core.verifier_profiles import (
    resolve_verifier_profile,
    task_with_verifier_profile,
)
from verigym.core.workspace import copy_tree_safely, normalize_relative_path
from verigym.experiments.state import atomic_dump_json, atomic_write_text
from verigym.profiles.identity import (
    RESOLVED_PROFILE_IDENTITY_COMPONENTS,
    require_resolved_profile_identity,
    resolved_profile_component_hashes,
)
from verigym.profiles.registry import ToolchainProfileRegistry
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.prompts.policy import agent_configuration_hash, resolve_prompt_policy
from verigym.protocols.repository_action import resolve_repository_action_protocol
from verigym.registry.base import PluginOrigin
from verigym.registry.collections import Registries, build_registries
from verigym.schemas.common import InteractionMode, ToolchainProfile
from verigym.schemas.run import RunConfig, RunResult
from verigym.schemas.runtime import (
    DockerExternalAgentRuntimeConfig,
    DockerRuntimeConfig,
    SessionSpec,
)
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier import VerifierStatus
from verigym.tools.base import SynthesisBackendPlugin

_IMAGE = "verigym/open-rtl-tools:iverilog12-yosys067-opensta310"
_CAMPAIGN_ID = "rtl-agenteval-codex-gpt54-xhigh-smoke-v7"
_OUTPUT = Path(f"/data/jzhu484/Agent/experiments/{_CAMPAIGN_ID}")
_SMOKE_V2_PLAN = Path(
    "/data/jzhu484/Agent/experiments/rtl-agenteval-codex-gpt54-xhigh-smoke-v2/plan.json"
)
_EXPECTED_CLI_VERSION = "codex-cli 0.147.0"
_EXPECTED_CODEX_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"
_PUBLIC_TEST_IMAGE = "verigym/codex-repository-agent:0.144.6"
_EXPECTED_PUBLIC_TEST_IMAGE_ID = (
    "sha256:41f8e89b37b2d809e19295642fc666f25ccc699b1f4519e36bc6d05e3bff5691"
)
_PUBLIC_TEST_IMAGE_CODEX_VERSION = "codex-cli 0.144.6"
_PUBLIC_TEST_IMAGE_CODEX_SHA256 = "a31ae9450a26216eb1e7c53102fd42123dd675974310b0e2ca3aa4cb622a2c15"
_EXPECTED_PUBLIC_TEST_LAUNCHER_SHA256 = (
    "e3276ee142e7de78fd60bf4078138152d1974c93f72f27fd2eb95a3f6493b407"
)
_TASKS = (
    "rtllm/counter_12_agent_eval_v1",
    "rtllm/up_down_counter_agent_eval_v1",
    "verilog-eval/v2-spec-to-rtl-agent-eval-v1/Prob001_zero",
    "rtl-repo/official-parquet-v1-agent-eval-v1/test-000000",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMERCIAL_DIAGNOSTIC = re.compile(
    rb"(?i)(license[_ -]?server|lsf|mcp[_ -]?server(?:_[a-z0-9_]+|\b)|\.db\b)"
)


@dataclass(frozen=True)
class PreparedProfile:
    profile: ToolchainProfile
    resolved: Any


class CampaignInfrastructureError(ConfigurationError):
    """A fail-fast campaign error that invalidates subsequent launches."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, default=_OUTPUT)
    parser.add_argument("--smoke-v2-plan", type=Path, default=_SMOKE_V2_PLAN)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument(
        "--broker-root",
        type=Path,
        default=Path("/data/jzhu484/Agent/.verigym-tmp/cb-ae2"),
    )
    parser.add_argument("--rtllm-source", type=Path, required=True)
    parser.add_argument("--verilog-eval-source", type=Path, required=True)
    parser.add_argument("--rtl-repo-source", type=Path, required=True)
    parser.add_argument("--pdk-root", type=Path, required=True)
    parser.add_argument("--dc-counter-profile", type=Path, required=True)
    parser.add_argument("--dc-up-down-profile", type=Path, required=True)
    parser.add_argument("--vcs-counter-profile", type=Path, required=True)
    parser.add_argument("--vcs-up-down-profile", type=Path, required=True)
    parser.add_argument("--image", default=_IMAGE)
    parser.add_argument("--codex-binary", default="codex")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    site_work = _new_path(arguments.site_work, "site-profile work directory")
    inputs = {
        "rtllm": _directory(arguments.rtllm_source),
        "verilog_eval": _directory(arguments.verilog_eval_source),
        "rtl_repo": _directory(arguments.rtl_repo_source),
        "pdk": _directory(arguments.pdk_root),
    }
    profile_paths = {
        "dc_counter": _regular_file(arguments.dc_counter_profile),
        "dc_up_down": _regular_file(arguments.dc_up_down_profile),
        "vcs_counter": _regular_file(arguments.vcs_counter_profile),
        "vcs_up_down": _regular_file(arguments.vcs_up_down_profile),
    }
    smoke_v2_plan = _regular_file(arguments.smoke_v2_plan, "smoke-v2 plan")
    capability_path, capability, auth = _codex_preflight(arguments.codex_binary, site_work)
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(capability_path)
    image_id = _docker_image_id(arguments.image)
    docker_config = _docker_config(arguments.image, image_id)

    registries = _registries()
    service = VeriGym(registries)
    source_configs = _source_configs(inputs)
    _validate_sources(service, source_configs)
    broker_regression = _repository_broker_regression_qualification(service, source_configs)
    prepared = _prepare_profiles(
        registries,
        site_work=site_work,
        image=arguments.image,
        image_id=image_id,
        pdk_root=inputs["pdk"],
        dc_paths=profile_paths,
    )
    runtime_descriptor, qualifications = _no_model_qualification(
        service,
        source_configs=source_configs,
        docker_config=docker_config,
        prepared=prepared,
        vcs_paths=profile_paths,
        scratch=site_work / "qualification",
    )
    qualifications["smoke_v2_identity_audit"] = _smoke_v2_identity_audit(smoke_v2_plan, prepared)
    qualifications["repository_broker_regression"] = broker_regression
    output = _new_path(arguments.output, "experiment output")
    broker_root = _new_path(arguments.broker_root, "Codex broker root")
    os.environ["VERIGYM_CODEX_BROKER_ROOT"] = str(_broker_root(broker_root))
    agent_options = _agent_options(capability, auth)
    run_configs = _frozen_run_configs(
        service,
        source_configs=source_configs,
        docker_config=docker_config,
        runtime_descriptor=runtime_descriptor,
        prepared=prepared,
        agent_options=agent_options,
        output=output / "runs",
    )
    plan = {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "tasks": list(_TASKS),
        "model": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "seed": 0,
        "samples_per_task": 1,
        "planned_codex_processes": 4,
        "automatic_retries": 0,
        "codex": {
            "version": capability.version_output,
            "executable_sha256": capability.executable_sha256,
            "capability_fingerprint": capability.capability_fingerprint,
            "agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
            "agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
            "prompt_hash": AGENTEVAL_PROMPT_HASH,
            "tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
            "auth": auth.safe_dict(),
        },
        "runtime": runtime_descriptor.model_dump(mode="json"),
        "profiles": {
            name: {
                "declared_hash": content_hash(item.profile),
                "resolved_hash": item.resolved.resolved_profile_hash,
                "component_hashes": resolved_profile_component_hashes(item.resolved),
            }
            for name, item in prepared.items()
        },
        "qualifications": qualifications,
        "run_config_hashes": [content_hash(item.identity_payload()) for item in run_configs],
        "pilot_requires_fully_successful_smoke": True,
        "benchmark_score_claimed": False,
    }

    if not arguments.execute:
        atomic_dump_json(site_work / "preflight-plan.json", plan)
        print(json.dumps({"status": "qualified_plan_only", "model_calls": 0}, sort_keys=True))
        return 0
    if os.environ.get("VERIGYM_RUN_RTL_AGENT_EVAL_SMOKE") != "1":
        raise ConfigurationError("execution requires VERIGYM_RUN_RTL_AGENT_EVAL_SMOKE=1")

    output.mkdir(parents=True)
    (output / "runs").mkdir()
    (output / "evidence").mkdir()
    atomic_dump_json(output / "plan.json", plan)
    results = _execute_exactly_four(service, run_configs, output)
    replay = _offline_replay(results)
    scan = _scan_outputs(
        results,
        service,
        source_configs,
        profile_paths,
        inputs,
        site_paths=(site_work, broker_root, output, smoke_v2_plan),
    )
    summary = _campaign_summary(results, replay, scan)
    atomic_dump_json(output / "replay.json", replay)
    atomic_dump_json(output / "security-scan.json", scan)
    atomic_dump_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["fully_successful"] else 2


def _new_path(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists() or resolved.is_symlink():
        raise ConfigurationError(f"{label} must not already exist")
    return resolved


def _directory(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    if resolved.is_symlink() or not resolved.is_dir():
        raise ConfigurationError("required source root is not a real directory")
    return resolved


def _regular_file(path: Path, label: str = "site profile") -> Path:
    if path.is_symlink():
        raise ConfigurationError(f"{label} cannot be a symlink")
    resolved = path.expanduser().resolve(strict=True)
    metadata = os.lstat(resolved)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 1024 * 1024:
        raise ConfigurationError(f"{label} must be a regular file no larger than 1 MiB")
    return resolved


def _docker_image_id(image: str) -> str:
    completed = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    image_id = completed.stdout.strip()
    if completed.returncode != 0 or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise ConfigurationError("the frozen OpenSTA Docker image is unavailable")
    return image_id


def _docker_config(image: str, image_id: str) -> DockerRuntimeConfig:
    launcher = Path(__file__).resolve().parents[1] / "src" / "verigym" / "public_test_launcher.py"
    if hash_bytes(launcher.read_bytes()) != _EXPECTED_PUBLIC_TEST_LAUNCHER_SHA256:
        raise ConfigurationError("the trusted public-test launcher identity changed")
    runtime_user = f"{os.getuid()}:{os.getgid()}"
    return DockerRuntimeConfig(
        image=image,
        expected_image_id=image_id,
        pull_policy="never",
        network_mode="none",
        run_as_user="10001:10001",
        memory_bytes=2 * 1024**3,
        cpus=2.0,
        pids_limit=256,
        tmpfs_bytes=128 * 1024**2,
        max_command_time_s=900,
        external_agent=DockerExternalAgentRuntimeConfig(
            image=_PUBLIC_TEST_IMAGE,
            expected_image_id=_EXPECTED_PUBLIC_TEST_IMAGE_ID,
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version=_PUBLIC_TEST_IMAGE_CODEX_VERSION,
            expected_executable_sha256=_PUBLIC_TEST_IMAGE_CODEX_SHA256,
            process_argv=[
                "/usr/local/bin/codex",
                "exec-server",
                "--listen",
                "stdio://",
            ],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels={
                "org.verigym.runtime.role": "repository-agent",
                "org.verigym.codex.version": "0.144.6",
                "org.verigym.codex.binary.sha256": _PUBLIC_TEST_IMAGE_CODEX_SHA256,
                "org.verigym.external_agent.protocol": ("codex_app_server_remote_environment_v1"),
                "org.verigym.public_test.protocol": "verigym_public_test_v1",
                "org.verigym.public_test_launcher.sha256": (_EXPECTED_PUBLIC_TEST_LAUNCHER_SHA256),
                "org.verigym.iverilog.version": "12.0",
                "org.verigym.provider_credentials": "absent",
                "org.verigym.credential_material": "absent",
            },
            pull_policy="never",
            run_as_user=runtime_user,
            memory_bytes=512 * 1024**2,
            cpus=1.0,
            pids_limit=128,
            tmpfs_bytes=64 * 1024**2,
            max_process_time_s=900,
            max_output_bytes=8 * 1024 * 1024,
        ),
    )


def _codex_preflight(binary: str, site_work: Path) -> tuple[Path, Any, Any]:
    os.environ["VERIGYM_CODEX_BINARY"] = binary
    os.environ.setdefault("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")
    executable, capability = discover_capabilities(force=True)
    if (
        capability.version_output != _EXPECTED_CLI_VERSION
        or capability.executable_sha256 != _EXPECTED_CODEX_SHA256
        or executable.sha256 != _EXPECTED_CODEX_SHA256
    ):
        raise ConfigurationError("Codex CLI differs from the frozen scoring identity")
    auth, _ = auth_identity_configuration()
    auth_preflight = run_auth_preflight(executable)
    if (
        not auth_preflight.external_prerequisite_satisfied
        or auth_preflight.model_calls != 0
        or auth_preflight.login_processes != 0
    ):
        raise ConfigurationError("the selected existing Codex authentication is unavailable")
    site_work.mkdir(parents=True)
    path = site_work / "codex-capabilities.json"
    atomic_dump_json(path, capability.safe_dict())
    atomic_dump_json(site_work / "codex-auth-preflight.json", auth_preflight.safe_dict())
    return path, capability, auth


def _broker_root(root: Path) -> Path:
    root.mkdir(parents=True)
    if len(str(root)) > 72:
        raise ConfigurationError("site work path is too long for the Unix broker socket")
    return root


def _registries() -> Registries:
    registries = build_registries()
    if "codex-cli-agenteval-agent" not in registries.agents.names():
        registries.agents.register(
            CodexCliAgentEvalAdapter(),
            origin=PluginOrigin(
                package="verigym-codex-cli",
                version="0.1.0",
                entry_point=None,
                registration="runtime",
            ),
        )
    required = {
        "rtllm",
        "rtl-repo",
        "verilog-eval",
        "synopsys.dc.mcp",
        "synopsys.vcs.mcp",
        "yosys.synth",
    }
    available = set(registries.suites.names()) | set(registries.tools.names())
    if not required.issubset(available):
        raise ConfigurationError("required RTL AgentEval integrations are unavailable")
    return registries


def _source_configs(inputs: dict[str, Path]) -> dict[str, SuiteSourceConfig]:
    return {
        "counter": SuiteSourceConfig(
            source_root=inputs["rtllm"], variant="counter_12_agent_eval_v1"
        ),
        "up_down": SuiteSourceConfig(
            source_root=inputs["rtllm"], variant="up_down_counter_agent_eval_v1"
        ),
        "verilog_eval": SuiteSourceConfig(
            source_root=inputs["verilog_eval"],
            variant="v2-spec-to-rtl-agent-eval-v1",
        ),
        "rtl_repo": SuiteSourceConfig(
            source_root=inputs["rtl_repo"],
            variant="official-parquet-v1-agent-eval-v1",
        ),
    }


def _validate_sources(service: VeriGym, configs: dict[str, SuiteSourceConfig]) -> None:
    for task_id, config in zip(_TASKS, configs.values(), strict=True):
        suite, task, assets = service.load_task(task_id, config)
        report = suite.validate_source()
        if not report.valid or not Path(assets.visible_root).is_dir() or task.id != task_id:
            raise ConfigurationError(f"source qualification failed for {task_id}")


def _repository_broker_regression_qualification(
    service: VeriGym,
    configs: dict[str, SuiteSourceConfig],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    total_empty_views = 0
    for task_id, config in zip(_TASKS, configs.values(), strict=True):
        _suite, _task, assets = service.load_task(task_id, config)
        root = Path(assets.visible_root)
        empty_files = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.stat().st_size != 0:
                continue
            relative = path.relative_to(root).as_posix()
            for concise in (None, True):
                rendered, metadata = bounded_read_view(
                    "",
                    relative,
                    concise=concise,
                    policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY,
                )
                if (
                    rendered
                    or metadata.get("line_count") != 0
                    or metadata.get("line_range") != [0, 0]
                ):
                    raise ConfigurationError("empty repository read regression failed")
                total_empty_views += 1
            empty_files += 1
        records.append({"task_id": task_id, "empty_files_checked": empty_files})
    if total_empty_views < 2:
        raise ConfigurationError("frozen broker regression did not exercise an empty file")
    return {
        "passed": True,
        "model_calls": 0,
        "empty_file_views_checked": total_empty_views,
        "records": records,
    }


def _prepare_profiles(
    registries: Registries,
    *,
    site_work: Path,
    image: str,
    image_id: str,
    pdk_root: Path,
    dc_paths: dict[str, Path],
) -> dict[str, PreparedProfile]:
    profiles_root = site_work / "profiles"
    profiles_root.mkdir()
    specifications = {
        "counter_open": ("counter_12", "clk", "rtl/counter_12.v"),
        "up_down_open": ("up_down_counter", "clk", "rtl/up_down_counter.v"),
    }
    generated: dict[str, ToolchainProfile] = {}
    for name, (top, clock, source) in specifications.items():
        sdc = profiles_root / f"{name}.sdc"
        atomic_write_text(sdc, f"create_clock -name {clock} -period 10 [get_ports {clock}]\n")
        profile_path = profiles_root / f"{name}.yaml"
        manifest_path = profiles_root / f"{name}-pdk-manifest.json"
        result = prepare_nangate45_profile(
            [
                "--pdk-root",
                str(pdk_root),
                "--sdc",
                str(sdc),
                "--runtime",
                "docker",
                "--opensta",
                "sta",
                "--docker-image",
                image,
                "--output-manifest",
                str(manifest_path),
                "--output-profile",
                str(profile_path),
                "--source",
                source,
                "--top",
                top,
                "--clock-name",
                clock,
                "--clock-period",
                "10",
                "--profile-id",
                f"rtl-agenteval-{name}-opensta-v1",
                "--profile-version",
                "1.0.0",
            ]
        )
        if result != 0:
            raise ConfigurationError("OpenSTA site-profile preparation failed")
        generated[name] = registries.profiles.load_file(profile_path)

    loader = ToolchainProfileRegistry()
    for name, source_key in (
        ("counter_dc", "dc_counter"),
        ("up_down_dc", "dc_up_down"),
    ):
        client = loader.load_file(dc_paths[source_key])
        _require_commercial_worker_release(client)
        generated[name] = bind_mcp_client_profile_to_docker(
            client,
            image=image,
            prepared_image_id=image_id,
            profile_id=f"rtl-agenteval-{name}-docker-v1",
            profile_version="1.0.0",
        )
        registries.profiles.register(generated[name])
        path = profiles_root / f"{name}.yaml"
        atomic_write_text(
            path,
            yaml.safe_dump(
                generated[name].model_dump(mode="json", exclude_none=True),
                sort_keys=False,
            ),
        )
    return {name: PreparedProfile(profile, None) for name, profile in generated.items()}


def _require_commercial_worker_release(profile: ToolchainProfile) -> str:
    protocol = profile.metadata.get("agent_feedback_worker_release_protocol")
    release_hash = profile.metadata.get("agent_feedback_worker_release_hash")
    if protocol != COMMERCIAL_WORKER_RELEASE_PROTOCOL:
        raise ConfigurationError("commercial DC profile lacks the v2 worker release contract")
    if not isinstance(release_hash, str) or _SHA256.fullmatch(release_hash) is None:
        raise ConfigurationError("commercial DC profile lacks a valid worker release identity")
    if profile.metadata.get("commercial_worker_release_protocol") != protocol or (
        profile.metadata.get("commercial_worker_release_hash") != release_hash
    ):
        raise ConfigurationError("commercial worker release aliases are inconsistent")
    return release_hash


def _smoke_v2_identity_audit(
    plan_path: Path,
    prepared: dict[str, PreparedProfile],
) -> dict[str, Any]:
    try:
        baseline = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("smoke-v2 identity plan is unreadable") from exc
    if not isinstance(baseline, dict) or baseline.get("campaign_id") != (
        "rtl-agenteval-codex-gpt54-xhigh-smoke-v2"
    ):
        raise ConfigurationError("smoke-v2 identity plan has the wrong campaign identity")
    baseline_profiles = baseline.get("profiles")
    if not isinstance(baseline_profiles, dict):
        raise ConfigurationError("smoke-v2 identity plan lacks profile identities")
    records: list[dict[str, Any]] = []
    for name in sorted(prepared):
        item = prepared[name]
        previous = baseline_profiles.get(name)
        if item.resolved is None or not isinstance(previous, dict):
            raise ConfigurationError("smoke-v2 identity plan is incomplete")
        expected_hash = previous.get("resolved_hash")
        if not isinstance(expected_hash, str) or _SHA256.fullmatch(expected_hash) is None:
            raise ConfigurationError("smoke-v2 profile identity is invalid")
        observed_hash = item.resolved.resolved_profile_hash
        previous_components = previous.get("component_hashes")
        if isinstance(previous_components, dict):
            if set(previous_components) != set(RESOLVED_PROFILE_IDENTITY_COMPONENTS) or any(
                not isinstance(value, str) or _SHA256.fullmatch(value) is None
                for value in previous_components.values()
            ):
                raise ConfigurationError("smoke-v2 component identity snapshot is invalid")
            observed_components = resolved_profile_component_hashes(item.resolved)
            changed = [
                component
                for component in RESOLVED_PROFILE_IDENTITY_COMPONENTS
                if previous_components[component] != observed_components[component]
            ]
        else:
            changed = (
                [] if expected_hash == observed_hash else list(RESOLVED_PROFILE_IDENTITY_COMPONENTS)
            )
        if (expected_hash == observed_hash) != (not changed):
            raise ConfigurationError("smoke-v2 profile snapshot is internally inconsistent")
        records.append(
            {
                "profile": name,
                "expected_hash": expected_hash,
                "observed_hash": observed_hash,
                "changed_components": changed,
                "component_resolution": (
                    "exact" if isinstance(previous_components, dict) else "fail_closed_hash_only"
                ),
            }
        )
    return {
        "comparison_completed": True,
        "model_calls": 0,
        "drift_observed": any(record["changed_components"] for record in records),
        "records": records,
    }


def _no_model_qualification(
    service: VeriGym,
    *,
    source_configs: dict[str, SuiteSourceConfig],
    docker_config: DockerRuntimeConfig,
    prepared: dict[str, PreparedProfile],
    vcs_paths: dict[str, Path],
    scratch: Path,
) -> tuple[Any, dict[str, Any]]:
    scratch.mkdir()
    runtime = service.registries.runtimes.get("docker").configure(docker_config)
    runtime.prepare("rtl-agenteval-smoke-preflight")
    try:
        descriptor = runtime.descriptor
        image = descriptor.image
        if image is None or image.iverilog_version is None or "12." not in image.iverilog_version:
            raise ConfigurationError("qualified Docker runtime does not expose Icarus 12")
        functional: dict[str, Any] = {}
        for key in ("counter", "up_down"):
            functional[key] = _qualify_functional(
                service,
                source_configs[key],
                runtime,
                scratch / f"functional-{key}",
            )
        functional["agent_compile_bridge"] = _qualify_agent_compile_bridge(
            service,
            source_configs=source_configs,
            runtime=runtime,
        )
        resolved_items: dict[str, PreparedProfile] = {}
        for name, key in (
            ("counter_open", "counter"),
            ("up_down_open", "up_down"),
            ("counter_dc", "counter"),
            ("up_down_dc", "up_down"),
        ):
            item = prepared[name]
            resolved, record = _qualify_synthesis(
                service,
                source_configs[key],
                runtime,
                item.profile,
                scratch / f"synthesis-{name}",
            )
            resolved_items[name] = PreparedProfile(item.profile, resolved)
            functional[f"synthesis_{name}"] = record
        functional["agent_ppa_feedback"] = _qualify_agent_ppa_feedback(
            service,
            source_configs=source_configs,
            runtime=runtime,
            prepared=resolved_items,
            scratch=scratch / "agent-ppa-feedback",
        )
        _qualify_vcs(
            service,
            rtllm_source=source_configs["counter"].source_root,
            profile_paths=(vcs_paths["vcs_counter"], vcs_paths["vcs_up_down"]),
            scratch=scratch / "vcs",
        )
        prepared.update(resolved_items)
        return descriptor, functional
    finally:
        runtime.close()


def _qualify_agent_compile_bridge(
    service: VeriGym,
    *,
    source_configs: dict[str, SuiteSourceConfig],
    runtime: Any,
) -> dict[str, Any]:
    """Exercise the exact agent-session public compile path without launching a model."""

    records: list[dict[str, Any]] = []
    for key, task_id in (
        ("counter", _TASKS[0]),
        ("up_down", _TASKS[1]),
        ("verilog_eval", _TASKS[2]),
    ):
        suite, task, assets = service.load_task(task_id, source_configs[key])
        reference = suite.reference_solution(task)
        if reference is None or len(assets.read_only_mounts) != 1:
            raise ConfigurationError("agent compile qualification assets are incomplete")
        session = runtime.create_session(
            SessionSpec(
                source_dir=assets.visible_root,
                label="agent",
                max_output_bytes=task.budget.max_output_bytes_per_tool,
                read_only_mounts=assets.read_only_mounts,
            )
        )
        try:
            if session.external_process_backend != "docker_outer_runtime_delegated":
                raise ConfigurationError("agent compile qualification lacks its utility image")
            for relative, content in sorted(reference.files.items()):
                path = f"repository/{normalize_relative_path(relative)}"
                session.write_file(path, content.encode("utf-8"))
            completed = session.execute_public_test("compile")
            if (
                completed.exit_code != 0
                or completed.timed_out
                or completed.oom_killed
                or completed.failure_origin == "control_plane"
            ):
                raise ConfigurationError("agent-session public compile qualification failed")
            records.append(
                {
                    "task_id": task_id,
                    "public_test_id": "compile",
                    "passed": True,
                    "changed_file_count": len(session.snapshot_diff().changed_files),
                }
            )
        finally:
            session.close()
    return {"passed": True, "model_calls": 0, "records": records}


def _qualify_agent_ppa_feedback(
    service: VeriGym,
    *,
    source_configs: dict[str, SuiteSourceConfig],
    runtime: Any,
    prepared: dict[str, PreparedProfile],
    scratch: Path,
) -> dict[str, Any]:
    """Execute exact open and commercial candidate-feedback paths before model use."""

    records: list[dict[str, Any]] = []
    for source_key, task_id, profile_name in (
        ("counter", _TASKS[0], "counter_open"),
        ("up_down", _TASKS[1], "up_down_dc"),
    ):
        suite, task, assets = service.load_task(task_id, source_configs[source_key])
        reference = suite.reference_solution(task)
        item = prepared[profile_name]
        if reference is None or item.resolved is None or item.profile.flow is None:
            raise ConfigurationError("agent PPA feedback qualification inputs are incomplete")
        backend = service.registries.tools.get(item.profile.flow.backend_plugin)
        if not isinstance(backend, SynthesisBackendPlugin):
            raise ConfigurationError("agent PPA feedback qualification backend is unavailable")
        candidate = scratch / profile_name
        copy_tree_safely(Path(assets.visible_root), candidate)
        for relative, content in sorted(reference.files.items()):
            destination = candidate / normalize_relative_path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        result, metrics, dispatched = execute_candidate_synthesis_feedback(
            task=task,
            candidate_dir=candidate,
            runtime=runtime,
            profile=item.profile,
            resolved=item.resolved,
            plugin=backend,
        )
        if result.status != VerifierStatus.PASSED or not metrics.synthesis_ok or not dispatched:
            subcategory = (
                metrics.failure_category
                if metrics.failure_category in AGENT_FEEDBACK_INFRASTRUCTURE_SUBCATEGORIES
                else result.error_category.value
            )
            raise ConfigurationError(f"agent PPA feedback qualification failed: {subcategory}")
        records.append(
            {
                "task_id": task_id,
                "profile_name": profile_name,
                "passed": True,
                "execution_dispatched": True,
                "synthesis_ok": True,
            }
        )
    return {"passed": True, "model_calls": 0, "records": records}


def _qualify_functional(
    service: VeriGym,
    source_config: SuiteSourceConfig,
    runtime: Any,
    scratch: Path,
) -> dict[str, Any]:
    suite = RTLLMSuite().with_source(source_config)
    task = suite.load_task(next(iter(suite.discover())))
    assets = suite.resolve_assets(task)
    outcomes = []
    for case in suite.conformance_cases():
        candidate = scratch / case.name
        copy_tree_safely(Path(assets.visible_root), candidate)
        for relative, content in case.candidate.files.items():
            destination = candidate / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        results = service._verify_candidate(
            suite=suite,
            task=task,
            assets=assets,
            runtime=runtime,
            candidate_dir=candidate,
            artifact_root=scratch / "artifacts" / case.name,
        )
        resolved = all(result.status == VerifierStatus.PASSED for result in results)
        if resolved is not case.expected_resolved:
            raise ConfigurationError("RTLLM Icarus reference/known-bad qualification failed")
        outcomes.append({"case": case.name, "resolved": resolved})
    return {"passed": True, "cases": outcomes}


def _qualify_synthesis(
    service: VeriGym,
    source_config: SuiteSourceConfig,
    runtime: Any,
    profile: ToolchainProfile,
    scratch: Path,
) -> tuple[Any, dict[str, Any]]:
    task_id = f"rtllm/{source_config.variant}"
    suite, task, assets = service.load_task(task_id, source_config)
    reference = suite.reference_solution(task)
    if reference is None or profile.flow is None:
        raise ConfigurationError("synthesis qualification lacks reference or flow")
    projection = resolve_synthesis_source_projection(task)
    backend = service.registries.tools.get(profile.flow.backend_plugin)
    if not isinstance(backend, SynthesisBackendPlugin):
        raise ConfigurationError("synthesis qualification backend is unavailable")
    first_resolved = resolve_toolchain_profile(
        profile,
        runtime,
        source_paths=projection.profile_sources,
        top_module=profile.flow.top_module,
        reference_candidate_hash=content_hash(reference),
        backend=backend,
        synthesis_source_projection_hash=projection.projection_hash,
    )
    resolved = resolve_toolchain_profile(
        profile,
        runtime,
        source_paths=projection.profile_sources,
        top_module=profile.flow.top_module,
        reference_candidate_hash=content_hash(reference),
        backend=backend,
        synthesis_source_projection_hash=projection.projection_hash,
    )
    comparison = require_resolved_profile_identity(first_resolved, resolved)
    candidate = scratch / "candidate"
    copy_tree_safely(Path(assets.visible_root), candidate)
    for relative, content in reference.files.items():
        destination = candidate / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="rtl-agenteval-synthesis-") as artifacts:
        evaluation = execute_synthesis_quality(
            suite=suite,
            task=task,
            candidate_dir=candidate,
            runtime=runtime,
            profile=profile,
            resolved=resolved,
            artifact_root=Path(artifacts),
            plugin=backend,
            correctness_passed=True,
        )
    if not all(result.status == VerifierStatus.PASSED for result in evaluation.results):
        raise ConfigurationError("reference synthesis qualification failed")
    if not evaluation.candidate.synthesis_ok or not evaluation.reference.synthesis_ok:
        raise ConfigurationError("reference synthesis returned no eligible metrics")
    skipped = execute_synthesis_quality(
        suite=suite,
        task=task,
        candidate_dir=candidate,
        runtime=runtime,
        profile=profile,
        resolved=resolved,
        artifact_root=scratch / "known-bad-gate",
        plugin=backend,
        correctness_passed=False,
    )
    if any(result.status != VerifierStatus.SKIPPED for result in skipped.results):
        raise ConfigurationError("known-bad correctness gate did not skip synthesis")
    return resolved, {
        "passed": True,
        "candidate_metrics_valid": evaluation.candidate.synthesis_ok,
        "reference_metrics_valid": evaluation.reference.synthesis_ok,
        "known_bad_synthesis_skipped": True,
        "consecutive_resolution": comparison.model_dump(mode="json"),
    }


def _qualify_vcs(
    service: VeriGym,
    *,
    rtllm_source: Path | None,
    profile_paths: tuple[Path, Path],
    scratch: Path,
) -> None:
    if rtllm_source is None:
        raise ConfigurationError("RTLLM source is unavailable for VCS qualification")
    runtime = service.registries.runtimes.get("local").configure(None)
    runtime.prepare("rtl-agenteval-vcs-preflight")
    try:
        for variant, profile_path in zip(
            ("counter_12", "up_down_counter"), profile_paths, strict=True
        ):
            suite = RTLLMSuite().with_source(
                SuiteSourceConfig(source_root=rtllm_source, variant=variant)
            )
            task = suite.load_task(next(iter(suite.discover())))
            assets = suite.resolve_assets(task)
            profile = load_verifier_profile(profile_path)
            resolved = resolve_verifier_profile(
                task=task, profile=profile, tools=service.registries.tools
            )
            effective_task = task_with_verifier_profile(task, profile)
            for case in suite.conformance_cases():
                candidate = scratch / variant / case.name
                copy_tree_safely(Path(assets.visible_root), candidate)
                for relative, content in case.candidate.files.items():
                    destination = candidate / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(content, encoding="utf-8")
                results = service._verify_candidate(
                    task=effective_task,
                    assets=assets,
                    runtime=runtime,
                    candidate_dir=candidate,
                    artifact_root=scratch / "artifacts" / variant / case.name,
                    verifier_profile=profile,
                    resolved_verifier_profile=resolved,
                )
                observed = all(item.status == VerifierStatus.PASSED for item in results)
                if observed is not case.expected_resolved:
                    raise ConfigurationError("VCS/MCP reference/known-bad qualification failed")
    finally:
        runtime.close()


def _agent_options(capability: Any, auth: Any) -> dict[str, Any]:
    return {
        "model_id": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "max_process_time_s": 900,
        "max_output_bytes": 8 * 1024 * 1024,
        "allow_proxy_environment": bool(
            os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        ),
        "expected_cli_version": _EXPECTED_CLI_VERSION,
        "expected_cli_executable_sha256": _EXPECTED_CODEX_SHA256,
        "expected_capability_fingerprint": capability.capability_fingerprint,
        "expected_prompt_hash": AGENTEVAL_PROMPT_HASH,
        "expected_tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        "expected_requested_auth_mode": auth.requested_auth_mode,
        "expected_resolved_auth_mode": auth.resolved_auth_mode,
        "expected_auth_semantic_id": auth.auth_semantic_id,
        "prompt_contract_id": "repository_action_v2_prompt_v3",
        "scoring_agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "scoring_agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
    }


def _frozen_run_configs(
    service: VeriGym,
    *,
    source_configs: dict[str, SuiteSourceConfig],
    docker_config: DockerRuntimeConfig,
    runtime_descriptor: Any,
    prepared: dict[str, PreparedProfile],
    agent_options: dict[str, Any],
    output: Path,
) -> list[RunConfig]:
    specifications = (
        (_TASKS[0], source_configs["counter"], "counter_open", True, "01-counter-open"),
        (_TASKS[1], source_configs["up_down"], "up_down_dc", True, "02-up-down-dc"),
        (_TASKS[2], source_configs["verilog_eval"], None, False, "03-verilog-eval"),
        (_TASKS[3], source_configs["rtl_repo"], None, False, "04-rtl-repo"),
    )
    result = []
    for task_id, source, profile_name, ppa, run_id in specifications:
        profile_id = prepared[profile_name].profile.id if profile_name else None
        base = RunConfig(
            task_id=task_id,
            mode=InteractionMode.AGENT,
            agent="codex-cli-agenteval-agent",
            agent_options=agent_options,
            suite_source=source,
            runtime="docker",
            docker_config=docker_config,
            toolchain_profile=profile_id,
            agent_ppa_feedback=ppa,
            agent_ppa_max_calls=3,
            seed=0,
            sample_index=0,
            output=output,
            run_id=run_id,
        )
        result.append(
            _freeze_run_config(
                service,
                base,
                runtime_descriptor=runtime_descriptor,
                expected_profile=(prepared[profile_name].resolved if profile_name else None),
            )
        )
    return result


def _freeze_run_config(
    service: VeriGym,
    config: RunConfig,
    *,
    runtime_descriptor: Any,
    expected_profile: Any,
) -> RunConfig:
    suite, task, assets = service.load_task(config.task_id, config.suite_source)
    profile = (
        service.registries.profiles.get(config.toolchain_profile)
        if config.toolchain_profile is not None
        else None
    )
    backend_name = profile.flow.backend_plugin if profile is not None and profile.flow else None
    feedback = resolve_agent_feedback_contract(
        task=task,
        ppa_enabled=config.agent_ppa_feedback,
        ppa_max_executions=config.agent_ppa_max_calls,
        resolved_profile=expected_profile,
        profile_backend=backend_name,
    )
    execution_task = task_with_agent_feedback_contract(task, feedback)
    agent = service.registries.agents.get(config.agent)
    prompt = resolve_prompt_policy(
        interaction_mode=config.mode,
        agent=agent,
        agent_options=config.agent_options,
        task=execution_task,
    )
    action = resolve_repository_action_protocol(
        agent_descriptor=agent.descriptor,
        protocol_spec=agent.action_protocol_spec,
        agent_options=config.agent_options,
        task=execution_task,
    )
    source_hash = task.source.content_hash or hash_directory(Path(assets.visible_root))
    prompt_hash = prompt.configuration_fingerprint if prompt is not None else None
    configuration_hash = agent_configuration_hash(agent.descriptor, config.agent_options)
    return config.model_copy(
        update={
            "expected_task_hash": content_hash(task),
            "expected_source_hash": source_hash,
            "expected_suite_source_snapshot": suite.source_snapshot(),
            "expected_runtime": runtime_descriptor,
            "expected_resolved_profile": expected_profile,
            "expected_prompt_policy": prompt,
            "expected_prompt_policy_hash": prompt_hash,
            "resolved_prompt_policy": prompt,
            "resolved_prompt_policy_hash": prompt_hash,
            "expected_agent_configuration_hash": configuration_hash,
            "resolved_agent_configuration_hash": configuration_hash,
            "expected_action_protocol": action,
            "resolved_action_protocol": action,
            "expected_agent_feedback_contract": feedback,
            "resolved_agent_feedback_contract": feedback,
        },
        deep=True,
    )


def _execute_exactly_four(
    service: VeriGym,
    configs: list[RunConfig],
    output: Path,
) -> list[RunResult]:
    if len(configs) != 4:
        raise ConfigurationError("smoke launcher must contain exactly four frozen runs")
    ledger: list[dict[str, Any]] = []
    results: list[RunResult] = []
    for ordinal, config in enumerate(configs, start=1):
        record = {
            "ordinal": ordinal,
            "run_id": config.run_id,
            "task_id": config.task_id,
            "authorization_granted": True,
            "process_started": False,
            "provider_observation_recorded": False,
            "retry_count": 0,
            "status": "authorized",
        }
        ledger.append(record)
        atomic_dump_json(output / "evidence" / "process-authorizations.json", {"records": ledger})
        try:
            run = service.run(config)
        except Exception:
            run_dir = config.output.expanduser().resolve() / str(config.run_id)
            _update_process_ledger_record(record, run_dir=run_dir)
            record["status"] = "infrastructure_failure"
            atomic_dump_json(
                output / "evidence" / "process-authorizations.json", {"records": ledger}
            )
            raise
        _update_process_ledger_record(record, run_dir=run.run_dir, run=run)
        record["resolved"] = run.scorecard.resolved
        results.append(run)
        failure = run.scorecard.failure
        infrastructure = run.scorecard.correctness.infrastructure_error or (
            failure is not None and failure.infrastructure
        )
        if infrastructure:
            record["status"] = "infrastructure_failure"
        elif failure is not None and failure.kind == "policy":
            record["status"] = "policy_failure"
        elif failure is not None:
            record["status"] = "contained_model_failure"
        elif not run.scorecard.resolved:
            record["status"] = "verifier_rejection"
        else:
            record["status"] = "completed"
        atomic_dump_json(output / "evidence" / "process-authorizations.json", {"records": ledger})
        if infrastructure and ordinal < len(configs):
            raise CampaignInfrastructureError(
                "smoke campaign stopped after an infrastructure-invalid run"
            )
    if len(results) != 4:
        raise ConfigurationError("four-process smoke stopped before all runs completed")
    return results


def _update_process_ledger_record(
    record: dict[str, Any],
    *,
    run_dir: Path,
    run: RunResult | None = None,
) -> None:
    evidence_root = run_dir / "artifacts" / "codex_cli"
    record["process_started"] = (evidence_root / "process.json").is_file()
    observations = run.manifest.external_agent_observations if run is not None else []
    record["provider_observation_recorded"] = (
        len(observations) == 1 and (evidence_root / "identity.json").is_file()
    )


def _offline_replay(results: list[RunResult]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for result in results:
        replay = replay_run(result.run_dir, verify=False)
        records.append(
            {
                "run_id": result.manifest.run_id,
                "integrity_valid": replay.integrity.status == "verified",
                "event_count": len(replay.events),
                "resolved": replay.scorecard.resolved,
            }
        )
    return {
        "schema_version": "1.0",
        "records": records,
        "all_valid": all(record["integrity_valid"] for record in records),
    }


def _scan_outputs(
    results: list[RunResult],
    service: VeriGym,
    configs: dict[str, SuiteSourceConfig],
    profile_paths: dict[str, Path],
    inputs: dict[str, Path],
    *,
    site_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    sensitive: list[tuple[str, bytes]] = []
    for task_id, key in ((_TASKS[0], "counter"), (_TASKS[1], "up_down")):
        suite, task, assets = service.load_task(task_id, configs[key])
        for asset in assets.hidden_assets:
            if asset.content:
                sensitive.append(("hidden_rtl", asset.content.encode()))
        reference = suite.reference_solution(task)
        if reference is not None:
            sensitive.extend(
                ("reference_rtl", value.encode()) for value in reference.files.values()
            )
    path_markers = [
        *(str(path).encode() for path in profile_paths.values()),
        *(str(path).encode() for path in inputs.values()),
        *(str(path).encode() for path in site_paths),
    ]
    findings: list[dict[str, str]] = []
    for result in results:
        for file in sorted(result.run_dir.rglob("*")):
            if file.is_symlink():
                findings.append({"run_id": result.manifest.run_id, "category": "symlink"})
                continue
            if not file.is_file() or file.stat().st_size > 16 * 1024 * 1024:
                continue
            relative = file.relative_to(result.run_dir).as_posix()
            payload = file.read_bytes()
            model_facing = relative.startswith("artifacts/codex_cli/")
            if not relative.startswith("candidate/"):
                for category, marker in sensitive:
                    scan_reference = category != "reference_rtl" or model_facing
                    if scan_reference and len(marker) >= 32 and marker in payload:
                        findings.append({"run_id": result.manifest.run_id, "category": category})
            for marker in path_markers:
                if model_facing and marker and marker in payload:
                    findings.append({"run_id": result.manifest.run_id, "category": "site_path"})
            if model_facing and _COMMERCIAL_DIAGNOSTIC.search(payload):
                findings.append(
                    {"run_id": result.manifest.run_id, "category": "commercial_diagnostic"}
                )
    unique = [dict(item) for item in {tuple(sorted(item.items())) for item in findings}]
    return {"schema_version": "1.0", "passed": not unique, "findings": unique}


def _campaign_summary(
    results: list[RunResult],
    replay: dict[str, Any],
    scan: dict[str, Any],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    infrastructure_complete = len(results) == 4 and replay["all_valid"] and scan["passed"]
    process_started_count = 0
    provider_observation_count = 0
    policy_failure_count = 0
    for result in results:
        observations = result.manifest.external_agent_observations
        broker_path = result.run_dir / "artifacts" / "codex_cli" / "broker.json"
        broker = (
            json.loads(broker_path.read_text(encoding="utf-8")) if broker_path.is_file() else {}
        )
        identity_ok = (
            len(observations) == 1
            and observations[0].invocation_count == 1
            and observations[0].requested_model_id == "gpt-5.4"
            and observations[0].observed_model_id in {None, "gpt-5.4"}
            and observations[0].effective_reasoning_effort == "xhigh"
            and observations[0].harness_id == AGENTEVAL_AGENT_VERSION_ID
            and observations[0].agent_version_hash == AGENTEVAL_AGENT_VERSION_HASH
            and observations[0].prompt_contract_hash == AGENTEVAL_PROMPT_HASH
            and observations[0].tool_policy_fingerprint == AGENTEVAL_TOOL_POLICY_FINGERPRINT
        )
        finish_ok = broker.get("finished") is True and broker.get("finish_calls") == 1
        process_started = (result.run_dir / "artifacts" / "codex_cli" / "process.json").is_file()
        provider_recorded = (
            identity_ok and (result.run_dir / "artifacts" / "codex_cli" / "identity.json").is_file()
        )
        process_started_count += int(process_started)
        provider_observation_count += int(provider_recorded)
        failure = result.scorecard.failure
        policy_failure = failure is not None and failure.kind == "policy"
        infrastructure_failure = result.scorecard.correctness.infrastructure_error or (
            failure is not None and failure.infrastructure
        )
        legal_candidate_ppa = any(
            evaluation.passed
            and evaluation.metrics is not None
            and evaluation.candidate_hash == result.manifest.candidate_hash
            and evaluation.profile_hash == result.manifest.resolved_profile_hash
            for evaluation in result.manifest.agent_feedback_evaluations
        )
        policy_failure_count += int(policy_failure)
        infrastructure_complete = (
            infrastructure_complete
            and process_started
            and provider_recorded
            and not infrastructure_failure
        )
        records.append(
            {
                "run_id": result.manifest.run_id,
                "task_id": result.manifest.task_id,
                "resolved": result.scorecard.resolved,
                "model_identity_valid": identity_ok,
                "process_started": process_started,
                "provider_observation_recorded": provider_recorded,
                "typed_finish": finish_ok,
                "policy_failure": policy_failure,
                "infrastructure_failure": infrastructure_failure,
                "failure_subcategory": (
                    broker.get("policy_failure_subcategory")
                    or broker.get("infrastructure_failure_subcategory")
                ),
                "ppa_feedback_count": len(result.manifest.agent_feedback_evaluations),
                "legal_candidate_ppa": legal_candidate_ppa,
            }
        )
    all_candidates_resolved = len(records) == 4 and all(record["resolved"] for record in records)
    fully_successful = (
        infrastructure_complete
        and process_started_count == 4
        and provider_observation_count == 4
        and policy_failure_count == 0
        and all_candidates_resolved
        and all(record["typed_finish"] for record in records)
        and len(records) >= 2
        and all(record["legal_candidate_ppa"] for record in records[:2])
    )
    return {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "codex_processes_authorized": 4,
        "codex_processes_started": process_started_count,
        "provider_observations_recorded": provider_observation_count,
        "automatic_retries": 0,
        "runs": records,
        "all_candidates_resolved": all_candidates_resolved,
        "infrastructure_complete": infrastructure_complete,
        "fully_successful": fully_successful,
        "pilot_authorized": fully_successful,
        "benchmark_score_claimed": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
