#!/usr/bin/env python3
"""Run one bounded Codex CLI episode with public Verilator feedback."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

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

from verigym.core.agent_feedback import (
    resolve_agent_feedback_contract,
    task_with_agent_feedback_contract,
)
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.experiments.state import atomic_dump_json
from verigym.prompts.policy import agent_configuration_hash, resolve_prompt_policy
from verigym.protocols.repository_action import resolve_repository_action_protocol
from verigym.provenance import get_build_provenance
from verigym.registry.base import PluginOrigin
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerExternalAgentRuntimeConfig, DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier import VerifierStatus

_CAMPAIGN_ID = "verilog-eval-verilator-public-codex-gpt54-xhigh-smoke-v1"
_VARIANT = "v2-spec-to-rtl-agent-eval-verilator-v1"
_TASK_ID = f"verilog-eval/{_VARIANT}/Prob001_zero"
_RUN_ID = "01-prob001-codex-public-verilator"
_VERIFIER_IMAGE = "verigym/rtl-verilator:5.052-iverilog12-r1"
_AGENT_IMAGE = "verigym/codex-repository-agent-verilator:0.147.0-v1"
_CLI_VERSION = "codex-cli 0.147.0"
_CLI_LAUNCHER_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"
_CONTAINER_CODEX_SHA256 = "cb0a15567e9a60a5820d54b0f6ae86d504dc3805c1eab21a47f70e3eb7b73a40"
_PROMPT_CONTRACT = "repository_action_v2_prompt_v6"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument("--broker-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--verifier-image", default=_VERIFIER_IMAGE)
    parser.add_argument("--agent-image", default=_AGENT_IMAGE)
    parser.add_argument("--codex-binary", default="codex")
    return parser


def _new_path(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists() or resolved.is_symlink():
        raise ConfigurationError(f"{label} must not already exist")
    return resolved


def _image_id(reference: str) -> str:
    completed = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", reference],
        capture_output=True,
        check=False,
        shell=False,
        text=True,
        timeout=30,
    )
    image_id = completed.stdout.strip()
    if completed.returncode != 0 or _SHA256.fullmatch(image_id) is None:
        raise ConfigurationError(f"required local Docker image is unavailable: {reference}")
    return image_id


def _configure_temp_root(site_work: Path) -> None:
    site_work.mkdir(mode=0o700, parents=True)
    temp_root = site_work / "tmp"
    temp_root.mkdir(mode=0o700)
    os.environ["TMPDIR"] = str(temp_root)
    tempfile.tempdir = str(temp_root)


def _codex_preflight(binary: str, site_work: Path) -> tuple[Path, Any, Any]:
    _configure_temp_root(site_work)
    os.environ["VERIGYM_CODEX_BINARY"] = binary
    os.environ.setdefault("VERIGYM_CODEX_AUTH_MODE", "chatgpt_cli_session")
    executable, capability = discover_capabilities(force=True)
    if (
        capability.version_output != _CLI_VERSION
        or capability.executable_sha256 != _CLI_LAUNCHER_SHA256
        or executable.sha256 != _CLI_LAUNCHER_SHA256
    ):
        raise ConfigurationError("Codex CLI differs from the frozen smoke identity")
    auth, _ = auth_identity_configuration()
    auth_preflight = run_auth_preflight(executable)
    if (
        not auth_preflight.external_prerequisite_satisfied
        or auth_preflight.model_calls != 0
        or auth_preflight.login_processes != 0
    ):
        raise ConfigurationError("the selected existing Codex authentication is unavailable")
    capability_path = site_work / "codex-capabilities.json"
    atomic_dump_json(capability_path, capability.safe_dict())
    atomic_dump_json(site_work / "codex-auth-preflight.json", auth_preflight.safe_dict())
    return capability_path, capability, auth


def _broker_root(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    if len(os.fsencode(resolved)) > 64:
        raise ConfigurationError("broker root is too long for its Unix socket")
    resolved.mkdir(parents=True)
    return resolved


def _registries() -> Any:
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
    if "verilator.compile" not in registries.tools.names():
        raise ConfigurationError("Verilator compile plugin is unavailable")
    return registries


def _docker_config(
    verifier_image: str,
    verifier_image_id: str,
    agent_image: str,
    agent_image_id: str,
) -> DockerRuntimeConfig:
    launcher = Path(__file__).resolve().parents[1] / "src/verigym/public_test_launcher_v2.py"
    launcher_sha256 = hash_bytes(launcher.read_bytes())
    runtime_user = f"{os.getuid()}:{os.getgid()}"
    return DockerRuntimeConfig(
        image=verifier_image,
        expected_image_id=verifier_image_id,
        pull_policy="never",
        network_mode="none",
        run_as_user="10001:10001",
        memory_bytes=2 * 1024**3,
        cpus=2.0,
        pids_limit=256,
        tmpfs_bytes=128 * 1024**2,
        max_command_time_s=900,
        external_agent=DockerExternalAgentRuntimeConfig(
            image=agent_image,
            expected_image_id=agent_image_id,
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version=_CLI_VERSION,
            expected_executable_sha256=_CONTAINER_CODEX_SHA256,
            process_argv=[
                "/usr/local/bin/codex",
                "exec-server",
                "--listen",
                "stdio://",
            ],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels={
                "org.verigym.runtime.role": "repository-agent",
                "org.verigym.codex.version": "0.147.0",
                "org.verigym.codex.binary.sha256": _CONTAINER_CODEX_SHA256,
                "org.verigym.external_agent.protocol": ("codex_app_server_remote_environment_v1"),
                "org.verigym.public_test.protocol": "verigym_public_test_v1",
                "org.verigym.public_test_launcher.sha256": launcher_sha256,
                "org.verigym.iverilog.version": "12.0",
                "org.verigym.verilator.version": "5.052",
                "org.verigym.rtl.base_image_id": verifier_image_id,
                "org.verigym.provider_credentials": "absent",
                "org.verigym.credential_material": "absent",
            },
            pull_policy="never",
            run_as_user=runtime_user,
            memory_bytes=1024 * 1024**2,
            cpus=2.0,
            pids_limit=256,
            tmpfs_bytes=128 * 1024**2,
            max_process_time_s=900,
            max_output_bytes=8 * 1024 * 1024,
        ),
    )


def _agent_options(capability: Any, auth: Any) -> dict[str, Any]:
    return {
        "model_id": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "max_process_time_s": 900,
        "max_output_bytes": 8 * 1024 * 1024,
        "allow_proxy_environment": bool(
            os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        ),
        "expected_cli_version": _CLI_VERSION,
        "expected_cli_executable_sha256": _CLI_LAUNCHER_SHA256,
        "expected_capability_fingerprint": capability.capability_fingerprint,
        "expected_prompt_hash": AGENTEVAL_PROMPT_HASH,
        "expected_tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        "expected_requested_auth_mode": auth.requested_auth_mode,
        "expected_resolved_auth_mode": auth.resolved_auth_mode,
        "expected_auth_semantic_id": auth.auth_semantic_id,
        "prompt_contract_id": _PROMPT_CONTRACT,
        "scoring_agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "scoring_agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
    }


def _freeze_config(
    service: VeriGym,
    *,
    source: SuiteSourceConfig,
    docker_config: DockerRuntimeConfig,
    runtime_descriptor: Any,
    agent_options: dict[str, Any],
    output: Path,
) -> tuple[RunConfig, dict[str, Any]]:
    suite, task, assets = service.load_task(_TASK_ID, source)
    if task.metadata.get("public_feedback_backend") != "verilator":
        raise ConfigurationError("task does not bind the Verilator public feedback partition")
    if [node.plugin for node in task.verifier.nodes] != [
        "verilog_eval.v2.compile",
        "verilog_eval.v2.regression",
    ]:
        raise ConfigurationError("task does not retain the independent hidden Icarus verifier")
    feedback = resolve_agent_feedback_contract(
        task=task,
        ppa_enabled=False,
        ppa_max_executions=3,
        resolved_profile=None,
        profile_backend=None,
    )
    execution_task = task_with_agent_feedback_contract(task, feedback)
    agent = service.registries.agents.get("codex-cli-agenteval-agent")
    prompt = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=agent,
        agent_options=agent_options,
        task=execution_task,
    )
    action = resolve_repository_action_protocol(
        agent_descriptor=agent.descriptor,
        protocol_spec=agent.action_protocol_spec,
        agent_options=agent_options,
        task=execution_task,
    )
    configuration_hash = agent_configuration_hash(agent.descriptor, agent_options)
    source_hash = task.source.content_hash or hash_directory(Path(assets.visible_root))
    config = RunConfig(
        task_id=_TASK_ID,
        mode=InteractionMode.AGENT,
        agent="codex-cli-agenteval-agent",
        agent_options=agent_options,
        suite_source=source,
        runtime="docker",
        docker_config=docker_config,
        seed=0,
        sample_index=0,
        output=output / "runs",
        run_id=_RUN_ID,
        expected_task_hash=content_hash(task),
        expected_source_hash=source_hash,
        expected_suite_source_snapshot=suite.source_snapshot(),
        expected_runtime=runtime_descriptor,
        expected_prompt_policy=prompt,
        expected_prompt_policy_hash=prompt.configuration_fingerprint,
        resolved_prompt_policy=prompt,
        resolved_prompt_policy_hash=prompt.configuration_fingerprint,
        expected_agent_configuration_hash=configuration_hash,
        resolved_agent_configuration_hash=configuration_hash,
        expected_action_protocol=action,
        resolved_action_protocol=action,
        expected_agent_feedback_contract=feedback,
        resolved_agent_feedback_contract=feedback,
    )
    return config, {
        "task_hash": content_hash(task),
        "source_hash": source_hash,
        "suite_source_hash": suite.source_snapshot().dataset_content_hash,
        "public_test_contract_hash": feedback.public_test_contract_hash,
        "agent_feedback_contract_hash": content_hash(feedback),
    }


def _scan_model_artifacts(run_dir: Path, path_markers: list[Path]) -> dict[str, Any]:
    findings: set[str] = set()
    markers = [str(path).encode() for path in path_markers]
    root = run_dir / "artifacts/codex_cli"
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            findings.add("symlink")
            continue
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            continue
        payload = path.read_bytes()
        if any(marker and marker in payload for marker in markers):
            findings.add("host_path")
    return {"passed": not findings, "findings": sorted(findings)}


def main() -> int:
    arguments = _parser().parse_args()
    output = _new_path(arguments.output, "experiment output")
    site_work = _new_path(arguments.site_work, "site work")
    broker_root = _new_path(arguments.broker_root, "Codex broker root")
    source_root = arguments.source_root.expanduser().resolve(strict=True)
    if not source_root.is_dir() or source_root.is_symlink():
        raise ConfigurationError("VerilogEval source must be a real directory")

    provenance = get_build_provenance()
    if provenance.dirty is not False or provenance.source_commit is None:
        raise ConfigurationError("Codex smoke requires a clean committed source tree")
    capability_path, capability, auth = _codex_preflight(arguments.codex_binary, site_work)
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(capability_path)
    os.environ["VERIGYM_CODEX_BROKER_ROOT"] = str(_broker_root(broker_root))

    verifier_id = _image_id(arguments.verifier_image)
    agent_id = _image_id(arguments.agent_image)
    docker_config = _docker_config(
        arguments.verifier_image,
        verifier_id,
        arguments.agent_image,
        agent_id,
    )
    registries = _registries()
    service = VeriGym(registries)
    source = SuiteSourceConfig(
        source_root=source_root,
        variant=_VARIANT,
        strict_compatibility=True,
    )
    runtime = registries.runtimes.get("docker").configure(docker_config)
    runtime.prepare("verilator-public-codex-preflight")
    try:
        runtime_descriptor = runtime.descriptor
        runtime_role_images = runtime.environment_summary()["docker_role_images"]
    finally:
        runtime.close()
    if runtime_descriptor.image is None or runtime_descriptor.image.verilator_version is None:
        raise ConfigurationError("prepared Docker runtime omitted its Verilator identity")

    options = _agent_options(capability, auth)
    config, identities = _freeze_config(
        service,
        source=source,
        docker_config=docker_config,
        runtime_descriptor=runtime_descriptor,
        agent_options=options,
        output=output,
    )
    plan = {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "task_id": _TASK_ID,
        "model": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "seed": 0,
        "sample_index": 0,
        "planned_codex_processes": 1,
        "automatic_retries": 0,
        "benchmark_score_claimed": False,
        "build_provenance": provenance.model_dump(mode="json"),
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
        "runtime_role_images": runtime_role_images,
        "identities": identities,
        "run_config_hash": content_hash(config.identity_payload()),
    }
    if not arguments.execute:
        atomic_dump_json(site_work / "preflight-plan.json", plan)
        print(json.dumps({"status": "qualified_plan_only", "model_processes": 0}))
        return 0
    if os.environ.get("VERIGYM_RUN_VERILATOR_PUBLIC_CODEX_SMOKE") != "1":
        raise ConfigurationError("execution requires VERIGYM_RUN_VERILATOR_PUBLIC_CODEX_SMOKE=1")

    output.mkdir(parents=True)
    (output / "runs").mkdir()
    (output / "evidence").mkdir()
    atomic_dump_json(output / "plan.json", plan)
    ledger = {
        "planned_codex_processes": 1,
        "automatic_retries": 0,
        "authorization_granted": True,
        "process_started": False,
        "provider_observation_recorded": False,
        "status": "authorized",
    }
    atomic_dump_json(output / "evidence/process-authorization.json", ledger)
    try:
        result = service.run(config)
    except BaseException:
        evidence = output / "runs" / _RUN_ID / "artifacts/codex_cli"
        ledger["process_started"] = (evidence / "process.json").is_file()
        ledger["provider_observation_recorded"] = (evidence / "identity.json").is_file()
        ledger["status"] = "terminal_failure_no_retry"
        atomic_dump_json(output / "evidence/process-authorization.json", ledger)
        raise

    observations = result.manifest.external_agent_observations
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
    broker = json.loads(
        (result.run_dir / "artifacts/codex_cli/broker.json").read_text(encoding="utf-8")
    )
    typed_finish = broker.get("finished") is True and broker.get("finish_calls") == 1
    feedback = result.manifest.agent_feedback_evaluations
    public_ok = (
        bool(feedback)
        and all(item.test_id == "compile" for item in feedback)
        and feedback[-1].passed
        and result.manifest.repository_public_tool_invocation_count == len(feedback)
    )
    hidden_results = result.scorecard.verifier_results
    hidden_ok = [item.node_id for item in hidden_results] == [
        "compile_hidden",
        "run_hidden",
    ] and all(item.status == VerifierStatus.PASSED for item in hidden_results)
    failure = result.scorecard.failure
    infrastructure_ok = not result.scorecard.correctness.infrastructure_error and not (
        failure is not None and failure.infrastructure
    )
    replay = replay_run(result.run_dir, verify=False)
    replay_ok = replay.integrity.status == "verified" and replay.scorecard.resolved == (
        result.scorecard.resolved
    )
    scan = _scan_model_artifacts(
        result.run_dir,
        [source_root, site_work, broker_root, output],
    )
    fully_successful = all(
        (
            result.scorecard.resolved,
            identity_ok,
            typed_finish,
            public_ok,
            hidden_ok,
            infrastructure_ok,
            replay_ok,
            scan["passed"],
        )
    )
    summary = {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "fully_successful": fully_successful,
        "candidate_resolved": result.scorecard.resolved,
        "one_codex_process": identity_ok,
        "typed_finish": typed_finish,
        "public_verilator_feedback_used": public_ok,
        "public_verilator_invocations": len(feedback),
        "hidden_icarus_final_verdict_passed": hidden_ok,
        "infrastructure_valid": infrastructure_ok,
        "offline_replay_verified": replay_ok,
        "security_scan_passed": scan["passed"],
        "model_processes_started": 1,
        "automatic_retries": 0,
        "benchmark_score_claimed": False,
    }
    ledger.update(
        {
            "process_started": True,
            "provider_observation_recorded": identity_ok,
            "status": "completed" if infrastructure_ok else "infrastructure_failure",
        }
    )
    atomic_dump_json(output / "evidence/process-authorization.json", ledger)
    atomic_dump_json(output / "replay.json", {"integrity": replay.integrity.status})
    atomic_dump_json(output / "security-scan.json", scan)
    atomic_dump_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if fully_successful else 2


if __name__ == "__main__":
    raise SystemExit(main())
