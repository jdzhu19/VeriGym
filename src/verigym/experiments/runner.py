"""Sequential-by-default and bounded-parallel experiment execution."""

from __future__ import annotations

import json
import os
import re
import stat
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from verigym.core.agent_feedback import (
    resolve_agent_feedback_contract,
    task_with_agent_feedback_contract,
)
from verigym.core.errors import (
    ArtifactIntegrityError,
    ConfigurationError,
    MissingDependencyError,
    RuntimeExecutionError,
    VeriGymError,
)
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.integrity import (
    remove_artifact_manifest,
    verify_artifact_manifest,
    write_experiment_artifact_manifest,
)
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.core.sampling import classify_sample_outcome
from verigym.core.verifier_profiles import (
    resolve_verifier_profile,
    task_with_verifier_profile,
)
from verigym.experiments.identity import plan_items_hash_payload
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.schemas import (
    BatchEvent,
    BatchResult,
    ExperimentConfig,
    ExperimentManifest,
    ExperimentPlan,
    ExperimentState,
    ModelProcessLedgerRecord,
    PlanItem,
    RunIndexRecord,
)
from verigym.experiments.state import (
    atomic_dump_json,
    atomic_dump_jsonl,
    atomic_write_text,
    load_json_model,
    load_jsonl_models,
)
from verigym.prompts.policy import (
    agent_configuration_hash,
    resolve_prompt_policy,
    validate_prompt_policy_binding,
)
from verigym.protocols.repository_action import (
    resolve_repository_action_protocol,
    validate_repository_action_protocol_binding,
)
from verigym.reporting.loader import load_report_inputs, validate_plan_binding
from verigym.reporting.service import ReportService
from verigym.schemas.external_agent import ExternalProcessResult
from verigym.schemas.run import RunConfig, RunManifest, RunResult
from verigym.schemas.sampling import SampleOutcome

ChildExecutor = Callable[[PlanItem, RunConfig], RunResult]


class _ParentArtifacts:
    def __init__(
        self,
        root: Path,
        manifest: ExperimentManifest,
        state: ExperimentState,
        *,
        events: list[BatchEvent] | None = None,
        records: list[RunIndexRecord] | None = None,
        process_ledger: list[ModelProcessLedgerRecord] | None = None,
        checkpoints: list[dict[str, object]] | None = None,
    ) -> None:
        self.root = root
        self.manifest = manifest
        self.state = state
        self.events = events or []
        self.records = records or []
        self.process_ledger = process_ledger or []
        self.checkpoints = checkpoints or []
        self.log_lines: list[str] = []
        self.lock = threading.Lock()

    def event(
        self,
        event_type: str,
        *,
        item: PlanItem | None = None,
        attempt: int | None = None,
        detail: dict[str, object] | None = None,
    ) -> None:
        with self.lock:
            event = BatchEvent(
                sequence=len(self.events),
                timestamp_utc=datetime.now(UTC),
                event_type=event_type,  # type: ignore[arg-type]
                experiment_id=self.manifest.experiment_id,
                plan_index=item.plan_index if item is not None else None,
                plan_item_id=item.plan_item_id if item is not None else None,
                attempt=attempt,
                detail=detail or {},
            )
            self.events.append(event)
            self.state = self.state.model_copy(update={"last_event_sequence": event.sequence})
            atomic_dump_jsonl(self.root / "events.jsonl", self.events)
            atomic_dump_json(self.root / "state.json", self.state)

    def scheduled(self, item: PlanItem, attempt: int) -> None:
        with self.lock:
            self.state = self.state.model_copy(
                update={"scheduled_count": self.state.scheduled_count + 1}
            )
            atomic_dump_json(self.root / "state.json", self.state)
        self.event("plan_item_scheduled", item=item, attempt=attempt)

    def started(self, item: PlanItem, attempt: int) -> None:
        with self.lock:
            active = self.state.active_count + 1
            self.state = self.state.model_copy(
                update={
                    "active_count": active,
                    "observed_max_concurrency": max(self.state.observed_max_concurrency, active),
                }
            )
            atomic_dump_json(self.root / "state.json", self.state)
        self.event("plan_item_started", item=item, attempt=attempt)

    def terminal(self, item: PlanItem, record: RunIndexRecord) -> None:
        with self.lock:
            self.records.append(record)
            self.state = self.state.model_copy(
                update={
                    "active_count": max(0, self.state.active_count - 1),
                    "terminal_count": self.state.terminal_count + 1,
                    "valid_terminal_count": self.state.valid_terminal_count
                    + int(record.artifact_validation_status == "valid"),
                    "infrastructure_error_count": self.state.infrastructure_error_count
                    + int(record.infrastructure_error),
                    "corrupt_attempt_count": self.state.corrupt_attempt_count
                    + int(
                        record.artifact_validation_status in {"partial", "corrupt", "incompatible"}
                    ),
                    "observed_model_api_call_count": (
                        self.state.observed_model_api_call_count + record.model_api_call_count
                    ),
                }
            )
            atomic_dump_jsonl(self.root / "run_index.jsonl", self.records)
            atomic_dump_json(self.root / "state.json", self.state)
        self.event(
            "plan_item_terminal",
            item=item,
            attempt=record.attempt,
            detail={
                "status": record.terminal_status,
                "artifact_validation_status": record.artifact_validation_status,
                "infrastructure_error": record.infrastructure_error,
            },
        )

    def authorize_model_process(
        self,
        item: PlanItem,
        attempt: int,
        *,
        resume: bool,
        maximum: int | None,
        maximum_api_calls: int | None,
    ) -> ModelProcessLedgerRecord | None:
        reason = _model_bearing_reason(item)
        if reason is None:
            return None
        with self.lock:
            if any(record.plan_index == item.plan_index for record in self.process_ledger):
                raise ConfigurationError(
                    f"plan item {item.plan_index} already consumed a model-process authorization"
                )
            if maximum is not None and len(self.process_ledger) >= maximum:
                raise ConfigurationError("campaign-wide model-process budget is exhausted")
            reserved_api_calls = _maximum_model_api_calls(item)
            authorized_api_calls = sum(
                record.maximum_model_api_calls or 0 for record in self.process_ledger
            )
            if (
                maximum_api_calls is not None
                and authorized_api_calls + reserved_api_calls > maximum_api_calls
            ):
                raise ConfigurationError("campaign-wide model API-call budget is exhausted")
            requested_model = item.system.model_id
            if requested_model is None:
                value = item.system.agent_options.get("model_id")
                requested_model = value if isinstance(value, str) else None
            record = ModelProcessLedgerRecord(
                ordinal=len(self.process_ledger) + 1,
                timestamp_utc=datetime.now(UTC),
                experiment_id=self.manifest.experiment_id,
                plan_index=item.plan_index,
                plan_item_id=item.plan_item_id,
                attempt=attempt,
                task_id=item.task_id,
                system_id=item.system.system_id,
                base_seed=item.base_seed,
                sample_index=item.sample_index,
                model_bearing_reason=reason,
                requested_model_id=requested_model,
                model_api_call_budget_policy="reserved_max_calls_v1",
                maximum_model_api_calls=reserved_api_calls,
                resume=resume,
            )
            _append_jsonl_record(self.root / "process-ledger.jsonl", record)
            self.process_ledger.append(record)
            self.state = self.state.model_copy(
                update={
                    "authorized_model_process_count": len(self.process_ledger),
                    "authorized_model_api_call_budget": (authorized_api_calls + reserved_api_calls),
                }
            )
            atomic_dump_json(self.root / "state.json", self.state)
        self.event(
            "model_process_authorized",
            item=item,
            attempt=attempt,
            detail={
                "ordinal": record.ordinal,
                "model_bearing_reason": record.model_bearing_reason,
                "retry": False,
                "resume": resume,
                "maximum_model_api_calls": record.maximum_model_api_calls,
            },
        )
        return record

    def checkpoint(self, *, reason: str) -> None:
        record: dict[str, object] = {
            "schema_version": "1.0",
            "sequence": len(self.checkpoints),
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "reason": reason,
            "planned_count": self.state.planned_count,
            "scheduled_count": self.state.scheduled_count,
            "terminal_count": self.state.terminal_count,
            "valid_terminal_count": self.state.valid_terminal_count,
            "infrastructure_error_count": self.state.infrastructure_error_count,
            "authorized_model_process_count": self.state.authorized_model_process_count,
            "authorized_model_api_call_budget": self.state.authorized_model_api_call_budget,
            "observed_model_api_call_count": self.state.observed_model_api_call_count,
            "active_count": self.state.active_count,
        }
        _append_jsonl_record(self.root / "summary-checkpoints.jsonl", record)
        self.checkpoints.append(record)
        self.event(
            "execution_checkpoint",
            detail={
                "checkpoint_sequence": record["sequence"],
                "reason": reason,
                "terminal_count": self.state.terminal_count,
            },
        )

    def replace_record(self, old: RunIndexRecord, new: RunIndexRecord) -> None:
        with self.lock:
            index = self.records.index(old)
            self.records[index] = new
            corrupt_states = {"partial", "corrupt", "incompatible"}
            self.state = self.state.model_copy(
                update={
                    "valid_terminal_count": self.state.valid_terminal_count
                    - int(old.artifact_validation_status == "valid")
                    + int(new.artifact_validation_status == "valid"),
                    "infrastructure_error_count": self.state.infrastructure_error_count
                    - int(old.infrastructure_error)
                    + int(new.infrastructure_error),
                    "corrupt_attempt_count": self.state.corrupt_attempt_count
                    - int(old.artifact_validation_status in corrupt_states)
                    + int(new.artifact_validation_status in corrupt_states),
                    "observed_model_api_call_count": (
                        self.state.observed_model_api_call_count
                        - old.model_api_call_count
                        + new.model_api_call_count
                    ),
                }
            )
            atomic_dump_jsonl(self.root / "run_index.jsonl", self.records)
            atomic_dump_json(self.root / "state.json", self.state)

    def set_status(self, status: str) -> None:
        with self.lock:
            self.manifest = self.manifest.model_copy(update={"status": status})
            self.state = self.state.model_copy(update={"status": status, "active_count": 0})
            atomic_dump_json(self.root / "experiment_manifest.json", self.manifest)
            atomic_dump_json(self.root / "state.json", self.state)

    def log(self, message: str) -> None:
        clean = "".join(
            character if ord(character) >= 32 or character == "\t" else " " for character in message
        )[:2048]
        with self.lock:
            self.log_lines.append(clean)
            atomic_write_text(self.root / "logs" / "batch.log", "\n".join(self.log_lines) + "\n")


