#!/usr/bin/env python3
"""Run one frozen Codex CLI episode with public and hidden VCS/MCP verification."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from run_rtl_agenteval_codex_smoke import (
    _broker_root,
    _codex_preflight,
    _docker_config,
    _docker_image_id,
    _new_path,
)
from verigym_codex_cli.agenteval_config import (
    AGENTEVAL_AGENT_VERSION_HASH,
    AGENTEVAL_AGENT_VERSION_ID,
    AGENTEVAL_PROMPT_HASH,
    AGENTEVAL_TOOL_POLICY_FINGERPRINT,
)

from verigym.core.agent_feedback import (
    resolve_agent_feedback_contract,
    task_with_agent_feedback_contract,
)
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.orchestrator import VeriGym
from verigym.core.public_test_profiles import resolve_public_test_profile
from verigym.core.replay import replay_run
from verigym.core.verifier_profiles import (
    resolve_verifier_profile,
    task_with_verifier_profile,
)
from verigym.experiments.state import atomic_dump_json
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.prompts.policy import agent_configuration_hash, resolve_prompt_policy
from verigym.protocols.repository_action import resolve_repository_action_protocol
from verigym.provenance import get_build_provenance
from verigym.registry.collections import build_registries
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig

_CAMPAIGN_ID = "verilog-eval-vcs-public-codex-gpt54-xhigh-smoke-v1"
_TASK_ID = "verilog-eval/v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1/Prob001_zero"
_VARIANT = "v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1"
_RUN_ID = "01-prob001-codex-public-vcs"
_IMAGE = "verigym/open-rtl-tools:iverilog12-yosys067-opensta310"
_CLI_VERSION = "codex-cli 0.147.0"
_CLI_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"
_PROMPT_CONTRACT = "repository_action_v2_prompt_v6"
_COMMERCIAL_SECRET = re.compile(rb"(?i)(license[_ -]?server|snpslmd|lm_license_file|\.db\b)")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument("--broker-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--hidden-profile", type=Path, required=True)
    parser.add_argument("--public-profile", type=Path, required=True)
    parser.add_argument("--public-preflight", type=Path, required=True)
    parser.add_argument("--hidden-preflight", type=Path, required=True)
    parser.add_argument("--image", default=_IMAGE)
    parser.add_argument("--codex-binary", default="codex")
    return parser


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
        "expected_cli_executable_sha256": _CLI_SHA256,
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


def _load_preflight(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    expected = {
        "passed": True,
        "commercial_jobs": 1,
        "model_calls": 0,
        "automatic_retries": 0,
        "task_count": 1,
    }
    if not isinstance(payload, dict) or any(
        payload.get(key) != value for key, value in expected.items()
    ):
        raise ConfigurationError("zero-model VCS/MCP reference preflight is not qualified")
    return {**expected, "receipt_sha256": hash_bytes(resolved.read_bytes())}


def _freeze_config(
    service: VeriGym,
    *,
    source: SuiteSourceConfig,
    hidden_profile: Any,
    public_profile: Any,
    docker_config: Any,
    runtime_descriptor: Any,
    agent_options: dict[str, Any],
    output: Path,
) -> tuple[RunConfig, dict[str, str]]:
    suite, raw_task, assets = service.load_task(_TASK_ID, source)
    hidden = resolve_verifier_profile(
        task=raw_task,
        profile=hidden_profile,
        tools=service.registries.tools,
    )
    task = task_with_verifier_profile(raw_task, hidden_profile)
    public = resolve_public_test_profile(
        task=task,
        profile=public_profile,
        tools=service.registries.tools,
    )
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
    source_hash = raw_task.source.content_hash or hash_directory(Path(assets.visible_root))
    config = RunConfig(
        task_id=_TASK_ID,
        mode=InteractionMode.AGENT,
        agent="codex-cli-agenteval-agent",
        agent_options=agent_options,
        suite_source=source,
        runtime="docker",
        docker_config=docker_config,
        verifier_profile_id=hidden_profile.id,
        verifier_profile=hidden_profile,
        expected_resolved_verifier_profile=hidden,
        public_test_profile_id=public_profile.id,
        public_test_profile=public_profile,
        expected_resolved_public_test_profile=public,
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
        "hidden_declared_hash": content_hash(hidden_profile),
        "hidden_resolved_hash": hidden.resolved_profile_hash,
        "public_declared_hash": content_hash(public_profile),
        "public_resolved_hash": public.resolved_profile_hash,
    }


def _scan_model_facing(
    *,
    run_dir: Path,
    service: VeriGym,
    source: SuiteSourceConfig,
    path_markers: list[Path],
) -> dict[str, Any]:
    suite, task, assets = service.load_task(_TASK_ID, source)
    sensitive: list[bytes] = []
    reference = suite.reference_solution(task)
    if reference is not None:
        sensitive.extend(value.encode() for value in reference.files.values())
    sensitive.extend(
        asset.content.encode()
        for asset in assets.hidden_assets
        if asset.content is not None and len(asset.content) >= 32
    )
    markers = [str(path).encode() for path in path_markers]
    findings: list[str] = []
    root = run_dir / "artifacts" / "codex_cli"
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            findings.append("symlink")
            continue
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            continue
        payload = path.read_bytes()
        if any(len(value) >= 32 and value in payload for value in sensitive):
            findings.append("hidden_or_reference_content")
        if any(value and value in payload for value in markers):
            findings.append("site_path")
        if _COMMERCIAL_SECRET.search(payload):
            findings.append("commercial_secret_or_asset")
    unique = sorted(set(findings))
    return {"passed": not unique, "findings": unique}


def main() -> int:
    arguments = _parser().parse_args()
    output = _new_path(arguments.output, "experiment output")
    site_work = _new_path(arguments.site_work, "site work")
    broker_root = _new_path(arguments.broker_root, "Codex broker root")
    source_root = arguments.source_root.expanduser().resolve(strict=True)
    hidden_path = arguments.hidden_profile.expanduser().resolve(strict=True)
    public_path = arguments.public_profile.expanduser().resolve(strict=True)
    public_preflight = _load_preflight(arguments.public_preflight)
    hidden_preflight = _load_preflight(arguments.hidden_preflight)

    provenance = get_build_provenance()
    if provenance.dirty is not False or provenance.source_commit is None:
        raise ConfigurationError("Codex smoke requires a clean committed source tree")
    capability_path, capability, auth = _codex_preflight(arguments.codex_binary, site_work)
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(capability_path)
    os.environ["VERIGYM_CODEX_BROKER_ROOT"] = str(_broker_root(broker_root))

    registries = build_registries()
    required_tools = {"synopsys.vcs.mcp", "synopsys.vcs.public-compile.mcp"}
    if not required_tools.issubset(registries.tools.names()):
        raise ConfigurationError("required VCS/MCP integrations are unavailable")
    if "codex-cli-agenteval-agent" not in registries.agents.names():
        raise ConfigurationError("frozen Codex AgentEval adapter is unavailable")
    service = VeriGym(registries)
    source = SuiteSourceConfig(
        source_root=source_root,
        variant=_VARIANT,
        strict_compatibility=True,
    )
    docker_config = _docker_config(arguments.image, _docker_image_id(arguments.image))
    runtime = registries.runtimes.get("docker").configure(docker_config)
    runtime.prepare("verilog-eval-vcs-public-codex-preflight")
    try:
        runtime_descriptor = runtime.descriptor
    finally:
        runtime.close()
    hidden_profile = load_verifier_profile(hidden_path)
    public_profile = load_verifier_profile(public_path)
    options = _agent_options(capability, auth)
    config, identities = _freeze_config(
        service,
        source=source,
        hidden_profile=hidden_profile,
        public_profile=public_profile,
        docker_config=docker_config,
        runtime_descriptor=runtime_descriptor,
        agent_options=options,
        output=output,
    )
    if identities["hidden_resolved_hash"] == identities["public_resolved_hash"]:
        raise ConfigurationError("public and hidden VCS/MCP identities must remain separate")
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
        "identities": identities,
        "preflight": {"public": public_preflight, "hidden": hidden_preflight},
        "run_config_hash": content_hash(config.identity_payload()),
    }
    if not arguments.execute:
        atomic_dump_json(site_work / "preflight-plan.json", plan)
        print(json.dumps({"status": "qualified_plan_only", "model_processes": 0}))
        return 0
    if os.environ.get("VERIGYM_RUN_VERILOG_EVAL_VCS_PUBLIC_CODEX_SMOKE") != "1":
        raise ConfigurationError(
            "execution requires VERIGYM_RUN_VERILOG_EVAL_VCS_PUBLIC_CODEX_SMOKE=1"
        )

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
    broker_path = result.run_dir / "artifacts/codex_cli/broker.json"
    broker = json.loads(broker_path.read_text(encoding="utf-8"))
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
    feedback = result.manifest.agent_feedback_evaluations
    public_ok = (
        bool(feedback)
        and all(item.test_id == "compile" for item in feedback)
        and all(item.profile_hash == identities["public_resolved_hash"] for item in feedback)
        and feedback[-1].passed
        and result.manifest.repository_public_tool_invocation_count == len(feedback)
    )
    profiles_ok = (
        result.manifest.resolved_verifier_profile_hash == identities["hidden_resolved_hash"]
        and result.manifest.resolved_public_test_profile_hash == identities["public_resolved_hash"]
    )
    typed_finish = broker.get("finished") is True and broker.get("finish_calls") == 1
    failure = result.scorecard.failure
    infrastructure_ok = not result.scorecard.correctness.infrastructure_error and not (
        failure is not None and failure.infrastructure
    )
    replay = replay_run(result.run_dir, verify=False)
    replay_ok = replay.integrity.status == "verified" and replay.scorecard.resolved == (
        result.scorecard.resolved
    )
    scan = _scan_model_facing(
        run_dir=result.run_dir,
        service=service,
        source=source,
        path_markers=[
            hidden_path,
            public_path,
            source_root,
            site_work,
            broker_root,
            output,
        ],
    )
    fully_successful = all(
        (
            result.scorecard.resolved,
            identity_ok,
            typed_finish,
            public_ok,
            profiles_ok,
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
        "public_vcs_feedback_used": public_ok,
        "public_vcs_invocations": len(feedback),
        "hidden_vcs_final_verdict_bound": profiles_ok,
        "profiles_separate": (
            identities["hidden_resolved_hash"] != identities["public_resolved_hash"]
        ),
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
