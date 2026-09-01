from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from tests.milestone9_helpers import experiment_config, offline_service
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.replay import replay_run
from verigym.core.verifier_profiles import task_with_verifier_profile
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.schemas.common import ErrorCategory, ToolDescriptor, ToolVisibility
from verigym.schemas.run import RunConfig
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.schemas.verifier_profile import ResolvedVerifierToolProfile, VerifierToolProfile
from verigym.tools.base import ToolContext, VerifierBackendPlugin


class _FakeVerifierBackend(VerifierBackendPlugin):
    descriptor = ToolDescriptor(
        name="test.verifier.mcp",
        version="1.0.0",
        provider="tests",
        capabilities=["fixed_profile"],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )

    def __init__(self) -> None:
        self.drift = False

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        del context
        return HealthCheckResult(healthy=True, message="fixed test verifier")

    def resolve_verifier_profile(
        self,
        profile: VerifierToolProfile,
        *,
        expected: ResolvedVerifierToolProfile | None = None,
    ) -> ResolvedVerifierToolProfile:
        payload: dict[str, object] = {
            "profile_id": profile.id,
            "profile_version": profile.version,
            "declared_profile_hash": content_hash(profile),
            "task_id": profile.task_id,
            "source_plugin": profile.source_plugin,
            "target_plugin": profile.target_plugin,
            "runtime": profile.runtime,
            "transport_sha256": profile.transport_sha256,
            "service_protocol": profile.service_protocol,
            "server_version": profile.server_version,
            "server_profile_id": profile.server_profile_id,
            "server_declared_profile_hash": profile.server_declared_profile_hash,
            "server_resolved_profile_hash": content_hash({"drift": self.drift}),
            "server_contract_hash": profile.server_contract_hash,
            "tool_version": profile.accepted_tool_version,
        }
        resolved = ResolvedVerifierToolProfile.model_validate(
            {**payload, "resolved_profile_hash": content_hash(payload)}
        )
        if expected is not None and resolved != expected:
            raise ConfigurationError("fake verifier identity drifted")
        return resolved

    def validate_request(self, request: dict[str, Any]) -> BaseModel:
        raise NotImplementedError

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        raise NotImplementedError

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        raise NotImplementedError

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.session is None:
            raise ConfigurationError("fake verifier requires a runtime session")
        output = str(raw_request["output"])
        context.session.write_file(output, b"fake-verifier-executable\n")
        return ToolResult(
            tool=self.descriptor.name,
            success=True,
            category=ErrorCategory.SUCCESS,
            message="fixed test verifier passed",
            metadata={"executable": output},
        )


def _profile(tmp_path: Path) -> tuple[VerifierToolProfile, Path]:
    wrapper = tmp_path / "fixed-transport"
    wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)
    profile = VerifierToolProfile(
        id="toy-and-vcs-mcp-v1",
        version="1.0.0",
        task_id="toy-rtl/and-gate-basic",
        source_plugin="iverilog.compile",
        target_plugin="test.verifier.mcp",
        transport_executable=str(wrapper),
        transport_sha256=hash_bytes(wrapper.read_bytes()),
        service_protocol="test.verifier.mcp.v1",
        server_version="1.0.0",
        server_profile_id="toy-and-server-v1",
        server_declared_profile_hash="a" * 64,
        server_contract_hash="b" * 64,
        accepted_tool_version="test-1.0",
    )
    path = tmp_path / "verifier-profile.yaml"
    path.write_text(
        yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    return profile, path


def test_verifier_profile_is_frozen_into_experiment_plan(tmp_path: Path) -> None:
    profile, profile_path = _profile(tmp_path)
    service = offline_service()
    backend = _FakeVerifierBackend()
    service.registries.tools.register(backend)
    base_config = experiment_config(
        tmp_path / "out",
        tasks=["and-gate-basic"],
        systems=[{"id": "good", "agent": {"id": "scripted"}}],
        seeds=[0],
    )
    payload = base_config.model_dump(mode="python")
    payload["verifier_profile"] = profile.id
    payload["verifier_profile_file"] = profile_path
    config = type(base_config).model_validate(payload)

    planner = ExperimentPlanner(service)
    plan = planner.build(config)
    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.verifier_profile == profile
    assert item.resolved_verifier_profile is not None
    assert item.resolved_verifier_profile.profile_id == profile.id
    _, original_task, _ = service.load_task(profile.task_id)
    transformed = task_with_verifier_profile(original_task, profile)
    assert content_hash(transformed) == item.task_hash
    assert transformed.verifier.nodes[0].plugin == backend.descriptor.name
    planner.verify_frozen_inputs(plan)

    batch = BatchRunner(planner=planner, service_factory=lambda: service).run(plan)
    assert batch.exit_code == 0
    child_dirs = [path for path in (batch.experiment_dir / "runs").iterdir() if path.is_dir()]
    assert len(child_dirs) == 1
    replay = replay_run(child_dirs[0], verify=True, service=service)
    assert replay.reverified_resolved is True

    backend.drift = True
    with pytest.raises(ConfigurationError, match="resolved verifier profile changed"):
        planner.verify_frozen_inputs(plan)


def test_verifier_profile_loader_rejects_duplicate_keys_and_symlinks(tmp_path: Path) -> None:
    profile, profile_path = _profile(tmp_path)
    assert load_verifier_profile(profile_path) == profile

    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema_version: '1.0'\nid: first\nid: second\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="duplicate verifier-profile key"):
        load_verifier_profile(duplicate)

    link = tmp_path / "profile-link.yaml"
    link.symlink_to(profile_path)
    with pytest.raises(ConfigurationError, match="regular, non-symlink"):
        load_verifier_profile(link)


def test_only_remote_mcp_may_use_local_controller_transport_for_docker(tmp_path: Path) -> None:
    from verigym.core.orchestrator import _uses_controller_verifier_transport

    profile, _ = _profile(tmp_path)
    config = RunConfig(
        task_id=profile.task_id,
        runtime="docker",
        verifier_profile_id=profile.id,
        verifier_profile=profile,
    )
    backend = _FakeVerifierBackend()

    assert not _uses_controller_verifier_transport(config, backend)
    backend.descriptor = backend.descriptor.model_copy(
        update={"capabilities": ["fixed_profile", "remote_mcp"]}
    )
    assert _uses_controller_verifier_transport(config, backend)
    assert not _uses_controller_verifier_transport(
        config.model_copy(update={"runtime": "local"}), backend
    )


def test_hidden_verification_can_require_a_typed_final_submission() -> None:
    from verigym.core.orchestrator import _verification_requires_final_submission

    assert not _verification_requires_final_submission(SimpleNamespace(metadata={}))
    assert _verification_requires_final_submission(
        SimpleNamespace(metadata={"verification_requires_final_submission": True})
    )
    with pytest.raises(ConfigurationError, match="must be a boolean"):
        _verification_requires_final_submission(
            SimpleNamespace(metadata={"verification_requires_final_submission": "true"})
        )