class BatchRunner:
    """Execute immutable plan items through the ordinary ``VeriGym.run`` service."""

    def __init__(
        self,
        *,
        planner: ExperimentPlanner | None = None,
        report_service: ReportService | None = None,
        child_executor: ChildExecutor | None = None,
        service_factory: Callable[[], VeriGym] | None = None,
    ) -> None:
        self.planner = planner or ExperimentPlanner()
        self.report_service = report_service or ReportService()
        self.service_factory = service_factory or VeriGym
        self.child_executor = child_executor or self._ordinary_child

    def run(self, plan: ExperimentPlan) -> BatchResult:
        self.planner.verify_frozen_inputs(plan)
        _validate_execution_plan(plan)
        root = _prepare_new_root(plan.config.output.root)
        parent = self._initialize(plan, root)
        return self._execute(plan, parent, completed=set())

    def prepare(self, plan: ExperimentPlan) -> Path:
        """Persist and optionally seal an immutable plan without executing a child."""

        self.planner.verify_frozen_inputs(plan)
        _validate_execution_plan(plan)
        root = _prepare_new_root(plan.config.output.root)
        self._initialize(plan, root)
        return root

    def resume(
        self,
        root: Path,
        *,
        supplied_config: ExperimentConfig | None = None,
    ) -> BatchResult:
        experiment_root = _existing_root(root)
        _validate_parent_directories(experiment_root)
        try:
            verify_artifact_manifest(experiment_root, expected_scope="experiment")
        except ArtifactIntegrityError as exc:
            # Linked children are checked again by replay, where the established
            # resume policy preserves and replaces corrupt attempts.
            if "runs/" not in str(exc):
                raise
        manifest = load_json_model(experiment_root / "experiment_manifest.json", ExperimentManifest)
        stored_config = load_json_model(
            experiment_root / "experiment_config.json", ExperimentConfig
        )
        config = stored_config.model_copy(
            update={"output": stored_config.output.model_copy(update={"root": experiment_root})}
        )
        if (
            supplied_config is not None
            and content_hash(supplied_config.identity_payload()) != manifest.config_hash
        ):
            raise ConfigurationError("resume configuration hash differs from the stored experiment")
        items = load_jsonl_models(experiment_root / "plan.jsonl", PlanItem)
        if content_hash(plan_items_hash_payload(items)) != manifest.plan_hash:
            raise ConfigurationError("stored plan hash differs from experiment_manifest.json")
        plan = ExperimentPlan(
            experiment_id=manifest.experiment_id,
            config_hash=manifest.config_hash,
            evaluation_config_hash=manifest.evaluation_config_hash,
            task_set_hash=manifest.task_set_hash,
            source_identity_hash=manifest.source_identity_hash,
            plan_hash=manifest.plan_hash,
            verigym_version=manifest.verigym_version,
            verigym_commit=manifest.verigym_commit,
            build_provenance=manifest.build_provenance,
            config=config,
            items=items,
        )
        self.planner.verify_frozen_inputs(plan)
        _validate_execution_plan(plan)
        events = (
            load_jsonl_models(experiment_root / "events.jsonl", BatchEvent)
            if (experiment_root / "events.jsonl").is_file()
            else []
        )
        records = (
            load_jsonl_models(experiment_root / "run_index.jsonl", RunIndexRecord)
            if (experiment_root / "run_index.jsonl").is_file()
            else []
        )
        process_ledger = (
            load_jsonl_models(
                experiment_root / "process-ledger.jsonl",
                ModelProcessLedgerRecord,
            )
            if (experiment_root / "process-ledger.jsonl").is_file()
            else []
        )
        _validate_process_ledger(plan, process_ledger)
        checkpoints = _load_checkpoint_records(experiment_root / "summary-checkpoints.jsonl")
        state = load_json_model(experiment_root / "state.json", ExperimentState)
        state = _recovered_state(plan, manifest, state, events, records)
        state = state.model_copy(
            update={
                "authorized_model_process_count": len(process_ledger),
                "authorized_model_api_call_budget": sum(
                    record.maximum_model_api_calls
                    for record in process_ledger
                    if record.maximum_model_api_calls is not None
                ),
                "observed_model_api_call_count": sum(
                    record.model_api_call_count for record in records
                ),
            }
        )
        parent = _ParentArtifacts(
            experiment_root,
            manifest,
            state,
            events=events,
            records=records,
            process_ledger=process_ledger,
            checkpoints=checkpoints,
        )
        self._reconcile_unindexed_children(plan, parent)
        completed = self._validate_resume_children(plan, parent)
        return self._execute(plan, parent, completed=completed, resume=True)

    def _initialize(self, plan: ExperimentPlan, root: Path) -> _ParentArtifacts:
        (root / "runs").mkdir()
        (root / "logs").mkdir()
        (root / "reports").mkdir()
        persisted_config = plan.config.model_copy(
            update={"output": plan.config.output.model_copy(update={"root": Path(".")})}
        )
        system_identities = []
        seen_systems: set[str] = set()
        runtime_identities = []
        seen_runtimes: set[str] = set()
        for item in plan.items:
            if item.system.system_id not in seen_systems:
                system_identities.append(item.system)
                seen_systems.add(item.system.system_id)
            if item.runtime_identity_hash not in seen_runtimes:
                runtime_identities.append(item.runtime_descriptor)
                seen_runtimes.add(item.runtime_identity_hash)
        manifest = ExperimentManifest(
            experiment_id=plan.experiment_id,
            created_at_utc=datetime.now(UTC),
            config_hash=plan.config_hash,
            evaluation_config_hash=plan.evaluation_config_hash,
            plan_hash=plan.plan_hash,
            task_set_hash=plan.task_set_hash,
            source_identity_hash=plan.source_identity_hash,
            suite_id=plan.config.suite.id,
            suite_versions=sorted({item.suite_version for item in plan.items}),
            release_ids=sorted(
                {item.release_id for item in plan.items if item.release_id is not None}
            ),
            suite_source_snapshots=sorted(
                {
                    item.suite_source_snapshot.model_dump_json(): item.suite_source_snapshot
                    for item in plan.items
                    if item.suite_source_snapshot is not None
                }.values(),
                key=lambda snapshot: snapshot.configuration_fingerprint,
            ),
            verigym_version=plan.verigym_version,
            verigym_commit=plan.verigym_commit,
            build_provenance=plan.build_provenance,
            selected_task_count=len({item.task_id for item in plan.items}),
            planned_item_count=len(plan.items),
            system_identities=system_identities,
            runtime_identities=runtime_identities,
            resolved_profile_hashes=sorted(
                {item.resolved_profile_hash for item in plan.items if item.resolved_profile_hash}
            ),
            sampling_policy=plan.config.runs,
            execution_policy=plan.config.execution,
            artifact_locations={
                "config": "experiment_config.json",
                "plan": "plan.jsonl",
                "events": "events.jsonl",
                "state": "state.json",
                "run_index": "run_index.jsonl",
                "process_ledger": "process-ledger.jsonl",
                "summary_checkpoints": "summary-checkpoints.jsonl",
                "plan_audit": "plan-audit.json",
                "normalized_config": "normalized-config.json",
                "runs": "runs",
                "reports": "reports",
            },
            status="planned",
        )
        state = ExperimentState(
            experiment_id=plan.experiment_id,
            config_hash=plan.config_hash,
            plan_hash=plan.plan_hash,
            status="planned",
            planned_count=len(plan.items),
        )
        atomic_dump_json(root / "experiment_config.json", persisted_config)
        atomic_dump_json(root / "normalized-config.json", plan.config.identity_payload())
        atomic_dump_jsonl(root / "plan.jsonl", plan.items)
        atomic_dump_json(root / "plan-audit.json", _plan_audit(plan, root / "plan.jsonl"))
        atomic_dump_json(root / "experiment_manifest.json", manifest)
        atomic_dump_json(root / "state.json", state)
        atomic_dump_jsonl(root / "events.jsonl", [])
        atomic_dump_jsonl(root / "run_index.jsonl", [])
        _create_append_only_ledger(root / "process-ledger.jsonl")
        _create_append_only_ledger(root / "summary-checkpoints.jsonl")
        atomic_write_text(root / "logs" / "batch.log", "")
        if plan.config.execution.seal_plan_before_execution:
            mode = stat.S_IMODE(os.lstat(root / "plan.jsonl").st_mode)
            os.chmod(root / "plan.jsonl", mode & ~0o222)
        return _ParentArtifacts(root, manifest, state)

    def _execute(
        self,
        plan: ExperimentPlan,
        parent: _ParentArtifacts,
        *,
        completed: set[int],
        resume: bool = False,
    ) -> BatchResult:
        remove_artifact_manifest(parent.root)
        parent.set_status("running")
        parent.event(
            "experiment_started",
            detail={"resume": resume, "remaining": len(plan.items) - len(completed)},
        )
        pending = [item for item in plan.items if item.plan_index not in completed]
        if not plan.config.execution.continue_on_infrastructure_error and any(
            record.infrastructure_error and record.artifact_validation_status == "valid"
            for record in _latest_records(parent.records).values()
        ):
            pending = []
        attempts = {
            item.plan_index: max(
                (
                    record.attempt
                    for record in parent.records
                    if record.plan_index == item.plan_index
                ),
                default=0,
            )
            + 1
            for item in pending
        }
        internal_failures = 0
        breaker_reason = _circuit_breaker_reason(parent.records, plan)
        if breaker_reason is not None:
            parent.event(
                "circuit_breaker_opened",
                detail={"reason": breaker_reason, "before_scheduling": True},
            )
            pending = []
        try:
            if plan.config.execution.max_workers == 1:
                for item in pending:
                    _assert_persisted_plan(parent.root, plan)
                    record, internal = self._run_item(
                        parent,
                        item,
                        attempts[item.plan_index],
                        resume=resume,
                    )
                    internal_failures += int(internal)
                    interval = plan.config.execution.summary_checkpoint_interval
                    if interval is not None and parent.state.terminal_count % interval == 0:
                        parent.checkpoint(reason=f"terminal_interval_{interval}")
                    if internal:
                        break
                    if (
                        record.infrastructure_error
                        and not plan.config.execution.continue_on_infrastructure_error
                    ):
                        break
                    breaker_reason = _circuit_breaker_reason(parent.records, plan)
                    if breaker_reason is not None:
                        parent.event(
                            "circuit_breaker_opened",
                            item=item,
                            attempt=record.attempt,
                            detail={"reason": breaker_reason},
                        )
                        break
            else:
                internal_failures += self._run_parallel(
                    plan,
                    parent,
                    pending,
                    attempts,
                    resume=resume,
                )
        except KeyboardInterrupt:
            parent.set_status("interrupted")
            parent.event("experiment_interrupted", detail={"reason": "keyboard_interrupt"})
            raise
        except ConfigurationError as exc:
            parent.log(f"experiment configuration drift: {exc}")
            parent.set_status("failed_configuration")
            raise
        infrastructure_failures = sum(
            record.infrastructure_error for record in _latest_records(parent.records).values()
        )
        if plan.config.execution.summary_checkpoint_interval is not None and (
            not parent.checkpoints
            or parent.checkpoints[-1].get("terminal_count") != parent.state.terminal_count
        ):
            parent.checkpoint(reason="execution_terminal")
        if internal_failures:
            status = "failed_internal"
            exit_code = 5
        elif infrastructure_failures:
            status = "completed_with_infrastructure_errors"
            exit_code = 4
        else:
            status = "completed"
            exit_code = 0
        parent.set_status(status)
        parent.event("report_started")
        try:
            reports = self.report_service.generate_all(parent.root)
            parent.event("report_completed", detail={"hashes": reports.hashes})
        except Exception as exc:
            parent.log(f"report generation failed: {type(exc).__name__}: {exc}")
            parent.set_status("failed_internal")
            return BatchResult(
                experiment_dir=parent.root,
                manifest=parent.manifest,
                state=parent.state,
                infrastructure_failures=infrastructure_failures,
                internal_failures=internal_failures + 1,
                exit_code=5,
            )
        parent.event(
            "experiment_completed",
            detail={
                "status": status,
                "infrastructure_failures": infrastructure_failures,
            },
        )
        write_experiment_artifact_manifest(parent.root, parent.manifest.experiment_id)
        return BatchResult(
            experiment_dir=parent.root,
            manifest=parent.manifest,
            state=parent.state,
            infrastructure_failures=infrastructure_failures,
            internal_failures=internal_failures,
            exit_code=exit_code,
        )

    def _run_parallel(
        self,
        plan: ExperimentPlan,
        parent: _ParentArtifacts,
        pending: list[PlanItem],
        attempts: dict[int, int],
        *,
        resume: bool,
    ) -> int:
        internal_failures = 0
        iterator = iter(pending)
        futures: dict[Future[tuple[RunIndexRecord, bool]], PlanItem] = {}
        stop = False
        with ThreadPoolExecutor(
            max_workers=plan.config.execution.max_workers,
            thread_name_prefix="verigym-batch",
        ) as executor:
            try:
                for _ in range(min(plan.config.execution.max_workers, len(pending))):
                    item = next(iterator, None)
                    if item is not None:
                        future = executor.submit(
                            self._run_item,
                            parent,
                            item,
                            attempts[item.plan_index],
                            resume,
                        )
                        futures[future] = item
                while futures:
                    done, _not_done = wait(futures, return_when=FIRST_COMPLETED)
                    for future in sorted(done, key=lambda value: futures[value].plan_index):
                        item = futures.pop(future)
                        if future.cancelled():
                            continue
                        record, internal = future.result()
                        internal_failures += int(internal)
                        stop = (
                            stop
                            or internal
                            or (
                                record.infrastructure_error
                                and not plan.config.execution.continue_on_infrastructure_error
                            )
                        )
                        if not stop:
                            next_item = next(iterator, None)
                            if next_item is not None:
                                next_future = executor.submit(
                                    self._run_item,
                                    parent,
                                    next_item,
                                    attempts[next_item.plan_index],
                                    resume,
                                )
                                futures[next_future] = next_item
                    if stop:
                        for future in futures:
                            future.cancel()
            except BaseException:
                for future in futures:
                    future.cancel()
                raise
        return internal_failures

    def _run_item(
        self,
        parent: _ParentArtifacts,
        item: PlanItem,
        attempt: int,
        resume: bool = False,
    ) -> tuple[RunIndexRecord, bool]:
        parent.scheduled(item, attempt)
        parent.started(item, attempt)
        run_id = _child_run_id(item, attempt)
        config = _child_config(
            parent.root,
            item,
            run_id,
            parent.manifest.experiment_id,
        )
        try:
            config = self._resolve_child_execution_contract(item, config)
            parent.authorize_model_process(
                item,
                attempt,
                resume=resume,
                maximum=parent.manifest.execution_policy.max_model_processes,
                maximum_api_calls=parent.manifest.execution_policy.max_model_api_calls,
            )
            result = self.child_executor(item, config)
            if (
                parent.manifest.execution_policy.resume_model_process_policy
                == "never_rerun_after_authorization"
            ):
                _validate_model_process_result(item, result)
            validate_plan_binding(result.manifest, result.scorecard, item)
            expected = (parent.root / "runs" / run_id).resolve(strict=True)
            if result.run_dir.resolve(strict=True) != expected:
                raise ConfigurationError("child orchestrator returned an unexpected run path")
            record = _record_from_result(parent.root, item, attempt, result)
            parent.terminal(item, record)
            return record, False
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            relative = f"runs/{run_id}"
            path = parent.root / relative
            exists = path.is_dir()
            if isinstance(exc, ConfigurationError):
                record = RunIndexRecord(
                    plan_index=item.plan_index,
                    plan_item_id=item.plan_item_id,
                    attempt=attempt,
                    child_run_id=run_id if exists else None,
                    relative_child_path=relative if exists else None,
                    terminal_status="incompatible",
                    resolved=False,
                    evaluable=False,
                    infrastructure_error=False,
                    child_exit_category="configuration_drift",
                    artifact_validation_status="incompatible" if exists else "missing",
                    message=f"{type(exc).__name__}: {exc}"[:1024],
                )
                parent.log(
                    f"plan[{item.plan_index}] attempt {attempt}: {type(exc).__name__}: {exc}"
                )
                parent.terminal(item, record)
                raise
            infrastructure, internal = _exception_class(exc)
            record = RunIndexRecord(
                plan_index=item.plan_index,
                plan_item_id=item.plan_item_id,
                attempt=attempt,
                child_run_id=run_id if exists else None,
                relative_child_path=relative if exists else None,
                terminal_status="failed_internal" if internal else "infrastructure_error",
                resolved=False,
                evaluable=False,
                infrastructure_error=infrastructure,
                child_exit_category=("internal_verigym_error" if internal else type(exc).__name__),
                artifact_validation_status="partial" if exists else "missing",
                message=f"{type(exc).__name__}: {exc}"[:1024],
            )
            parent.log(f"plan[{item.plan_index}] attempt {attempt}: {type(exc).__name__}: {exc}")
            parent.terminal(item, record)
            return record, internal

    def _resolve_child_execution_contract(
        self,
        item: PlanItem,
        config: RunConfig,
    ) -> RunConfig:
        """Resolve execution-owned bindings before model-process authorization."""

        service = self.planner.service
        _, task, _ = service.load_task(item.task_id, item.suite_source)
        if config.verifier_profile is not None:
            resolved_verifier = resolve_verifier_profile(
                task=task,
                profile=config.verifier_profile,
                tools=service.registries.tools,
                expected=config.expected_resolved_verifier_profile,
            )
            if resolved_verifier != item.resolved_verifier_profile:
                raise ConfigurationError("verifier profile differs from frozen plan")
            task = task_with_verifier_profile(task, config.verifier_profile)
        profile = (
            service.registries.profiles.get(config.toolchain_profile)
            if config.toolchain_profile is not None
            else None
        )
        feedback_contract = resolve_agent_feedback_contract(
            task=task,
            ppa_enabled=config.agent_ppa_feedback,
            ppa_max_executions=config.agent_ppa_max_calls,
            resolved_profile=item.resolved_profile,
            profile_backend=(
                profile.flow.backend_plugin
                if profile is not None and profile.flow is not None
                else None
            ),
        )
        if feedback_contract != item.agent_feedback_contract:
            raise ConfigurationError("agent feedback contract differs from frozen plan")
        execution_task = task_with_agent_feedback_contract(task, feedback_contract)
        agent = service.registries.agents.get(item.system.agent_id)
        actual_agent_hash = agent_configuration_hash(agent.descriptor, config.agent_options)
        if actual_agent_hash != item.system.agent_configuration_hash:
            raise ConfigurationError("agent execution configuration differs from frozen plan")
        try:
            resolved_prompt = resolve_prompt_policy(
                interaction_mode=config.mode,
                agent=agent,
                agent_options=config.agent_options,
                task=execution_task,
            )
            resolved_prompt_hash = (
                resolved_prompt.configuration_fingerprint if resolved_prompt is not None else None
            )
            validate_prompt_policy_binding(
                expected=item.prompt_policy,
                expected_hash=item.prompt_policy_hash,
                resolved=resolved_prompt,
                resolved_hash=resolved_prompt_hash,
            )
            resolved_action_protocol = resolve_repository_action_protocol(
                agent_descriptor=agent.descriptor,
                protocol_spec=agent.action_protocol_spec,
                agent_options=config.agent_options,
                task=execution_task,
            )
            validate_repository_action_protocol_binding(
                expected=item.action_protocol,
                resolved=resolved_action_protocol,
            )
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc
        return config.model_copy(
            update={
                "resolved_prompt_policy": resolved_prompt,
                "resolved_prompt_policy_hash": resolved_prompt_hash,
                "resolved_agent_configuration_hash": actual_agent_hash,
                "resolved_action_protocol": resolved_action_protocol,
                "resolved_agent_feedback_contract": feedback_contract,
            }
        )

    def _ordinary_child(self, item: PlanItem, config: RunConfig) -> RunResult:
        del item
        return self.service_factory().run(config)

    def _reconcile_unindexed_children(
        self,
        plan: ExperimentPlan,
        parent: _ParentArtifacts,
    ) -> None:
        """Recover complete or bound-partial children created before an index write."""

        runs_root = parent.root / "runs"
        metadata = os.lstat(runs_root)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ConfigurationError("experiment runs path must be a real directory")
        known_paths = {
            record.relative_child_path
            for record in parent.records
            if record.relative_child_path is not None
        }
        by_item_id = {item.plan_item_id: item for item in plan.items}
        for child in sorted(runs_root.iterdir(), key=lambda path: path.name):
            relative = child.relative_to(parent.root).as_posix()
            if relative in known_paths or child.is_symlink() or not child.is_dir():
                continue
            try:
                _validate_orphan_tree(child)
                replay = replay_run(child, verify=False)
                plan_item_id = replay.manifest.plan_item_id
                item = by_item_id.get(plan_item_id or "")
                if item is None:
                    raise ConfigurationError("unindexed child has no matching plan item")
                if replay.manifest.experiment_id != parent.manifest.experiment_id:
                    raise ConfigurationError("unindexed child belongs to another experiment")
                if replay.manifest.run_id != child.name:
                    raise ConfigurationError("unindexed child run ID differs from its directory")
                validate_plan_binding(replay.manifest, replay.scorecard, item)
                attempt = _orphan_attempt(item, child.name, parent.records)
                result = RunResult(
                    run_dir=child,
                    manifest=replay.manifest,
                    scorecard=replay.scorecard,
                )
                record = _record_from_result(parent.root, item, attempt, result)
                parent.log(
                    f"recovered unindexed terminal child for plan[{item.plan_index}] "
                    f"attempt {attempt}"
                )
                parent.terminal(item, record)
                known_paths.add(relative)
                continue
            except Exception as exc:
                reason = str(exc)[:1024]
            try:
                manifest = load_json_model(child / "run_manifest.json", RunManifest)
                item = by_item_id.get(manifest.plan_item_id or "")
            except Exception:
                item = None
            if item is None:
                parent.log(f"unindexed child {relative} could not be bound: {reason}")
                continue
            attempt = _orphan_attempt(item, child.name, parent.records)
            manifest_path = child / "run_manifest.json"
            score_path = child / "scorecard.json"
            record = RunIndexRecord(
                plan_index=item.plan_index,
                plan_item_id=item.plan_item_id,
                attempt=attempt,
                child_run_id=child.name,
                relative_child_path=relative,
                terminal_status="partial",
                resolved=False,
                evaluable=False,
                infrastructure_error=False,
                child_exit_category="partial_artifact",
                artifact_validation_status="partial",
                child_manifest_hash=(
                    hash_bytes(manifest_path.read_bytes())
                    if not manifest_path.is_symlink() and manifest_path.is_file()
                    else None
                ),
                scorecard_hash=(
                    hash_bytes(score_path.read_bytes())
                    if not score_path.is_symlink() and score_path.is_file()
                    else None
                ),
                message=reason,
            )
            parent.terminal(item, record)
            parent.event(
                "plan_item_corrupt",
                item=item,
                attempt=attempt,
                detail={"reason": reason, "recovered_unindexed": True},
            )
            known_paths.add(relative)

    def _validate_resume_children(
        self,
        plan: ExperimentPlan,
        parent: _ParentArtifacts,
    ) -> set[int]:
        inputs = load_report_inputs(parent.root)
        valid = {(run.plan_index, run.attempt): run for run in inputs.valid_runs}
        latest = _latest_records(parent.records)
        completed: set[int] = set()
        for item in plan.items:
            record = latest.get(item.plan_index)
            if record is None:
                continue
            run = valid.get((item.plan_index, record.attempt))
            if run is not None:
                try:
                    replay_run(parent.root / run.relative_path, verify=False)
                except Exception as exc:
                    corrupt = record.model_copy(
                        update={
                            "artifact_validation_status": "corrupt",
                            "terminal_status": "corrupt",
                            "resolved": False,
                            "evaluable": False,
                            "infrastructure_error": False,
                            "child_exit_category": "corrupt_artifact",
                            "message": str(exc)[:1024],
                        }
                    )
                    parent.replace_record(record, corrupt)
                    parent.event(
                        "plan_item_corrupt",
                        item=item,
                        attempt=record.attempt,
                        detail={"reason": str(exc)[:1024]},
                    )
                    continue
                completed.add(item.plan_index)
                parent.event(
                    "plan_item_reused_on_resume",
                    item=item,
                    attempt=record.attempt,
                    detail={"runtime_calls": 0, "model_calls": 0},
                )
            elif record.artifact_validation_status == "valid":
                corrupt = record.model_copy(
                    update={
                        "artifact_validation_status": "corrupt",
                        "terminal_status": "corrupt",
                        "resolved": False,
                        "evaluable": False,
                        "infrastructure_error": False,
                        "child_exit_category": "corrupt_artifact",
                        "message": "parent/child artifact validation failed during resume",
                    }
                )
                parent.replace_record(record, corrupt)
                parent.event(
                    "plan_item_corrupt",
                    item=item,
                    attempt=record.attempt,
                    detail={"reason": "artifact validation failed"},
                )
            elif record.terminal_status in {
                "completed",
                "failed",
                "error",
                "cancelled",
                "infrastructure_error",
            }:
                # A terminal invalid attempt is preserved but never reused or aggregated.
                continue
        if plan.config.execution.resume_model_process_policy == "never_rerun_after_authorization":
            by_index = {item.plan_index: item for item in plan.items}
            latest = _latest_records(parent.records)
            for authorization in parent.process_ledger:
                index = authorization.plan_index
                if index in completed:
                    continue
                item = by_index[index]
                record = latest.get(index)
                if record is None:
                    record = RunIndexRecord(
                        plan_index=index,
                        plan_item_id=item.plan_item_id,
                        attempt=authorization.attempt,
                        terminal_status="interrupted_after_model_authorization",
                        resolved=False,
                        evaluable=False,
                        infrastructure_error=True,
                        child_exit_category="model_process_authorization_consumed",
                        artifact_validation_status="missing",
                        message=(
                            "strict resume preserved an authorization with no valid "
                            "terminal child; the item was not rerun"
                        ),
                    )
                    parent.terminal(item, record)
                elif record.artifact_validation_status != "valid":
                    preserved = record.model_copy(
                        update={
                            "terminal_status": "interrupted_after_model_authorization",
                            "resolved": False,
                            "evaluable": False,
                            "infrastructure_error": True,
                            "child_exit_category": ("model_process_authorization_consumed"),
                            "message": (
                                "strict resume preserved the prior attempt after a "
                                "model-process authorization; the item was not rerun"
                            ),
                        }
                    )
                    parent.replace_record(record, preserved)
                completed.add(index)
                parent.event(
                    "plan_item_reused_on_resume",
                    item=item,
                    attempt=authorization.attempt,
                    detail={
                        "runtime_calls": 0,
                        "model_calls": 0,
                        "reason": "model_process_authorization_already_consumed",
                    },
                )
        return completed


