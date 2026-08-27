"""Resolve and execute revision-bound AgentEval compile/PPA feedback."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_directory
from verigym.core.synthesis import execute_candidate_synthesis_feedback
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.runtimes.base import Runtime, RuntimeSession
from verigym.schemas.agent_feedback import (
    AgentFeedbackCategory,
    AgentFeedbackContract,
    AgentFeedbackEvaluation,
    AgentFeedbackMetrics,
)
from verigym.schemas.common import ToolchainProfile
from verigym.schemas.task import VeriTask
from verigym.schemas.tool import CompletedCommand
from verigym.schemas.verifier import VerifierStatus
from verigym.tools.base import SynthesisBackendPlugin

_DECLARATION_KEY = "agent_eval"
_OPEN_PPA_FLOW = "verigym-yosys-opensta-atp-v2"
_OPEN_PPA_BACKENDS = frozenset({"yosys.synth", "yosys.stat"})


def resolve_agent_feedback_contract(
    *,
    task: VeriTask,
    ppa_enabled: bool,
    ppa_max_executions: int,
    resolved_profile: ResolvedToolchainProfile | None,
    profile_backend: str | None,
) -> AgentFeedbackContract | None:
    """Resolve a declared AgentEval interface before any agent/model lookup."""

    declaration = task.metadata.get(_DECLARATION_KEY)
    if declaration is None:
        if ppa_enabled:
            raise ConfigurationError("--agent-ppa-feedback requires an AgentEval task variant")
        return None
    if not isinstance(declaration, dict):
        raise ConfigurationError("AgentEval task feedback declaration is malformed")
    required = {
        "benchmark_variant",
        "compile_test_id",
        "ppa_supported",
        "public_test_contract_hash",
    }
    if set(declaration) != required:
        raise ConfigurationError("AgentEval task feedback declaration has an unexpected schema")
    variant = declaration["benchmark_variant"]
    compile_test_id = declaration["compile_test_id"]
    ppa_supported = declaration["ppa_supported"]
    public_contract_hash = declaration["public_test_contract_hash"]
    if (
        not isinstance(variant, str)
        or not variant
        or compile_test_id not in {None, "compile"}
        or not isinstance(ppa_supported, bool)
        or (
            public_contract_hash is not None
            and (not isinstance(public_contract_hash, str) or len(public_contract_hash) != 64)
        )
    ):
        raise ConfigurationError("AgentEval task feedback declaration contains invalid values")
    if ppa_enabled and not ppa_supported:
        raise ConfigurationError(f"task variant {variant!r} does not support PPA feedback")
    if ppa_enabled:
        if resolved_profile is None or profile_backend is None:
            raise ConfigurationError(
                "--agent-ppa-feedback requires one resolved Yosys/OpenSTA toolchain profile"
            )
        if profile_backend not in _OPEN_PPA_BACKENDS:
            raise ConfigurationError(
                "agent-visible commercial PPA is unavailable in phase one; "
                "select the Yosys/OpenSTA ATP v2 profile"
            )
        if (
            resolved_profile.flow_template_id != _OPEN_PPA_FLOW
            or resolved_profile.metric_scope != "synthesis_area_timing_power"
        ):
            raise ConfigurationError(
                "agent PPA feedback requires verigym-yosys-opensta-atp-v2 area/timing/power"
            )
        if resolved_profile.top_module != task.metadata.get("candidate_top"):
            raise ConfigurationError("agent PPA profile top differs from the AgentEval task top")
    public_ids = [value for value in (compile_test_id, "ppa" if ppa_enabled else None) if value]
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "contract_id": "agent_feedback_contract.v1",
        "resolver_id": "agent_feedback_contract_resolver_v1",
        "task_id": task.id,
        "benchmark_variant": variant,
        "state_machine_id": "repository_action_state_machine_v3",
        "compile_test_id": compile_test_id,
        "ppa_test_id": "ppa" if ppa_enabled else None,
        "public_test_ids": public_ids,
        "compile_required_for_finish": compile_test_id is not None,
        "ppa_requires_compile": True,
        "patch_invalidates_compile": True,
        "patch_invalidates_ppa": True,
        "patch_invalidates_diff": True,
        "ppa_supported": ppa_supported,
        "ppa_enabled": ppa_enabled,
        "ppa_max_executions": ppa_max_executions,
        "resolved_profile_hash": (
            resolved_profile.resolved_profile_hash if ppa_enabled and resolved_profile else None
        ),
        "profile_backend": profile_backend if ppa_enabled else None,
        "public_test_contract_hash": public_contract_hash,
    }
    return AgentFeedbackContract.model_validate(
        {**payload, "configuration_fingerprint": content_hash(payload)}
    )


def task_with_agent_feedback_contract(
    task: VeriTask,
    contract: AgentFeedbackContract | None,
) -> VeriTask:
    """Attach only the resolved public contract to an execution-context task copy."""

    if contract is None:
        return task
    metadata = dict(task.metadata)
    metadata["agent_feedback_contract"] = contract.model_dump(mode="json")
    return task.model_copy(update={"metadata": metadata}, deep=True)


def public_feedback_test_ids(task: VeriTask) -> list[str]:
    """Return the run-resolved public IDs, falling back to repository repair v1."""

    feedback = task.metadata.get("agent_feedback_contract")
    if isinstance(feedback, dict):
        values = feedback.get("public_test_ids")
        if isinstance(values, list) and all(isinstance(value, str) for value in values):
            return list(values)
        raise ValueError("resolved AgentEval public-test identity is malformed")
    repository = task.metadata.get("repository_repair")
    values = repository.get("public_test_ids") if isinstance(repository, dict) else []
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        return []
    return sorted(values)


class AgentFeedbackController:
    """Serial candidate feedback executor shared by typed and external agents."""

    def __init__(
        self,
        *,
        contract: AgentFeedbackContract,
        task: VeriTask,
        runtime: Runtime,
        profile: ToolchainProfile | None,
        resolved_profile: ResolvedToolchainProfile | None,
        backend: SynthesisBackendPlugin | None,
    ) -> None:
        self.contract = contract
        self._task = task
        self._runtime = runtime
        self._profile = profile
        self._resolved_profile = resolved_profile
        self._backend = backend
        self._compile_passed_hash: str | None = None
        self._ppa_executions = 0
        self._cache: dict[
            tuple[str, str], tuple[AgentFeedbackCategory, AgentFeedbackMetrics | None]
        ] = {}
        self._evaluations: list[AgentFeedbackEvaluation] = []
        self._lock = threading.Lock()

    @property
    def evaluations(self) -> list[AgentFeedbackEvaluation]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._evaluations]

    def execute(self, test_id: str, session: RuntimeSession) -> CompletedCommand:
        with self._lock:
            candidate_hash = hash_directory(
                session.root,
                excluded_names={".verigym_internal"},
            )
            if test_id == self.contract.compile_test_id:
                started = time.monotonic()
                completed = session.execute_public_test(test_id)
                infrastructure = _compile_infrastructure_failure(completed)
                passed = completed.exit_code == 0 and not infrastructure
                self._compile_passed_hash = candidate_hash if passed else None
                category: AgentFeedbackCategory = (
                    "passed"
                    if passed
                    else "infrastructure_error"
                    if infrastructure
                    else "compile_failed"
                )
                self._record(
                    test_id=test_id,
                    candidate_hash=candidate_hash,
                    profile_hash=None,
                    cache_hit=False,
                    synthesis_executed=False,
                    duration_s=time.monotonic() - started,
                    category=category,
                    metrics=None,
                )
                update: dict[str, Any] = {
                    "metadata": {
                        **completed.metadata,
                        "agent_feedback_protocol": "agent_feedback_contract.v1",
                        "candidate_hash": candidate_hash,
                    }
                }
                if infrastructure:
                    update.update(
                        failure_origin="control_plane",
                        failure_reason=completed.failure_reason or "agent_compile_infrastructure",
                    )
                return completed.model_copy(update=update)
            if test_id != self.contract.ppa_test_id:
                return self._feedback_command(
                    test_id=test_id,
                    candidate_hash=candidate_hash,
                    category="ppa_disabled",
                    metrics=None,
                    cache_hit=False,
                    synthesis_executed=False,
                    started=time.monotonic(),
                )
            started = time.monotonic()
            profile_hash = self.contract.resolved_profile_hash
            assert profile_hash is not None
            if self._compile_passed_hash != candidate_hash:
                return self._feedback_command(
                    test_id=test_id,
                    candidate_hash=candidate_hash,
                    category="compile_required",
                    metrics=None,
                    cache_hit=False,
                    synthesis_executed=False,
                    started=started,
                    profile_hash=profile_hash,
                )
            key = (candidate_hash, profile_hash)
            cached = self._cache.get(key)
            if cached is not None:
                category, metrics = cached
                return self._feedback_command(
                    test_id=test_id,
                    candidate_hash=candidate_hash,
                    category=category,
                    metrics=metrics,
                    cache_hit=True,
                    synthesis_executed=False,
                    started=started,
                    profile_hash=profile_hash,
                )
            if self._ppa_executions >= self.contract.ppa_max_executions:
                return self._feedback_command(
                    test_id=test_id,
                    candidate_hash=candidate_hash,
                    category="ppa_quota_exhausted",
                    metrics=None,
                    cache_hit=False,
                    synthesis_executed=False,
                    started=started,
                    profile_hash=profile_hash,
                )
            assert self._profile is not None
            assert self._resolved_profile is not None
            assert self._backend is not None
            self._ppa_executions += 1
            try:
                result, raw_metrics = execute_candidate_synthesis_feedback(
                    task=self._task,
                    candidate_dir=session.root,
                    runtime=self._runtime,
                    profile=self._profile,
                    resolved=self._resolved_profile,
                    plugin=self._backend,
                )
            except Exception:
                return self._feedback_command(
                    test_id=test_id,
                    candidate_hash=candidate_hash,
                    category="infrastructure_error",
                    metrics=None,
                    cache_hit=False,
                    synthesis_executed=True,
                    started=started,
                    profile_hash=profile_hash,
                    infrastructure=True,
                )
            if result.status == VerifierStatus.PASSED and raw_metrics.synthesis_ok:
                metrics = AgentFeedbackMetrics(
                    area=raw_metrics.mapped_area_raw,
                    area_unit=raw_metrics.mapped_area_unit,
                    maximum_path_delay=raw_metrics.critical_path_delay_raw,
                    worst_negative_slack=raw_metrics.worst_negative_slack_raw,
                    timing_unit=raw_metrics.timing_unit,
                    power=raw_metrics.total_power_raw,
                    power_unit=raw_metrics.power_unit,
                )
                category = "passed"
            elif result.status == VerifierStatus.FAILED:
                metrics = None
                category = "synthesis_failed"
            else:
                return self._feedback_command(
                    test_id=test_id,
                    candidate_hash=candidate_hash,
                    category="infrastructure_error",
                    metrics=None,
                    cache_hit=False,
                    synthesis_executed=True,
                    started=started,
                    profile_hash=profile_hash,
                    infrastructure=True,
                )
            self._cache[key] = (category, metrics)
            return self._feedback_command(
                test_id=test_id,
                candidate_hash=candidate_hash,
                category=category,
                metrics=metrics,
                cache_hit=False,
                synthesis_executed=True,
                started=started,
                profile_hash=profile_hash,
            )

    def _feedback_command(
        self,
        *,
        test_id: str,
        candidate_hash: str,
        category: AgentFeedbackCategory,
        metrics: AgentFeedbackMetrics | None,
        cache_hit: bool,
        synthesis_executed: bool,
        started: float,
        profile_hash: str | None = None,
        infrastructure: bool = False,
    ) -> CompletedCommand:
        duration = time.monotonic() - started
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "protocol": "verigym_agent_feedback_v1",
            "test_id": test_id,
            "passed": category == "passed",
            "category": category,
            "candidate_hash": candidate_hash,
            "profile_hash": profile_hash,
            "cache_hit": cache_hit,
            "duration_s": duration,
            "candidate_metrics": metrics.model_dump(mode="json") if metrics else None,
        }
        self._record(
            test_id=test_id,
            candidate_hash=candidate_hash,
            profile_hash=profile_hash,
            cache_hit=cache_hit,
            synthesis_executed=synthesis_executed,
            duration_s=duration,
            category=category,
            metrics=metrics,
        )
        return CompletedCommand(
            argv=["verigym-agent-feedback", test_id],
            cwd=".",
            exit_code=0 if category == "passed" else 1,
            stdout=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            duration_s=duration,
            failure_reason=(category if category != "passed" else None),
            failure_origin=(
                "control_plane"
                if infrastructure
                else ("candidate_process" if category != "passed" else None)
            ),
            runtime_role="agent_feedback",
            metadata={
                "agent_feedback_protocol": "verigym_agent_feedback_v1",
                "network_policy": "none",
                "public_assets_read_only": True,
            },
        )

    def _record(
        self,
        *,
        test_id: str,
        candidate_hash: str,
        profile_hash: str | None,
        cache_hit: bool,
        synthesis_executed: bool,
        duration_s: float,
        category: AgentFeedbackCategory,
        metrics: AgentFeedbackMetrics | None,
    ) -> None:
        identity = {
            "test_id": test_id,
            "candidate_hash": candidate_hash,
            "profile_hash": profile_hash,
            "cache_hit": cache_hit,
            "synthesis_executed": synthesis_executed,
            "category": category,
            "passed": category == "passed",
            "metrics": metrics.model_dump(mode="json") if metrics else None,
        }
        self._evaluations.append(
            AgentFeedbackEvaluation(
                sequence=len(self._evaluations),
                test_id=test_id,
                candidate_hash=candidate_hash,
                profile_hash=profile_hash,
                cache_hit=cache_hit,
                synthesis_executed=synthesis_executed,
                duration_s=duration_s,
                category=category,
                passed=category == "passed",
                metrics=metrics,
                observation_hash=content_hash(identity),
            )
        )


def _compile_infrastructure_failure(completed: CompletedCommand) -> bool:
    if completed.failure_origin == "control_plane" or completed.error is not None:
        return True
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(payload, dict) or payload.get("protocol") != "verigym_public_test_v1":
        return False
    commands = payload.get("commands")
    return bool(
        isinstance(commands, list)
        and any(
            isinstance(command, dict)
            and command.get("category") == "command_failed"
            and command.get("exit_code") is None
            for command in commands
        )
    )


__all__ = [
    "AgentFeedbackController",
    "public_feedback_test_ids",
    "resolve_agent_feedback_contract",
    "task_with_agent_feedback_contract",
]
