"""Sequential-by-default and bounded-parallel experiment execution."""

from __future__ import annotations

import os
import re
import stat
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

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
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.schemas import (
    BatchEvent,
    BatchResult,
    ExperimentConfig,
    ExperimentManifest,
    ExperimentPlan,
    ExperimentState,
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
from verigym.reporting.loader import load_report_inputs, validate_plan_binding
from verigym.reporting.service import ReportService
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
    ) -> None:
        self.root = root
        self.manifest = manifest
        self.state = state
        self.events = events or []
        self.records = records or []
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
        root = _prepare_new_root(plan.config.output.root)
        parent = self._initialize(plan, root)
        return self._execute(plan, parent, completed=set())

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
        if content_hash([item.model_dump(mode="json") for item in items]) != manifest.plan_hash:
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
        state = load_json_model(experiment_root / "state.json", ExperimentState)
        state = _recovered_state(plan, manifest, state, events, records)
        parent = _ParentArtifacts(
            experiment_root,
            manifest,
            state,
            events=events,
            records=records,
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
        atomic_dump_jsonl(root / "plan.jsonl", plan.items)
        atomic_dump_json(root / "experiment_manifest.json", manifest)
        atomic_dump_json(root / "state.json", state)
        atomic_dump_jsonl(root / "events.jsonl", [])
        atomic_dump_jsonl(root / "run_index.jsonl", [])
        atomic_write_text(root / "logs" / "batch.log", "")
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
        try:
            if plan.config.execution.max_workers == 1:
                for item in pending:
                    record, internal = self._run_item(parent, item, attempts[item.plan_index])
                    internal_failures += int(internal)
                    if internal:
                        break
                    if (
                        record.infrastructure_error
                        and not plan.config.execution.continue_on_infrastructure_error
                    ):
                        break
            else:
                internal_failures += self._run_parallel(plan, parent, pending, attempts)
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
                            self._run_item, parent, item, attempts[item.plan_index]
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
            result = self.child_executor(item, config)
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
        child_exit_category=failure,
        artifact_validation_status="valid",
        child_manifest_hash=hash_bytes((result.run_dir / "run_manifest.json").read_bytes()),
        scorecard_hash=hash_bytes((result.run_dir / "scorecard.json").read_bytes()),
        artifact_manifest_hash=hash_bytes((result.run_dir / "artifact_manifest.json").read_bytes()),
    )


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