def _record_from_result(
    root: Path,
    item: PlanItem,
    attempt: int,
    result: RunResult,
) -> RunIndexRecord:
    relative = result.run_dir.relative_to(root).as_posix()
    outcome, _candidate_verdict = classify_sample_outcome(result.scorecard)
    infrastructure = outcome == SampleOutcome.INFRASTRUCTURE_ERROR
    cancelled = outcome == SampleOutcome.CANCELLED_TRUNCATED
    evaluable = not infrastructure and not cancelled
    failure = (
        result.scorecard.failure.category
        if result.scorecard.failure is not None
        else next(
            (
                verifier.error_category.value
                for verifier in result.scorecard.verifier_results
                if verifier.status.value in {"failed", "error"}
            ),
            outcome.value,
        )
    )
    return RunIndexRecord(
        plan_index=item.plan_index,
        plan_item_id=item.plan_item_id,
        attempt=attempt,
        child_run_id=result.manifest.run_id,
        relative_child_path=relative,
        terminal_status=result.scorecard.status,
        resolved=result.scorecard.resolved,
        evaluable=evaluable,
        infrastructure_error=infrastructure,
        model_api_call_count=len(result.manifest.model_observations),
        child_exit_category=failure,
        artifact_validation_status="valid",
        child_manifest_hash=hash_bytes((result.run_dir / "run_manifest.json").read_bytes()),
        scorecard_hash=hash_bytes((result.run_dir / "scorecard.json").read_bytes()),
        artifact_manifest_hash=hash_bytes((result.run_dir / "artifact_manifest.json").read_bytes()),
    )


def _model_bearing_reason(
    item: PlanItem,
) -> Literal["configured_model_client", "external_coding_agent"] | None:
    if item.system.model_id is not None:
        return "configured_model_client"
    if "external_coding_agent" in item.system.agent_descriptor.capabilities:
        return "external_coding_agent"
    return None


def _maximum_model_api_calls(item: PlanItem) -> int:
    if item.system.model_id is None:
        return 0
    if item.action_protocol is not None:
        return item.action_protocol.max_completion_calls
    return 1


def _validate_model_process_result(item: PlanItem, result: RunResult) -> None:
    reason = _model_bearing_reason(item)
    if reason is None:
        return
    if reason == "configured_model_client":
        model_observations = result.manifest.model_observations
        if item.action_protocol is None:
            if len(model_observations) != 1:
                raise ConfigurationError(
                    "model-bearing child did not record exactly one model call"
                )
            return
        if not 1 <= len(model_observations) <= item.action_protocol.max_completion_calls:
            raise ConfigurationError(
                "repository-action child recorded an invalid model API-call count"
            )
        records = result.manifest.action_protocol_records
        if len(records) != sum(
            observation.safe_provider_request_id is not None for observation in model_observations
        ):
            raise ConfigurationError(
                "repository-action child protocol records do not cover successful responses"
            )
        observation_ids = {observation.request_id for observation in model_observations}
        record_ids = [record.request_id for record in records]
        if len(record_ids) != len(set(record_ids)) or not set(record_ids) <= observation_ids:
            raise ConfigurationError(
                "repository-action child protocol/model request linkage is invalid"
            )
        return
    external_observations = result.manifest.external_agent_observations
    if sum(identity.invocation_count for identity in external_observations) != 1:
        raise ConfigurationError(
            "external coding-agent child did not record exactly one model process"
        )
    identity = external_observations[-1]
    options = item.system.agent_options
    expected_values = {
        "requested_model_id": options.get("model_id"),
        "requested_reasoning_effort": options.get("reasoning_effort"),
        "effective_reasoning_effort": options.get("reasoning_effort"),
        "executable_version": options.get("expected_cli_version"),
        "executable_sha256": options.get("expected_cli_executable_sha256"),
        "capability_fingerprint": options.get("expected_capability_fingerprint"),
        "requested_auth_mode": options.get("expected_requested_auth_mode"),
        "resolved_auth_mode": options.get("expected_resolved_auth_mode"),
        "auth_semantic_id": options.get("expected_auth_semantic_id"),
    }
    for field, expected in expected_values.items():
        if expected is None:
            continue
        if getattr(identity, field) != expected:
            raise ConfigurationError(f"external coding-agent identity mutation: {field}")
    expected_track = (
        "codex_cli_readonly_single_turn_agent"
        if item.system.agent_id == "codex-cli-readonly-agent"
        else "codex_cli_external_agent"
        if item.system.agent_id == "codex-cli-agent"
        else None
    )
    if expected_track is not None and identity.integration_track != expected_track:
        raise ConfigurationError("external coding-agent identity mutation: integration_track")
    if identity.observed_model_id != identity.requested_model_id:
        raise ConfigurationError(
            "external coding-agent observed model differs from the requested model"
        )
    if identity.identity_confidence != "observed":
        raise ConfigurationError("external coding-agent model identity was not directly observed")
    expected_backend = options.get("expected_execution_backend")
    if expected_backend is not None:
        runtime_path = result.run_dir / "artifacts" / "codex_cli" / "runtime_process.json"
        if not runtime_path.is_file() or runtime_path.is_symlink():
            raise ConfigurationError("external coding-agent runtime identity evidence is missing")
        runtime_result = ExternalProcessResult.model_validate_json(
            runtime_path.read_text(encoding="utf-8")
        )
        runtime_identity = runtime_result.runtime_identity
        if runtime_identity.execution_backend != expected_backend:
            raise ConfigurationError("external coding-agent identity mutation: execution_backend")
        docker = item.docker_config
        external = docker.external_agent if docker is not None else None
        if docker is None or external is None:
            raise ConfigurationError(
                "runtime-delegated external coding agent has no frozen Docker identity"
            )
        frozen_values = {
            "verifier_image_id": docker.expected_image_id,
            "agent_image_id": external.expected_image_id,
            "agent_executable_name": external.expected_executable_name,
            "agent_executable_sha256": external.expected_executable_sha256,
            "agent_executable_version": external.expected_executable_version,
        }
        for field, expected in frozen_values.items():
            if expected is None or getattr(runtime_identity, field) != expected:
                raise ConfigurationError(f"external coding-agent identity mutation: {field}")
        if not runtime_result.cleanup_complete:
            raise ConfigurationError(
                "external coding-agent security breach: incomplete runtime cleanup"
            )


def _plan_audit(plan: ExperimentPlan, plan_path: Path) -> dict[str, object]:
    task_ids = sorted({item.task_id for item in plan.items})
    system_ids = sorted({item.system.system_id for item in plan.items})
    base_seeds = sorted({item.base_seed for item in plan.items})
    sample_indices = list(range(plan.config.runs.samples_per_task))
    expected_cells = {
        (task_id, system_id, base_seed, sample_index)
        for task_id in task_ids
        for system_id in system_ids
        for base_seed in base_seeds
        for sample_index in sample_indices
    }
    observed_cells = {
        (
            item.task_id,
            item.system.system_id,
            item.base_seed,
            item.sample_index,
        )
        for item in plan.items
    }
    item_ids = [item.plan_item_id for item in plan.items]
    child_seeds = [item.child_seed for item in plan.items]
    model_bearing_item_count = sum(_model_bearing_reason(item) is not None for item in plan.items)
    maximum = plan.config.execution.max_model_processes
    planned_model_api_call_budget = sum(_maximum_model_api_calls(item) for item in plan.items)
    maximum_api_calls = plan.config.execution.max_model_api_calls
    strict_process_policy = (
        plan.config.execution.resume_model_process_policy == "never_rerun_after_authorization"
    )
    process_budget_exact = (
        maximum == model_bearing_item_count
        if strict_process_policy
        else maximum is None or maximum >= model_bearing_item_count
    )
    model_api_call_budget_exact = (
        maximum_api_calls == planned_model_api_call_budget
        if any(item.action_protocol is not None for item in plan.items)
        else maximum_api_calls is None or maximum_api_calls >= planned_model_api_call_budget
    )
    strict_resume_ready = (
        plan.config.execution.resume_model_process_policy != "never_rerun_after_authorization"
        or (
            maximum is not None
            and plan.config.execution.seal_plan_before_execution
            and bool(plan.config.execution.frozen_campaign_identity)
        )
    )
    return {
        "schema_version": "1.0",
        "experiment_id": plan.experiment_id,
        "config_hash": plan.config_hash,
        "evaluation_config_hash": plan.evaluation_config_hash,
        "task_set_hash": plan.task_set_hash,
        "source_identity_hash": plan.source_identity_hash,
        "plan_hash": plan.plan_hash,
        "plan_file_sha256": hash_bytes(plan_path.read_bytes()),
        "planned_item_count": len(plan.items),
        "unique_plan_item_id_count": len(set(item_ids)),
        "unique_child_seed_count": len(set(child_seeds)),
        "task_count": len(task_ids),
        "system_count": len(system_ids),
        "base_seed_count": len(base_seeds),
        "samples_per_task_system": plan.config.runs.samples_per_task,
        "task_system_seed_sample_cells_complete": observed_cells == expected_cells,
        "model_bearing_item_count": model_bearing_item_count,
        "max_model_processes": maximum,
        "model_process_budget_exact": process_budget_exact,
        "planned_model_api_call_budget": planned_model_api_call_budget,
        "max_model_api_calls": maximum_api_calls,
        "model_api_call_budget_exact": model_api_call_budget_exact,
        "strict_resume_ready": strict_resume_ready,
        "frozen_campaign_identity_hash": (
            content_hash(plan.config.execution.frozen_campaign_identity)
            if plan.config.execution.frozen_campaign_identity
            else None
        ),
        "max_workers": plan.config.execution.max_workers,
        "plan_sealed_before_execution": (plan.config.execution.seal_plan_before_execution),
        "passed": bool(
            len(plan.items) == len(set(item_ids)) == len(set(child_seeds))
            and observed_cells == expected_cells
            and process_budget_exact
            and model_api_call_budget_exact
            and strict_resume_ready
        ),
    }


def _validate_execution_plan(plan: ExperimentPlan) -> None:
    execution = plan.config.execution
    if execution.resume_model_process_policy != "never_rerun_after_authorization":
        return
    model_bearing = sum(_model_bearing_reason(item) is not None for item in plan.items)
    if execution.max_model_processes != model_bearing:
        raise ConfigurationError("strict model-process campaign requires an exact process budget")
    planned_api_calls = sum(_maximum_model_api_calls(item) for item in plan.items)
    if any(item.action_protocol is not None for item in plan.items) and (
        execution.max_model_api_calls != planned_api_calls
    ):
        raise ConfigurationError(
            "strict multi-turn model campaign requires an exact model API-call budget"
        )


def _assert_persisted_plan(root: Path, plan: ExperimentPlan) -> None:
    path = root / "plan.jsonl"
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError("persisted experiment plan is not a regular file")
    if plan.config.execution.seal_plan_before_execution and stat.S_IMODE(metadata.st_mode) & 0o222:
        raise ConfigurationError("persisted experiment plan is no longer sealed")
    items = load_jsonl_models(path, PlanItem)
    if content_hash(plan_items_hash_payload(items)) != plan.plan_hash:
        raise ConfigurationError("persisted experiment plan identity mutated")


def _create_append_only_ledger(path: Path) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append_jsonl_record(
    path: Path,
    record: ModelProcessLedgerRecord | dict[str, object],
) -> None:
    value = (
        record.model_dump(mode="json") if isinstance(record, ModelProcessLedgerRecord) else record
    )
    payload = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load_checkpoint_records(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ConfigurationError(f"blank summary checkpoint at line {line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"invalid summary checkpoint at line {line_number}") from exc
        if not isinstance(value, dict) or value.get("sequence") != len(records):
            raise ConfigurationError("summary checkpoint sequence is invalid")
        records.append(value)
    return records


def _validate_process_ledger(
    plan: ExperimentPlan,
    records: list[ModelProcessLedgerRecord],
) -> None:
    by_index = {item.plan_index: item for item in plan.items}
    if [record.ordinal for record in records] != list(range(1, len(records) + 1)):
        raise ConfigurationError("model-process ledger ordinals are not contiguous")
    if len({record.plan_index for record in records}) != len(records):
        raise ConfigurationError("model-process ledger authorizes a plan item more than once")
    maximum = plan.config.execution.max_model_processes
    if maximum is not None and len(records) > maximum:
        raise ConfigurationError("model-process ledger exceeds the configured budget")
    maximum_api_calls = plan.config.execution.max_model_api_calls
    if maximum_api_calls is not None and (
        sum(record.maximum_model_api_calls or 0 for record in records) > maximum_api_calls
    ):
        raise ConfigurationError("model-process ledger exceeds the model API-call budget")
    for record in records:
        item = by_index.get(record.plan_index)
        if (
            item is None
            or item.plan_item_id != record.plan_item_id
            or item.task_id != record.task_id
            or item.system.system_id != record.system_id
            or _model_bearing_reason(item) != record.model_bearing_reason
            or (
                record.model_api_call_budget_policy == "reserved_max_calls_v1"
                and _maximum_model_api_calls(item) != record.maximum_model_api_calls
            )
            or record.retry is not False
        ):
            raise ConfigurationError("model-process ledger identity differs from the plan")


_SHARED_INFRASTRUCTURE_CATEGORIES = {
    "authentication",
    "rate_limit",
    "transport",
    "process_boundary",
    "sandbox_backend_unavailable",
}


def _circuit_breaker_reason(
    records: list[RunIndexRecord],
    plan: ExperimentPlan,
) -> str | None:
    latest = sorted(_latest_records(records).values(), key=lambda record: record.plan_index)
    total_limit = plan.config.execution.max_total_infrastructure_failures
    total = sum(record.infrastructure_error for record in latest)
    if total_limit is not None and total >= total_limit:
        return f"total_infrastructure_failures:{total}"
    consecutive_limit = (
        plan.config.execution.max_consecutive_identical_shared_infrastructure_failures
    )
    if consecutive_limit is None:
        return None
    category: str | None = None
    count = 0
    for record in latest:
        if (
            record.infrastructure_error
            and record.child_exit_category in _SHARED_INFRASTRUCTURE_CATEGORIES
        ):
            if record.child_exit_category == category:
                count += 1
            else:
                category = record.child_exit_category
                count = 1
        else:
            category = None
            count = 0
    if category is not None and count >= consecutive_limit:
        return f"consecutive_shared_infrastructure:{category}:{count}"
    return None


def _child_config(
    root: Path,
    item: PlanItem,
    run_id: str,
    experiment_id: str,
) -> RunConfig:
    return RunConfig(
        task_id=item.task_id,
        mode=item.interaction_mode,
        agent=item.system.agent_id,
        agent_options=item.system.agent_options,
        model=item.system.model_id,
        model_options=item.system.model_options.model_copy(
            update={"sample_index": item.sample_index}
        ),
        max_invalid_actions=item.max_invalid_actions,
        suite_source=item.suite_source,
        sample_index=item.sample_index,
        runtime=item.runtime_id,
        docker_config=item.docker_config,
        toolchain_profile=item.requested_profile_id,
        verifier_profile_id=(
            item.verifier_profile.id if item.verifier_profile is not None else None
        ),
        verifier_profile=item.verifier_profile,
        agent_ppa_feedback=item.agent_feedback_contract.ppa_enabled
        if item.agent_feedback_contract is not None
        else False,
        agent_ppa_max_calls=item.agent_feedback_contract.ppa_max_executions
        if item.agent_feedback_contract is not None
        else 3,
        seed=item.child_seed,
        output=root / "runs",
        run_id=run_id,
        experiment_id=experiment_id,
        plan_item_id=item.plan_item_id,
        system_id=item.system.system_id,
        base_seed=item.base_seed,
        expected_task_hash=item.task_hash,
        expected_source_hash=item.source_hash,
        expected_suite_source_snapshot=item.suite_source_snapshot,
        expected_runtime=item.runtime_descriptor,
        expected_resolved_profile=item.resolved_profile,
        expected_resolved_verifier_profile=item.resolved_verifier_profile,
        expected_prompt_policy=item.prompt_policy,
        expected_prompt_policy_hash=item.prompt_policy_hash,
        expected_agent_configuration_hash=item.system.agent_configuration_hash,
        expected_action_protocol=item.action_protocol,
        expected_agent_feedback_contract=item.agent_feedback_contract,
    )


def _child_run_id(item: PlanItem, attempt: int) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    task_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", item.task_id).strip(".-")[:80] or "task"
    return f"{timestamp}-{task_slug}-{item.plan_item_id[:10]}-a{attempt}-{uuid.uuid4().hex[:8]}"


def _orphan_attempt(
    item: PlanItem,
    run_id: str,
    records: list[RunIndexRecord],
) -> int:
    match = re.search(r"-a([1-9][0-9]*)(?:-[0-9a-f]{8})?$", run_id)
    parsed = int(match.group(1)) if match is not None else 1
    used = {record.attempt for record in records if record.plan_index == item.plan_index}
    if parsed not in used:
        return parsed
    return max(used, default=0) + 1


def _recovered_state(
    plan: ExperimentPlan,
    manifest: ExperimentManifest,
    stored: ExperimentState,
    events: list[BatchEvent],
    records: list[RunIndexRecord],
) -> ExperimentState:
    if (
        stored.experiment_id != manifest.experiment_id
        or stored.config_hash != manifest.config_hash
        or stored.plan_hash != manifest.plan_hash
        or stored.planned_count != len(plan.items)
    ):
        raise ConfigurationError("stored experiment state identity does not match the plan")
    if [event.sequence for event in events] != list(range(len(events))):
        raise ConfigurationError("batch event sequences are not contiguous")
    if any(event.experiment_id != manifest.experiment_id for event in events):
        raise ConfigurationError("batch event experiment identity mismatch")
    attempts = {(record.plan_index, record.attempt) for record in records}
    if len(attempts) != len(records):
        raise ConfigurationError("run index contains duplicate plan-index/attempt records")
    by_index = {item.plan_index: item for item in plan.items}
    if any(
        (item := by_index.get(record.plan_index)) is None
        or item.plan_item_id != record.plan_item_id
        for record in records
    ):
        raise ConfigurationError("run index contains a record that does not match the plan")
    corrupt_states = {"partial", "corrupt", "incompatible"}
    active = 0
    observed = 0
    for event in events:
        if event.event_type == "plan_item_started":
            active += 1
            observed = max(observed, active)
        elif event.event_type == "plan_item_terminal":
            active = max(0, active - 1)
        elif event.event_type == "experiment_interrupted":
            active = 0
    return stored.model_copy(
        update={
            "status": "running",
            "scheduled_count": sum(event.event_type == "plan_item_scheduled" for event in events),
            "terminal_count": len(records),
            "valid_terminal_count": sum(
                record.artifact_validation_status == "valid" for record in records
            ),
            "infrastructure_error_count": sum(record.infrastructure_error for record in records),
            "corrupt_attempt_count": sum(
                record.artifact_validation_status in corrupt_states for record in records
            ),
            "active_count": 0,
            "observed_max_concurrency": max(stored.observed_max_concurrency, observed),
            "last_event_sequence": len(events) - 1,
        }
    )


def _exception_class(exc: BaseException) -> tuple[bool, bool]:
    if isinstance(exc, (MissingDependencyError, RuntimeExecutionError)):
        return True, False
    if isinstance(exc, ConfigurationError):
        return False, True
    if isinstance(exc, VeriGymError):
        return exc.exit_code in {3, 4}, exc.exit_code not in {3, 4}
    return False, True


def _validate_orphan_tree(root: Path) -> None:
    count = 0
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in [*names, *files]:
            count += 1
            if count > 100_000:
                raise ConfigurationError("unindexed child contains too many filesystem entries")
            metadata = os.lstat(base / name)
            if stat.S_ISLNK(metadata.st_mode):
                raise ConfigurationError("unindexed child contains a symlink")
            if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
                raise ConfigurationError("unindexed child contains a special file")


def _latest_records(records: list[RunIndexRecord]) -> dict[int, RunIndexRecord]:
    result: dict[int, RunIndexRecord] = {}
    for record in sorted(records, key=lambda item: (item.plan_index, item.attempt)):
        result[record.plan_index] = record
    return result


def _prepare_new_root(path: Path) -> Path:
    root = path.expanduser()
    if ".." in root.parts or any(ord(character) < 32 for character in root.as_posix()):
        raise ConfigurationError("experiment output path contains traversal or control characters")
    _reject_symlink_components(root)
    if root.exists():
        if not root.is_dir() or any(root.iterdir()):
            raise ConfigurationError(
                f"experiment output already exists and is not empty: {root}; use --resume"
            )
    else:
        root.mkdir(parents=True)
    return root.resolve(strict=True)


def _existing_root(path: Path) -> Path:
    root = path.expanduser()
    _reject_symlink_components(root)
    metadata = os.lstat(root)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ConfigurationError("resume path must be a real experiment directory")
    return root.resolve(strict=True)


def _validate_parent_directories(root: Path) -> None:
    for name in ("runs", "logs", "reports"):
        path = root / name
        try:
            metadata = os.lstat(path)
        except OSError as exc:
            raise ConfigurationError(f"experiment parent directory is unavailable: {name}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ConfigurationError(f"experiment parent path must be a real directory: {name}")


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor) if path.is_absolute() else Path.cwd()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ConfigurationError(f"experiment output traverses a symlink: {current}")


__all__ = ["BatchRunner", "ChildExecutor"]
